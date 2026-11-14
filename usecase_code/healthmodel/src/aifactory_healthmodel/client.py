"""Runtime client for an AI Factory health model: read health, history and alerts, set alerts.

Bridge pattern: ``HealthModelClient`` is the abstraction, the ARM transport
(``request(method, url, body) -> dict | None``) the implementation.
``infrastructure.azure_cli.AzCliTransport`` uses the signed-in Azure CLI;
``infrastructure.identity.TokenTransport`` uses any azure-identity credential (managed
identity in an app, DefaultAzureCredential locally). Decorators add retries and a circuit
breaker, and ``ReadOnlyTransport`` guarantees read-only use (``bootstrap.runtime_transport``).
"""
from __future__ import annotations

import copy
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote

from .catalog import HEALTH_STATES, NAME_PATTERN, SEVERITIES

ARM = "https://management.azure.com"
API_VERSION = "2026-09-01-preview"
ALERTS_API_VERSION = "2025-05-25-preview"
MANAGED_BY = "aifactory-healthmodel"
UNCHANGED = object()

MODEL_ID = re.compile(
    r"/subscriptions/(?P<sub>[0-9a-f-]{36})/resourceGroups/(?P<rg>[\w().-]{1,90})/providers/"
    r"Microsoft\.CloudHealth/healthmodels/(?P<name>[a-zA-Z][a-zA-Z0-9-]{1,42}[a-zA-Z0-9])", re.I)
ALERT_ID = re.compile(
    r"/subscriptions/[0-9a-f-]{36}(?:/resourceGroups/[\w().-]{1,90}/providers/Microsoft\.CloudHealth/healthmodels/"
    r"[a-zA-Z0-9-]{3,44})?/providers/Microsoft\.AlertsManagement/alerts/[0-9a-zA-Z-]+", re.I)
ACTION_GROUP_ID = re.compile(
    r"/subscriptions/[0-9a-f-]{36}/resourceGroups/[\w().-]{1,90}/providers/microsoft\.insights/actiongroups/[^/]+", re.I)
TIME_RANGES = {1: "1h", 24: "1d", 168: "7d", 720: "30d"}
ALERT_STATES = ("New", "Acknowledged", "Closed")
READ_ONLY_ENTITY_FIELDS = ("healthState", "provisioningState", "discoveredBy", "deletionDate")
SEVERITY_ORDER = {"Unhealthy": 0, "Degraded": 1, "Unknown": 2, "Healthy": 3}


class HealthModelError(RuntimeError):
    """An Azure Resource Manager call failed; carries the ARM error code."""

    def __init__(self, message: str, code: str = "AzureRequestFailed", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def _utc(hours: float) -> tuple[str, str]:
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=hours)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


