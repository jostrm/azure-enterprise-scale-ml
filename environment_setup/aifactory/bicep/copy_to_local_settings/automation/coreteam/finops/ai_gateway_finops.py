"""Offline workbook builder, reviewed-rate validator and metadata-only producer.

No Azure SDK, credentials, ingestion setup or network calls are performed here.
Applications remain responsible for authentication, text-only workload validation,
completion detection and using their existing approved telemetry exporter.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
EVENT_NAME = "aifactory.ai-gateway.usage"
SCHEMA = "aifactory.ai-gateway.usage/v1"
DISPLAY_NAME = "AI Gateway - Usage and Cost by App and User"
MAX_EXACT_INT = 9007199254740991
EMPTY_CONFIG = {"applications": [], "rates": [], "trustedTelemetryResourceIds": []}
GROUPS = ["Application", "APIM subscription", "User", "Team", "Deployment", "Model", "Day"]
_UNSET = object()
RESOURCE_PATTERN = (
    r"/subscriptions/[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}/resourceGroups/[^/]+/providers/"
    r"{provider}/{kind}/[^/]+"
)


def _resource(value, provider, kind):
    if not isinstance(value, str) or not re.fullmatch(
        RESOURCE_PATTERN.format(provider=re.escape(provider), kind=kind), value, re.I
    ):
        raise ValueError(f"Expected a full {provider}/{kind} resource ID")
    return value.lower()


def _text(value, label, *, optional=False):
    if not isinstance(value, str) or len(value) > 256 or (not optional and not value.strip()):
        raise ValueError(f"{label} must be a nonempty metadata string of at most 256 characters")
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamps must be ISO 8601 strings with an explicit timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO 8601 timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("Timestamps require an explicit timezone")
    return result.astimezone(timezone.utc)


def _host(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", value
    ):
        raise ValueError("backendHost must be the actual backend DNS host, not a URL or pool name")
    return value.lower()


def _rate(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Rates must be finite nonnegative JSON numbers")
    number = Decimal(str(value))
    if not number.is_finite() or not 0 <= number <= MAX_EXACT_INT:
        raise ValueError("Rates must be finite nonnegative JSON numbers")
    return number


def validate_config(configuration):
    """Validate exact mappings and half-open, nonoverlapping rate intervals."""
    config = copy.deepcopy(configuration)
    if not isinstance(config, dict) or set(config) != set(EMPTY_CONFIG):
        raise ValueError(f"Configuration requires exactly these keys: {', '.join(EMPTY_CONFIG)}")
    if any(not isinstance(config[key], list) for key in EMPTY_CONFIG):
        raise ValueError("Configuration values must be arrays")
    if any(len(config[key]) > 1000 for key in EMPTY_CONFIG):
        raise ValueError("Configuration supports at most 1000 entries per array")
    config["trustedTelemetryResourceIds"] = [
        _resource(value, "Microsoft.Insights", "components")
        for value in config["trustedTelemetryResourceIds"]
    ]
    seen = set()
    for application in config["applications"]:
        if not isinstance(application, dict) or set(application) != {
            "gatewayResourceId", "apimSubscriptionId", "applicationId", "teamId"
        }:
            raise ValueError("Application mappings require gatewayResourceId/apimSubscriptionId/applicationId/teamId")
        application["gatewayResourceId"] = _resource(
            application["gatewayResourceId"], "Microsoft.ApiManagement", "service")
        for key in ("apimSubscriptionId", "applicationId", "teamId"):
            _text(application[key], key)
        key = (application["gatewayResourceId"], application["apimSubscriptionId"])
        if key in seen:
            raise ValueError("Duplicate APIM subscription application mapping")
        seen.add(key)
    periods = {}
    for rate in config["rates"]:
        if not isinstance(rate, dict) or set(rate) != {
            "gatewayResourceId", "backendHost", "deployment", "model", "validFrom", "validTo",
            "currency", "meter", "billingMode", "inputPerMillion", "cachedInputPerMillion",
            "outputPerMillion",
        }:
            raise ValueError("Rate card entry has missing or unknown fields")
        rate["gatewayResourceId"] = _resource(rate["gatewayResourceId"], "Microsoft.ApiManagement", "service")
        rate["backendHost"] = _host(rate["backendHost"])
        for key in ("deployment", "model"):
            _text(rate[key], key)
        if rate["meter"] != "openai-text-tokens" or rate["billingMode"] != "consumption":
            raise ValueError("Only OpenAI text consumption token rates are supported; PTU is not token billing")
        if not isinstance(rate["currency"], str) or not re.fullmatch(r"[A-Z]{3}", rate["currency"]):
            raise ValueError("currency must be a three-letter uppercase currency code")
        for key in ("inputPerMillion", "cachedInputPerMillion", "outputPerMillion"):
            _rate(rate[key])
        start, end = _timestamp(rate["validFrom"]), _timestamp(rate["validTo"])
        if start >= end:
            raise ValueError("validTo must be later than validFrom (exclusive upper bound)")
        key = tuple(rate[field] for field in ("gatewayResourceId", "backendHost", "deployment", "model"))
        for previous_start, previous_end in periods.setdefault(key, []):
            if start < previous_end and end > previous_start:
                raise ValueError("Overlapping rates for the same gateway/backend/deployment/model")
        periods[key].append((start, end))
    return config


def _token(value):
    return type(value) is int and 0 <= value <= MAX_EXACT_INT


def make_usage_event(
    *, gateway_resource_id, correlation_id, apim_subscription_id, backend_host,
    deployment, model, api_kind, usage, completed, text_only, observed_at=None,
    authenticated_subject=None, pseudonym_key=None, identity_validated=False,
    validated_application_id="",
):
    """Create one metadata-only event after a response or failed stream.

    Pass only the provider's final usage object, never the full request/response.
    `completed` means successful response/stream completion, not just HTTP 200.
    `text_only` is a server-side assertion excluding audio/images/tools/other meters.
    No JWT is verified by this helper; identity_validated is the application's
    assertion AFTER signature, issuer, audience and delegated-user validation.
    """
    gateway = _resource(gateway_resource_id, "Microsoft.ApiManagement", "service")
    for value, label in ((correlation_id, "correlation_id"),
                         (apim_subscription_id, "apim_subscription_id"),
                         (deployment, "deployment"), (model, "model")):
        _text(value, label, optional=label == "apim_subscription_id")
    if api_kind not in ("chat", "responses"):
        raise ValueError("Only OpenAI Chat Completions and Responses usage are supported")
    if type(completed) is not bool or type(text_only) is not bool or type(identity_validated) is not bool:
        raise ValueError("Completion, text-only and validated-identity assertions must be booleans")
    _text(validated_application_id, "validated_application_id", optional=True)
    if (authenticated_subject is not None or validated_application_id) and not identity_validated:
        raise ValueError("End-user/application identity must be validated server-side")
    user_id = ""
    if authenticated_subject is not None:
        _text(authenticated_subject, "authenticated_subject")
        if not isinstance(pseudonym_key, bytes) or len(pseudonym_key) < 32:
            raise ValueError("A private pseudonym key of at least 32 bytes is required")
        user_id = hmac.new(
            pseudonym_key, (gateway + "\0" + authenticated_subject).encode(), hashlib.sha256
        ).hexdigest()
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    observed_at = _timestamp(observed_at).isoformat()
    usage = usage if isinstance(usage, dict) else {}
    input_key, output_key = ("prompt_tokens", "completion_tokens") if api_kind == "chat" else (
        "input_tokens", "output_tokens")
    input_tokens, output_tokens, total_tokens = (
        usage.get(input_key), usage.get(output_key), usage.get("total_tokens"))
    input_details = usage.get(input_key + "_details")
    output_details = usage.get(output_key + "_details")
    input_details = {} if input_details is None else input_details
    output_details = {} if output_details is None else output_details
    details_valid = isinstance(input_details, dict) and isinstance(output_details, dict)
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = output_details if isinstance(output_details, dict) else {}
    cached = input_details.get("cached_tokens")
    known = all(_token(value) for value in (input_tokens, output_tokens, total_tokens))
    known = known and total_tokens == input_tokens + output_tokens
    cache_valid = cached is None or (_token(cached) and known and cached <= input_tokens)
    # Reasoning is already part of output; prediction/audio/unknown nonzero detail
    # meters need a separate billing adapter and are deliberately not priced.
    unsupported_details = any(
        value not in (0, None) for key, value in input_details.items() if key != "cached_tokens"
    ) or any(
        value not in (0, None) for key, value in output_details.items() if key != "reasoning_tokens"
    )
    reasoning = output_details.get("reasoning_tokens")
    details_valid = details_valid and (
        reasoning is None or (_token(reasoning) and known and reasoning <= output_tokens))
    usage_complete = completed and known and cache_valid and details_valid
    payload = {
        "schema": SCHEMA, "gateway_resource_id": gateway, "correlation_id": correlation_id.lower(),
        "apim_subscription_id": apim_subscription_id,
        "backend_host": "" if backend_host == "" else _host(backend_host),
        "deployment": deployment, "model": model, "api_kind": api_kind,
        "observed_at": observed_at, "usage_complete": usage_complete,
        "text_only": text_only and not unsupported_details,
        "input_tokens": input_tokens if usage_complete else None,
        "output_tokens": output_tokens if usage_complete else None,
        "total_tokens": total_tokens if usage_complete else None,
        "cached_input_tokens": cached if usage_complete else None,
        "user_id": user_id, "validated_application_id": validated_application_id,
    }
    return {"name": EVENT_NAME, "properties": {"finops": json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False)}}


def emit_usage_event(logger, event):
    """Use an existing Azure Monitor logging exporter; never configure one here."""
    logger.info(EVENT_NAME, extra={
        "microsoft.custom_event.name": EVENT_NAME, "finops": event["properties"]["finops"],
    })


def estimate_cost(payload, configuration):
    """Offline reference calculation for a normalized trusted producer payload."""
    config = validate_config(configuration)
    missing = {"amount": None, "currency": None}
    if payload.get("schema") != SCHEMA or payload.get("usage_complete") is not True:
        return {**missing, "status": "Incomplete usage"}
    if payload.get("text_only") is not True or payload.get("api_kind") not in ("chat", "responses"):
        return {**missing, "status": "Unsupported meter"}
    incoming, outgoing, total = (payload.get(key) for key in ("input_tokens", "output_tokens", "total_tokens"))
    if not all(_token(value) for value in (incoming, outgoing, total)) or incoming + outgoing != total:
        return {**missing, "status": "Invalid usage"}
    cached = payload.get("cached_input_tokens")
    if cached is not None and (not _token(cached) or cached > incoming):
        return {**missing, "status": "Invalid cache split"}
    observed = _timestamp(payload["observed_at"])
    matches = [
        rate for rate in config["rates"]
        if rate["gatewayResourceId"] == payload["gateway_resource_id"].lower()
        and rate["backendHost"] == payload["backend_host"].lower()
        and rate["deployment"] == payload["deployment"] and rate["model"] == payload["model"]
        and _timestamp(rate["validFrom"]) <= observed < _timestamp(rate["validTo"])
    ]
    if len(matches) != 1:
        return {**missing, "status": "No exact effective rate"}
    rate = matches[0]
    input_rate, cache_rate, output_rate = (
        _rate(rate[key]) for key in ("inputPerMillion", "cachedInputPerMillion", "outputPerMillion"))
    if cached is None:
        if input_rate != cache_rate:
            return {**missing, "status": "Missing cache split"}
        amount = Decimal(incoming) * input_rate + Decimal(outgoing) * output_rate
    else:
        amount = Decimal(incoming - cached) * input_rate + Decimal(cached) * cache_rate + Decimal(outgoing) * output_rate
    return {"amount": (amount / Decimal(1000000)).normalize(),
            "currency": rate["currency"], "status": "Estimated (not billed)"}


def build_workbook(configuration=None):
    config = validate_config(EMPTY_CONFIG if configuration is None else configuration)
    query = (HERE / "ai-gateway-finops.kql").read_text(encoding="utf-8")
    parameters = [
        {"id": "finops-workspaces", "name": "Workspaces", "type": 5, "isRequired": True,
         "multiSelect": True, "value": [], "queryType": 1,
         "resourceType": "microsoft.resourcegraph/resources",
         "query": "Resources | where type =~ 'microsoft.operationalinsights/workspaces' | project value=id, label=id, selected=false | order by label asc",
         "typeSettings": {
             "resourceTypeFilter": ["microsoft.operationalinsights/workspaces"],
             "additionalResourceOptions": [], "showDefault": False}},
        {"id": "finops-time", "name": "TimeRange", "type": 4, "isRequired": True,
         "value": {"durationMs": 604800000}, "typeSettings": {"selectableValues": [
             {"durationMs": 3600000}, {"durationMs": 86400000}, {"durationMs": 604800000},
             {"durationMs": 2592000000}]}},
        {"id": "finops-group", "name": "GroupBy", "type": 2, "isRequired": True,
         "value": "Application", "multiSelect": False,
         "jsonData": json.dumps([{"value": value, "label": value} for value in GROUPS])},
        {"id": "finops-config", "name": "Configuration", "type": 1, "isRequired": True,
         "value": json.dumps(config, separators=(",", ":")), "label": "Reviewed configuration JSON",
         "typeSettings": {"editorLanguage": "json", "multiLineText": True, "multiLineHeight": 160}},
    ]
    intro = (
        f"# {DISPLAY_NAME}\n\n"
        "**Estimated showback, not an invoice.** Select the existing Log Analytics workspace(s) "
        "receiving APIM LLM and gateway logs. No telemetry/resource discovery is required to deploy "
        "this workbook. Default: last 7 days, no prices and no trusted enrichment sources.\n\n"
        "Native logs immediately report observed input/output/total tokens; unknown, interrupted or "
        "conflicting usage remains blank, never zero. Prices require the optional trusted metadata "
        "event for completed, text-only OpenAI Chat Completions/Responses and an exact effective "
        "reviewed rate. No native cached-token field is assumed. PTU, images, audio, tools and "
        "other provider meters are not priced. Reasoning tokens are already part of output.\n\n"
        "Application/team mapping uses **APIM consumer subscription IDs, not Azure subscription IDs**. "
        "User means a server-validated HMAC pseudonym, not a gateway managed identity or a caller header. "
        "Unmapped/unknown identities remain visible. Distinct users across multiple gateways are "
        "gateway-scoped pseudonyms and are not an organization-wide unique population.\n\n"
        "See `environment_setup/aigateway/readme.md` → **AI gateway FinOps workbook** for setup, "
        "the metadata producer, import steps and rate configuration. Empty results: check the time "
        "range, selected workspace, collection, RBAC and private-network access. This workbook "
        "does not turn on diagnostics or change gateway policies."
    )
    sections = [
        ("coverage", "Observed request coverage and token totals (not all gateway traffic)", "table", """
