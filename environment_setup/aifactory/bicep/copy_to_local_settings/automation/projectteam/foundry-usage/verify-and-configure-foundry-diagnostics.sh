#!/usr/bin/env bash
set -euo pipefail

readonly DIAGNOSTICS_API_VERSION="2021-05-01-preview"
readonly DEFAULT_SETTING_NAME="foundry-usage-to-log-analytics"
readonly REQUIRED_CATEGORIES=("RequestResponse" "Trace")

usage() {
  cat <<'EOF'
Usage:
  ./verify-and-configure-foundry-diagnostics.sh \
    --subscription-id <subscription-id> \
    --resource-group <resource-group> \
    --workspace-resource-id <log-analytics-workspace-resource-id> \
    [--setting-name foundry-usage-to-log-analytics] \
    [--enable-azure-openai-request-usage] \
    [--apply]

Without --apply, the script only verifies configuration. With --apply, it
creates or updates the diagnostic setting that targets the supplied workspace,
enabling RequestResponse and Trace without removing existing categories or
destinations. The script also reports whether the setting writes to
AzureDiagnostics or resource-specific tables. Add
--enable-azure-openai-request-usage to also enable the token-focused
AzureOpenAIRequestUsage category when supported by the resource.
EOF
}

subscription_id=""
resource_group=""
workspace_resource_id=""
setting_name="$DEFAULT_SETTING_NAME"
enable_azure_openai_request_usage=false
apply=false

while (($#)); do
  case "$1" in
    --subscription-id) subscription_id="$2"; shift 2 ;;
    --resource-group) resource_group="$2"; shift 2 ;;
    --workspace-resource-id) workspace_resource_id="$2"; shift 2 ;;
    --setting-name) setting_name="$2"; shift 2 ;;
    --enable-azure-openai-request-usage) enable_azure_openai_request_usage=true; shift ;;
    --apply) apply=true; shift ;;
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

az account set --subscription "$subscription_id" --only-show-errors
workspace_resource_id="${workspace_resource_id%/}"
workspace_resource_id_lower="$(tr '[:upper:]' '[:lower:]' <<<"$workspace_resource_id")"

if ! az resource show --ids "$workspace_resource_id" --query id -o tsv --only-show-errors >/dev/null; then
  echo "The supplied Log Analytics workspace resource ID was not found." >&2
  exit 1
fi

temporary_body="$(mktemp)"
trap 'rm -f "$temporary_body"' EXIT
required_categories=("${REQUIRED_CATEGORIES[@]}")
if "$enable_azure_openai_request_usage"; then
  required_categories+=("AzureOpenAIRequestUsage")
fi

resources="$(az resource list \
  --resource-group "$resource_group" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --query '[].{id:id,name:name,kind:kind}' \
  -o json --only-show-errors)"

if [[ "$(jq 'length' <<<"$resources")" -eq 0 ]]; then
  echo "No Foundry or Azure OpenAI resources were found in $resource_group." >&2
  exit 1
fi

while IFS= read -r resource; do
  resource_id="$(jq -r '.id' <<<"$resource")"
  resource_name="$(jq -r '.name' <<<"$resource")"
  echo "Checking $resource_name"

  categories="$(az rest --method get \
    --url "https://management.azure.com${resource_id}/providers/microsoft.insights/diagnosticSettingsCategories?api-version=${DIAGNOSTICS_API_VERSION}" \
    -o json --only-show-errors)"
  for category in "${required_categories[@]}"; do
    if ! jq -e --arg category "$category" '.value[] | select(.name == $category and .properties.categoryType == "Logs")' \
      <<<"$categories" >/dev/null; then
      echo "  ERROR: $category is not a supported log category for this resource." >&2
      continue 2
    fi
  done

  settings="$(az rest --method get \
    --url "https://management.azure.com${resource_id}/providers/microsoft.insights/diagnosticSettings?api-version=${DIAGNOSTICS_API_VERSION}" \
    -o json --only-show-errors)"
  target_setting="$(jq -c --arg workspace "$workspace_resource_id_lower" '
    .value[]
    | select((.properties.workspaceId // "" | ascii_downcase) == $workspace)
    | {name: .name, properties: .properties}
  ' <<<"$settings" | head -n 1)"
  needs_apply=false

  if [[ -z "$target_setting" ]]; then
    if ! "$apply"; then
      echo "  MISSING: no diagnostic setting sends logs to the requested workspace."
      continue
    fi
    target_setting="$(jq -nc \
      --arg workspace "$workspace_resource_id" \
      --argjson categories "$(printf '%s\n' "${required_categories[@]}" | jq -R . | jq -sc .)" \
      '{
        name: "'"$setting_name"'",
        properties: {
          workspaceId: $workspace,
          logAnalyticsDestinationType: "AzureDiagnostics",
          logs: [$categories[] | {category: ., enabled: true}]
        }
      }')"
    needs_apply=true
    echo "  PATCH: creating $setting_name with RequestResponse and Trace."
  fi

  missing_categories=()
  for category in "${required_categories[@]}"; do
    if ! jq -e --arg category "$category" '
      any(.properties.logs[]?;
        .enabled == true and (.category == $category or .categoryGroup == "allLogs"))
    ' <<<"$target_setting" >/dev/null; then
      missing_categories+=("$category")
    fi
  done

  if ((${#missing_categories[@]})); then
    if ! "$apply"; then
      echo "  MISSING: ${missing_categories[*]} is disabled or absent."
      continue
    fi
    target_setting="$(jq \
      --argjson categories "$(printf '%s\n' "${required_categories[@]}" | jq -R . | jq -sc .)" '
      .properties.logs = (
        (.properties.logs // [])
        | map(
            if .category as $category | ($categories | index($category)) != null
            then .enabled = true
            else .
            end
          )
        | reduce $categories[] as $category (
            .;
            if any(.[]; .category == $category)
            then .
            else . + [{category: $category, enabled: true}]
            end
          )
      )' <<<"$target_setting")"
    needs_apply=true
    echo "  PATCH: enabling ${missing_categories[*]}."
  else
    echo "  OK: ${required_categories[*]} are enabled."
  fi

  destination_type="$(jq -r '.properties.logAnalyticsDestinationType // "AzureDiagnostics"' <<<"$target_setting")"
  case "$destination_type" in
    AzureDiagnostics)
      echo "  OK: the diagnostic setting writes to AzureDiagnostics."
      ;;
    Dedicated)
      echo "  INFO: the diagnostic setting writes to resource-specific tables; AzureDiagnostics queries must be adapted."
      ;;
    *)
      echo "  INFO: logAnalyticsDestinationType is $destination_type; verify the destination table before using AzureDiagnostics queries."
      ;;
  esac

  if "$apply" && "$needs_apply"; then
    jq '{properties: .properties}' <<<"$target_setting" >"$temporary_body"
    setting_to_update="$(jq -r '.name' <<<"$target_setting")"
    az rest --method put \
      --url "https://management.azure.com${resource_id}/providers/microsoft.insights/diagnosticSettings/${setting_to_update}?api-version=${DIAGNOSTICS_API_VERSION}" \
      --body "@${temporary_body}" \
      -o none --only-show-errors
    echo "  APPLIED: $setting_to_update"
  elif "$apply"; then
    echo "  NO CHANGE: the setting is already compliant."
  fi
done < <(jq -c '.[]' <<<"$resources")
