#!/bin/bash
# =============================================================================
# delete-caphost-and-foundry-and-its-subnet.sh
#
# One-shot, manual cleanup for a single AI Foundry 2025 (AIServices) account.
# Combines the logic of the pipeline tasks:
#   06a_Delete_CapabilityHosts                 -> delete caphosts in correct order
#   06b_Delete_Service_If_Not_Enabled_And_Exists (Foundry section) -> delete account
#   06c_Purge_SoftDeleted (Foundry part)       -> purge the soft-deleted account
# ...and then (opt-in) reuses the tested:
#   delete-subnets-for-projects.sh --purpose aca-002  -> delete the agent subnet
# to give a "once-and-only-once" (DRY) implementation of the subnet deletion.
#
# WHY this script exists
# ----------------------
# Purging the Foundry account ALONE can leave orphaned capability hosts and the
# managed agent backend holding the delegated agent subnet, which then blocks
# redeployment with "Subnet already in use" / "Invalid vnet resource ID". The
# Microsoft-recommended teardown ORDER is:
#   1. project capability host(s)
#   2. wait ~60s
#   3. account capability host(s)        (long-running; we poll until gone)
#   4. nested project(s)
#   5. private endpoints on the account
#   6. account (soft-delete)
#   7. purge soft-deleted account        [unless --no-purge]
#   8. agent subnet snt-prj{nnn}-aca-002 [only with --delete-subnet]
# Doing it out of order (or skipping caphosts) is the usual cause of "Error-1".
#
# This script ENUMERATES the actual caphosts/projects via REST (it does NOT
# reconstruct names from salt), so it also detects + removes "ghost" caphosts
# that linger after a project was deleted in the portal.
#
# NOTE ON THE TWO ACA SUBNETS
# ---------------------------
# Each project has TWO ACA subnets: snt-prj{nnn}-aca and snt-prj{nnn}-aca-002.
# Foundry's agent network injection uses ONLY the -002 subnet (it is the one
# delegated to Microsoft.App/environments). Therefore subnet deletion defaults
# to --purpose aca-002 so the other ACA subnet is left untouched.
#
# Usage:
#   bash delete-caphost-and-foundry-and-its-subnet.sh \
#       --subscription   <sub-id> \
#       --resource-group <project-rg> \
#       [--account-name   <aif2...>]        # auto-discovered in the RG if omitted
#       [--project-name   <foundry-project>]# optional; otherwise all projects enumerated
#       [--location       swedencentral] \
#       [--api-version    2025-04-01-preview] \
#       [--list-only]                        # only run the "ghost" detection, change nothing
#       [--no-purge]                         # soft-delete the account but do NOT purge
#       [--skip-account-delete]              # only clean caphosts (+ optional subnet)
#       [--skip-caphost-delete]              # skip caphost delete; go straight to account
#                                            #   teardown (cascades + force-clears a
#                                            #   stuck-'Creating' ghost caphost)
#       [--delete-subnet]                    # also delete snt-prj{nnn}-aca-002
#         [--project-number       <nnn>]     #   required with --delete-subnet
#         [--vnet-resource-group  <vnet-rg>] #   required with --delete-subnet
#         [--vnet-name            <vnet>]    #   required with --delete-subnet
#         [--subnet-purpose       aca-002]   #   override the subnet suffix (default aca-002)
#       [--whatif]                           # dry-run: show actions, change nothing
#
# Auto-derive from variables.yaml (no need to type subscription / RG / vnet):
#   Pass --vars-file <path-to-variables.yaml> [--env dev|test|prod] and the
#   script derives, using the SAME concat logic as job-2-genai-services.yaml:
#     subscription        = <env>_sub_id
#     project RG          = {admin_aifactoryPrefixRG}{projectPrefix}project{project_number_000}-{admin_locationSuffix}-{env}{admin_aifactorySuffixRG}{projectSuffix}
#     vnet RG             = vnetResourceGroup_param  OR  {admin_aifactoryPrefixRG}{vnetResourceGroupBase}-{admin_locationSuffix}-{env}{admin_aifactorySuffixRG}
#     vnet name           = vnetNameFull_param       OR  {vnetNameBase}-{admin_locationSuffix}-{env}{admin_commonResourceSuffix}
#     project number      = project_number_000  (override with --project-number)
#     location            = admin_location
#   Any explicit CLI flag overrides the value derived from the file.
#
# Examples:
#   # Detect ghost caphosts for project 015 using only variables.yaml:
#   bash delete-caphost-and-foundry-and-its-subnet.sh \
#       --vars-file aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml \
#       --env dev --list-only
#
#   # Just detect ghost caphosts for an account (no changes):
#   bash delete-caphost-and-foundry-and-its-subnet.sh \
#       --subscription 612e830e-b795-424e-ba5d-cd0a5dadecf4 \
#       --resource-group mrvel-1-project014-sdc-dev-007 --list-only
#
#   # Full teardown incl. the agent subnet, all derived from variables.yaml:
#   bash delete-caphost-and-foundry-and-its-subnet.sh \
#       --vars-file aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml \
#       --env dev --delete-subnet
# =============================================================================

