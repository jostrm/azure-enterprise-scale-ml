"""Bounded, read-only dashboard observations; only aggregates leave the collector.

The injected Azure CLI runner owns transport timeouts. No subprocess, credentials,
telemetry exporters, role changes or connectivity workarounds are created here.
"""
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit


Az = Callable[..., subprocess.CompletedProcess[str]]
MAX_PAGES = 100
MAX_ROWS = 100_000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
STORAGE_MAX_AGE = timedelta(days=2)
ARM = "https://management.azure.com"
RESOURCE_QUERY = "[].{id:id,type:type,kind:kind,name:name}"
GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
RG_PATTERN = re.compile(rf"/subscriptions/({GUID})/resourceGroups/([A-Za-z0-9_().-]{{1,90}})", re.I)
SEGMENT = r"[A-Za-z0-9_().-]+"
RESOURCE_PATTERN = re.compile(
    rf"({RG_PATTERN.pattern})/providers/([A-Za-z][A-Za-z0-9.]+)((?:/{SEGMENT}/{SEGMENT})+)", re.I
)
EMAIL = re.compile(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+")
ML = "microsoft.machinelearningservices/workspaces"
ML_REGISTRY = "microsoft.machinelearningservices/registries"
STORAGE = "microsoft.storage/storageaccounts"
ADF = "microsoft.datafactory/factories"
SEARCH = "microsoft.search/searchservices"
FOUNDRY = "microsoft.cognitiveservices/accounts/projects"
FOUNDRY_ACCOUNT = "microsoft.cognitiveservices/accounts"
ACTIVITY_API = "2015-04-01"
METRICS_API = "2018-01-01"
MODEL_API = "2025-06-01"
FOUNDRY_ARM_API = "2025-06-01"
SEARCH_ARM_API = "2025-05-01"
SEARCH_API = "2025-09-01"
NEW_AGENT_API = "v1"
CLASSIC_AGENT_API = "2025-05-01"
AI_AUDIENCE = "https://ai.azure.com"
SEARCH_AUDIENCE = "https://search.azure.com"
SERVICE_NAME = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
CURSOR = re.compile(r"[A-Za-z0-9_.:-]{1,512}")
PAGING_KEYS = {"$skiptoken", "$skipToken", "skiptoken", "continuationToken", "after"}
ACTIVITY_PAGING_KEYS = PAGING_KEYS - {"after"}
UNAVAILABLE = "Read unavailable; access, connectivity, or API support could not be verified."
INCOMPLETE = "Incomplete response; no aggregate is reported."
INVALID = "Invalid response; no aggregate is reported."
METRIC_KEYS = ("activity", "agents", "models", "storage", "adf", "search")


class ObservationError(Exception):
    """A deliberately payload-free failure safe to display on a shared dashboard."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ObservationError(INVALID)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ObservationError(INVALID) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ObservationError(INVALID)
    return parsed.astimezone(timezone.utc)


def _number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 2**63 - 1
    return isinstance(value, float) and math.isfinite(value) and 0 <= value <= 2**63 - 1


def _metric(value=None, status="unavailable", detail=UNAVAILABLE, **extra) -> dict:
    return {"value": value, "status": status, "detail": detail, **extra}


def _resource_parts(identifier: str):
    match = RESOURCE_PATTERN.fullmatch(identifier)
    if not match:
        return None
    group, subscription, rg_name, namespace, tail = match.groups()
    pieces = tail.strip("/").split("/")
    kind = (namespace + "/" + "/".join(pieces[::2])).lower()
    return group, subscription, rg_name, kind, pieces[1::2]


def _url_parts(url: str):
    if not isinstance(url, str) or len(url) > 32768 or re.search(r"[\x00-\x20\\]", url):
        return None
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
            or parsed.port is not None or parsed.netloc.lower() != parsed.hostname
            or parsed.fragment or "%" in parsed.path
            or "//" in parsed.path or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            return None
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    query = dict(pairs)
    if len(query) != len(pairs) or any(not key or not value for key, value in pairs):
        return None
    return parsed, query


def _flags(args, command_length):
    values = {}
    cursor = command_length
    while cursor < len(args):
        key = args[cursor]
        if key in values or not key.startswith("--"):
            return None
        if key == "--only-show-errors":
            values[key] = True
            cursor += 1
        elif cursor + 1 < len(args) and not args[cursor + 1].startswith("--"):
            values[key] = args[cursor + 1]
            cursor += 2
        else:
            return None
    return values


def _valid_window(value: str) -> bool:
    parts = value.split("/")
    if len(parts) != 2:
        return False
    try:
        duration = _time(parts[1]) - _time(parts[0])
    except ObservationError:
        return False
    return timedelta(0) < duration <= timedelta(days=30)


def _valid_read_url(url: str, subscription: str, audience: str | None) -> bool:
    components = _url_parts(url)
    if components is None:
        return False
    parsed, query = components
    if parsed.hostname != "management.azure.com":
        return _valid_data_url(parsed, query, audience)
    if audience is not None:
        return False
    activity_path = f"/subscriptions/{subscription}/providers/microsoft.insights/eventtypes/management/values"
    if parsed.path.lower() == activity_path.lower():
        if (
            set(query) - {"api-version", "$filter", *ACTIVITY_PAGING_KEYS}
            or query.get("api-version", ACTIVITY_API) != ACTIVITY_API
        ):
            return False
        if "$filter" in query:
            expression = re.fullmatch(
                r"eventTimestamp ge '([^']+)' and eventTimestamp le '([^']+)' and resourceGroupName eq '([A-Za-z0-9_().-]{1,90})'",
                query["$filter"],
            )
            if not expression or not _valid_window("/".join(expression.groups()[:2])):
                return False
        return bool(
            ("api-version" in query and "$filter" in query)
            or any(key in query for key in ACTIVITY_PAGING_KEYS)
        )
    suffix = "/providers/microsoft.insights/metrics"
    if parsed.path.lower().endswith(suffix):
        resource = _resource_parts(parsed.path[:-len(suffix)])
        if not resource or resource[1].lower() != subscription.lower():
            return False
        if set(query) - {"api-version", "metricnames", "metricnamespace", "aggregation", "interval", "timespan", *PAGING_KEYS}:
            return False
        if query.get("api-version") != METRICS_API or not _valid_window(query.get("timespan", "")):
            return False
        if query.get("metricnamespace", "").lower() != resource[3]:
            return False
        return (
            resource[3] == STORAGE and query.get("metricnames") == "UsedCapacity"
            and query.get("aggregation") == "Average" and query.get("interval") == "PT1H"
        ) or (
            resource[3] == ADF
            and query.get("metricnames") == "PipelineSucceededRuns,PipelineFailedRuns,PipelineCancelledRuns"
            and query.get("aggregation") == "Total" and query.get("interval") == "FULL"
        )
    if parsed.path.lower().endswith("/models"):
        resource = _resource_parts(parsed.path[:-len("/models")])
        return bool(
            resource and resource[1].lower() == subscription.lower() and resource[3] in {ML, ML_REGISTRY}
            and query.get("api-version") == MODEL_API and query.get("listViewType") == "All"
            and not (set(query) - {"api-version", "listViewType", *PAGING_KEYS})
        )
    return False


def _valid_data_url(parsed, query, audience) -> bool:
    # Data-plane shapes are deliberately narrower than Azure CLI's generic GET.
    if (
        re.fullmatch(SERVICE_NAME + r"\.search\.windows\.net", parsed.hostname or "")
        and parsed.path == "/indexes" and audience == SEARCH_AUDIENCE
    ):
        return bool(
            query.get("api-version") == SEARCH_API and query.get("$select") == "name"
            and not (set(query) - {"api-version", "$select", *PAGING_KEYS})
        )
    if not (
        re.fullmatch(SERVICE_NAME + r"\.services\.ai\.azure\.com", parsed.hostname or "")
        and audience == AI_AUDIENCE
    ):
        return False
    path = re.fullmatch(rf"/api/projects/({SEGMENT})/(agents|assistants)", parsed.path)
    if not path or set(query) - {"api-version", "limit", "order", "after"}:
        return False
    return bool(
        query.get("api-version") == (NEW_AGENT_API if path[2] == "agents" else CLASSIC_AGENT_API)
        and query.get("limit") == "100" and query.get("order") == "asc"
        and ("after" not in query or CURSOR.fullmatch(query["after"]))
    )


def is_read_command(args) -> bool:
    """Allow only the exact known read shapes used here, with explicit subscription.

    Endpoint provenance is checked separately by Collector against discovered ARM
    metadata; a stateless predicate cannot establish endpoint ownership.
    """
    if not isinstance(args, (list, tuple)) or not args or any(not isinstance(arg, str) for arg in args):
        return False
    prefix = tuple(args[:2])
    if prefix in {("resource", "list"), ("resource", "show")}:
        flags = _flags(args, 2)
    elif args[0] == "rest":
        flags = _flags(args, 1)
    else:
        return False
    if flags is None or not re.fullmatch(GUID, flags.get("--subscription", "")):
        return False
    if flags.get("--output") != "json" or flags.get("--only-show-errors") is not True:
        return False
    common = {"--subscription", "--output", "--only-show-errors"}
    if prefix == ("resource", "list"):
        return bool(
            set(flags) == common | {"--resource-group", "--query"}
            and re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", flags["--resource-group"])
            and flags["--query"] == RESOURCE_QUERY
        )
    if prefix == ("resource", "show"):
        if set(flags) != common | {"--ids", "--api-version"}:
            return False
        parts = _resource_parts(flags["--ids"])
        return bool(
            parts and parts[1].lower() == flags["--subscription"].lower()
            and (
                (parts[3] == FOUNDRY and flags["--api-version"] == FOUNDRY_ARM_API)
                or (parts[3] == SEARCH and flags["--api-version"] == SEARCH_ARM_API)
            )
        )
    return bool(
        set(flags) in (common | {"--method", "--url"}, common | {"--method", "--url", "--resource"})
        and flags.get("--method") == "get"
        and _valid_read_url(flags["--url"], flags["--subscription"], flags.get("--resource"))
    )


class Collector:
    def __init__(self, az: Az, now: datetime | None = None):
        now = now if now is not None else datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Snapshot time must be timezone-aware.")
        self.az = az
        # Monitor FULL buckets start at minute grain, even for second-precision requests.
        self.now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
        self.start = self.now - timedelta(days=30)
        self._cache = {}

    def _read(self, subscription, *args):
        command = (*args, "--subscription", subscription, "--output", "json", "--only-show-errors")
        if not is_read_command(command):
            raise ObservationError(INVALID)
        try:
            result = self.az(*command)
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            # The dashboard launcher reports missing CLI/runtime and launch failures
            # as RuntimeError. Catch only at this transport boundary, never parsing.
            raise ObservationError(UNAVAILABLE) from None
        if result.returncode:
            raise ObservationError(UNAVAILABLE)
        if not isinstance(result.stdout, str):
            raise ObservationError(INVALID)
        if len(result.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ObservationError(INCOMPLETE)
        try:
            return json.loads(result.stdout)
        except (ValueError, RecursionError):
            raise ObservationError(INVALID) from None

    def _get(self, subscription, url, audience=None):
        extra = ("--resource", audience) if audience else ()
        return self._read(subscription, "rest", "--method", "get", "--url", url, *extra)

    def _pages(self, subscription, first, *, field="value", audience=None, cursor_paging=False, activity_paging=False):
        initial = _url_parts(first)
        if initial is None:
            raise ObservationError(INVALID)
        initial_url, initial_query = initial
        seen, rows = set(), 0
        current = first
        for _ in range(MAX_PAGES):
            parts = _url_parts(current)
            if parts is None:
                raise ObservationError(INCOMPLETE)
            parsed, query = parts
            immutable = {key: value for key, value in query.items() if key not in PAGING_KEYS}
            expected = {key: value for key, value in initial_query.items() if key not in PAGING_KEYS}
            arm_path = parsed.hostname == "management.azure.com"
            path = parsed.path.lower() if arm_path else parsed.path
            initial_path = initial_url.path.lower() if arm_path else initial_url.path
            same_query = (
                all(key in expected and expected[key] == value for key, value in immutable.items())
                if activity_paging else immutable == expected
            )
            identity = (parsed.scheme, parsed.netloc.lower(), path, tuple(sorted(query.items())))
            if (
                parsed.scheme != initial_url.scheme or parsed.netloc.lower() != initial_url.netloc.lower()
                or path != initial_path or not same_query or identity in seen
            ):
                raise ObservationError(INCOMPLETE)
            seen.add(identity)
            payload = self._get(subscription, current, audience)
            if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
                raise ObservationError(INVALID)
            page = payload[field]
            rows += len(page)
            if rows > MAX_ROWS or any(not isinstance(item, dict) for item in page):
                raise ObservationError(INCOMPLETE)
            yield page
            if any(
                payload.get(key) is not None and not isinstance(payload[key], str)
                for key in ("nextLink", "@odata.nextLink")
            ):
                raise ObservationError(INCOMPLETE)
            links = [payload[key] for key in ("nextLink", "@odata.nextLink") if payload.get(key)]
            if len(links) > 1 or payload.get("@search.nextPageParameters"):
                raise ObservationError(INCOMPLETE)
            if cursor_paging:
                if links or not isinstance(payload.get("has_more"), bool):
                    raise ObservationError(INCOMPLETE)
                if not payload["has_more"]:
                    return
                cursor = payload.get("last_id")
                if not page or not isinstance(cursor, str) or not CURSOR.fullmatch(cursor) or page[-1].get("id") != cursor:
                    raise ObservationError(INCOMPLETE)
                current = first.split("?", 1)[0] + "?" + urlencode({**initial_query, "after": cursor})
                continue
            if payload.get("has_more"):
                raise ObservationError(INCOMPLETE)
            next_url = links[0] if links else None
            if next_url in (None, ""):
                return
            if not isinstance(next_url, str):
                raise ObservationError(INCOMPLETE)
            current = next_url
        raise ObservationError(INCOMPLETE)

    def collect(self, resource_group_id: str) -> dict:
        match = RG_PATTERN.fullmatch(resource_group_id) if isinstance(resource_group_id, str) else None
        if not match:
            raise ValueError("A resource-group ARM ID is required.")
        cache_key = resource_group_id.lower()
        if cache_key in self._cache:
            return copy.deepcopy(self._cache[cache_key])
        subscription, rg_name = match.groups()
        metrics = {}
        try:
            metrics["activity"] = self._activity(subscription, rg_name, resource_group_id)
        except ObservationError as error:
            metrics["activity"] = _metric(detail=str(error))
        try:
            resources = self._resources(subscription, rg_name, resource_group_id)
        except ObservationError as error:
            metrics.update({key: _metric(detail=str(error)) for key in METRIC_KEYS if key != "activity"})
        else:
            for key in METRIC_KEYS[1:]:
                try:
                    metrics[key] = getattr(self, "_" + key)(subscription, resources)
                except ObservationError as error:
                    metrics[key] = _metric(detail=str(error))
        result = {
            "observedAt": _iso(self.now), "windowStart": _iso(self.start),
            "windowEnd": _iso(self.now), "metrics": metrics,
        }
        self._cache[cache_key] = copy.deepcopy(result)
        return result

    def _resources(self, subscription, rg_name, group):
        payload = self._read(
            subscription, "resource", "list", "--resource-group", rg_name, "--query", RESOURCE_QUERY,
        )
        if not isinstance(payload, list):
            raise ObservationError(INVALID)
        if len(payload) > MAX_ROWS:
            raise ObservationError(INCOMPLETE)
        found = {}
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ObservationError(INVALID)
            if item["type"].lower() not in {ML, ML_REGISTRY, STORAGE, ADF, SEARCH, FOUNDRY, FOUNDRY_ACCOUNT}:
                continue
            if not all(isinstance(item.get(key), str) for key in ("id", "name")):
                raise ObservationError(INVALID)
            parts = _resource_parts(item["id"])
            if (
                not parts or parts[0].lower() != group.lower() or parts[3] != item["type"].lower()
                or item["name"].lower() not in {parts[4][-1].lower(), "/".join(parts[4]).lower()}
                or (item.get("kind") is not None and not isinstance(item["kind"], str))
            ):
                raise ObservationError(INVALID)
            key = item["id"].lower()
            if key in found and found[key] != item:
                raise ObservationError(INVALID)
            found[key] = item
        return list(found.values())

    def _activity(self, subscription, rg_name, group):
        query = urlencode({
            "api-version": ACTIVITY_API,
            "$filter": f"eventTimestamp ge '{_iso(self.start)}' and eventTimestamp le '{_iso(self.now)}' and resourceGroupName eq '{rg_name}'",
        })
        url = f"{ARM}/subscriptions/{subscription}/providers/microsoft.insights/eventtypes/management/values?{query}"
        classifications = {}
        for page in self._pages(subscription, url, activity_paging=True):
            for item in page:
                resource_id = item.get("resourceId")
                if not isinstance(resource_id, str):
                    raise ObservationError(INVALID)
                if not (resource_id.lower() == group.lower() or resource_id.lower().startswith(group.lower() + "/")):
                    continue
                event_group = item.get("resourceGroupName")
                if event_group is not None and (not isinstance(event_group, str) or event_group.lower() != rg_name.lower()):
                    continue
                timestamp = _time(item.get("eventTimestamp"))
                if timestamp < self.start or timestamp > self.now:
                    continue
                identifier = item.get("eventDataId")
                if not isinstance(identifier, str) or not identifier:
                    raise ObservationError(INVALID)
                identifier = identifier.lower()
                classification = self._identity(item)
                if identifier in classifications and classifications[identifier] != classification:
                    raise ObservationError(INCOMPLETE)
                classifications[identifier] = classification
        count = sum(value == "counted" for value in classifications.values())
        unknown = sum(value == "unknown" for value in classifications.values())
        return _metric(
            None if unknown else count, "unavailable" if unknown else "ok",
            "Email-caller Activity Log events in the last 30 days with positive user/delegated-scope claims; app/managed identities excluded. Delegated automation may remain."
            + (" Unclassified identities prevent a complete count." if unknown else ""),
            classifiedEvents=count, unclassifiedEvents=unknown,
        )

    @staticmethod
    def _identity(item):
        caller = item.get("caller")
        if caller is None or caller == "":
            return "excluded"
        if not isinstance(caller, str):
            return "unknown"
        if not EMAIL.fullmatch(caller):
            return "excluded"
        claims = item.get("claims")
        if isinstance(claims, str):
            try:
                claims = json.loads(claims)
            except (ValueError, RecursionError):
                return "unknown"
        if not isinstance(claims, dict):
            return "unknown"
        if any(
            (key.rsplit("/", 1)[-1].lower() == "idtyp" and isinstance(value, str) and value.lower() == "app")
            or (key.rsplit("/", 1)[-1].lower() == "xms_mirid" and value)
            for key, value in claims.items()
        ):
            return "excluded"
        if any(not isinstance(value, str) for value in claims.values()):
            return "unknown"
        if any(
            isinstance(value, str) and (
                (key.rsplit("/", 1)[-1].lower() == "idtyp" and value.lower() == "user")
                or (key in {"scp", "http://schemas.microsoft.com/identity/claims/scope"} and bool(value.strip()))
            )
            for key, value in claims.items()
        ):
            return "counted"
        return "unknown"

    def _agents(self, subscription, resources):
        projects = self._matching(resources, FOUNDRY)
        legacy_projects = [
            item for item in self._matching(resources, ML) if str(item.get("kind", "")).lower() == "project"
        ]
        if not projects:
            if legacy_projects or any(
                str(item.get("kind", "")).lower() == "aiservices"
                for item in self._matching(resources, FOUNDRY_ACCOUNT)
            ):
                return _metric(detail="No supported Foundry project endpoint was discovered; agent inventory is unavailable.")
            return self._absent()
        endpoints = []
        endpoint_failure = bool(legacy_projects)
        for project in projects:
            try:
                endpoints.append(self._project_endpoint(subscription, project))
            except ObservationError:
                endpoint_failure = True
        counts, statuses = {}, {}
        for population, path, version in (
            ("new", "agents", NEW_AGENT_API), ("classic", "assistants", CLASSIC_AGENT_API),
        ):
            identities = set()
            failed = endpoint_failure
            for endpoint in endpoints:
                try:
                    url = endpoint + "/" + path + "?" + urlencode({
                        "api-version": version, "limit": "100", "order": "asc",
                    })
                    for page in self._pages(subscription, url, field="data", audience=AI_AUDIENCE, cursor_paging=True):
                        for item in page:
                            identifier = item.get("id")
                            if not isinstance(identifier, str) or not CURSOR.fullmatch(identifier):
                                raise ObservationError(INVALID)
                            identities.add((endpoint, identifier))
                except ObservationError:
                    failed = True
            counts[population] = None if failed else len(identities)
            statuses[population] = "unavailable" if failed else "ok"
        complete = all(value is not None for value in counts.values())
        return _metric(
            sum(counts.values()) if complete else None, "ok" if complete else "unavailable",
            "Foundry inventory: new agents (v1) and classic assistants (2025-05-01) are separate populations, not versions or runtime traffic."
            + ("" if complete else " One or more populations could not be completely read."),
            newCount=counts["new"], classicCount=counts["classic"],
            newStatus=statuses["new"], classicStatus=statuses["classic"],
            resourceCount=len(projects) + len(legacy_projects),
        )

    def _project_endpoint(self, subscription, project):
        payload = self._read(
            subscription, "resource", "show", "--ids", project["id"], "--api-version", FOUNDRY_ARM_API,
        )
        if (
            not isinstance(payload, dict) or not isinstance(payload.get("id"), str)
            or payload["id"].lower() != project["id"].lower()
        ):
            raise ObservationError(INVALID)
        properties = payload.get("properties")
        endpoints = properties.get("endpoints") if isinstance(properties, dict) else None
        endpoint = endpoints.get("AI Foundry API") if isinstance(endpoints, dict) else None
        parts = _url_parts(endpoint) if isinstance(endpoint, str) else None
        if parts is None:
            raise ObservationError(INVALID)
        parsed, query = parts
        project_name = _resource_parts(project["id"])[4][-1]
        if (
            query or parsed.query or not re.fullmatch(SERVICE_NAME + r"\.services\.ai\.azure\.com", parsed.hostname or "")
            or parsed.path.lower() != "/api/projects/" + project_name.lower()
        ):
            raise ObservationError(INVALID)
        return endpoint

    def _models(self, subscription, resources):
        workspaces = [
            item for item in self._matching(resources, ML)
            if str(item.get("kind", "")).lower() not in {"hub", "project"}
        ] + self._matching(resources, ML_REGISTRY)
        if not workspaces:
            return self._absent()
        identities = {}
        for workspace in workspaces:
            prefix = workspace["id"] + "/models/"
            url = ARM + workspace["id"] + "/models?" + urlencode({
                "api-version": MODEL_API, "listViewType": "All",
            })
            for page in self._pages(subscription, url):
                for item in page:
                    identifier, properties = item.get("id"), item.get("properties")
                    if (
                        not isinstance(identifier, str) or not identifier.lower().startswith(prefix.lower())
                        or not re.fullmatch(SEGMENT, identifier[len(prefix):])
                        or not isinstance(properties, dict) or not isinstance(properties.get("isArchived", False), bool)
                    ):
                        raise ObservationError(INVALID)
                    identity = identifier.lower()
                    archived = properties.get("isArchived", False)
                    if identity in identities and identities[identity] != archived:
                        raise ObservationError(INCOMPLETE)
                    identities[identity] = archived
        return _metric(
            len(identities), "ok",
            "Distinct registered AML model containers across workspaces and registries, including archived containers; not model versions or deployments.",
            archivedCount=sum(identities.values()), resourceCount=len(workspaces),
        )

    def _storage(self, subscription, resources):
        accounts = self._matching(resources, STORAGE)
        if not accounts:
            return self._absent()
        total, samples = 0, []
        for account in accounts:
            metrics = self._monitor(subscription, account, ["UsedCapacity"], "Average", "PT1H", self.now - STORAGE_MAX_AGE)
            points = self._points(metrics["UsedCapacity"], "Bytes")
            available = []
            for point in points:
                timestamp = _time(point.get("timeStamp"))
                if not self.now - STORAGE_MAX_AGE <= timestamp <= self.now:
                    continue
                value = point.get("average")
                if value is None:
                    continue
                if not _number(value):
                    raise ObservationError(INVALID)
                available.append((timestamp, value))
            if not available:
                raise ObservationError("No recent UsedCapacity Average sample is available; no aggregate is reported.")
            timestamp, value = max(available, key=lambda pair: pair[0])
            if any(other_value != value for other_time, other_value in available if other_time == timestamp):
                raise ObservationError(INVALID)
            total += value
            samples.append(timestamp)
        if not _number(total):
            raise ObservationError(INVALID)
        return _metric(
            total, "ok", "Sum of each storage account's latest non-null UsedCapacity Average sample within 48 hours; not a sum over time.",
            unit="Bytes", resourceCount=len(accounts), oldestSampleAt=_iso(min(samples)),
        )

    def _adf(self, subscription, resources):
        factories = self._matching(resources, ADF)
        if not factories:
            return self._absent()
        names = ["PipelineSucceededRuns", "PipelineFailedRuns", "PipelineCancelledRuns"]
        total = 0
        for factory in factories:
            metrics = self._monitor(subscription, factory, names, "Total", "FULL", self.start)
            for name in names:
                points = self._points(metrics[name], "Count")
                samples = {}
                for point in points:
                    timestamp = _time(point.get("timeStamp"))
                    if not self.start <= timestamp <= self.now:
                        continue
                    value = point.get("total")
                    if not _number(value) or int(value) != value:
                        raise ObservationError(INCOMPLETE)
                    if timestamp in samples and samples[timestamp] != value:
                        raise ObservationError(INVALID)
                    samples[timestamp] = value
                if not samples:
                    raise ObservationError("Completed-run metric samples are unavailable; no aggregate is reported.")
                total += sum(samples.values())
        if not _number(total):
            raise ObservationError(INVALID)
        return _metric(
            int(total), "ok",
            "Sum of PipelineSucceededRuns, PipelineFailedRuns and PipelineCancelledRuns Total samples in the last 30 days.",
            resourceCount=len(factories),
        )

    def _search(self, subscription, resources):
        services = self._matching(resources, SEARCH)
        if not services:
            return self._absent()
        identities = set()
        for service in services:
            endpoint = self._search_endpoint(subscription, service)
            url = endpoint + "/indexes?" + urlencode({
                "api-version": SEARCH_API, "$select": "name",
            })
            for page in self._pages(subscription, url, audience=SEARCH_AUDIENCE):
                for item in page:
                    index = item.get("name")
                    if not isinstance(index, str) or not index:
                        raise ObservationError(INVALID)
                    identities.add((service["id"].lower(), index))
        return _metric(
            len(identities), "ok", "Current AI Search index inventory from the read-only index list API; not indexed documents or requests.",
            resourceCount=len(services),
        )

    def _search_endpoint(self, subscription, service):
        payload = self._read(
            subscription, "resource", "show", "--ids", service["id"], "--api-version", SEARCH_ARM_API,
        )
        if (
            not isinstance(payload, dict) or not isinstance(payload.get("id"), str)
            or payload["id"].lower() != service["id"].lower()
        ):
            raise ObservationError(INVALID)
        properties = payload.get("properties")
        endpoint = properties.get("endpoint") if isinstance(properties, dict) else None
        parts = _url_parts(endpoint) if isinstance(endpoint, str) else None
        if parts is None:
            raise ObservationError(INVALID)
        parsed, query = parts
        name = _resource_parts(service["id"])[4][-1].lower()
        if (
            not re.fullmatch(SERVICE_NAME, name) or parsed.hostname != name + ".search.windows.net"
            or parsed.path not in {"", "/"} or query or parsed.query
        ):
            raise ObservationError(INVALID)
        return endpoint.rstrip("/")

    def _monitor(self, subscription, resource, names, aggregation, interval, start):
        url = ARM + resource["id"] + "/providers/microsoft.insights/metrics?" + urlencode({
            "api-version": METRICS_API, "metricnamespace": resource["type"],
            "metricnames": ",".join(names), "aggregation": aggregation,
            "interval": interval, "timespan": _iso(start) + "/" + _iso(self.now),
        })
        metrics = {}
        for page in self._pages(subscription, url):
            for item in page:
                name = item.get("name")
                name = name.get("value") if isinstance(name, dict) else None
                if name not in names or name in metrics:
                    raise ObservationError(INVALID)
                if item.get("errorCode") not in (None, "", "Success"):
                    raise ObservationError(UNAVAILABLE)
                metrics[name] = item
        if set(metrics) != set(names):
            raise ObservationError(INCOMPLETE)
        return metrics

    @staticmethod
    def _points(metric, unit):
        if metric.get("unit") != unit:
            raise ObservationError(INVALID)
        series = metric.get("timeseries")
        if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
            raise ObservationError(INCOMPLETE)
        # Requests do not split by dimensions: adding overlapping series would overcount.
        if series[0].get("metadatavalues") not in (None, []):
            raise ObservationError(INCOMPLETE)
        points = series[0].get("data")
        if not isinstance(points, list) or len(points) > MAX_ROWS or any(not isinstance(item, dict) for item in points):
            raise ObservationError(INCOMPLETE)
        return points

    @staticmethod
    def _matching(resources, kind):
        return [item for item in resources if item["type"].lower() == kind]

    @staticmethod
    def _absent():
        return _metric(status="not-deployed", detail="No matching service was discovered in this resource group.")