class HealthModelClient:
    def __init__(self, model_id: str, transport, api_version: str = API_VERSION, sleep=time.sleep):
        match = MODEL_ID.fullmatch(model_id or "")
        if not match:
            raise ValueError("model_id must be a Microsoft.CloudHealth/healthmodels resource ID.")
        self.model_id = model_id
        self.subscription_id = match["sub"]
        self.resource_group = match["rg"]
        self.name = match["name"]
        self.transport = transport
        self.api_version = api_version
        self._sleep = sleep

    @classmethod
    def from_names(cls, subscription_id: str, resource_group: str, name: str, transport, **kwargs):
        return cls(f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
                   f"Microsoft.CloudHealth/healthmodels/{name}", transport, **kwargs)

    # ------------------------------------------------------------------ helpers
    def _url(self, path: str = "", api_version: str | None = None, **query) -> str:
        params = {"api-version": api_version or self.api_version, **{k: v for k, v in query.items() if v is not None}}
        return f"{ARM}{self.model_id}{path}?{urlencode(params)}"

    def _entity_path(self, entity: str) -> str:
        entity = self.name if entity in ("root", "", None) else entity
        if not NAME_PATTERN.fullmatch(entity) and entity != self.name:
            raise ValueError(f"Invalid entity name: {entity!r}")
        return f"/entities/{quote(entity)}"

    def _list(self, url: str) -> list:
        items = []
        while url:
            page = self.transport.request("GET", url) or {}
            items.extend(page.get("value", []))
            url = page.get("nextLink")
        return items

    # ------------------------------------------------------------------ reads
    def model(self) -> dict:
        return self.transport.request("GET", self._url())

    def entities(self) -> list[dict]:
        return self._list(self._url("/entities"))

    def entity(self, name: str) -> dict:
        return self.transport.request("GET", self._url(self._entity_path(name)))

    def relationships(self) -> list[dict]:
        return self._list(self._url("/relationships"))

    def summary(self) -> dict:
        """Root, layer and leaf health with the signals that are degraded or unhealthy."""
        entities = {e["name"]: e for e in self.entities()}
        relationships = self.relationships()
        children, parent = {}, {}
        for rel in relationships:
            props = rel.get("properties", {})
            children.setdefault(props.get("parentEntityName"), []).append(props.get("childEntityName"))
            parent.setdefault(props.get("childEntityName"), props.get("parentEntityName"))

        def state(name):
            return (entities.get(name, {}).get("properties", {}).get("healthState")) or "Unknown"

        def display(name):
            return entities.get(name, {}).get("properties", {}).get("displayName") or name

        def path(name):
            chain, seen = [], set()
            while name and name not in seen:
                seen.add(name)
                chain.append(display(name))
                name = parent.get(name)
            return list(reversed(chain))

        leaves = [n for n in entities if n != self.name and not children.get(n)]
        # Leaves, plus any entity (the root included) whose own signals, such as an
        # external report, are failing.
        candidates = [n for n in entities
                      if (n != self.name and not children.get(n)) or failing_signals(entities[n])]
        problems = sorted((n for n in candidates if state(n) in ("Unhealthy", "Degraded")),
                          key=lambda n: (SEVERITY_ORDER[state(n)], n))
        errors = [{"entity": n, "displayName": display(n), **item}
                  for n in sorted(entities) for item in signal_errors(entities[n])]
        hints = []
        if any("authorization" in e["error"].lower() or "permission" in e["error"].lower() for e in errors):
            hints.append("Some signals cannot read data: grant the health model identity Monitoring Reader on the "
                         "monitored resource groups (deploy assigns it; new assignments can take up to 30 minutes).")
        return {
            "model": self.name,
            "root": {"name": self.name, "displayName": display(self.name), "state": state(self.name)},
            "layers": [{"name": n, "displayName": display(n), "state": state(n)} for n in children.get(self.name, [])],
            "counts": dict(Counter(state(n) for n in entities)),
            "problems": [{"name": n, "displayName": display(n), "state": state(n), "path": path(n),
                          "signals": failing_signals(entities[n])} for n in problems],
            "unknown": [{"name": n, "displayName": display(n)} for n in leaves if state(n) == "Unknown"],
            "signalErrors": errors,
            "hints": hints,
        }

    def history(self, entity: str, hours: float = 24, top: int = 1000) -> list[dict]:
        start, end = _utc(hours)
        body = {"startAt": start, "endAt": end, "top": top}
        return (self.transport.request("POST", self._url(self._entity_path(entity) + "/getHistory"), body)
                or {}).get("history", [])

    def signal_history(self, entity: str, signal: str, hours: float = 24, top: int = 1000) -> list[dict]:
        start, end = _utc(hours)
        body = {"signalName": signal, "startAt": start, "endAt": end, "top": top}
        return (self.transport.request("POST", self._url(self._entity_path(entity) + "/getSignalHistory"), body)
                or {}).get("history", [])

    def annotations(self, entity: str = "root", hours: float = 24) -> list[dict]:
        start, end = _utc(hours)
        response = self.transport.request("POST", self._url(self._entity_path(entity) + "/getDataAnnotations"),
                                          {"startAt": start, "endAt": end, "top": 100})
        return (response or {}).get("annotations", [])

    # ------------------------------------------------------------------ writes
    def ingest_health_report(self, entity: str, signal: str, state: str, *, value: float | None = None,
                             expires_in_minutes: int = 60, context: str | None = None,
                             evaluation_rules: dict | None = None) -> None:
        """Report an externally evaluated signal (synthetic probe, pipeline smoke test, on-premises check)."""
        if state not in HEALTH_STATES:
            raise ValueError(f"state must be one of {HEALTH_STATES}.")
        if not NAME_PATTERN.fullmatch(signal or "") or len(signal) > 260:
            raise ValueError("signal must be 3-260 letters, digits or hyphens.")
        if not 1 <= int(expires_in_minutes) <= 10080:
            raise ValueError("expires_in_minutes must be between 1 and 10080.")
        if context is not None and len(context) > 4096:
            raise ValueError("context is limited to 4096 characters.")
        body = {"signalName": signal, "healthState": state}
        if value is not None:
            body["value"] = value
        if evaluation_rules is not None:
            body["evaluationRules"] = evaluation_rules
        body["expiresInMinutes"] = int(expires_in_minutes)
        if context:
            body["additionalContext"] = context
        self.transport.request("POST", self._url(self._entity_path(entity) + "/ingestHealthReport"), body)

    def add_annotation(self, entity: str, details: dict, description: str | None = None) -> dict:
        """Mark a deployment, incident or change on the health timeline."""
        if not details or len(details) > 10:
            raise ValueError("Annotations need 1-10 detail entries.")
        if any(not isinstance(v, str) or len(v) > 256 for v in details.values()):
            raise ValueError("Annotation detail values must be strings of at most 256 characters.")
        body = {"annotationDetails": dict(details)}
        if description:
            body["description"] = description[:4096]
        return self.transport.request("POST", self._url(self._entity_path(entity) + "/addDataAnnotation"), body)

    def set_entity_alerts(self, entity: str, *, unhealthy=UNCHANGED, degraded=UNCHANGED,
                          wait_seconds: int = 120) -> dict:
        """Change health-state alerts of one entity.

        A dict changes only the fields it contains (existing action groups and description are kept;
        pass ``actionGroupIds: []`` to clear them). None disables the alert, UNCHANGED keeps it.
        """
        current = self.entity(entity)
        properties = writable_properties(current.get("properties", {}))
        alerts = dict(properties.get("alerts") or {})
        label = properties.get("displayName") or entity
        for key, change in (("unhealthy", unhealthy), ("degraded", degraded)):
            if change is UNCHANGED:
                continue
            if change is None:
                alerts.pop(key, None)
            else:
                if not isinstance(change, dict):
                    raise ValueError("Alert configuration must be an object.")
                alerts[key] = validate_alert({**(alerts.get(key) or {}), **change}, f"{label} is {key}.")
        properties["alerts"] = alerts
        result = self.transport.request("PUT", self._url(self._entity_path(entity)), {"properties": properties})
        return self._wait_for_entity(entity, result, wait_seconds)

    def _wait_for_entity(self, entity: str, result: dict | None, wait_seconds: int) -> dict:
        deadline = time.monotonic() + wait_seconds
        while True:
            provisioning = ((result or {}).get("properties") or {}).get("provisioningState")
            if provisioning in (None, "Succeeded"):
                return result or {}
            if provisioning in ("Failed", "Canceled"):
                raise HealthModelError(f"Updating entity {entity} ended in state {provisioning}.", "EntityUpdateFailed")
            if time.monotonic() > deadline:
                raise HealthModelError(f"Timed out waiting for entity {entity} to update.", "EntityUpdateTimeout")
            self._sleep(5)
            result = self.entity(entity)

    def delete_entity(self, name: str) -> None:
        if name == self.name:
            raise ValueError("The root entity cannot be deleted.")
        self.transport.request("DELETE", self._url(self._entity_path(name)))

    def delete_relationship(self, name: str) -> None:
        if not NAME_PATTERN.fullmatch(name or ""):
            raise ValueError(f"Invalid relationship name: {name!r}")
        self.transport.request("DELETE", self._url(f"/relationships/{quote(name)}"))

    def stale_managed(self, desired_entities: set[str], desired_relationships: set[str]) -> dict:
        """Entities/relationships created by this tool that are no longer in the plan."""
        def managed(item):
            return (item.get("properties", {}).get("tags") or {}).get("managedBy") == MANAGED_BY
        return {
            "entities": sorted(e["name"] for e in self.entities()
                               if managed(e) and e["name"] not in desired_entities and e["name"] != self.name),
            "relationships": sorted(r["name"] for r in self.relationships()
                                    if managed(r) and r["name"] not in desired_relationships),
        }

    # ------------------------------------------------------------------ alerts
    def alerts(self, hours: int = 24, state: str | None = None) -> list[dict]:
        """Azure Monitor alerts fired by this health model (entity health-state alerts)."""
        if hours not in TIME_RANGES:
            raise ValueError(f"hours must be one of {sorted(TIME_RANGES)} (Alerts Management time ranges).")
        if state is not None and state not in ALERT_STATES:
            raise ValueError(f"state must be one of {ALERT_STATES}.")
        query = {"api-version": ALERTS_API_VERSION, "targetResourceGroup": self.resource_group,
                 "timeRange": TIME_RANGES[hours], "includeContext": "true"}
        if state:
            query["alertState"] = state
        url = f"{ARM}/subscriptions/{self.subscription_id}/providers/Microsoft.AlertsManagement/alerts?{urlencode(query)}"
        prefix = self.model_id.lower()
        rows = []
        for item in self._list(url):
            properties = item.get("properties", {})
            essentials = properties.get("essentials", {})
            context = properties.get("context") or {}
            target = (essentials.get("targetResource") or "")
            if not target.lower().startswith(prefix):
                continue
            rows.append({
                "id": item.get("id"), "name": item.get("name"),
                "entity": context.get("entityName") or _entity_from(target) or self.name,
                "entityDisplayName": context.get("entityDisplayName"),
                "severity": essentials.get("severity"), "state": essentials.get("alertState"),
                "condition": essentials.get("monitorCondition"), "firedAt": essentials.get("startDateTime"),
                "resolvedAt": essentials.get("monitorConditionResolvedDateTime"),
                "description": essentials.get("description"), "monitorService": essentials.get("monitorService"),
                "timeline": context.get("linkToHealthTimeline"),
            })
        return rows

    def change_alert_state(self, alert_id: str, new_state: str, comment: str | None = None) -> dict:
        if not ALERT_ID.fullmatch(alert_id or ""):
            raise ValueError("alert_id must be an Alerts Management alert resource ID.")
        if new_state not in ALERT_STATES:
            raise ValueError(f"new_state must be one of {ALERT_STATES}.")
        query = urlencode({"api-version": ALERTS_API_VERSION, "newState": new_state})
        return self.transport.request("POST", f"{ARM}{alert_id}/changestate?{query}",
                                      {"comments": comment} if comment else None)


