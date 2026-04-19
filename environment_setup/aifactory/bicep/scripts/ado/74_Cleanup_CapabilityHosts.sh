#!/bin/bash

echo "=== Capability Host Cleanup ==="
echo "This task cleans up capability hosts before account deletion."
echo "Reason: Before deleting a Foundry Account, its Account Capability Host must be removed first."
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

# Find all AI Foundry V2 accounts (aif2* prefix)
aif2_accounts=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.CognitiveServices/accounts" \
  --query "[?starts_with(name, 'aif2')].name" \
  -o tsv 2>/dev/null)

if [ -z "$aif2_accounts" ]; then
  echo "No AI Foundry V2 accounts found. Nothing to clean up."
  exit 0
fi

API_VERSION="2025-04-01-preview"
deleted_count=0

while IFS= read -r account_name; do
  [ -z "$account_name" ] && continue
  echo ""
  echo "Processing account: $account_name"

  # --- Step 1: Delete project-level capability hosts ---
  projects=$(az rest \
    --method GET \
    --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects?api-version=${API_VERSION}" \
    --query "value[].name" -o tsv 2>/dev/null)

  if [ -n "$projects" ]; then
    while IFS= read -r proj_name; do
      [ -z "$proj_name" ] && continue
      echo "  Checking project-level caphosts for project: $proj_name"

      proj_caphosts=$(az rest \
        --method GET \
        --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${proj_name}/capabilityHosts?api-version=${API_VERSION}" \
        --query "value[].name" -o tsv 2>/dev/null)

      if [ -n "$proj_caphosts" ]; then
        while IFS= read -r ch_name; do
          [ -z "$ch_name" ] && continue
          echo "    Deleting project caphost: $ch_name"
          az rest \
            --method DELETE \
            --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${proj_name}/capabilityHosts/${ch_name}?api-version=${API_VERSION}" \
            --headers "Content-Type=application/json" 2>&1 \
            && { echo "    ✅ Delete initiated for project caphost: $ch_name"; deleted_count=$((deleted_count + 1)); } \
            || echo "    ⚠️  Could not delete project caphost: $ch_name (non-fatal)"
        done <<< "$proj_caphosts"
      fi
    done <<< "$projects"
  fi

  # --- Step 2: Delete account-level capability hosts (async — may take minutes) ---
  echo "  Checking account-level caphosts for: $account_name"

  acct_caphosts=$(az rest \
    --method GET \
    --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts?api-version=${API_VERSION}" \
    --query "value[].name" -o tsv 2>/dev/null)

  if [ -n "$acct_caphosts" ]; then
    while IFS= read -r ch_name; do
      [ -z "$ch_name" ] && continue
      echo "    Deleting account caphost: $ch_name (this may take several minutes...)"

      # Use curl to capture async operation header
      access_token=$(az account get-access-token --query accessToken -o tsv 2>/dev/null)
      tmp_headers="/tmp/caphost_delete_headers_$$.txt"

      http_response=$(curl -s -w "\n%{http_code}" -X DELETE \
        -H "Authorization: Bearer $access_token" \
        -H "Content-Type: application/json" \
        "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts/${ch_name}?api-version=${API_VERSION}" \
        -D "$tmp_headers" 2>/dev/null)
      http_code=$(echo "$http_response" | tail -n1)

      if [ "$http_code" = "202" ] || [ "$http_code" = "200" ]; then
        # Poll async operation if header present
        async_url=$(grep -i "Azure-AsyncOperation" "$tmp_headers" 2>/dev/null | sed 's/.*: //' | tr -d '\r')
        if [ -n "$async_url" ]; then
          echo "    Polling deletion status..."
          poll_count=0
          max_polls=120  # 10 min max (120 * 5s)
          while [ $poll_count -lt $max_polls ]; do
            sleep 5
            poll_count=$((poll_count + 1))
            status=$(az rest --method GET --url "$async_url" --query "status" -o tsv 2>/dev/null)
            if [ "$status" = "Succeeded" ]; then
              echo "    ✅ Account caphost deleted: $ch_name"
              deleted_count=$((deleted_count + 1))
              break
            elif [ "$status" = "Failed" ] || [ "$status" = "Canceled" ]; then
              echo "    ⚠️  Account caphost deletion $status: $ch_name (non-fatal)"
              break
            fi
            if [ $((poll_count % 6)) -eq 0 ]; then
              echo "    ⏳ Still deleting... ($((poll_count * 5))s elapsed, status: $status)"
            fi
          done
          if [ $poll_count -ge $max_polls ]; then
            echo "    ⚠️  Timed out waiting for account caphost deletion: $ch_name (non-fatal)"
          fi
        else
          echo "    ✅ Account caphost deleted: $ch_name"
          deleted_count=$((deleted_count + 1))
        fi
      elif [ "$http_code" = "404" ]; then
        echo "    ℹ️  Account caphost not found (already deleted): $ch_name"
      else
        echo "    ⚠️  Could not delete account caphost: $ch_name (HTTP $http_code, non-fatal)"
      fi
      rm -f "$tmp_headers"
    done <<< "$acct_caphosts"
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