# NOTE: deliberately NOT 'set -e' - we want to continue past expected errors
# (ParentResourceNotFound / ResourceNotFound / already-purged, etc.).
set -uo pipefail

# Git Bash / MSYS on Windows rewrites args that look like POSIX paths (e.g. ARM
# IDs '/subscriptions/...') into 'C:/Program Files/Git/...'. Disable it so REST
# URLs and resource IDs pass through verbatim. Harmless on Linux/macOS.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -----------------------------------------------------------------------------
# Parse arguments
# -----------------------------------------------------------------------------
SUBSCRIPTION_ID=""
RESOURCE_GROUP=""
ACCOUNT_NAME=""
PROJECT_NAME=""
LOCATION="swedencentral"
API_VERSION="2025-04-01-preview"
LIST_ONLY="false"
NO_PURGE="false"
SKIP_ACCOUNT_DELETE="false"
SKIP_CAPHOST_DELETE="false"
DELETE_SUBNET="false"
PROJECT_NUMBER=""
VNET_RESOURCE_GROUP=""
VNET_NAME=""
SUBNET_PURPOSE="aca-002"
WHATIF="false"
VARS_FILE=""
ENV_NAME="dev"

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --subscription)         SUBSCRIPTION_ID="$2";      shift 2 ;;
    --resource-group)       RESOURCE_GROUP="$2";       shift 2 ;;
    --account-name)         ACCOUNT_NAME="$2";         shift 2 ;;
    --project-name)         PROJECT_NAME="$2";         shift 2 ;;
    --location)             LOCATION="$2";             shift 2 ;;
    --api-version)          API_VERSION="$2";          shift 2 ;;
    --vars-file)            VARS_FILE="$2";            shift 2 ;;
    --env)                  ENV_NAME="$2";             shift 2 ;;
    --list-only)            LIST_ONLY="true";          shift 1 ;;
    --no-purge)             NO_PURGE="true";           shift 1 ;;
    --skip-account-delete)  SKIP_ACCOUNT_DELETE="true";shift 1 ;;
    --skip-caphost-delete)  SKIP_CAPHOST_DELETE="true";shift 1 ;;
    --delete-subnet)        DELETE_SUBNET="true";      shift 1 ;;
    --project-number)       PROJECT_NUMBER="$2";       shift 2 ;;
    --vnet-resource-group)  VNET_RESOURCE_GROUP="$2";  shift 2 ;;
    --vnet-name)            VNET_NAME="$2";            shift 2 ;;
    --subnet-purpose)       SUBNET_PURPOSE="$2";       shift 2 ;;
    --whatif)               WHATIF="true";             shift 1 ;;
    -h|--help)              usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

