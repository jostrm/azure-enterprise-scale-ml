#!/bin/bash
# =============================================================================
# throttle-genai.sh
# Throttle (cap) or un-throttle Azure AI Foundry / Cognitive Services (and
# optionally AI Search) at a Resource Group or Subscription scope by cutting
# network access. Fully revertible - prior state is saved into resource tags.
#
# Mechanisms (both handled, matching AI Factory public + private setups):
#   1. Public accounts   -> publicNetworkAccess=Disabled, networkAcls.defaultAction=Deny
#   2. Private endpoints -> every APPROVED private endpoint connection set to 'Rejected'
#
# Requires: az CLI logged in with rights on Microsoft.CognitiveServices/accounts.
#
# Usage:
#   ./throttle-genai.sh --action throttle   --scope resourcegroup --resource-group <rg>
#   ./throttle-genai.sh --action unthrottle --scope subscription  --subscription <subId>
#   ./throttle-genai.sh --action status     --scope resourcegroup --resource-group <rg>
# Options:
#   --include-search   also throttle Microsoft.Search/searchServices
#   --dry-run          print actions only
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

ACTION=""; SCOPE=""; SUBSCRIPTION=""; RESOURCE_GROUP=""; INCLUDE_SEARCH="false"; DRY_RUN="false"
# AI Factory naming
ESML_AIFACTORY_EXISTS="false"; VARS_FILE=""; ENV_NAME="dev"; PROJECT_NUMBER=""
VNET_RESOURCE_GROUP=""; VNET_NAME=""; PRIVATE_DNS_RG=""; STORAGE_ACCOUNT_NAME=""

TAG_STATE="esmlThrottleState"
TAG_PREV_PNA="esmlThrottlePrevPublicNet"
TAG_PREV_ACL="esmlThrottlePrevDefaultAcl"
TAG_PREV_PECS="esmlThrottledPeConns"
TAG_TIMESTAMP="esmlThrottleTimestampUtc"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --action)                 ACTION="$2"; shift 2;;
    --scope)                  SCOPE="$2"; shift 2;;
    --subscription)           SUBSCRIPTION="$2"; shift 2;;
    --resource-group)         RESOURCE_GROUP="$2"; shift 2;;
    --include-search)         INCLUDE_SEARCH="true"; shift;;
    --esml-aifactory-exists)  ESML_AIFACTORY_EXISTS="true"; shift;;
    --vars-file)              VARS_FILE="$2"; shift 2;;
    --env)                    ENV_NAME="$2"; shift 2;;
    --project-number)         PROJECT_NUMBER="$2"; shift 2;;
    --vnet-resource-group)    VNET_RESOURCE_GROUP="$2"; shift 2;;
    --vnet-name)              VNET_NAME="$2"; shift 2;;
    --private-dns-rg)         PRIVATE_DNS_RG="$2"; shift 2;;
    --storage-account)        STORAGE_ACCOUNT_NAME="$2"; shift 2;;
    --dry-run)                DRY_RUN="true"; shift;;
    --help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo -e "${RED}Unknown parameter: $1${NC}"; exit 1;;
  esac
done

ACTION="$(echo "$ACTION" | tr '[:upper:]' '[:lower:]')"
SCOPE="$(echo "$SCOPE" | tr '[:upper:]' '[:lower:]')"

[[ "$ACTION" =~ ^(throttle|unthrottle|status)$ ]] || { echo -e "${RED}--action must be throttle|unthrottle|status${NC}"; exit 1; }
[[ "$SCOPE"  =~ ^(subscription|resourcegroup)$ ]] || { echo -e "${RED}--scope must be subscription|resourcegroup${NC}"; exit 1; }

# Reads a top-level "key: value" from an AI Factory variables.yaml.
_yaml_get() {
  local file="$1" key="$2"
  grep -E "^[[:space:]]*${key}:" "$file" 2>/dev/null | head -n1 \
    | sed -E "s/^[[:space:]]*${key}:[[:space:]]*//" \
    | sed -E 's/[[:space:]]*#.*$//' \
    | sed -E 's/^"//; s/"[[:space:]]*$//' \
    | tr -d '\r'
}