Usage
| summarize ObservedRequests=count(), KnownUsage=countif(UsageKnown),
    WithNativeLogs=countif(HasNative), WithTrustedEvents=countif(HasEvent),
    WithApplication=countif(Application != 'Unknown'), WithUser=countif(User != 'Unknown'),
    PricedRequests=countif(isnotnull(EstimatedCost)), UnknownUsage=countif(not(UsageKnown)),
    InputTokens=sum(InputTokens), OutputTokens=sum(OutputTokens), TotalTokens=sum(TotalTokens)
| extend InputTokens=iff(KnownUsage > 0, InputTokens, real(null)),
    OutputTokens=iff(KnownUsage > 0, OutputTokens, real(null)),
    TotalTokens=iff(KnownUsage > 0, TotalTokens, real(null)),
    PricingCoveragePercent=iff(ObservedRequests > 0, 100.0 * PricedRequests / ObservedRequests, real(null)),
    ApplicationCoveragePercent=iff(ObservedRequests > 0, 100.0 * WithApplication / ObservedRequests, real(null)),
    UserCoveragePercent=iff(ObservedRequests > 0, 100.0 * WithUser / ObservedRequests, real(null)),
    IgnoredUntrustedEvents=UntrustedEventCount,
    ConfigurationStatus=iff(ConfigShapeValid, 'Validate edited JSON with the offline helper', 'INVALID configuration shape'),
    Status=iff(ObservedRequests == 0,
        'NO DATA: choose workspace/time; verify existing LLM + gateway diagnostic collection and access',
        'Observed correlations only; missing collection, sampling, retries and interrupted streams can undercount')