# -----------------------------------------------------------------------------
# Optionally derive everything from variables.yaml (the same concat logic used
# by job-2-genai-services.yaml: targetResourceGroup + vnetResourceGroup/Name).
# Explicit CLI flags always WIN over values derived from the file.
# -----------------------------------------------------------------------------
# Read a scalar 'key: "value"' (or 'key: value') from a flat YAML file. The
# trailing ':' anchor prevents prefix collisions (admin_location vs
# admin_locationSuffix). Strips inline '# comments' and surrounding quotes.
_yaml_get() {
  local file="$1" key="$2"
  grep -E "^[[:space:]]*${key}:" "$file" 2>/dev/null | head -n1 \
    | sed -E "s/^[[:space:]]*${key}:[[:space:]]*//" \
    | sed -E 's/[[:space:]]*#.*$//' \
    | sed -E 's/^"//; s/"[[:space:]]*$//' \
    | tr -d '\r'
}

if [ -n "$VARS_FILE" ]; then
  if [ ! -f "$VARS_FILE" ]; then
    echo "ERROR: --vars-file '$VARS_FILE' not found."
    exit 1
  fi
  echo "Deriving values from '$VARS_FILE' (env=$ENV_NAME)..."

  _prefixRG=$(_yaml_get "$VARS_FILE" admin_aifactoryPrefixRG)
  _projectPrefix=$(_yaml_get "$VARS_FILE" projectPrefix)
  _projectSuffix=$(_yaml_get "$VARS_FILE" projectSuffix)
  _projNum=$(_yaml_get "$VARS_FILE" project_number_000)
  _locSuffix=$(_yaml_get "$VARS_FILE" admin_locationSuffix)
  _suffixRG=$(_yaml_get "$VARS_FILE" admin_aifactorySuffixRG)
  _commonSuffix=$(_yaml_get "$VARS_FILE" admin_commonResourceSuffix)
  _location=$(_yaml_get "$VARS_FILE" admin_location)
  _vnetNameBase=$(_yaml_get "$VARS_FILE" vnetNameBase)
  _vnetRgBase=$(_yaml_get "$VARS_FILE" vnetResourceGroupBase)
  _vnetRgParam=$(_yaml_get "$VARS_FILE" vnetResourceGroup_param)
  _vnetNameParam=$(_yaml_get "$VARS_FILE" vnetNameFull_param)

  case "$ENV_NAME" in
    dev)  _subId=$(_yaml_get "$VARS_FILE" dev_sub_id) ;;
    test) _subId=$(_yaml_get "$VARS_FILE" test_sub_id) ;;
    prod) _subId=$(_yaml_get "$VARS_FILE" prod_sub_id) ;;
    *) echo "ERROR: --env must be one of dev|test|prod (got '$ENV_NAME')."; exit 1 ;;
  esac

  # Project number: CLI override wins, else from file.
  [ -z "$PROJECT_NUMBER" ] && PROJECT_NUMBER="$_projNum"

  # Project resource group (== job-2 targetResourceGroup).
  _projectRG="${_prefixRG}${_projectPrefix}project${PROJECT_NUMBER}-${_locSuffix}-${ENV_NAME}${_suffixRG}${_projectSuffix}"

  # VNet RG: honor BYO vnetResourceGroup_param, else the common-RG fallback.
  if [ -n "$_vnetRgParam" ]; then
    _vnetRG="$_vnetRgParam"
  else
    _vnetRG="${_prefixRG}${_vnetRgBase}-${_locSuffix}-${ENV_NAME}${_suffixRG}"
  fi

  # VNet name: honor BYO vnetNameFull_param, else the common-vnet fallback.
  if [ -n "$_vnetNameParam" ]; then
    _vnetName="$_vnetNameParam"
  else
    _vnetName="${_vnetNameBase}-${_locSuffix}-${ENV_NAME}${_commonSuffix}"
  fi

  # Fill ONLY the values the user did not pass explicitly (CLI wins).
  [ -z "$SUBSCRIPTION_ID" ]     && SUBSCRIPTION_ID="$_subId"
  [ -z "$RESOURCE_GROUP" ]     && RESOURCE_GROUP="$_projectRG"
  [ -z "$VNET_RESOURCE_GROUP" ] && VNET_RESOURCE_GROUP="$_vnetRG"
  [ -z "$VNET_NAME" ]          && VNET_NAME="$_vnetName"
  [ -z "$LOCATION" ] || [ "$LOCATION" = "swedencentral" ] && [ -n "$_location" ] && LOCATION="$_location"

  echo "  Derived subscription      : $SUBSCRIPTION_ID"
  echo "  Derived project RG        : $RESOURCE_GROUP"
  echo "  Derived project number    : $PROJECT_NUMBER"
  echo "  Derived vnet RG           : $VNET_RESOURCE_GROUP"
  echo "  Derived vnet name         : $VNET_NAME"
  echo "  Derived location          : $LOCATION"