# --- Derive AI Factory resource names when --esml-aifactory-exists ---
if [[ "$ESML_AIFACTORY_EXISTS" == "true" ]]; then
  [[ -n "$VARS_FILE" ]] || { echo -e "${RED}--esml-aifactory-exists requires --vars-file <variables.yaml>${NC}"; exit 1; }
  [[ -f "$VARS_FILE" ]] || { echo -e "${RED}--vars-file '$VARS_FILE' not found${NC}"; exit 1; }
  echo -e "${CYAN}Deriving AI Factory resource names from '$VARS_FILE' (env=$ENV_NAME)...${NC}"

  _prefixRG=$(_yaml_get "$VARS_FILE" admin_aifactoryPrefixRG)
  _projectPrefix=$(_yaml_get "$VARS_FILE" projectPrefix)
  _projectSuffix=$(_yaml_get "$VARS_FILE" projectSuffix)
  _projNum=$(_yaml_get "$VARS_FILE" project_number_000)
  _locSuffix=$(_yaml_get "$VARS_FILE" admin_locationSuffix)
  _suffixRG=$(_yaml_get "$VARS_FILE" admin_aifactorySuffixRG)
  _commonSuffix=$(_yaml_get "$VARS_FILE" admin_commonResourceSuffix)
  _vnetNameBase=$(_yaml_get "$VARS_FILE" vnetNameBase)
  _vnetRgBase=$(_yaml_get "$VARS_FILE" vnetResourceGroupBase)
  _vnetRgParam=$(_yaml_get "$VARS_FILE" vnetResourceGroup_param)
  _vnetNameParam=$(_yaml_get "$VARS_FILE" vnetNameFull_param)

  case "$ENV_NAME" in
    dev)  _subId=$(_yaml_get "$VARS_FILE" dev_sub_id) ;;
    test) _subId=$(_yaml_get "$VARS_FILE" test_sub_id) ;;
    prod) _subId=$(_yaml_get "$VARS_FILE" prod_sub_id) ;;
    *) echo -e "${RED}--env must be dev|test|prod (got '$ENV_NAME')${NC}"; exit 1 ;;
  esac

  [[ -z "$PROJECT_NUMBER" ]] && PROJECT_NUMBER="$_projNum"

  _projectRG="${_prefixRG}${_projectPrefix}project${PROJECT_NUMBER}-${_locSuffix}-${ENV_NAME}${_suffixRG}${_projectSuffix}"
  if [[ -n "$_vnetRgParam" ]]; then _vnetRG="$_vnetRgParam"; else _vnetRG="${_prefixRG}${_vnetRgBase}-${_locSuffix}-${ENV_NAME}${_suffixRG}"; fi
  if [[ -n "$_vnetNameParam" ]]; then _vnetName="$_vnetNameParam"; else _vnetName="${_vnetNameBase}-${_locSuffix}-${ENV_NAME}${_commonSuffix}"; fi

  # Fill ONLY the values not passed explicitly (CLI wins).
  [[ -z "$SUBSCRIPTION" ]]         && SUBSCRIPTION="$_subId"
  [[ -z "$RESOURCE_GROUP" ]]       && RESOURCE_GROUP="$_projectRG"
  [[ -z "$VNET_RESOURCE_GROUP" ]]  && VNET_RESOURCE_GROUP="$_vnetRG"
  [[ -z "$VNET_NAME" ]]            && VNET_NAME="$_vnetName"
  # AI Factory private DNS zones live in the vnet/common RG by convention.
  [[ -z "$PRIVATE_DNS_RG" ]]       && PRIVATE_DNS_RG="$_vnetRG"

  echo -e "${GREEN}  project RG        : $RESOURCE_GROUP${NC}"
  echo -e "${GREEN}  vnet RG           : $VNET_RESOURCE_GROUP${NC}"
  echo -e "${GREEN}  vnet name         : $VNET_NAME${NC}"
  echo -e "${GREEN}  private DNS RG    : $PRIVATE_DNS_RG${NC}"
fi

if [[ "$SCOPE" == "resourcegroup" && -z "$RESOURCE_GROUP" ]]; then
  echo -e "${RED}--resource-group is required when --scope resourcegroup (or use --esml-aifactory-exists --vars-file ...)${NC}"; exit 1
fi
command -v az >/dev/null 2>&1 || { echo -e "${RED}az CLI not found. Install and 'az login'.${NC}"; exit 1; }

if [[ -z "$SUBSCRIPTION" ]]; then SUBSCRIPTION="$(az account show --query id -o tsv)"; fi
echo -e "${CYAN}Using subscription: $SUBSCRIPTION${NC}"
az account set --subscription "$SUBSCRIPTION"