"""),
        ("cost-by-currency", "Estimated subtotal by currency — unpriced requests excluded, not zero", "table", """
Usage
| where isnotnull(EstimatedCost)
| summarize EstimatedSubtotal=sum(EstimatedCost), PricedRequests=count() by Currency
| extend Basis='Estimated consumption tokens, not billed; reconcile separately with Cost Management'
"""),
        ("breakdown", "Usage and estimated cost by selected group — currencies and unknowns kept separate", "table", """
Usage
| summarize Requests=count(), KnownUsage=countif(UsageKnown), PricedRequests=countif(isnotnull(EstimatedCost)),
    InputTokens=sum(InputTokens), OutputTokens=sum(OutputTokens), TotalTokens=sum(TotalTokens),
    EstimatedSubtotal=sum(EstimatedCost) by Group, Currency, PricingStatus
| extend InputTokens=iff(KnownUsage > 0, InputTokens, real(null)),
    OutputTokens=iff(KnownUsage > 0, OutputTokens, real(null)),
    TotalTokens=iff(KnownUsage > 0, TotalTokens, real(null)),
    EstimatedSubtotal=iff(PricedRequests > 0, EstimatedSubtotal, real(null))
| order by Requests desc
"""),
        ("token-trend", "Daily observed token trend", "timechart", """
