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

# Helper: delete a caphost via az rest with error classification.
# A capability host can ONLY be DELETEd from a STABLE provisioningState
# (Succeeded / Failed / Canceled). While Creating / Updating / Accepted /
# Deleting the ARM DELETE is REJECTED with HTTP 409 Conflict:
#   "Capability Host <name> is currently non deleting, retry after its complete".
# So we first POLL (GET on the same URL) until the caphost is stable (or gone),
# then issue DELETE, retrying on Conflict within the budget below.
# Args: $1=full_delete_url $2=display_label
# Returns: 0 if deleted/not-found, 1 if failed (non-fatal)
delete_caphost_with_error_handling() {
  local delete_url="$1"
  local label="$2"

  # ---- Phase 1: wait until the caphost reaches a STABLE state (or NotFound) ----
  # GET uses the same URL as DELETE; budget ~30 min at 15s cadence.
  local max_wait_iters=120
  local i state get_output
  for ((i = 1; i <= max_wait_iters; i++)); do
    get_output=$(az rest --method GET --url "$delete_url" 2>&1) || true
    if echo "$get_output" | grep -qi "ResourceNotFound\|ParentResourceNotFound\|NotFound\|Workspace not found"; then
      echo "    ℹ️  $label not found before delete — already gone. Continuing."
      return 0
    fi
    state=$(echo "$get_output" | grep -oE '"provisioningState"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"provisioningState"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
    case "$state" in
      Succeeded|Failed|Canceled)
        echo "    Caphost $label is stable (provisioningState=$state) — safe to delete."
        break
        ;;
      "" )
        # Could not parse state (transient/list-vs-item) — proceed to delete attempt.
        echo "    Caphost $label state unknown (will attempt delete)."
        break
        ;;
      * )
        echo "    [$i/$max_wait_iters] Caphost $label is '$state' (non-stable) — waiting 15s before delete..."
        sleep 15
        ;;
    esac
  done

  # ---- Phase 2: issue DELETE, retrying on Conflict ("currently non deleting") ----
  echo "    Deleting: $label ..."
  local delete_output max_del_retries=120 d
  for ((d = 1; d <= max_del_retries; d++)); do
    delete_output=$(az rest --method DELETE --url "$delete_url" --headers "Content-Type=application/json" 2>&1) || true
    if echo "$delete_output" | grep -qi "currently non deleting\|Conflict"; then
      echo "    [$d/$max_del_retries] DELETE rejected (caphost not yet in deletable state) — waiting 15s and retrying..."
      sleep 15
      continue
    fi
    break
  done

  if echo "$delete_output" | grep -q "ParentResourceNotFound"; then
    echo "    ⚠️  ParentResourceNotFound: parent resource no longer exists (e.g., project deleted)."
    echo "       Caphost was implicitly removed. Continuing."
    return 0
  elif echo "$delete_output" | grep -qi "Workspace not found"; then
    echo "    ⚠️  'Workspace not found': internal workspace reference broken (project deleted externally)."
    echo "       Azure will clean up in background. Continuing."
    return 0
  elif echo "$delete_output" | grep -qi "ResourceNotFound\|NotFound"; then
    echo "    ℹ️  Not found — already deleted or never created."
    return 0
  elif echo "$delete_output" | grep -qi '"status":"Succeeded"\|"provisioningState":"Succeeded"\|Accepted'; then
    echo "    ✅ Delete accepted/succeeded: $label"
    deleted_count=$((deleted_count + 1))
    return 0
  else
    # Unknown response — log but don't fail the pipeline
    echo "    ⚠️  Unexpected response (non-fatal): $label"
    echo "$delete_output" | head -5
    return 1
  fi
}

# Helper: strip "parent/" prefix from resource names returned by the API
# The API returns name as "accountName/projectName" or "accountName/caphostName"
# We only need the last segment.
strip_parent_prefix() {
  local full_name="$1"
  echo "${full_name##*/}"
}