def _entity_from(resource_id: str) -> str | None:
    match = re.search(r"/entities/([^/?#]+)", resource_id or "", re.I)
    return match.group(1) if match else None


def failing_signals(entity: dict) -> list[dict]:
    """Signals of an entity whose last evaluation is Degraded or Unhealthy."""
    rows = []
    for group_name, group in (entity.get("properties", {}).get("signalGroups") or {}).items():
        if not isinstance(group, dict):
            continue
        for signal in group.get("signals") or []:
            status = signal.get("status") or {}
            if status.get("healthState") in ("Degraded", "Unhealthy"):
                rows.append({"name": signal.get("name"), "displayName": signal.get("displayName") or signal.get("name"),
                             "state": status.get("healthState"), "value": status.get("value"),
                             "reportedAt": status.get("reportedAt")})
        health = (group.get("resourceHealth") or {}).get("status") or {}
        if health.get("healthState") in ("Degraded", "Unhealthy"):
            rows.append({"name": "resource-health", "displayName": "Azure Resource Health",
                         "state": health["healthState"], "value": health.get("value"),
                         "reportedAt": health.get("reportedAt")})
    return sorted(rows, key=lambda r: (SEVERITY_ORDER.get(r["state"], 9), r["name"] or ""))


def signal_errors(entity: dict) -> list[dict]:
    """Signals whose last evaluation failed (missing RBAC, invalid metric, query error)."""
    rows = []
    for group in (entity.get("properties", {}).get("signalGroups") or {}).values():
        if not isinstance(group, dict):
            continue
        for signal in group.get("signals") or []:
            error = (signal.get("status") or {}).get("error")
            if error:
                rows.append({"signal": signal.get("name"), "error": str(error)[:500]})
        error = ((group.get("resourceHealth") or {}).get("status") or {}).get("error")
        if error:
            rows.append({"signal": "resource-health", "error": str(error)[:500]})
    return rows


