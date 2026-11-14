"""Read-only, MCP-ready tool definitions for AI Factory health models.

``TOOLS`` follows the Model Context Protocol tool shape (name, description,
inputSchema, annotations) so an MCP server, such as the AI Factory MCP
package, can register them unchanged. ``call_tool`` validates arguments and
dispatches to a ``HealthModelClient`` created by the host's factory, so the
host decides authentication and authorization. There are deliberately no
write tools: alert changes and health reports stay operator actions.
"""
from __future__ import annotations

import re

from .client import ALERT_STATES, MODEL_ID, TIME_RANGES

MODEL_ID_SCHEMA = {"type": "string", "minLength": 80, "maxLength": 400,
                   "description": "Resource ID of the Microsoft.CloudHealth/healthmodels resource: "
                                  "/subscriptions/{id}/resourceGroups/{rg}/providers/Microsoft.CloudHealth/healthmodels/{name}. "
                                  "Validated server-side (case-insensitive)."}
ENTITY_SCHEMA = {"type": "string", "pattern": r"^(root|[a-zA-Z0-9][a-zA-Z0-9-]{1,258}[a-zA-Z0-9])$",
                 "description": "Entity name, or 'root' for the whole workload."}
HOURS_SCHEMA = {"type": "number", "minimum": 1, "maximum": 720, "description": "Look-back window in hours."}
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {"modelId": MODEL_ID_SCHEMA, **properties},
            "required": ["modelId", *required], "additionalProperties": False}


TOOLS = [
    {
        "name": "healthmodel_summary",
        "title": "AI Factory health summary",
        "description": "Current health of an AI Factory Azure Monitor health model: root and layer states, "
                       "degraded or unhealthy resources with their failing signals, and resources without data.",
        "inputSchema": _schema({}, []),
        "annotations": READ_ONLY,
    },
    {
        "name": "healthmodel_alerts",
        "title": "AI Factory health alerts",
        "description": "Azure Monitor alerts fired by the health model when an entity became degraded or "
                       "unhealthy, with severity, state (New, Acknowledged, Closed) and the affected entity.",
        "inputSchema": _schema({
            "hours": {"type": "integer", "enum": sorted(TIME_RANGES), "default": 24,
                      "description": "Time range: 1, 24, 168 (7 days) or 720 (30 days) hours."},
            "state": {"type": "string", "enum": list(ALERT_STATES)},
        }, []),
        "annotations": READ_ONLY,
    },
    {
        "name": "healthmodel_entity_history",
        "title": "Entity health history",
        "description": "Health state transitions of one health model entity (or the root) in a time window, "
                       "to see when and how often a component became degraded or unhealthy.",
        "inputSchema": _schema({"entity": ENTITY_SCHEMA, "hours": HOURS_SCHEMA}, ["entity"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "healthmodel_signal_history",
        "title": "Signal history",
        "description": "Values and health states of one signal on one entity over time, for example the "
                       "model availability or throttled calls of an AI Foundry account.",
        "inputSchema": _schema({"entity": ENTITY_SCHEMA, "signal": {"type": "string", "pattern": r"^[a-zA-Z0-9][a-zA-Z0-9-]{1,258}[a-zA-Z0-9]$"},
                                "hours": HOURS_SCHEMA}, ["entity", "signal"]),
        "annotations": READ_ONLY,
    },
]
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def validate(arguments: dict, schema: dict) -> dict:
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    properties = schema["properties"]
    unknown = set(arguments) - set(properties)
    if unknown and schema.get("additionalProperties") is False:
        raise ValueError(f"Unknown arguments: {sorted(unknown)}")
    for name in schema["required"]:
        if name not in arguments:
            raise ValueError(f"Missing required argument: {name}")
    for name, value in arguments.items():
        rule = properties[name]
        kind = rule["type"]
        if kind == "string" and not isinstance(value, str):
            raise ValueError(f"{name} must be a string.")
        if kind in ("integer", "number") and (isinstance(value, bool) or not isinstance(value, (int, float))
                                              or (kind == "integer" and not float(value).is_integer())):
            raise ValueError(f"{name} must be a {kind}.")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"{name} must be one of {rule['enum']}.")
        if "pattern" in rule and not re.fullmatch(rule["pattern"].strip("^$"), value, re.I):
            raise ValueError(f"{name} has an invalid format.")
        if name == "modelId" and not MODEL_ID.fullmatch(value):
            raise ValueError("modelId must be a Microsoft.CloudHealth/healthmodels resource ID.")
        if "minimum" in rule and value < rule["minimum"] or "maximum" in rule and value > rule["maximum"]:
            raise ValueError(f"{name} is out of range.")
    return arguments


def read_only_client_factory(auth: str = "cli"):
    """Default factory for MCP hosts: clients share one resilient transport that refuses every write."""
    from .bootstrap import runtime_transport
    from .client import HealthModelClient

    transport = runtime_transport(auth, read_only=True)
    return lambda model_id: HealthModelClient(model_id, transport)


def call_tool(client_factory, name: str, arguments: dict) -> dict:
    tool = _BY_NAME[name]
    args = validate(arguments, tool["inputSchema"])
    client = client_factory(args["modelId"])
    if name == "healthmodel_summary":
        return client.summary()
    if name == "healthmodel_alerts":
        return {"alerts": client.alerts(hours=int(args.get("hours", 24)), state=args.get("state"))}
    hours = float(args.get("hours", 24))
    if name == "healthmodel_entity_history":
        return {"entity": args["entity"], "history": client.history(args["entity"], hours=hours)}
    return {"entity": args["entity"], "signal": args["signal"],
            "history": client.signal_history(args["entity"], args["signal"], hours=hours)}