while IFS= read -r account_name; do
  [ -z "$account_name" ] && continue
  echo ""
  echo "Processing account: $account_name"

  # --- Step 1: Delete PROJECT-level capability hosts (must be done BEFORE account caphost) ---
  # Strategy: List projects, then for each project attempt to delete its caphosts.
  # If a project was already deleted externally, LIST won't return it but the account
  # caphost may still reference it. The delete_caphost_with_error_handling function
  # handles ParentResourceNotFound gracefully.
  
  projects_raw=$(az rest \
    --method GET \
    --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects?api-version=${API_VERSION}" \
    --query "value[].name" -o tsv 2>/dev/null || echo "")

  if [ -n "$projects_raw" ]; then
    while IFS= read -r proj_name_raw; do
      [ -z "$proj_name_raw" ] && continue
      # API may return "accountName/projectName" — strip to just "projectName"
      proj_name=$(strip_parent_prefix "$proj_name_raw")
      echo "  Project: $proj_name — checking for capability hosts..."

      # List caphosts for this project (may be empty if none exist)
      proj_caphosts_raw=$(az rest \
        --method GET \
        --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${proj_name}/capabilityHosts?api-version=${API_VERSION}" \
        --query "value[].name" -o tsv 2>/dev/null || echo "")

      if [ -n "$proj_caphosts_raw" ]; then
        while IFS= read -r ch_name_raw; do
          [ -z "$ch_name_raw" ] && continue
          ch_name=$(strip_parent_prefix "$ch_name_raw")

          delete_url="https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${proj_name}/capabilityHosts/${ch_name}?api-version=${API_VERSION}"
          delete_caphost_with_error_handling "$delete_url" "project caphost ${proj_name}/${ch_name}" \
            && project_caphosts_deleted=$((project_caphosts_deleted + 1))
        done <<< "$proj_caphosts_raw"
      else
        echo "    No project-level capability hosts found (or project already deleted)."
      fi
    done <<< "$projects_raw"
  else
    echo "  No projects found under account $account_name (may have been deleted already)."
    echo "  Will still attempt to clean up account-level caphosts."
  fi

  # --- Step 1b: Wait for project caphost cleanup to propagate before deleting account caphost ---
  # Always sleep if we deleted any project caphosts OR if no projects were found (to be safe)
  if [ $project_caphosts_deleted -gt 0 ]; then
    echo ""
    echo "  ⏳ Waiting 60s for project caphost deletion to propagate before deleting account caphost..."
    sleep 60
  elif [ -z "$projects_raw" ]; then
    echo ""
    echo "  ⏳ No projects listed (may be deleted) — waiting 60s before account caphost cleanup (ordering safety)..."
    sleep 60
  fi

  # --- Step 2: Delete ACCOUNT-level capability hosts (only after all project caphosts are gone) ---
  echo "  Checking account-level caphosts for: $account_name"

  acct_caphosts_raw=$(az rest \
    --method GET \
    --url "https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts?api-version=${API_VERSION}" \
    --query "value[].name" -o tsv 2>/dev/null || echo "")

  if [ -n "$acct_caphosts_raw" ]; then
    while IFS= read -r ch_name_raw; do
      [ -z "$ch_name_raw" ] && continue
      ch_name=$(strip_parent_prefix "$ch_name_raw")

      delete_url="https://management.azure.com/subscriptions/${dev_test_prod_sub_id}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts/${ch_name}?api-version=${API_VERSION}"
      delete_caphost_with_error_handling "$delete_url" "account caphost ${account_name}/${ch_name}"
    done <<< "$acct_caphosts_raw"
  else
    echo "  No account-level capability hosts found (or already deleted)."
  fi

done <<< "$aif2_accounts"

echo ""
echo "========================================"
echo "Caphost cleanup complete. Deleted: $deleted_count"
echo "========================================"

# Always exit 0 — this is a best-effort cleanup task, must never break the pipeline
exit 0
