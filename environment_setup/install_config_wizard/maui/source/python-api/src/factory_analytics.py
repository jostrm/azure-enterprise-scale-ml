"""Evidence-labelled analytics for the current factory, never demonstration charts."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.operations import OperationsService, parse_resource_group_name
from src.factory_scope import current_factory_scope
from src.ticketing import TicketService, TicketError, factory_folder, now_iso
from src.project_metadata import (
    _display_text, current_factory_project_snapshot, owner_from_project_state,
    planned_environments_from_project_state, project_state_in_factory_scope,
)


ENVIRONMENTS = ("dev", "stage", "prod")
# Only actual service switches are mapped; security/network/add-another-instance flags are not services.
SERVICES = (
    ("AI Search", "enableAISearch", "microsoft.search/searchservices", ""),
    ("Azure OpenAI", "enableAzureOpenAI", "microsoft.cognitiveservices/accounts", "openai"),
    ("AI Foundry", "enableAIFoundry", "microsoft.cognitiveservices/accounts", "aiservices"),
    ("AI Services", "enableAIServices", "microsoft.cognitiveservices/accounts", "cognitiveservices"),
    ("AI Vision", "enableAzureAIVision", "microsoft.cognitiveservices/accounts", "computervision"),
    ("Speech", "enableAzureSpeech", "microsoft.cognitiveservices/accounts", "speechservices"),
    ("Document Intelligence", "enableAIDocIntelligence", "microsoft.cognitiveservices/accounts", "formrecognizer"),
    ("Content Safety", "enableContentSafety", "microsoft.cognitiveservices/accounts", "contentsafety"),
    ("Azure Machine Learning", "enableAzureMachineLearning", "microsoft.machinelearningservices/workspaces", ""),
    ("AI Foundry Hub", "enableAIFoundryHub", "microsoft.machinelearningservices/workspaces", "hub"),
    ("Databricks", "enableDatabricks", "microsoft.databricks/workspaces", ""),
    ("Data Factory", "enableDatafactory", "microsoft.datafactory/factories", ""),
    ("AKS", "enableAKS", "microsoft.containerservice/managedclusters", ""),
    ("Cosmos DB", "enableCosmosDB", "microsoft.documentdb/databaseaccounts", ""),
    ("PostgreSQL", "enablePostgreSQL", "microsoft.dbforpostgresql/flexibleservers", ""),
    ("Redis", "enableRedisCache", "microsoft.cache/redis", ""),
    ("SQL Database", "enableSQLDatabase", "microsoft.sql/servers/databases", ""),
    ("Elasticsearch", "enableElasticsearch", "microsoft.elastic/monitors", ""),
    ("Functions", "enableFunction", "microsoft.web/sites", "functionapp"),
    ("Web App", "enableWebApp", "microsoft.web/sites", "app"),
    ("Container Apps", "enableContainerApps", "microsoft.app/containerapps", ""),
    ("Logic Apps", "enableLogicApps", "microsoft.logic/workflows", ""),
    ("Event Hubs", "enableEventHubs", "microsoft.eventhub/namespaces", ""),
    ("Bot Service", "enableBotService", "microsoft.botservice/botservices", ""),
    ("Project VM", "enableProjectVM", "microsoft.compute/virtualmachines", ""),
    ("Bing", "enableBing", "microsoft.bing/accounts", ""),
    ("Bing Custom Search", "enableBingCustomSearch", "microsoft.bing/accounts", "bing.customsearch"),
)
DEPARTMENTS = ("HR", "Marketing", "Central IT", "Central AI Team", "Finance", "Unknown")
UNKNOWN = "Unknown"


def _number(value):
    text = str(value or "")
    return str(int(text)) if re.fullmatch(r"\d{1,6}", text) else ""


def _text(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    return _display_text(value)


def _tags(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return {re.sub(r"[^a-z0-9]", "", str(key).lower()): _text(item) for key, item in value.items()} if isinstance(value, dict) else {}


def project_metadata(state, groups=(), project=None):
    sources = [state, _tags(state.get("tagsProject")), _tags(state.get("tags"))]
    sources.extend(_tags(group.get("tags")) for group in groups)

    def first(keys):
        for source in sources:
            normalized = _tags(source)
            for key in keys:
                if normalized.get(key):
                    return normalized[key]
        return UNKNOWN

    owner = owner_from_project_state(state, (project or {}).get("project_number"))
    if owner == UNKNOWN:
        for group in groups:
            owner = owner_from_project_state({"tags": group.get("tags")})
            if owner != UNKNOWN:
                break
    return {
        "owner": owner,
        "cost_center": first((
            "tagcostceterproject", "tagcostcenterproject", "tagcostcenter",
            "costcenter", "costcentre", "billingcostcenter",
        )),
        "department": first(("department", "businessunit", "team")),
    }


def _agent(resource):
    kind = str(resource.get("type") or "").casefold()
    return kind in {
        "microsoft.cognitiveservices/accounts/projects/agents",
        "microsoft.cognitiveservices/accounts/projects/assistants",
        "microsoft.machinelearningservices/workspaces/agents",
    }


def _model(resource):
    kind = str(resource.get("type") or "").casefold()
    return kind in {
        "microsoft.cognitiveservices/accounts/deployments",
        "microsoft.machinelearningservices/workspaces/models",
        "microsoft.machinelearningservices/workspaces/models/versions",
        "microsoft.machinelearningservices/registries/models",
        "microsoft.machinelearningservices/registries/models/versions",
    }


def _observed_count(count):
    return f"{count} observed (enumeration may be incomplete)" if count else "Unknown (not enumerated)"


def _matches(resource, resource_type, kind):
    if str(resource.get("type") or "").casefold() != resource_type:
        return False
    actual = str(resource.get("kind") or "").casefold()
    if resource_type == "microsoft.machinelearningservices/workspaces" and not kind:
        return actual not in {"hub", "project"}
    if kind == "app":
        return actual in {"app", "app,linux", "linux", "app,container,linux"}
    return not kind or kind in actual.split(",")


class FactoryAnalytics:
    def __init__(self, operations=None, tickets=None, clock=time.time):
        self.operations = operations or OperationsService()
        self.store = self.operations.store
        self.tickets = tickets or TicketService(self.store)
        self.clock = clock
        with self.store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS factory_lifecycle_observations (
                    aifactory_folder TEXT NOT NULL, scope_key TEXT NOT NULL,
                    project_number TEXT NOT NULL, environment TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    observations INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(aifactory_folder,scope_key,project_number,environment)
                );
            """)

    def _observe(self, folder, local, inventory, deployed):
        scope = {key: local.get(key) for key in (
            "subscriptions", "tenant_ids", "subscription_tenants", "prefix_rg", "suffix_rg", "monitoring_targets",
        )}
        scope_key = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
        try:
            sample = datetime.fromisoformat(str(inventory.get("collected_at") or "").replace("Z", "+00:00"))
            valid_time = sample.tzinfo is not None and sample.timestamp() <= self.clock() + 60
            timestamp = sample.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        except ValueError:
            valid_time, timestamp = False, ""
        real = inventory.get("source") in {"azure", "cached"}
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if real and valid_time:
                existing = db.execute(
                    "SELECT * FROM factory_lifecycle_observations WHERE aifactory_folder=? AND scope_key=?",
                    (folder, scope_key),
                ).fetchall()
                for row in existing:
                    if (
                        inventory.get("is_complete") is True and timestamp > row["last_seen_at"]
                        and row["environment"] not in deployed.get(row["project_number"], set())
                    ):
                        db.execute("""
                            UPDATE factory_lifecycle_observations SET active=0,last_seen_at=?
                            WHERE aifactory_folder=? AND scope_key=? AND project_number=? AND environment=?
                        """, (timestamp, folder, scope_key, row["project_number"], row["environment"]))
                for project, environments in deployed.items():
                    for environment in environments:
                        db.execute("""
                            INSERT INTO factory_lifecycle_observations
                            (aifactory_folder,scope_key,project_number,environment,first_seen_at,last_seen_at)
                            VALUES (?,?,?,?,?,?)
                            ON CONFLICT(aifactory_folder,scope_key,project_number,environment) DO UPDATE SET
                            first_seen_at=CASE WHEN active=0 THEN excluded.first_seen_at ELSE first_seen_at END,
                            observations=CASE WHEN active=0 THEN 1 ELSE observations+1 END,
                            active=1,last_seen_at=excluded.last_seen_at
                            WHERE excluded.last_seen_at>last_seen_at
                        """, (folder, scope_key, project, environment, timestamp, timestamp))
            rows = db.execute(
                "SELECT * FROM factory_lifecycle_observations WHERE aifactory_folder=? AND scope_key=? AND active=1",
                (folder, scope_key),
            ).fetchall()
        return {(row["project_number"], row["environment"]): dict(row) for row in rows}

    def current(self, folder):
        folder = factory_folder(folder)
        overview = self.operations.overview(folder)
        # Do not use overall source: monitoring mock fallbacks can coexist with real inventory.
        inventory = overview.get("resource_inventory") or {}
        source = inventory.get("source", "unavailable")
        real = source in {"azure", "cached"}
        complete = real and inventory.get("is_complete") is True
        local = self.operations.discovery.discover(folder)
        scope = current_factory_scope(folder)
        states, excluded_snapshots = {}, 0
        for item in local.get("project_snapshots", []):
            number = _number(item.get("project_number"))
            state = current_factory_project_snapshot(
                folder, item.get("project_number"), item.get("path"), scope, local.get("orchestrator", "")
            ) if number and item.get("path") else None
            if state is None:
                excluded_snapshots += 1
            else:
                states[number] = state
        # Root variables can contain one project in older factories without project snapshots.
        variables = self.operations.discovery._read_json(Path(folder) / "variables.json")
        dev = variables.get("dev") or {}
        number = _number(dev.get("project_number_000")) if isinstance(dev, dict) else ""
        if number and number not in states and project_state_in_factory_scope(
            dev, scope, local.get("orchestrator", "")
        ):
            states[number] = dev
        planned = set(states)
        groups = inventory.get("resource_groups", []) if real else []
        resources = inventory.get("resources", []) if real else []
        deployed, project_groups, project_resources = defaultdict(set), defaultdict(list), defaultdict(list)
        group_keys = {}
        for group in groups:
            parsed = parse_resource_group_name(str(group.get("name") or ""))
            number = _number(parsed["project_number"])
            if number:
                project_groups[number].append(group)
                if parsed["environment"]:
                    deployed[number].add(parsed["environment"])
                group_keys[(str(group.get("subscriptionId") or "").casefold(), str(group.get("name") or "").casefold())] = number
        unique_resources = {}
        for resource in resources:
            identifier = str(resource.get("id") or "")
            if not identifier:
                continue
            unique_resources[identifier.casefold()] = resource
        resources = list(unique_resources.values())
        for resource in resources:
            key = (str(resource.get("subscriptionId") or "").casefold(), str(resource.get("resourceGroup") or "").casefold())
            number = group_keys.get(key)
            if number:
                project_resources[number].append(resource)
        assigned_ids = {
            str(resource["id"]).casefold() for items in project_resources.values() for resource in items
        }
        unassigned = [resource for resource in resources if str(resource["id"]).casefold() not in assigned_ids]
        roster = {
            _number(project.get("project_number")): project for project in overview.get("projects", [])
            if _number(project.get("project_number")) in planned | project_groups.keys()
        }
        projects = sorted(planned | project_groups.keys(), key=int)
        planned_by_project = {
            number: set(planned_environments_from_project_state(states.get(number, {}), number))
            for number in projects
        }
        display = {
            _number(item): str(item) for item in local.get("project_numbers", []) if _number(item)
        }
        display.update({number: str(project["project_number"]) for number, project in roster.items()})
        metadata = {
            number: project_metadata(states.get(number, {}), project_groups[number], roster.get(number))
            for number in projects
        }
        lifecycle = self._observe(folder, local, inventory, deployed)
        warnings = [
            "Lifecycle ages are observed since real scoped inventory samples, not configuration modification times.",
            "Agent/model APIs are not exhaustively enumerated: missing objects are Unknown, never inferred from workspaces or SKUs.",
        ]
        if excluded_snapshots:
            warnings.append(
                f"{excluded_snapshots} historical, out-of-scope or unverified project snapshots were excluded "
                "from current planned projects, services and owner metadata; missing scope is not active configuration."
            )
        try:
            ticket_data = self.tickets.list_tickets(folder)
            tickets = ticket_data["tickets"]
            ticket_source = "private SQLite / current Azure user"
        except TicketError as exc:
            if exc.status_code not in {401, 403}:
                raise
            tickets, ticket_data = [], None
            ticket_source = "unavailable / current Azure identity unverified"
            warnings.append("Private tickets and request/blocker totals are unavailable until the factory's current Azure user is verified.")

        sections = []

        def section(title, description, columns, rows, row_source=source):
            sections.append({
                "title": title, "description": description, "columns": columns,
                "rows": [[str(cell) for cell in row] for row in rows], "source": row_source,
            })

        def deployed_count(count):
            return str(count) if complete else f"{count} observed; total unknown" if count else UNKNOWN

        section(
            "Projects by environment",
            "Planned = an explicit valid subscription target in that project's current saved state. "
            "Deployed = observed project resource group, "
            "not a claim that all desired services are healthy. Environments are independent, not highest-stage-only.",
            ["Environment", "Planned projects", "Deployed projects", "Inventory basis"],
            [[env.title(), sum(env in planned_by_project[number] for number in projects),
              deployed_count(sum(env in deployed[number] for number in projects)), source] for env in ENVIRONMENTS],
        )
        blockers = Counter(_number(ticket["project_number"]) for ticket in tickets
                           if ticket.get("severity", "blocker" if ticket["type"] == "Blocker" else "minor") == "blocker"
                           and ticket["status"] != "Solved")
        ticket_projects = {_number(ticket["project_number"]): ticket["project_number"] for ticket in tickets}
        section(
            "Private blocker tickets by project",
            "Your unsolved blocker-severity tickets, including projects without local configuration or observed inventory. "
            "Ticket naming metadata is not evidence of a planned or deployed project.",
            ["Project", "Unsolved blocker tickets"],
            [[ticket_projects[number] if number else "Factory-wide / unknown project", count]
             for number, count in sorted(blockers.items(), key=lambda item: int(item[0]) if item[0] else -1)]
            if ticket_data is not None else [[UNKNOWN, UNKNOWN]],
            ticket_source,
        )
        # Current report schema has no project attribution. Do not assign regional failures to every project.
        attributed = defaultdict(set)
        blocker_ticket_ids = {
            ticket["id"] for ticket in tickets
            if ticket.get("severity", "blocker" if ticket["type"] == "Blocker" else "minor") == "blocker"
            and ticket["status"] != "Solved"
        }
        unattributed = 0
        for region in overview.get("regions", []):
            for finding in region.get("pipeline_findings") or []:
                number = _number(finding.get("project_number"))
                if number not in projects or finding.get("status", "failed") != "failed":
                    unattributed += 1
                    continue
                signature = (finding.get("run_id"), finding.get("check_id"), finding.get("service"), finding.get("environment"))
                # A finding carrying a ticket ID is represented by that ticket, never counted twice.
                if finding.get("ticket_id") in blocker_ticket_ids:
                    continue
                attributed[number].add(signature)
        section(
            "Projects, owners and deployment status",
            "Owners come from current project technical_admins_email or owner tags; absent owners remain Unknown. "
            f"Blockers are your unsolved blocker-severity tickets plus project-attributed pipeline findings; {unattributed} "
            "unattributed regional findings excluded. Agent/model counts are observed lower bounds.",
            ["Project", "Owner", "Dev", "Stage", "Prod", "Planned environments", "Deployed environments",
             "Technical blockers", "Agents", "ML models / deployments"],
            [[
                display.get(number, number), metadata[number]["owner"],
                *["Deployed (observed)" if env in deployed[number] else
                  "Planned / not observed" if env in planned_by_project[number] else
                  "Not deployed" if complete else UNKNOWN for env in ENVIRONMENTS],
                len(planned_by_project[number]) if number in states else UNKNOWN,
                deployed_count(len(deployed[number])),
                str(blockers[number] + len(attributed[number])) if ticket_data is not None else
                f"{len(attributed[number])} pipeline findings; private tickets unknown",
                _observed_count(sum(_agent(resource) for resource in project_resources[number])),
                _observed_count(sum(_model(resource) for resource in project_resources[number])),
            ] for number in projects],
        )
        stalled_rows, date_rows = [], []
        for env in ("dev", "stage"):
            # Dev without Stage/Prod, or Stage without Prod; unknown inventory cannot prove non-promotion.
            eligible = [number for number in projects if env in deployed[number] and "prod" not in deployed[number]
                        and (env != "dev" or "stage" not in deployed[number])]
            for days in (7, 30, 180, 365, 1095):
                known = 0
                unknown = len(projects) if not complete else 0
                if complete:
                    for number in eligible:
                        item = lifecycle.get((number, env))
                        span = 0 if not item else (
                            datetime.fromisoformat(item["last_seen_at"].replace("Z", "+00:00"))
                            - datetime.fromisoformat(item["first_seen_at"].replace("Z", "+00:00"))
                        ).total_seconds() / 86400
                        if item and item["observations"] >= 2 and span > days:
                            known += 1
                        else:
                            unknown += 1
                stalled_rows.append([env.title(), f">{days} days", known, unknown,
                                     "Observed since; cumulative lower bound, not historical deployment age"])
        for number in projects:
            for env in ENVIRONMENTS:
                item = lifecycle.get((number, env))
                if item and env in deployed[number]:
                    date_rows.append([display.get(number, number), metadata[number]["owner"], env.title(),
                                      item["first_seen_at"], item["last_seen_at"], item["observations"]])
        section(
            "Stalled Dev / Stage (cumulative)",
            "Thresholds overlap (a >365-day project is also >180/>30/>7). A single sample or a shorter observed "
            "history cannot rule out an older project, so age stays unknown. Cached reads never advance sample time. "
            "No historical age or continuous activity is inferred between samples.",
            ["Environment", "Threshold", "Observed stalled", "Age/status unknown", "Date basis"], stalled_rows,
        )
        section(
            "Lifecycle observations",
            "Persisted scoped inventory observations only. A confirmed absence resets that environment's next observation period.",
            ["Project", "Owner", "Environment", "Observed since", "Last real sample", "Distinct samples"], date_rows,
            "SQLite lifecycle / " + source,
        )
        service_rows, configured_services = [], {}
        for label, flag, resource_type, kind in SERVICES:
            configured = sum(str(state.get(flag, "")).casefold() == "true" for state in states.values())
            count = sum(_matches(resource, resource_type, kind) for resource in resources)
            configured_services[label.casefold()] = (configured, count)
            service_rows.append([label, configured, deployed_count(count), resource_type])
        # A shared ARM resource type (for example cognitive accounts) can map to several kinds.
        for resource_type in {item[2] for item in SERVICES}:
            configured_services[resource_type] = (
                sum(row[1] for row in service_rows if row[3] == resource_type),
                sum(str(item.get("type") or "").casefold() == resource_type for item in resources),
            )
        configured_services["azure ai search"] = configured_services["ai search"]
        for title, reverse in (("Configured services — most used", True), ("Configured services — least used", False)):
            section(title, "Counts of current projects with an explicit enabled service flag; all mapped services, including zero, are retained.",
                    ["Service", "Configured projects", "Deployed resource instances", "Azure resource type"],
                    sorted(service_rows, key=lambda row: ((-row[1]) if reverse else row[1], row[0])),
                    "local configuration / " + source)
        for title, reverse in (("Deployed services — most used", True), ("Deployed services — least used", False)):
            section(title, "Scoped observed resource counts; zero is only asserted with complete inventory. "
                    "These are service instances, not agent/model counts.",
                    ["Service", "Configured projects", "Deployed resource instances", "Azure resource type"],
                    sorted(service_rows, key=lambda row: (
                        (-configured_services[row[0].casefold()][1]) if reverse else configured_services[row[0].casefold()][1], row[0]
                    )))
        observed_types = Counter(str(item.get("type") or "Unknown") for item in resources)
        section(
            "All observed Azure resource types",
            "Includes common/shared resources and types without a Wizard service switch. "
            "Counts are observed instances; an absent child-resource type is not evidence of zero agents/models.",
            ["Azure resource type", "Observed instances"],
            [[name, count] for name, count in sorted(observed_types.items(), key=lambda pair: (-pair[1], pair[0]))],
        )
        requested = Counter(ticket["requested_service"].strip() or "Unspecified" for ticket in tickets
                            if ticket["type"] == "Request Azure service" and ticket["status"] != "Solved")
        agent_rows = [
            [display.get(number, number), metadata[number]["owner"],
             ", ".join(env.title() for env in ENVIRONMENTS if env in deployed[number]) or "None observed",
             _observed_count(sum(_agent(resource) for resource in project_resources[number])),
             _observed_count(sum(_model(resource) for resource in project_resources[number])),
             metadata[number]["cost_center"], metadata[number]["department"]] for number in projects
        ]
        if any(_agent(resource) or _model(resource) for resource in unassigned):
            agent_rows.append([
                "Unknown / common project", UNKNOWN, "Not project-attributed",
                _observed_count(sum(_agent(resource) for resource in unassigned)),
                _observed_count(sum(_model(resource) for resource in unassigned)), UNKNOWN, UNKNOWN,
            ])
        section(
            "Requested Azure services unavailable",
            "Your unsolved service-request tickets only. Request evidence is not an Azure regional availability check. "
            "Unmapped service names are explicitly unknown; no paid probes are performed.",
            ["Requested service", "Open requests", "Current factory evidence"],
            [[name, count, "Not mapped in Wizard service catalog" if name.casefold() not in configured_services else
              "Not configured / not observed deployed" if configured_services[name.casefold()] == (0, 0) and complete else
              "Configured or observed; request may concern another capability" if any(configured_services[name.casefold()]) else
              "Not configured; deployment availability unknown"] for name, count in sorted(requested.items())],
            ticket_source,
        )
        section(
            "Agents and ML models per project",
            "Only actual agent/model/deployment resource types qualify; workspaces, model names in configuration, "
            "prompts and SKUs do not prove a deployed object.",
            ["Project", "Owner", "Environments", "Agents", "ML models / deployments", "Cost center", "Department"],
            agent_rows,
        )
        cost_centers, departments = Counter(), Counter()
        for number in [*projects, ""]:
            meta = metadata.get(number, {"cost_center": UNKNOWN, "department": UNKNOWN})
            cost_centers.setdefault(meta["cost_center"], 0)
            for resource in project_resources[number] if number else unassigned:
                if not _agent(resource):
                    continue
                tags = _tags(resource.get("tags"))
                center = tags.get("costcenter") or meta["cost_center"]
                department = tags.get("department") or meta["department"]
                normalized = re.sub(r"[^a-z]", "", department.lower())
                canonical = next((label for label in DEPARTMENTS if re.sub(r"[^a-z]", "", label.lower()) == normalized), "Unknown")
                cost_centers[center] += 1
                departments[canonical] += 1
        cost_centers.setdefault("Unknown", 0)
        section("Agents by cost center", "Agent resource tags override project cost-center metadata; missing metadata is Unknown.",
                ["Cost center", "Agents"], [[name, _observed_count(count)] for name, count in sorted(cost_centers.items())])
        section("Agents by department", "HR, Marketing, Central IT, Central AI Team and Finance are always shown. "
                "Unrecognized or missing departments are grouped as Unknown; missing enumeration is not zero agents.",
                ["Department", "Agents"], [[name, _observed_count(departments[name])] for name in DEPARTMENTS])
        section("Tickets by status", "Only private records owned by the currently authenticated Azure user in this factory.",
                ["Status", "Count"], [[status, ticket_data["counts"][status.lower()] if ticket_data else UNKNOWN]
                                      for status in ("New", "Active", "Solved")], ticket_source)
        if overview.get("warning"):
            warnings.insert(0, overview["warning"])
        return {
            "title": "Current AI Factory", "source": "local / " + source,
            "generated_at": now_iso(self.clock), "warning": " ".join(warnings), "sections": sections,
        }