def writable_properties(properties: dict) -> dict:
    """Entity properties that can be sent back in a PUT (read-only state removed)."""
    properties = copy.deepcopy(properties)
    for field in READ_ONLY_ENTITY_FIELDS:
        properties.pop(field, None)
    groups = properties.get("signalGroups") or {}
    groups.pop("external", None)
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        for signal in group.get("signals") or []:
            signal.pop("status", None)
        if isinstance(group.get("resourceHealth"), dict):
            group["resourceHealth"] = {"enabled": group["resourceHealth"].get("enabled", "Enabled")}
        group.pop("status", None)
    return properties


def validate_alert(config: dict, default_description: str) -> dict:
    if not isinstance(config, dict):
        raise ValueError("Alert configuration must be an object.")
    unknown = set(config) - {"severity", "description", "actionGroupIds"}
    if unknown:
        raise ValueError(f"Unsupported alert fields: {sorted(unknown)}")
    if config.get("severity") not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}.")
    description = config.get("description", default_description)
    if not isinstance(description, str) or not 1 <= len(description) <= 1000:
        raise ValueError("description must be 1-1000 characters.")
    groups = list(config.get("actionGroupIds") or [])
    if len(groups) > 5:
        raise ValueError("At most five action groups can be notified per entity.")
    for group in groups:
        if not ACTION_GROUP_ID.fullmatch(group):
            raise ValueError(f"Not an action group resource ID: {group!r}")
    result = {"severity": config["severity"], "description": description}
    if groups:
        result["actionGroupIds"] = groups
    return result
