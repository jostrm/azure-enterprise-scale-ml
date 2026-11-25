"""Pure-stdlib workbook fragments; billing is queried live by the Azure portal.

Append billing_parameters() to a parameter step after the shared TimeRange,
then append billing_items(). No workspace, Azure SDK, rates or saved bill is used.
The caller supplies TimeRange (normally 2592000000 milliseconds / last 30 days).
"""
import copy
import json


API_VERSION = "2025-03-01"
RESOURCE_SCOPE = "/subscriptions/{BillingResource:subscription}"
SUBSCRIPTION_SCOPE = "/subscriptions/{BillingSubscription}"
RESOURCE_FILTER = {"dimensions": {
    "name": "ResourceId", "operator": "In", "values": ["{BillingResource:escapejson}"]}}
DEPLOYMENT_GROUP = {"type": "TagKey", "name": "deployment"}
METER_GROUP = {"type": "Dimension", "name": "Meter"}


def billing_parameters():
    """Return independent subscription and Foundry account pickers."""
    return [
        {"id": "billing-subscription", "name": "BillingSubscription",
         "label": "Billing subscription", "type": 6, "isRequired": True,
         "multiSelect": False, "defaultValue": "value::1",
         "typeSettings": {"additionalResourceOptions": ["value::1"], "showDefault": False}},
        {"id": "billing-resource", "name": "BillingResource",
         "label": "Billed Foundry / OpenAI resource", "type": 5, "isRequired": True,
         "multiSelect": False, "value": "", "queryType": 1,
         "resourceType": "microsoft.resourcegraph/resources",
         "crossComponentResources": ["{BillingSubscription}"],
         "query": (
             "Resources\n"
             "| where type =~ 'microsoft.cognitiveservices/accounts'\n"
             "| where ['kind'] in~ ('AIServices', 'OpenAI')\n"
             "| project value=id, label=id, selected=false\n"
             "| order by label asc"),
         "typeSettings": {
             "additionalResourceOptions": [], "showDefault": False}},
    ]