run() { # run or echo when dry-run
  if [[ "$DRY_RUN" == "true" ]]; then echo -e "${YELLOW}  [dry-run] $*${NC}"; else eval "$@"; fi
}

list_cognitive() {
  if [[ "$SCOPE" == "resourcegroup" ]]; then
    az resource list -g "$RESOURCE_GROUP" --resource-type 'Microsoft.CognitiveServices/accounts' \
      --query "[].{name:name, rg:resourceGroup, id:id}" -o json
  else
    az resource list --resource-type 'Microsoft.CognitiveServices/accounts' \
      --query "[].{name:name, rg:resourceGroup, id:id}" -o json
  fi
}

list_search() {
  if [[ "$SCOPE" == "resourcegroup" ]]; then
    az resource list -g "$RESOURCE_GROUP" --resource-type 'Microsoft.Search/searchServices' \
      --query "[].{name:name, rg:resourceGroup, id:id}" -o json
  else
    az resource list --resource-type 'Microsoft.Search/searchServices' \
      --query "[].{name:name, rg:resourceGroup, id:id}" -o json
  fi
}

get_tag() { # $1 resourceId $2 tagKey
  az resource show --ids "$1" --query "tags.$2" -o tsv 2>/dev/null || true
}

throttle_account() {
  local id="$1" name="$2" rg="$3"
  echo -e "${CYAN}-> Cognitive account: $name (rg: $rg)${NC}"

  local state; state="$(get_tag "$id" "$TAG_STATE")"
  if [[ "$state" == "throttled" ]]; then echo -e "${YELLOW}   already throttled - skipping${NC}"; return; fi

  local prevPna prevAcl
  prevPna="$(az resource show --ids "$id" --query "properties.publicNetworkAccess" -o tsv 2>/dev/null || echo Enabled)"
  prevAcl="$(az resource show --ids "$id" --query "properties.networkAcls.defaultAction" -o tsv 2>/dev/null || echo Allow)"
  [[ -z "$prevPna" || "$prevPna" == "None" ]] && prevPna="Enabled"
  [[ -z "$prevAcl" || "$prevAcl" == "None" ]] && prevAcl="Allow"

  # 1) Reject approved private endpoint connections
  local rejected=""
  local pecs; pecs="$(az network private-endpoint-connection list --id "$id" \
      --query "[?properties.privateLinkServiceConnectionState.status=='Approved'].{name:name,id:id}" -o json 2>/dev/null || echo '[]')"
  local count; count="$(echo "$pecs" | jq 'length')"
  local i=0
  while [[ $i -lt $count ]]; do
    local pn pid
    pn="$(echo "$pecs" | jq -r ".[$i].name")"
    pid="$(echo "$pecs" | jq -r ".[$i].id")"
    echo -e "${CYAN}   rejecting private endpoint connection: $pn${NC}"
    run "az network private-endpoint-connection reject --id \"$pid\" --description 'Throttled by esml aimodel-throttling' -o none"
    rejected="${rejected}${pn};"
    i=$((i+1))
  done

  # 2) Block public path
  echo -e "${CYAN}   setting publicNetworkAccess=Disabled, networkAcls.defaultAction=Deny${NC}"
  run "az resource update --ids \"$id\" --set properties.publicNetworkAccess=Disabled properties.networkAcls.defaultAction=Deny -o none"

  # 3) Save state to tags
  run "az resource tag --ids \"$id\" --is-incremental --tags \
    ${TAG_STATE}=throttled ${TAG_PREV_PNA}=${prevPna} ${TAG_PREV_ACL}=${prevAcl} \
    ${TAG_PREV_PECS}=\"${rejected}\" ${TAG_TIMESTAMP}=\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" -o none"
  echo -e "${GREEN}   throttled (prev publicNet=$prevPna, prev acl=$prevAcl)${NC}"
}

