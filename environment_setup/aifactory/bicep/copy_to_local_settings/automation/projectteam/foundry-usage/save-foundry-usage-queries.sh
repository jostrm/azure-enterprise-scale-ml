#!/usr/bin/env bash
set -euo pipefail

readonly SAVED_SEARCH_API_VERSION="2022-10-01"

usage() {
  cat <<'EOF'
Usage:
  ./save-foundry-usage-queries.sh \
    --subscription-id <subscription-id> \
    --resource-group <foundry-resource-group> \
    --workspace-resource-id <log-analytics-workspace-resource-id> \
    [--telemetry-table AzureDiagnostics]

The script validates each query against Log Analytics, then creates or updates
three saved queries in the Azure portal:
  AIFactory-usage-query-01 - Foundry requests per day
  AIFactory-usage-query-02 - Azure OpenAI requests per day
  AIFactory-usage-query-03 - model deployment token usage

Use AzureDiagnostics when the diagnostic setting's logAnalyticsDestinationType
is AzureDiagnostics or unset. For Dedicated destinations, pass the correct
resource-specific table after verifying it in Log Analytics.
EOF
}

subscription_id=""
resource_group=""
workspace_resource_id=""
telemetry_table="AzureDiagnostics"

while (($#)); do
  case "$1" in
    --subscription-id) subscription_id="$2"; shift 2 ;;
    --resource-group) resource_group="$2"; shift 2 ;;
    --workspace-resource-id) workspace_resource_id="$2"; shift 2 ;;
    --telemetry-table) telemetry_table="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for value in "$subscription_id" "$resource_group" "$workspace_resource_id"; do
  if [[ -z "$value" ]]; then
    usage >&2
    exit 2
  fi
done

for command in az jq; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "$command is required." >&2
    exit 1
  fi
done
if [[ ! "$telemetry_table" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]]; then
  echo "--telemetry-table must be a Log Analytics table name." >&2
  exit 2
fi

az account set --subscription "$subscription_id" --only-show-errors
workspace_resource_id="${workspace_resource_id%/}"
workspace_customer_id="$(az resource show --ids "$workspace_resource_id" --query properties.customerId -o tsv --only-show-errors)"
if [[ -z "$workspace_customer_id" ]]; then
  echo "The supplied resource is not a Log Analytics workspace." >&2
  exit 1
fi

resources="$(az resource list \
  --resource-group "$resource_group" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --query '[].{id:id,kind:kind}' \
  -o json --only-show-errors)"
foundry_ids="$(jq -c '[.[] | select((.kind // "" | ascii_downcase) != "openai") | .id | ascii_downcase]' <<<"$resources")"
openai_ids="$(jq -c '[.[] | select((.kind // "" | ascii_downcase) == "openai") | .id | ascii_downcase]' <<<"$resources")"

usage_events() {
  local target_ids="$1"
  local categories="$2"
  cat <<EOF
let StartTime = ago(30d);
let TargetResourceIds = dynamic(${target_ids});
let IncludedCategories = dynamic(${categories});
let UsageEvents =
    ${telemetry_table}
    | where TimeGenerated >= StartTime
    | where tolower(ResourceProvider) == "microsoft.cognitiveservices"
    | extend ActualResourceId = tolower(iff(
        isnotempty(tostring(column_ifexists("_ResourceId", ""))),
        tostring(column_ifexists("_ResourceId", "")),
        tostring(column_ifexists("ResourceId", ""))))
    | where array_index_of(TargetResourceIds, ActualResourceId) >= 0
    | where array_index_of(IncludedCategories, Category) >= 0
    | extend Properties = todynamic(column_ifexists("properties_s", "{}"))
    | extend ModelDeployment = coalesce(
        tostring(Properties["modelDeploymentName"]),
        tostring(Properties["deploymentName"]),
        tostring(Properties["deployment"]),
        tostring(Properties["model"]),
        "Unspecified");
EOF
}

request_query() {
  local target_ids="$1"
  usage_events "$target_ids" '["RequestResponse", "Trace"]'
  cat <<'EOF'
UsageEvents
| summarize Requests = count() by Day = bin(TimeGenerated, 1d), ModelDeployment
| order by Day asc
| render timechart
EOF
}

token_query() {
  usage_events "$foundry_ids" '["AzureOpenAIRequestUsage"]'
  cat <<'EOF'
UsageEvents
| extend InputTokens = coalesce(todouble(Properties["inputTokens"]), todouble(Properties["promptTokens"]), todouble(Properties["input_tokens"]), 0.0)
| extend OutputTokens = coalesce(todouble(Properties["outputTokens"]), todouble(Properties["completionTokens"]), todouble(Properties["output_tokens"]), 0.0)
| extend CachedTokens = coalesce(todouble(Properties["cachedTokens"]), todouble(Properties["cacheReadInputTokens"]), todouble(Properties["cached_tokens"]), 0.0)
| summarize InputTokens = sum(InputTokens), OutputTokens = sum(OutputTokens), CachedTokens = sum(CachedTokens) by Day = bin(TimeGenerated, 1d), ModelDeployment
| extend TotalTokens = InputTokens + OutputTokens + CachedTokens
| order by Day asc
| render timechart
EOF
}

save_query() {
  local saved_search_name="$1"
  local display_name="$2"
  local query="$3"
  local validation_body
  local saved_search_body
  validation_body="$(jq -nc --arg query "$query" '{query: $query}')"
  echo "Validating $display_name"
  az rest --method post \
    --url "https://api.loganalytics.io/v1/workspaces/${workspace_customer_id}/query" \
    --resource "https://api.loganalytics.io" \
    --headers "Content-Type=application/json" \
    --body "$validation_body" \
    -o none --only-show-errors

  saved_search_body="$(jq -nc \
    --arg category "AIFactory usage" \
    --arg display_name "$display_name" \
    --arg query "$query" \
    '{properties: {category: $category, displayName: $display_name, query: $query, version: 2}}')"
  az rest --method put \
    --url "https://management.azure.com${workspace_resource_id}/savedSearches/${saved_search_name}?api-version=${SAVED_SEARCH_API_VERSION}" \
    --body "$saved_search_body" \
    -o none --only-show-errors
  echo "Saved $display_name"
}

save_query "AIFactory-usage-query-01" "AIFactory-usage-query-01 - Foundry requests per day" "$(request_query "$foundry_ids")"
save_query "AIFactory-usage-query-02" "AIFactory-usage-query-02 - Azure OpenAI requests per day" "$(request_query "$openai_ids")"
save_query "AIFactory-usage-query-03" "AIFactory-usage-query-03 - Foundry model deployment token usage" "$(token_query)"