fi

if [ -z "$SUBSCRIPTION_ID" ] || [ -z "$RESOURCE_GROUP" ]; then
  echo "ERROR: subscription and resource group are required (pass --subscription/--resource-group, or --vars-file <variables.yaml>)."
  usage
fi

if [ "$DELETE_SUBNET" = "true" ]; then
  if [ -z "$PROJECT_NUMBER" ] || [ -z "$VNET_RESOURCE_GROUP" ] || [ -z "$VNET_NAME" ]; then
    echo "ERROR: --delete-subnet requires --project-number, --vnet-resource-group and --vnet-name."
    usage
  fi
fi

echo "Setting subscription: $SUBSCRIPTION_ID"
az account set --subscription "$SUBSCRIPTION_ID" 2>/dev/null || true

# -----------------------------------------------------------------------------
# Discover the AI Foundry (AIServices) account if not provided. Account names
# start with 'aif2' and have NO hyphen; project sub-resources are 'aif2-p...'
# but they are NOT returned by 'accounts' list, so this is safe.
# -----------------------------------------------------------------------------
if [ -z "$ACCOUNT_NAME" ]; then
  echo "Discovering AI Foundry account (aif2*) in resource group '$RESOURCE_GROUP'..."
  ACCOUNT_NAME=$(az resource list \
    --resource-group "$RESOURCE_GROUP" \
    --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[?starts_with(name, 'aif2')].name | [0]" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")
fi

if [ -z "$ACCOUNT_NAME" ] || [ "$ACCOUNT_NAME" = "None" ]; then
  echo "No AI Foundry account (aif2*) found in '$RESOURCE_GROUP'."
  echo "The account may already be deleted/purged. Continuing to caphost/subnet checks where possible."
  ACCOUNT_NAME=""
fi

BASE_URL=""
[ -n "$ACCOUNT_NAME" ] && \
  BASE_URL="https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${ACCOUNT_NAME}"

echo ""
echo "================ Configuration ================"
echo "Subscription      : $SUBSCRIPTION_ID"
echo "Resource Group    : $RESOURCE_GROUP"
echo "Foundry Account   : ${ACCOUNT_NAME:-<none found>}"
echo "Project (optional): ${PROJECT_NAME:-<all enumerated>}"
echo "Location          : $LOCATION"
echo "API Version       : $API_VERSION"
echo "List only         : $LIST_ONLY"
echo "Skip acct delete  : $SKIP_ACCOUNT_DELETE"
echo "Skip caphost del  : $SKIP_CAPHOST_DELETE"
echo "Purge after delete: $([ "$NO_PURGE" = "true" ] && echo false || echo true)"
echo "Delete subnet     : $DELETE_SUBNET $([ "$DELETE_SUBNET" = "true" ] && echo "(snt-prj${PROJECT_NUMBER}-${SUBNET_PURPOSE})")"
[ "$WHATIF" = "true" ] && echo "Mode              : WhatIf (no changes will be made)"
echo "==============================================="
echo ""

# =============================================================================
# Helpers
# =============================================================================