def _body(grouping, *, daily=False, selected=False, overview=False):
    filters = copy.deepcopy(RESOURCE_FILTER)
    if overview:
        filters = {"dimensions": {"name": "ResourceType", "operator": "In",
                                  "values": ["microsoft.cognitiveservices/accounts"]}}
    elif selected:
        filters = {"and": [filters, {"tags": {
            "name": "deployment", "operator": "In",
            "values": ["{BillingDeployment:escapejson}"]}}]}
    return {
        "type": "ActualCost", "timeframe": "Custom",
        "timePeriod": {"from": "{TimeRange:startISO}", "to": "{TimeRange:endISO}"},
        "dataset": {"granularity": "Daily" if daily else "None",
                    "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                    "filter": filters, "grouping": copy.deepcopy(grouping)},
    }


def _columns(names):
    columns = []
    for index, name in enumerate(names):
        column = {"path": f"$[{index}]", "columnid": name}
        if name == "UsageDate":
            column.update(columnType="datetime",
                          substringRegexMatch="^([0-9]{4})([0-9]{2})([0-9]{2})$",
                          substringReplace="$1-$2-$3")
        columns.append(column)
    return columns


def _endpoint(body, columns, *, scope=RESOURCE_SCOPE, table_path="$.properties.rows"):
    # ARMEndpoint/1.0 / queryType 12 matches genericProjectWorkbookItems.bicep.
    # POST is synchronous, but unlike GETARRAY it does not follow properties.nextLink.
    return json.dumps({
        "version": "ARMEndpoint/1.0", "method": "POST",
        "path": scope + "/providers/Microsoft.CostManagement/query",
        "headers": [], "urlParams": [{"key": "api-version", "value": API_VERSION}],
        "batchDisabled": True, "data": json.dumps(body, separators=(",", ":")),
        "transformers": [{"type": "jsonpath",
                          "settings": {"tablePath": table_path, "columns": columns}}],
    }, separators=(",", ":"))


def _pair(name, title, body, names, *, scope=RESOURCE_SCOPE,
          table_path="$.properties.rows", visualization="table"):
    """Every result is accompanied by a visible schema and pagination inspector."""
    settings = {
        "version": "KqlItem/1.0", "queryType": 12, "size": 0,
        "noDataMessage": (
            "Billing unavailable, not zero. Check selection, time, billing delay and Cost "
            "Management Reader at subscription scope. On 204, 403, 429 or unsupported tags, "
            "use Cost Analysis; do not substitute telemetry estimates."),
    }
    rows = {"type": 3, "name": name, "content": {
        **settings, "title": title, "visualization": visualization,
        "query": _endpoint(body, _columns(names), scope=scope, table_path=table_path),
    }}
    if visualization == "table":
        rows["content"]["gridSettings"] = {
            "filter": True, "rowLimit": 10000,
            "formatters": [{"columnMatch": "Cost", "formatter": 0,
                            "numberFormat": {"unit": 0, "options": {
                                "style": "decimal", "useGrouping": True,
                                "maximumFractionDigits": 8}}}],
        }
    status = {"type": 3, "name": name + "-status", "content": {
        **settings, "title": "Response status · expected columns: " + ", ".join(
            "TagValue" if name == "DeploymentTag" else name for name in names),
        "visualization": "table",
        "query": _endpoint(body, [
            {"path": "$.nextLink", "columnid": "NextPage"},
            {"path": "$.nextLink", "columnid": "PaginationWarning",
             "substringRegexMatch": ".+", "substringReplace": "INCOMPLETE — further billing pages exist"},
            {"path": "$.columns", "columnid": "ReturnedColumns"},
        ], scope=scope, table_path="$.properties"),
    }}
    return [rows, status]


def _text(name, text):
    return {"type": 1, "name": name, "content": {"json": text}}


def _on_demand(name, label, items):
    return {"type": 12, "name": name, "content": {
        "version": "NotebookGroup/1.0", "groupType": "editable",
        "loadType": "explicit", "loadButtonText": label, "items": items,
    }}


def billing_items():
    """Return billed-cost navigation, deployment drilldowns and daily raw-meter views."""
    intro = _text("billing-heading", (
        "## Foundry billed cost · resource → deployment → daily input / output / cached meters\n\n"
        "**Live Azure Cost Management ActualCost, not an invoice and not a token-rate estimate.** "
        "Default time range is last 30 days. Current selection: **{TimeRange:label}** "
        "({TimeRange:startISO} → {TimeRange:endISO}). Cost normally arrives 8–24 hours after usage "
        "and current-period charges can change before invoice finalization. Amounts are before "
        "invoice credits and taxes; any returned negative adjustments, reservations and non-token "
        "meters remain signed billing rows. No currency conversion or hardcoded prices.\n\n"
        "Choose a billing subscription and a Foundry resource; workspace selection is not required. "
        "Each drill filters the actual **ResourceId**, then the billing **deployment** tag. "
        "Model or Meter names never identify a deployment. Blank DeploymentTag means "
        "**Unattributed (no deployment tag)**, not zero cost or a guessed model deployment.\n\n"
        "**Pagination safety:** these are returned-page amounts, never a guaranteed complete bill. "
        "Every table has a response-status table: a nonempty **NextPage** (`properties.nextLink`) "
        "means **INCOMPLETE**. Native workbook **POST** does not fetch later pages. Narrow the "
        "resource/deployment/time scope or use Cost Analysis/export for complete pagination. "
        "The status request is a separate live read; missing/failed status is unverified, not complete. "
        "Also compare ReturnedColumns with the expected order; stop interpreting costs on mismatch.\n\n"
        "Open additional tables only as needed to limit API throttling. On 429, wait before refreshing."
    ))
    overview = _on_demand(
        "billing-resource-overview", "Show resource costs in the selected subscription",
        [_text("billing-resource-overview-note", (
            "### Subscription resource costs · {BillingSubscription}\n"
            "This billing inventory includes **all Cognitive Services accounts**, including "
            "Foundry/OpenAI and other kinds, and historical/deleted accounts still billed. "
            "Choose a current AIServices/OpenAI account in the resource picker for the drill below. "
            "Marketplace/SaaS charges billed to a different resource ID are outside this account scope."
        ))] + _pair(
            "billing-resources", "Returned billed cost by Cognitive Services resource and currency",
            _body([{"type": "Dimension", "name": "ResourceId"}], overview=True),
            ["Cost", "ResourceId", "Currency"], scope=SUBSCRIPTION_SCOPE))
    scope = _text("billing-scope", (
        "### Selected Foundry resource\n"
        "**Resource:** `{BillingResource}`  \n"
        "**Subscription from resource ID:** `{BillingResource:subscription}`  \n"
        "**Time:** {TimeRange:label} ({TimeRange:startISO} → {TimeRange:endISO})\n\n"
        "[Open subscription Cost Analysis]"
        "(https://portal.azure.com/#view/Microsoft_Azure_CostManagement/CostAnalysis/"
        "scope/%2Fsubscriptions%2F{BillingResource:subscription}) · "
        "[Open resource](https://portal.azure.com/#resource{BillingResource}/overview)\n\n"
        "In Cost Analysis select the same dates, filter Resource, group by **Meter**, "
        "then filter tag **deployment**. Resource-group/subscription scopes also show Marketplace "
        "charges not assigned to this Foundry resource. Cost Management Reader at subscription "
        "scope is required for these subscription-scoped queries; the workbook grants no access."
    ))
    deployment_rows = _pair(
        "billing-deployments", "Deployment-tag billed cost · click a nonblank deployment row to drill",
        _body([DEPLOYMENT_GROUP]), ["Cost", "TagKey", "DeploymentTag", "Currency"])
    deployment_rows[0]["content"].update(
        exportParameters=True,
        exportedParameters=[
            {"fieldName": "DeploymentTag", "parameterName": "BillingDeployment",
             "parameterType": 1, "defaultValue": ""},
            {"fieldName": "Currency", "parameterName": "BillingCurrency",
             "parameterType": 1, "defaultValue": ""},
        ],
    )
    meter_note = _text("billing-meter-note", (
        "**Input / output / cached cost:** the **Meter** column is Azure's unmodified billing label. "
        "Input, output, cache-read and cache-write meters are separate rows with their actual "
        "Cost and Currency, not multiplied token estimates. Cache-write is not merged with "
        "cached-input/cache-read cost. A missing cached meter is unavailable/not separately "
        "reported, not proof of zero cache use or cost. Unknown, combined, audio/image, hosting, "
        "PTU/reservation and other meters are retained; they are never forced into a token category. "
        "Use the grid filter to inspect input/output/cache names without changing the source query.\n\n"
        "Untagged charges remain in the all-deployment detail and resource-only fallback. "
        "If tag grouping is unsupported, the fallback still shows the resource's billed daily meters."
    ))
    selected_body = _body([METER_GROUP], daily=True, selected=True)
    selected = [_text("billing-deployment-scope", (
        "### Selected deployment · `{BillingDeployment}`\n"
        "**Resource:** `{BillingResource}`  \n"
        "**Deployment tag:** `{BillingDeployment}` · **Selected row currency:** `{BillingCurrency}`  \n"
        "**Time:** {TimeRange:label}\n\n"
        "Daily table retains every returned currency. The optional trend shows only the selected "
        "row's currency; never add different currencies together."
    ))] + _pair(
        "billing-deployment-daily",
        "Daily billed input / output / cached / other meters · {BillingDeployment} · all currencies",
        selected_body, ["Cost", "UsageDate", "Meter", "Currency"])
    trend = _pair(
        "billing-deployment-trend",
        "Daily billed meters · {BillingDeployment} · {BillingCurrency} · returned page only",
        selected_body, ["Cost", "UsageDate", "Meter", "Currency"],
        table_path='$.properties.rows[?(@[3] == "{BillingCurrency:escapejson}")]',
        visualization="timechart")
    trend[0]["content"].update(size=1, chartSettings={
        "xAxis": "UsageDate", "yAxis": ["Cost"], "group": "Meter",
        "createOtherGroup": 0, "showLegend": True, "showMetrics": False,
    })
    selected.append(_on_demand(
        "billing-trend-details", "Show daily meter trend · selected currency only", trend))
    selected_group = {
        "type": 12, "name": "billing-selected-deployment",
        "conditionalVisibility": {
            "parameterName": "BillingDeployment", "comparison": "isNotEqualTo", "value": ""},
        "content": {"version": "NotebookGroup/1.0", "groupType": "editable", "items": selected},
    }
    all_deployments = _on_demand(
        "billing-all-deployments-details", "Show daily costs for all deployments, including unattributed",
        _pair("billing-all-deployments-daily",
              "Daily billed cost · deployment tag → raw Meter · all currencies (blank tag = Unattributed)",
              _body([DEPLOYMENT_GROUP, METER_GROUP], daily=True),
              ["Cost", "UsageDate", "TagKey", "DeploymentTag", "Meter", "Currency"]))
    fallback = _on_demand(
        "billing-resource-meter-details", "Show daily resource meters · no deployment tag required",
        _pair("billing-resource-meters",
              "Daily resource input / output / cached / other billed meters · all currencies, no tag filter",
              _body([METER_GROUP], daily=True), ["Cost", "UsageDate", "Meter", "Currency"]))
    return [intro, overview, scope, *deployment_rows, meter_note,
            selected_group, all_deployments, fallback]
