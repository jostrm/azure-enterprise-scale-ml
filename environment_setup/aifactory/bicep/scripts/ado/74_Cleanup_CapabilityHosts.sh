#!/bin/bash

echo "=== Capability Host Cleanup ==="
echo "This task cleans up capability hosts before account deletion."
echo "Correct order: 1) Delete PROJECT caphosts  2) Wait  3) Delete ACCOUNT caphosts  4) Delete/purge account"
echo "Reason: Before deleting a Foundry Account, its Account Capability Host must be removed first."
echo "        Before deleting the Account Capability Host, all Project Capability Hosts must be removed."
echo "Residual dependencies (subnets, ACA apps) can cause 'Subnet already in use' errors otherwise."

# Map positional arguments passed from the pipeline
if [ $# -ge 1 ]; then dev_test_prod_sub_id="$1"; fi
if [ $# -ge 2 ]; then admin_aifactoryPrefixRG="$2"; fi
if [ $# -ge 3 ]; then project_number_000="$3"; fi
if [ $# -ge 4 ]; then admin_locationSuffix="$4"; fi
if [ $# -ge 5 ]; then dev_test_prod="$5"; fi
if [ $# -ge 6 ]; then admin_aifactorySuffixRG="$6"; fi
if [ $# -ge 7 ]; then admin_prjResourceSuffix="$7"; fi
if [ $# -ge 8 ]; then aifactory_salt="$8"; fi
if [ $# -ge 9 ]; then aifactory_salt_random="$9"; fi
if [ $# -ge 10 ]; then deployment_random_value="${10}"; fi
if [ $# -ge 11 ]; then projectPrefix="${11}"; fi
if [ $# -ge 12 ]; then projectSuffix="${12}"; fi

az account set --subscription "$dev_test_prod_sub_id"

# Build resource group name (same logic as 73_)
commonRGNamePrefix="$admin_aifactoryPrefixRG"
projectNumber="$project_number_000"
projectName="prj${projectNumber}"
locationSuffix="$admin_locationSuffix"
envName="$dev_test_prod"
aifactorySuffixRG="$admin_aifactorySuffixRG"

projectNameReplaced="${projectName/prj/project}"
targetResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"

echo "Target Resource Group: $targetResourceGroup"

# Find all AI Foundry V2 accounts (aif2* prefix, but NOT projects which start with aif2-p)
aif2_accounts=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.CognitiveServices/accounts" \
  --query "[?starts_with(name, 'aif2') && !starts_with(name, 'aif2-p')].name" \
  -o tsv 2>/dev/null)

if [ -z "$aif2_accounts" ]; then
  echo "No AI Foundry V2 accounts found. Nothing to clean up."
  exit 0
fi

API_VERSION="2025-04-01-preview"
deleted_count=0
project_caphosts_deleted=0

# Helper: strip "parent/" prefix from resource names returned by the API
# The API returns name as "accountName/projectName" or "accountName/caphostName"
# We only need the last segment.
strip_parent_prefix() {
  local full_name="$1"
  echo "${full_name##*/}"
}

# Helper: delete a caphost via curl with async polling
# Args: $1=full_delete_url $2=display_label
delete_caphost_with_poll() {
  local delete_url="$1"
  local label="$2"

  local access_token
  access_token=$(az account get-access-token --query accessToken -o tsv 2>/dev/null)
  local tmp_headers="/tmp/caphost_delete_headers_$$.txt"

  local http_response
  http_response=$(curl -s -w "\n%{http_code}" -X DELETE \
    -H "Authorization: Bearer $access_token" \
    -H "Content-Type: application/json" \
    "$delete_url" \
    -D "$tmp_headers" 2>/dev/null)
  local http_body
  http_body=$(echo "$http_response" | head -n -1)
  local http_code
  http_code=$(echo "$http_response" | tail -n1)

  if [ "$http_code" = "202" ] || [ "$http_code" = "200" ]; then
    # Poll async operation if header present
    local async_url
    async_url=$(grep -i "Azure-AsyncOperation" "$tmp_headers" 2>/dev/null | sed 's/.*: //' | tr -d '\r')
    if [ -n "$async_url" ]; then
      echo "    Polling deletion status for $label..."
      local poll_count=0
      local max_polls=120  # 10 min max (120 * 5s)
      while [ $poll_count -lt $max_polls ]; do
        sleep 5
        poll_count=$((poll_count + 1))
        local status
        status=$(az rest --method GET --url "$async_url" --query "status" -o tsv 2>/dev/null)
        if [ "$status" = "Succeeded" ]; then
          echo "    ✅ Deleted: $label"
          deleted_count=$((deleted_count + 1))
          rm -f "$tmp_headers"
          return 0
        elif [ "$status" = "Failed" ] || [ "$status" = "Canceled" ]; then
          echo "    ⚠️  Deletion $status: $label (non-fatal)"
          rm -f "$tmp_headers"
          return 1
        fi
        if [ $((poll_count % 6)) -eq 0 ]; then
          echo "    ⏳ Still deleting $label... ($((poll_count * 5))s elapsed, status: $status)"
        fi
      done
      echo "    ⚠️  Timed out waiting for deletion: $label (non-fatal)"
      rm -f "$tmp_headers"
      return 1
    else
      echo "    ✅ Deleted (sync): $label"
      deleted_count=$((deleted_count + 1))
      rm -f "$tmp_headers"
      return 0
    fi
  elif [ "$http_code" = "404" ]; then
    echo "    ℹ️  Not found (already deleted): $label"
    rm -f "$tmp_headers"
    return 0
  else
    echo "    ⚠️  Could not delete: $label (HTTP $http_code, non-fatal)"
    [ -n "$http_body" ] && echo "    Response: $http_body"
    rm -f "$tmp_headers"
    return 1
  fi
}

while IFS= read -r account_name; do
  [ -z "$account_name" ] && continue
  echo ""
  echo "Processing account: $account_name"

  # --- Step 1: Delete PROJECT-level capability hosts (must be done BEFORE account caphost) ---
  projects_raw=$(az rest \
    --method GET \
    --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects?api-version=${API_VERSION}" \
    --query "value[].name" -o tsv 2>/dev/null)

  if [ -n "$projects_raw" ]; then
    while IFS= read -r proj_name_raw; do
      [ -z "$proj_name_raw" ] && continue
      # API may return "accountName/projectName" — strip to just "projectName"
      proj_name=$(strip_parent_prefix "$proj_name_raw")
      echo "  Checking project-level caphosts for project: $proj_name"

      proj_caphosts_raw=$(az rest \
        --method GET \
        --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${proj_name}/capabilityHosts?api-version=${API_VERSION}" \
        --query "value[].name" -o tsv 2>/dev/null)

      if [ -n "$proj_caphosts_raw" ]; then
        while IFS= read -r ch_name_raw; do
          [ -z "$ch_name_raw" ] && continue
          ch_name=$(strip_parent_prefix "$ch_name_raw")
          echo "    Deleting project caphost: ${account_name}/${proj_name}/${ch_name}"

          delete_url="https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${proj_name}/capabilityHosts/${ch_name}?api-version=${API_VERSION}"
          delete_caphost_with_poll "$delete_url" "project caphost ${proj_name}/${ch_name}" \
            && project_caphosts_deleted=$((project_caphosts_deleted + 1))
        done <<< "$proj_caphosts_raw"
      else
        echo "    No project-level capability hosts found for $proj_name."
      fi
    done <<< "$projects_raw"
  else
    echo "  No projects found under account $account_name."
  fi

  # --- Step 1b: Wait for project caphost cleanup to propagate before deleting account caphost ---
  if [ $project_caphosts_deleted -gt 0 ]; then
    echo ""
    echo "  ⏳ Waiting 60s for project caphost deletion to propagate before deleting account caphost..."
    sleep 60
  fi

  # --- Step 2: Delete ACCOUNT-level capability hosts (only after all project caphosts are gone) ---
  echo "  Checking account-level caphosts for: $account_name"

  acct_caphosts_raw=$(az rest \
    --method GET \
    --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts?api-version=${API_VERSION}" \
    --query "value[].name" -o tsv 2>/dev/null)

  if [ -n "$acct_caphosts_raw" ]; then
    while IFS= read -r ch_name_raw; do
      [ -z "$ch_name_raw" ] && continue
      ch_name=$(strip_parent_prefix "$ch_name_raw")
      echo "    Deleting account caphost: ${account_name}/${ch_name} (this may take several minutes...)"

      delete_url="https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts/${ch_name}?api-version=${API_VERSION}"
      delete_caphost_with_poll "$delete_url" "account caphost ${account_name}/${ch_name}"
    done <<< "$acct_caphosts_raw"
  else
    echo "  No account-level capability hosts found."
  fi

done <<< "$aif2_accounts"

echo ""
echo "========================================"
echo "Caphost cleanup complete. Deleted: $deleted_count"
echo "========================================"

# Always exit 0 — this is a best-effort cleanup task, must never break the pipeline
exit 0