# GET .value[].name from a caphost/projects collection URL. Empty on any error.
_rest_list_names() {
  local url="$1"
  az rest --method GET --url "$url" --query "value[].name" -o tsv 2>/dev/null | tr -d '\r' || echo ""
}

# Project names can come back as 'account/project'; keep only the leaf.
_leaf() { echo "${1##*/}"; }

# URL-encode the single '@' in the account caphost name (e.g. acct@aml_aiagentservice).
_enc_at() { echo "${1//@/%40}"; }

# -----------------------------------------------------------------------------
# Robustly delete ONE capability host (account- or project-level) by URL.
#
# WHY this is not a single DELETE:
#   A caphost can ONLY be deleted from a STABLE provisioningState
#   (Succeeded/Failed/Canceled). While it is still Creating/Updating/Accepted
#   the ARM DELETE is rejected with:
#       Conflict: "... is currently non deleting, retry after its complete"
#   So we must: wait until the create/update finishes -> issue DELETE ->
#   then wait until it is gone, retrying DELETE if a Conflict comes back.
#
# Loop (10s cadence, ~30 min budget):
#   NotFound/empty            -> success
#   Creating/Updating/Accepted-> create/update in flight: WAIT (do not delete)
#   Deleting                  -> delete already running: WAIT
#   Succeeded/Failed/Canceled -> STABLE: issue DELETE (retry on Conflict)
#
# Usage: _delete_caphost_robust <url> <label>
# -----------------------------------------------------------------------------
_delete_caphost_robust() {
  local url="$1" label="$2"
  local max=180 i=0 state out
  while [ "$i" -lt "$max" ]; do
    state=$(az rest --method GET --url "$url" \
      --query "properties.provisioningState" -o tsv 2>/dev/null | tr -d '\r' || echo "NotFound")

    if [ -z "$state" ] || [ "$state" = "NotFound" ]; then
      echo "    $label fully deleted."
      return 0
    fi

    case "$state" in
      Creating|Updating|Accepted|Provisioning)
        [ $((i % 6)) -eq 0 ] && echo "    $label still provisioning (state=$state) - waiting for a stable state before delete ($((i*10))s)"
        ;;
      Deleting)
        [ $((i % 6)) -eq 0 ] && echo "    $label delete in progress (state=$state, $((i*10))s)"
        ;;
      *)
        # Stable state -> attempt DELETE.
        out=$(az rest --method DELETE --url "$url" --headers "Content-Type=application/json" 2>&1) || true
        if echo "$out" | grep -qiE "non deleting|retry after|Conflict|currently"; then
          [ $((i % 6)) -eq 0 ] && echo "    $label busy (Conflict) - retrying delete ($((i*10))s)"
        elif echo "$out" | grep -qiE "ResourceNotFound|NotFound"; then
          echo "    $label not found - already deleted."
          return 0
        else
          echo "    $label delete accepted (was state=$state)."
        fi
        ;;
    esac

    sleep 10
    i=$((i + 1))
  done
  echo "    WARNING: $label not confirmed deleted after $((max*10))s - proceeding anyway."
  return 1
}