unthrottle_account() {
  local id="$1" name="$2" rg="$3"
  echo -e "${CYAN}-> Cognitive account: $name (rg: $rg)${NC}"

  local state; state="$(get_tag "$id" "$TAG_STATE")"
  if [[ "$state" != "throttled" ]]; then echo -e "${YELLOW}   not throttled by this tool - skipping${NC}"; return; fi

  local prevPna prevAcl pecs
  prevPna="$(get_tag "$id" "$TAG_PREV_PNA")"; [[ -z "$prevPna" ]] && prevPna="Enabled"
  prevAcl="$(get_tag "$id" "$TAG_PREV_ACL")"; [[ -z "$prevAcl" ]] && prevAcl="Allow"
  pecs="$(get_tag "$id" "$TAG_PREV_PECS")"

  echo -e "${CYAN}   restoring publicNetworkAccess=$prevPna, networkAcls.defaultAction=$prevAcl${NC}"
  run "az resource update --ids \"$id\" --set properties.publicNetworkAccess=$prevPna properties.networkAcls.defaultAction=$prevAcl -o none"

  if [[ -n "$pecs" && "$pecs" != "None" ]]; then
    IFS=';' read -ra arr <<< "$pecs"
    for pn in "${arr[@]}"; do
      [[ -z "$pn" ]] && continue
      echo -e "${CYAN}   approving private endpoint connection: $pn${NC}"
      run "az network private-endpoint-connection approve --resource-name \"$name\" -g \"$rg\" --name \"$pn\" --type 'Microsoft.CognitiveServices/accounts' --description 'Un-throttled by esml aimodel-throttling' -o none"
    done
  fi

  run "az resource tag --ids \"$id\" --is-incremental --tags ${TAG_STATE}=normal -o none"
  echo -e "${GREEN}   un-throttled (restored)${NC}"
}

status_account() {
  local id="$1" name="$2"
  local state pna acl
  state="$(get_tag "$id" "$TAG_STATE")"; [[ -z "$state" ]] && state="normal"
  pna="$(az resource show --ids "$id" --query "properties.publicNetworkAccess" -o tsv 2>/dev/null || true)"
  acl="$(az resource show --ids "$id" --query "properties.networkAcls.defaultAction" -o tsv 2>/dev/null || true)"
  printf "  %-45s state=%-9s publicNet=%-9s acl=%s\n" "$name" "$state" "$pna" "$acl"
}

# small helper to count json array length using jq
command -v jq >/dev/null 2>&1 || { echo -e "${RED}jq is required. Install jq.${NC}"; exit 1; }

ACCOUNTS_JSON="$(list_cognitive)"
ACC_COUNT="$(echo "$ACCOUNTS_JSON" | jq 'length')"
echo -e "${CYAN}Found $ACC_COUNT Cognitive Services account(s) in scope '$SCOPE'.${NC}"

idx=0
while [[ $idx -lt $ACC_COUNT ]]; do
  id="$(echo "$ACCOUNTS_JSON"   | jq -r ".[$idx].id")"
  name="$(echo "$ACCOUNTS_JSON" | jq -r ".[$idx].name")"
  rg="$(echo "$ACCOUNTS_JSON"   | jq -r ".[$idx].rg")"
  case "$ACTION" in
    throttle)   throttle_account   "$id" "$name" "$rg";;
    unthrottle) unthrottle_account "$id" "$name" "$rg";;
    status)     status_account     "$id" "$name";;
  esac
  idx=$((idx+1))
done

if [[ "$INCLUDE_SEARCH" == "true" ]]; then
  SEARCH_JSON="$(list_search)"; S_COUNT="$(echo "$SEARCH_JSON" | jq 'length')"
  echo -e "${CYAN}Found $S_COUNT AI Search service(s) in scope.${NC}"
  sidx=0
  while [[ $sidx -lt $S_COUNT ]]; do
    sname="$(echo "$SEARCH_JSON" | jq -r ".[$sidx].name")"
    srg="$(echo "$SEARCH_JSON"   | jq -r ".[$sidx].rg")"
    case "$ACTION" in
      throttle)   echo -e "${CYAN}-> AI Search: $sname -> disabled${NC}"; run "az search service update -g \"$srg\" -n \"$sname\" --public-access disabled -o none";;
      unthrottle) echo -e "${CYAN}-> AI Search: $sname -> enabled${NC}";  run "az search service update -g \"$srg\" -n \"$sname\" --public-access enabled -o none";;
      status)     pna="$(az search service show -g "$srg" -n "$sname" --query publicNetworkAccess -o tsv 2>/dev/null || true)"; printf "  %-45s publicNet=%s\n" "$sname" "$pna";;
    esac
    sidx=$((sidx+1))
  done
fi

echo -e "${GREEN}Done. action=$ACTION scope=$SCOPE $( [[ "$DRY_RUN" == "true" ]] && echo '(dry-run - no changes made)')${NC}"