Usage
| summarize KnownUsage=countif(UsageKnown), InputTokens=sum(InputTokens), OutputTokens=sum(OutputTokens)
    by Day=bin(TimeGenerated, 1d)
| project Day, InputTokens=iff(KnownUsage > 0, InputTokens, real(null)),
    OutputTokens=iff(KnownUsage > 0, OutputTokens, real(null))
| order by Day asc
"""),
        ("cost-trend", "Daily priced-only estimate trend by currency (not a complete bill)", "timechart", """
Usage
| where isnotnull(EstimatedCost)
| summarize EstimatedSubtotal=sum(EstimatedCost) by Day=bin(TimeGenerated, 1d), Currency
| order by Day asc
"""),
        ("gaps", "Attribution and pricing gaps — repair configuration, never replace blanks with zero", "table", """
Usage
| where PricingStatus != 'Estimated (not billed)' or Application == 'Unknown' or User == 'Unknown'
| summarize Requests=count() by GatewayResourceId, ApimSubscriptionId, BackendHost, Deployment, Model,
    Application, Team, PricingStatus
| order by Requests desc
"""),
    ]
    items = [
        {"type": 1, "name": "overview", "content": {"json": intro}},
        {"type": 9, "name": "finops-parameters", "content": {
            "version": "KqlParameterItem/1.0", "parameters": parameters, "style": "above"}},
    ]
    for name, title, visualization, suffix in sections:
        items.append({"type": 3, "name": name, "content": {
            "version": "KqlItem/1.0", "title": title, "query": query + "\n" + suffix.strip(),
            "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces",
            "crossComponentResources": ["{Workspaces}"], "timeContextFromParameter": "TimeRange",
            "visualization": visualization,
            "noDataMessage": "No matching observations/prices. Check coverage, collection, access and reviewed configuration; no data is not zero cost.",
        }})
    return {"version": "Notebook/1.0", "items": items, "fallbackResourceIds": ["Azure Monitor"], "isLocked": False}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_config(path):
    """Load a reviewed JSON file, rejecting duplicate keys and invalid rates."""
    return validate_config(json.loads(
        Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_pairs))


def _validate_saved_parameter(name, value):
    if name == "Workspaces":
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("Saved Workspaces must be an array of at most 100 workspace resource IDs")
        for resource_id in value:
            _resource(resource_id, "Microsoft.OperationalInsights", "workspaces")
    elif name == "GroupBy":
        if value not in GROUPS:
            raise ValueError("Saved GroupBy is not a supported grouping")
    elif name == "TimeRange":
        if not isinstance(value, dict):
            raise ValueError("Saved TimeRange must be a duration or explicit UTC range")
        if set(value) == {"durationMs"}:
            if type(value["durationMs"]) is not int or not 1 <= value["durationMs"] <= 31622400000:
                raise ValueError("Saved TimeRange duration must be positive and at most 366 days")
        elif set(value) == {"startTime", "endTime"}:
            duration = (_timestamp(value["endTime"]) - _timestamp(value["startTime"])).total_seconds()
            if not 0 < duration <= 31622400:
                raise ValueError("Saved TimeRange must be ordered and at most 366 days")
        else:
            raise ValueError("Saved TimeRange has unsupported fields")
    return copy.deepcopy(value)


def render_workbook(configuration=None, existing_serialized_data=None, *, config=_UNSET, existing=_UNSET):
    """Render for deployment without silently clearing saved rates or mappings.

    An explicit configuration (including EMPTY_CONFIG) is authoritative. Otherwise
    preserve the existing workbook's saved Configuration and validated workspace,
    time and grouping values. Missing/malformed saved configuration fails closed.
    Only a genuinely new workbook (existing_serialized_data=None) starts empty.
    The config/existing keyword aliases support dashboard adapters using a parsed
    Notebook dictionary; do not combine aliases with their canonical arguments.
    """
    if config is not _UNSET:
        if configuration is not None:
            raise ValueError("Specify configuration or config, not both")
        configuration = config
    if existing is not _UNSET:
        if existing_serialized_data is not None:
            raise ValueError("Specify existing_serialized_data or existing, not both")
        existing_serialized_data = json.dumps(existing, allow_nan=False) if isinstance(existing, dict) else existing
    if configuration is not None:
        return build_workbook(configuration)
    if existing_serialized_data is None:
        return build_workbook()
    if not isinstance(existing_serialized_data, str):
        raise ValueError("Existing serializedData must be a workbook JSON string")
    existing = json.loads(existing_serialized_data, object_pairs_hook=_unique_pairs)
    if not isinstance(existing, dict) or existing.get("version") != "Notebook/1.0":
        raise ValueError("Existing workbook must be Notebook/1.0; supply an explicit reviewed configuration")
    parameters = []

    def collect(items):
        if not isinstance(items, list):
            raise ValueError("Existing workbook items must be an array")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Existing workbook contains an invalid item")
            content = item.get("content", {})
            if not isinstance(content, dict):
                continue
            if item.get("type") == 9:
                values = content.get("parameters", [])
                if not isinstance(values, list):
                    raise ValueError("Existing workbook parameters must be an array")
                parameters.extend(value for value in values if isinstance(value, dict)
                                  and value.get("name") in {"Configuration", "Workspaces", "TimeRange", "GroupBy"})
            elif item.get("type") == 12:
                collect(content.get("items", []))

    collect(existing.get("items", []))
    saved_config = [parameter for parameter in parameters if parameter["name"] == "Configuration"]
    if len(saved_config) != 1 or not isinstance(saved_config[0].get("value"), str):
        raise ValueError("Existing workbook needs exactly one saved Configuration value; supply an explicit reviewed configuration")
    if len({parameter["name"] for parameter in parameters}) != len(parameters):
        raise ValueError("Existing workbook has duplicate saved parameters")
    saved = json.loads(saved_config[0]["value"], object_pairs_hook=_unique_pairs)
    rendered = build_workbook(validate_config(saved))
    targets = {parameter["name"]: parameter for item in rendered["items"] if item["type"] == 9
               for parameter in item["content"]["parameters"]}
    for parameter in parameters:
        name = parameter["name"]
        if name != "Configuration":
            targets[name]["value"] = _validate_saved_parameter(name, parameter.get("value"))
    return rendered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Reviewed configuration JSON (default: empty)")
    parser.add_argument("--existing-workbook", type=Path,
                        help="Saved workbook JSON whose configuration is preserved unless --config is explicit")
    parser.add_argument("--output", type=Path, help="Write workbook JSON for portal Advanced Editor import")
    parser.add_argument("--check", action="store_true", help="Check committed default workbook is current; no writes")
    args = parser.parse_args(argv)
    if args.check and (args.config or args.output or args.existing_workbook):
        parser.error("--check cannot be combined with --config, --existing-workbook or --output")
    if not args.check and not args.output:
        parser.error("--output is required unless --check is used")
    try:
        config = load_config(args.config) if args.config else None
        existing = args.existing_workbook.read_text(encoding="utf-8-sig") if args.existing_workbook else None
        workbook = render_workbook(configuration=config, existing_serialized_data=existing)
        if args.check:
            existing = json.loads((HERE / "ai-gateway-finops.workbook.json").read_text(encoding="utf-8"))
            if existing != workbook:
                raise ValueError("Static workbook is stale; regenerate it with --output")
            print("AI gateway FinOps workbook is current")
        else:
            args.output.write_text(json.dumps(workbook, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Wrote {args.output}; no Azure operations performed")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