# -----------------------------------------------------------------------------
# STEP 0 - LIST capability hosts ("ghost" detection): account + each project.
# Mirrors the exact GET URLs from the Microsoft guidance.
# -----------------------------------------------------------------------------
list_caphosts() {
  if [ -z "$BASE_URL" ]; then
    echo "[0/8] No account present -> nothing to list."
    return 0
  fi

  echo "[0/8] Listing capability hosts (ghost detection) for account '$ACCOUNT_NAME'..."

  echo "  Account-level capability hosts:"
  local acct_chs
  acct_chs=$(_rest_list_names "${BASE_URL}/capabilityHosts?api-version=${API_VERSION}")
  if [ -n "$acct_chs" ]; then echo "$acct_chs" | sed '/^$/d' | sed 's/^/    - /'; else echo "    (none)"; fi

  echo "  Projects under the account:"
  local projects
  if [ -n "$PROJECT_NAME" ]; then
    projects="$PROJECT_NAME"
  else
    projects=$(_rest_list_names "${BASE_URL}/projects?api-version=${API_VERSION}")
  fi
  if [ -z "$projects" ]; then
    echo "    (none)"
  else
    while IFS= read -r proj; do
      [ -z "$proj" ] && continue
      proj=$(_leaf "$proj")
      echo "    project '$proj' capability hosts:"
      local pchs
      pchs=$(_rest_list_names "${BASE_URL}/projects/${proj}/capabilityHosts?api-version=${API_VERSION}")
      if [ -n "$pchs" ]; then echo "$pchs" | sed '/^$/d' | sed 's/^/        - /'; else echo "        (none)"; fi
    done <<< "$projects"
  fi
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 1 - DELETE project-level capability host(s) for every project.
# -----------------------------------------------------------------------------
delete_project_caphosts() {
  [ -z "$BASE_URL" ] && return 0
  echo "[1/8] Deleting PROJECT capability host(s)..."

  local projects
  if [ -n "$PROJECT_NAME" ]; then
    projects="$PROJECT_NAME"
  else
    projects=$(_rest_list_names "${BASE_URL}/projects?api-version=${API_VERSION}")
  fi
  if [ -z "$projects" ]; then
    echo "  No projects found under the account."
    return 0
  fi

  while IFS= read -r proj; do
    [ -z "$proj" ] && continue
    proj=$(_leaf "$proj")
    local pchs
    pchs=$(_rest_list_names "${BASE_URL}/projects/${proj}/capabilityHosts?api-version=${API_VERSION}")
    if [ -z "$pchs" ]; then
      echo "  project '$proj': no capability hosts."
      continue
    fi
    while IFS= read -r ch; do
      [ -z "$ch" ] && continue
      ch=$(_leaf "$ch")
      if [ "$WHATIF" = "true" ]; then
        echo "  [WhatIf] Would DELETE project caphost: $proj/$ch"
        continue
      fi
      echo "  Deleting project caphost: $proj/$ch"
      _delete_caphost_robust \
        "${BASE_URL}/projects/${proj}/capabilityHosts/${ch}?api-version=${API_VERSION}" \
        "project caphost '$proj/$ch'"
    done <<< "$pchs"
  done <<< "$projects"
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 3 - DELETE account-level capability host(s), then POLL until gone.
# The account caphost delete is long-running; we poll GET until NotFound.
# -----------------------------------------------------------------------------
delete_account_caphosts() {
  [ -z "$BASE_URL" ] && return 0
  echo "[3/8] Deleting ACCOUNT capability host(s)..."

  local acct_chs
  acct_chs=$(_rest_list_names "${BASE_URL}/capabilityHosts?api-version=${API_VERSION}")
  if [ -z "$acct_chs" ]; then
    echo "  No account-level capability hosts."
    return 0
  fi

  while IFS= read -r ch; do
    [ -z "$ch" ] && continue
    ch=$(_leaf "$ch")
    local ch_enc
    ch_enc=$(_enc_at "$ch")
    if [ "$WHATIF" = "true" ]; then
      echo "  [WhatIf] Would DELETE account caphost: $ch"
      continue
    fi
    echo "  Deleting account caphost: $ch"
    _delete_caphost_robust \
      "${BASE_URL}/capabilityHosts/${ch_enc}?api-version=${API_VERSION}" \
      "account caphost '$ch'"
  done <<< "$acct_chs"
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 4 - DELETE nested project(s).
# -----------------------------------------------------------------------------
delete_projects() {
  [ -z "$BASE_URL" ] && return 0
  echo "[4/8] Deleting nested project(s)..."

  local projects
  if [ -n "$PROJECT_NAME" ]; then
    projects="$PROJECT_NAME"
  else
    projects=$(_rest_list_names "${BASE_URL}/projects?api-version=${API_VERSION}")
  fi
  if [ -z "$projects" ]; then
    echo "  No projects to delete."
    return 0
  fi

  while IFS= read -r proj; do
    [ -z "$proj" ] && continue
    proj=$(_leaf "$proj")
    if [ "$WHATIF" = "true" ]; then
      echo "  [WhatIf] Would DELETE project: $proj"
      continue
    fi
    echo "  Deleting project: $proj"
    az rest --method DELETE \
      --url "${BASE_URL}/projects/${proj}?api-version=${API_VERSION}" \
      --headers "Content-Type=application/json" 2>&1 | sed 's/^/    /' || true
  done <<< "$projects"
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 5 - DELETE private endpoints for the account (+ matching NICs).
# Ported from delete-services-if-disabled.sh delete_private_endpoints().
# -----------------------------------------------------------------------------
delete_account_private_endpoints() {
  [ -z "$ACCOUNT_NAME" ] && return 0
  echo "[5/8] Deleting private endpoints for account '$ACCOUNT_NAME'..."

  local pend_list
  pend_list=$(az network private-endpoint list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?(name == '${ACCOUNT_NAME}' || starts_with(name, '${ACCOUNT_NAME}-pend') || starts_with(name, 'p-${ACCOUNT_NAME}') || starts_with(name, 'pend-${ACCOUNT_NAME}'))].name" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")

  if [ -z "$pend_list" ]; then
    echo "  No private endpoints found for '$ACCOUNT_NAME'."
  else
    while IFS= read -r pend_name; do
      [ -z "$pend_name" ] && continue
      if [ "$WHATIF" = "true" ]; then
        echo "  [WhatIf] Would DELETE private endpoint: $pend_name"
        continue
      fi
      echo "  Deleting private endpoint: $pend_name"
      if ! az network private-endpoint delete --resource-group "$RESOURCE_GROUP" --name "$pend_name" 2>&1 | sed 's/^/    /'; then
        echo "    Normal delete failed - trying REST force delete"
        az rest --method DELETE \
          --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01" \
          2>&1 | sed 's/^/    /' || echo "    Force delete also failed for $pend_name"
      fi
    done <<< "$pend_list"
    [ "$WHATIF" = "false" ] && { echo "  Waiting 10s for PE deletions to settle..."; sleep 10; }
  fi

  # Orphan NICs left behind by the PEs.
  local nic_list
  nic_list=$(az network nic list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?(starts_with(name, '${ACCOUNT_NAME}-pend') || starts_with(name, '${ACCOUNT_NAME}.nic'))].name" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")
  if [ -n "$nic_list" ]; then
    while IFS= read -r nic_name; do
      [ -z "$nic_name" ] && continue
      if [ "$WHATIF" = "true" ]; then
        echo "  [WhatIf] Would DELETE NIC: $nic_name"
        continue
      fi
      echo "  Deleting NIC: $nic_name"
      az network nic delete --resource-group "$RESOURCE_GROUP" --name "$nic_name" 2>&1 | sed 's/^/    /' || echo "    Failed to delete NIC $nic_name"
    done <<< "$nic_list"
  fi
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 6 - Soft-delete the account.
# -----------------------------------------------------------------------------
delete_account() {
  [ -z "$ACCOUNT_NAME" ] && { echo "[6/8] No account to delete."; return 0; }
  echo "[6/8] Soft-deleting Foundry account '$ACCOUNT_NAME'..."
  if [ "$WHATIF" = "true" ]; then
    echo "  [WhatIf] Would run: az cognitiveservices account delete -g $RESOURCE_GROUP -n $ACCOUNT_NAME"
    return 0
  fi
  az cognitiveservices account delete \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACCOUNT_NAME" 2>&1 | sed 's/^/  /' || echo "  (account delete returned non-zero - it may already be gone)"
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 7 - Purge the soft-deleted account.
# -----------------------------------------------------------------------------
purge_account() {
  [ -z "$ACCOUNT_NAME" ] && { echo "[7/8] No account to purge."; return 0; }
  echo "[7/8] Purging soft-deleted Foundry account '$ACCOUNT_NAME'..."
  if [ "$WHATIF" = "true" ]; then
    echo "  [WhatIf] Would run: az cognitiveservices account purge -g $RESOURCE_GROUP -n $ACCOUNT_NAME -l $LOCATION"
    return 0
  fi
  az cognitiveservices account purge \
    --subscription "$SUBSCRIPTION_ID" \
    --location "$LOCATION" \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACCOUNT_NAME" 2>&1 | sed 's/^/  /' || echo "  (purge returned non-zero - it may already be purged or not yet soft-deleted)"
  echo ""
}

# -----------------------------------------------------------------------------
# STEP 8 - Delete the Foundry agent subnet snt-prj{nnn}-aca-002 (DRY: reuse
# the tested delete-subnets-for-projects.sh with --purpose aca-002).
# -----------------------------------------------------------------------------
delete_agent_subnet() {
  [ "$DELETE_SUBNET" != "true" ] && return 0
  echo "[8/8] Deleting agent subnet snt-prj${PROJECT_NUMBER}-${SUBNET_PURPOSE} via delete-subnets-for-projects.sh..."

  local sub_script="${SCRIPT_DIR}/delete-subnets-for-projects.sh"
  if [ ! -f "$sub_script" ]; then
    echo "  ERROR: cannot find $sub_script - skipping subnet deletion."
    return 0
  fi

  local whatif_arg=()
  [ "$WHATIF" = "true" ] && whatif_arg=(--whatif)

  bash "$sub_script" \
    --projects-from "$PROJECT_NUMBER" \
    --resource-group "$VNET_RESOURCE_GROUP" \
    --vnet-name "$VNET_NAME" \
    --subscription "$SUBSCRIPTION_ID" \
    --purpose "$SUBNET_PURPOSE" \
    "${whatif_arg[@]}"
  echo ""
}

# =============================================================================
# MAIN
# =============================================================================
list_caphosts

if [ "$LIST_ONLY" = "true" ]; then
  echo "--list-only set: ghost detection complete, no changes made."
  exit 0
fi

# 06a: caphosts in correct order (project -> wait -> account)
if [ "$SKIP_CAPHOST_DELETE" = "true" ]; then
  echo "[1-3/8] --skip-caphost-delete set: skipping caphost deletion. The account"
  echo "        delete below will cascade and force-clear any stuck caphost."
else
  delete_project_caphosts

  if [ -n "$BASE_URL" ] && [ "$WHATIF" = "false" ]; then
    echo "[2/8] Waiting 60s before deleting account caphost (required ordering)..."
    sleep 60
  else
    echo "[2/8] (skip 60s wait - whatif or no account)"
  fi

  delete_account_caphosts
fi

# 06b: delete the Foundry account (projects -> PEs -> account) unless skipped
if [ "$SKIP_ACCOUNT_DELETE" = "true" ]; then
  echo "[4-7/8] --skip-account-delete set: leaving projects/PEs/account in place."
else
  delete_projects
  delete_account_private_endpoints
  delete_account
  if [ "$NO_PURGE" = "true" ]; then
    echo "[7/8] --no-purge set: account left soft-deleted (NOT purged)."
  else
    purge_account
  fi
fi

# subnet (opt-in, DRY via sibling script)
delete_agent_subnet

echo "=== Done ==="
if [ "$WHATIF" = "true" ]; then
  echo "WhatIf mode: no changes were made."
else
  echo "Cleanup complete for account '${ACCOUNT_NAME:-<none>}' in RG '$RESOURCE_GROUP'."
  echo "NOTE: after an account PURGE, the agent subnet backend can take ~20 min to"
  echo "      fully release. If you also deleted the subnet, redeploy can proceed once"
  echo "      the VNet shows the subnet gone and provisioningState=Succeeded."
fi
