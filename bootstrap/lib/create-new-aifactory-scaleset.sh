#!/usr/bin/env bash

set -euo pipefail

readonly AIF_SUBMODULE_URL="https://github.com/jostrm/azure-enterprise-scale-ml"
readonly AIF_SUBMODULE_BRANCH="${AIF_SUBMODULE_BRANCH:-release/v1.24}"
readonly AIF_ADO_RESOURCE="https://app.vssps.visualstudio.com/"
readonly AIF_SCALESET_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MSYS2_ARG_CONV_EXCL="${MSYS2_ARG_CONV_EXCL:+$MSYS2_ARG_CONV_EXCL;}/subscriptions/;/providers/;/eid1/;scope=/subscriptions/;privateLinksDnsZones="
readonly AIF_SIMPLE_MODE_CONTRACT_VERSION=1

aif_scaleset_usage() {
  cat <<'EOF'
Usage: ADO-create-new-aifactory-scaleset.sh [options]
       GHA-create-new-aifactory-scaleset.sh [options]
       ALL-create-new-aifactory-scaleset.sh --orchestrator ado|gha [options]

Options:
  --repo-root PATH     Target AI Factory repository root.
  --dry-run            Collect and validate answers without changing anything.
  --prepare-only       Prepare Azure, identity, configuration, and automation only.
  --no-wait            Dispatch pipelines/workflows without waiting for completion.
  --non-interactive    Read answers from AIF_* environment variables only.
  --yes                Accept the final execution summary.
  --help               Show this help.

Common non-interactive variables:
  AIF_TOPOLOGY=s|hs
  AIF_NETWORK_MODE=priv|h|pub
  AIF_IDENTITY_MODE=c|mi|sp
  AIF_LOCATION=eastus2
  AIF_TENANT_ID=<guid>
  AIF_DEV_SUBSCRIPTION_ID=<guid>
  AIF_DEV_VNET_CIDR=172.16.0.0/18
  AIF_PREFIX=acme-ai-
  AIF_SCALESET_SUFFIX=001
  AIF_PROJECT_NUMBER=001
  AIF_TEAM_GROUP_NAME=acme-ai-prj001-team
  AIF_TEAM_MEMBER_EMAIL=jostrm@microsoft.com
  AIF_TEAM_GROUP_ID=<existing-group-object-id>
  AIF_AZURE_ML_PRINCIPAL_ID=<existing-enterprise-app-object-id>
  AIF_DATABRICKS_PRINCIPAL_ID=<existing-enterprise-app-object-id>
  AIF_ADMIN_VM_SIZE=Standard_D2s_v5
  AIF_SETUP_HUB_ACCESS=y|n
  AIF_CONFIGURE_VPN_CLIENT=y|n
  AIF_SIMPLE_MODE=true   Opt in to private-ai-foundation-v1 (GHA, DEV only).
  AIF_COST_CENTER=123456 Simple Mode common and project cost-center tags.
EOF
  if [[ "${AIF_ROUTE:-}" == "gha" ]]; then
    cat <<'EOF'

GitHub Actions route:
  GITHUB_REPOSITORY=owner/repository
EOF
  else
    cat <<'EOF'

Azure DevOps route:
  ADO_ORGANIZATION=https://dev.azure.com/organization
  ADO_PROJECT=project
  ADO_REPOSITORY_NAME=repository
  ADO_RUNNER_MODE=s|h
EOF
  fi
}

aif_shell_quote() {
  printf '%q ' "$@"
}

aif_mutate() {
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: $(aif_shell_quote "$@")"
    return 0
  fi
  "$@"
}

aif_require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    aif_error "Required command '$1' is not available." >&2
    exit 1
  fi
}

aif_is_windows() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

aif_cleanup() {
  local resource_group
  for resource_group in \
    "${AIF_TEMP_BOOTSTRAP_RG:-}" \
    "${AIF_TEMP_MANAGED_RG:-}"; do
    [[ -n "$resource_group" ]] || continue
    az group delete \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --name "$resource_group" \
      --yes \
      --no-wait \
      --output none 2>/dev/null || true
  done
  [[ -z "${AIF_STATE_DIR:-}" ]] || rm -rf -- "$AIF_STATE_DIR"
}

aif_python() {
  if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    AIF_PYTHON=(python)
  elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
    AIF_PYTHON=(py -3)
  elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    AIF_PYTHON=(python3)
  else
    aif_error "A working Python 3 interpreter is required." >&2
    exit 1
  fi
}

aif_prompt_value() {
  local variable_name="$1" prompt="$2" default_value="${3:-}" required="${4:-true}"
  local -n output="$variable_name"
  while [[ -z "$output" ]]; do
    if [[ "$AIF_NON_INTERACTIVE" == "true" ]]; then
      if [[ -n "$default_value" ]]; then
        output="$default_value"
        break
      fi
      if [[ "$required" == "true" ]]; then
        aif_error "$prompt is required in non-interactive mode." >&2
        exit 1
      fi
      break
    fi
    local suffix=""
    [[ -z "$default_value" ]] || suffix=" [$default_value]"
    read -r -p "$(aif_prompt "$prompt$suffix: ")" output
    output="${output:-$default_value}"
    [[ "$required" != "true" || -n "$output" ]] || aif_warn "A value is required."
  done
}

aif_prompt_secret() {
  local variable_name="$1" prompt="$2"
  local -n output="$variable_name"
  if [[ -n "$output" ]]; then
    return
  fi
  if [[ "$AIF_NON_INTERACTIVE" == "true" ]]; then
    aif_error "$prompt is required in non-interactive mode." >&2
    exit 1
  fi
  read -r -s -p "$(aif_prompt "$prompt (input hidden): ")" output
  printf '\n'
  if [[ -z "$output" ]]; then
    aif_error "$prompt cannot be empty." >&2
    exit 1
  fi
}

aif_prompt_choice() {
  local variable_name="$1" prompt="$2" default_value="$3" allowed="$4"
  local -n output="$variable_name"
  while true; do
    if [[ -z "$output" ]]; then
      if [[ "$AIF_NON_INTERACTIVE" == "true" ]]; then
        output="$default_value"
      else
        read -r -p "$(aif_prompt "$prompt [$default_value]: ")" output
        output="${output:-$default_value}"
      fi
    fi
    if [[ " $allowed " == *" ${output,,} "* ]]; then
      output="${output,,}"
      return
    fi
    aif_warn "Choose one of: ${allowed// /, }."
    [[ "$AIF_NON_INTERACTIVE" != "true" ]] || exit 1
    output=""
  done
}

aif_prompt_yes_no() {
  local variable_name="$1" prompt="$2" default_value="$3"
  local -n output="$variable_name"
  aif_prompt_choice "$variable_name" "$prompt" "$default_value" "y yes n no true false"
  case "$output" in
    y|yes|true) output="true" ;;
    *) output="false" ;;
  esac
}

aif_simple_mode_defaults() {
  AIF_SIMPLE_MODE="${AIF_SIMPLE_MODE:-false}"
  if [[ "$AIF_SIMPLE_MODE" != "true" && "$AIF_SIMPLE_MODE" != "false" ]]; then
    aif_error "AIF_SIMPLE_MODE must be true or false." >&2
    exit 1
  fi
  [[ "$AIF_SIMPLE_MODE" == "true" ]] || return 0
  if [[ "$AIF_ROUTE" != "gha" || "$AIF_NO_WAIT" == "true" ||
        "$AIF_PREPARE_ONLY" == "true" || "$AIF_DRY_RUN" == "true" ]]; then
    aif_error "Simple Mode requires the GHA full DEV chain with default waiting; use the Python manifest for an offline preview." >&2
    exit 1
  fi
  if [[ -n "${AIF_SP_CLIENT_SECRET:-}" || -n "${AIF_SP_CLIENT_ID:-}" ||
        -n "${AIF_MI_RESOURCE_ID:-}" ]]; then
    aif_error "Simple Mode creates managed identity/OIDC and accepts no service-principal credentials." >&2
    exit 1
  fi
  local binding name expected
  for binding in \
    AIF_TOPOLOGY=s AIF_NETWORK_MODE=priv AIF_ACCESS_HUB_MODE=i \
    AIF_IDENTITY_MODE=c AIF_SEEDING_MODE=c AIF_SEED_PROJECT_SP=false \
    AIF_SETUP_HUB_ACCESS=true AIF_CONFIGURE_VPN_CLIENT=false \
    AIF_DEV_VNET_CIDR=172.16.0.0/20 AIF_PROJECT_NUMBER=001; do
    name="${binding%%=*}"; expected="${binding#*=}"
    if [[ -n "${!name:-}" && "${!name}" != "$expected" ]]; then
      aif_error "Simple Mode requires $binding; use Advanced Mode for other settings." >&2
      exit 1
    fi
    printf -v "$name" '%s' "$expected"
  done
  AIF_COST_CENTER="${AIF_COST_CENTER:-123456}"
  if [[ ! "$AIF_COST_CENTER" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
    aif_error "Cost center must be 1-64 letters, digits, underscores or hyphens." >&2
    exit 1
  fi
}

aif_validate_guid() {
  [[ "$1" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]
}

aif_validate_number_3() {
  [[ "$1" =~ ^[0-9]{1,3}$ ]] && ((10#$1 >= 1 && 10#$1 <= 999))
}

aif_validate_cidr() {
  "${AIF_PYTHON[@]}" - "$1" <<'PY'
import ipaddress
import sys

network = ipaddress.ip_network(sys.argv[1], strict=True)
if network.version != 4 or network.prefixlen > 20:
    raise SystemExit(1)
PY
}

aif_validate_ip_allowlist() {
  "${AIF_PYTHON[@]}" - "$1" <<'PY'
import ipaddress
import sys

for item in filter(None, (part.strip() for part in sys.argv[1].split(","))):
    if "/" in item:
        ipaddress.ip_network(item, strict=False)
    else:
        ipaddress.ip_address(item)
PY
}

aif_validate_network_plan() {
  "${AIF_PYTHON[@]}" - "$@" <<'PY'
import ipaddress
import sys

networks = [ipaddress.ip_network(value, strict=True) for value in sys.argv[1:]]
for index, network in enumerate(networks):
    for other in networks[index + 1:]:
        if network.overlaps(other):
            raise SystemExit(f"Overlapping network ranges: {network} and {other}")
PY
}

aif_validate_access_hub_cidr() {
  "${AIF_PYTHON[@]}" - "$1" <<'PY'
import ipaddress
import sys

network = ipaddress.ip_network(sys.argv[1], strict=True)
if network.version != 4 or network.prefixlen > 24:
    raise SystemExit(1)
PY
}

aif_resolve_repo_root() {
  if [[ -n "$AIF_REPO_ROOT" ]]; then
    AIF_REPO_ROOT="$(realpath -m "$AIF_REPO_ROOT")"
    return
  fi
  local entry_dir superproject
  entry_dir="$(cd "$(dirname "$AIF_ENTRYPOINT")" && pwd)"
  superproject="$(git -C "$entry_dir" rev-parse --show-superproject-working-tree 2>/dev/null || true)"
  if [[ -n "$superproject" ]]; then
    AIF_REPO_ROOT="$superproject"
  elif [[ -d "$entry_dir/.git" || -f "$entry_dir/.git" ]]; then
    AIF_REPO_ROOT="$entry_dir"
  else
    aif_error "Could not determine the target repository. Use --repo-root PATH." >&2
    exit 1
  fi
}

aif_current_origin_slug() {
  local origin
  origin="$(git -C "$AIF_REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  [[ -n "$origin" ]] || return 0
  "${AIF_PYTHON[@]}" - "$origin" <<'PY'
import re
import sys
from urllib.parse import unquote, urlparse

url = sys.argv[1].rstrip("/")
if "/_git/" in url:
    print(unquote(url.rsplit("/_git/", 1)[1]).removesuffix(".git"))
else:
    match = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", url)
    if match:
        print(match.group(1))
PY
}

aif_current_ado_coordinates() {
  local origin
  origin="$(git -C "$AIF_REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  [[ -n "$origin" ]] || return 0
  "${AIF_PYTHON[@]}" - "$origin" <<'PY'
import re
import sys
from urllib.parse import unquote, urlparse

url = sys.argv[1].rstrip("/")
ssh = re.search(r"ssh\.dev\.azure\.com:v3/([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$", url)
if ssh:
    print("\n".join(unquote(value) for value in ssh.groups()))
    raise SystemExit

parsed = urlparse(url)
host = (parsed.hostname or "").lower()
parts = [unquote(part) for part in parsed.path.split("/") if part]
if host == "dev.azure.com" and len(parts) >= 4 and parts[-2] == "_git":
    print(parts[0])
    print(parts[-3])
    print(parts[-1].removesuffix(".git"))
elif host.endswith(".visualstudio.com") and len(parts) >= 3 and parts[-2] == "_git":
    print(host.removesuffix(".visualstudio.com"))
    print(parts[-3])
    print(parts[-1].removesuffix(".git"))
else:
    raise SystemExit(f"Unsupported Azure DevOps origin URL: {url}")
PY
}

aif_collect_answers() {
  local current_tenant current_subscription current_repo current_user
  current_tenant="$(az account show --query tenantId --output tsv 2>/dev/null || true)"
  current_subscription="$(az account show --query id --output tsv 2>/dev/null || true)"
  current_user="$(az account show --query user.name --output tsv 2>/dev/null || true)"
  current_tenant="${current_tenant//$'\r'/}"
  current_subscription="${current_subscription//$'\r'/}"
  current_user="${current_user//$'\r'/}"
  [[ "$current_user" == *@* ]] || current_user=""
  current_repo="$(aif_current_origin_slug)"
  current_repo="${current_repo//$'\r'/}"

  AIF_TOPOLOGY="${AIF_TOPOLOGY:-}"
  AIF_NETWORK_MODE="${AIF_NETWORK_MODE:-}"
  AIF_IDENTITY_MODE="${AIF_IDENTITY_MODE:-}"
  AIF_TENANT_ID="${AIF_TENANT_ID:-}"
  AIF_DEV_SUBSCRIPTION_ID="${AIF_DEV_SUBSCRIPTION_ID:-}"
  AIF_LOCATION="${AIF_LOCATION:-}"
  AIF_DEV_VNET_CIDR="${AIF_DEV_VNET_CIDR:-}"
  AIF_PREFIX="${AIF_PREFIX:-}"
  AIF_SCALESET_SUFFIX="${AIF_SCALESET_SUFFIX:-}"
  AIF_PROJECT_NUMBER="${AIF_PROJECT_NUMBER:-}"
  AIF_TEAM_GROUP_NAME="${AIF_TEAM_GROUP_NAME:-}"
  AIF_TEAM_MEMBER_EMAIL="${AIF_TEAM_MEMBER_EMAIL:-}"
  AIF_TEAM_GROUP_ID="${AIF_TEAM_GROUP_ID:-}"
  AIF_AZURE_ML_PRINCIPAL_ID="${AIF_AZURE_ML_PRINCIPAL_ID:-}"
  AIF_DATABRICKS_PRINCIPAL_ID="${AIF_DATABRICKS_PRINCIPAL_ID:-}"
  AIF_IP_ALLOWLIST="${AIF_IP_ALLOWLIST:-}"
  AIF_ACCESS_HUB_MODE="${AIF_ACCESS_HUB_MODE:-}"
  AIF_ACCESS_HUB_SUBSCRIPTION_ID="${AIF_ACCESS_HUB_SUBSCRIPTION_ID:-}"
  AIF_ACCESS_HUB_RESOURCE_GROUP="${AIF_ACCESS_HUB_RESOURCE_GROUP:-}"
  AIF_ACCESS_HUB_VNET_NAME="${AIF_ACCESS_HUB_VNET_NAME:-}"
  AIF_ACCESS_HUB_VNET_CIDR="${AIF_ACCESS_HUB_VNET_CIDR:-}"
  AIF_VPN_CLIENT_CIDR="${AIF_VPN_CLIENT_CIDR:-}"
  AIF_SETUP_HUB_ACCESS="${AIF_SETUP_HUB_ACCESS:-}"
  AIF_CONFIGURE_VPN_CLIENT="${AIF_CONFIGURE_VPN_CLIENT:-}"
  AIF_SEEDING_MODE="${AIF_SEEDING_MODE:-}"
  AIF_SEEDING_RESOURCE_GROUP="${AIF_SEEDING_RESOURCE_GROUP:-}"
  AIF_SEEDING_KEYVAULT_NAME="${AIF_SEEDING_KEYVAULT_NAME:-}"
  local seeding_resource_group_input="$AIF_SEEDING_RESOURCE_GROUP"
  local seeding_keyvault_name_input="$AIF_SEEDING_KEYVAULT_NAME"
  AIF_SEED_PROJECT_SP="${AIF_SEED_PROJECT_SP:-}"
  AIF_ADD_BASTION="${AIF_ADD_BASTION:-}"
  AIF_MI_RESOURCE_ID="${AIF_MI_RESOURCE_ID:-}"
  AIF_SP_CLIENT_ID="${AIF_SP_CLIENT_ID:-}"
  AIF_SP_CLIENT_SECRET="${AIF_SP_CLIENT_SECRET:-}"
  AIF_ADMIN_VM_SIZE="${AIF_ADMIN_VM_SIZE:-Standard_D2s_v5}"

  aif_section "01 / Architecture and networking"
  aif_prompt_choice AIF_TOPOLOGY \
    "Topology: standalone (s) or hub/spoke with central DNS (hs)" "s" "s hs"
  aif_prompt_choice AIF_NETWORK_MODE \
    "Networking: private-only (priv; enforced by policy)" \
    "priv" "priv"
  aif_prompt_choice AIF_IDENTITY_MODE \
    "Deployment identity: create managed identity (c), existing managed identity (mi), or existing service principal (sp)" \
    "c" "c mi sp"
  aif_prompt_value AIF_LOCATION \
    "Azure region (swedencentral, westeurope, northeurope, eastus, eastus2, uksouth, westgermany)" \
    "swedencentral"
  case "${AIF_LOCATION,,}" in
    swedencentral) AIF_LOCATION="swedencentral"; AIF_LOCATION_SHORT="sdc" ;;
    westeurope) AIF_LOCATION="westeurope"; AIF_LOCATION_SHORT="weu" ;;
    northeurope) AIF_LOCATION="northeurope"; AIF_LOCATION_SHORT="neu" ;;
    eastus) AIF_LOCATION="eastus"; AIF_LOCATION_SHORT="eus" ;;
    eastus2) AIF_LOCATION="eastus2"; AIF_LOCATION_SHORT="eus2" ;;
    uksouth) AIF_LOCATION="uksouth"; AIF_LOCATION_SHORT="uks" ;;
    westgermany|germanywestcentral)
      AIF_LOCATION="germanywestcentral"
      AIF_LOCATION_SHORT="gwc"
      ;;
    *)
      aif_error "Unsupported region '$AIF_LOCATION'." >&2
      exit 1
      ;;
  esac
  aif_prompt_value AIF_DEV_VNET_CIDR "DEV vNet CIDR (canonical IPv4 /20 or larger; no XX placeholder)" "172.16.0.0/18"
  if ! aif_validate_cidr "$AIF_DEV_VNET_CIDR"; then
    aif_error "DEV vNet CIDR must be a canonical IPv4 /20 or larger range; resolve XX to the DEV octet first." >&2
    exit 1
  fi

  if [[ "$AIF_TOPOLOGY" == "s" ]]; then
    aif_prompt_choice AIF_ACCESS_HUB_MODE \
      "Standalone access hub: integrated in DEV common network (i) or external connectivity subscription (e)" \
      "i" "i e"
    if [[ "$AIF_ACCESS_HUB_MODE" == "e" ]]; then
      aif_prompt_value AIF_ACCESS_HUB_SUBSCRIPTION_ID \
        "External access-hub subscription ID" ""
      aif_prompt_value AIF_ACCESS_HUB_RESOURCE_GROUP \
        "External access-hub and private-DNS resource group" \
        "aifactory-connectivity"
      aif_prompt_value AIF_ACCESS_HUB_VNET_CIDR \
        "External access-hub vNet CIDR" "10.240.0.0/22"
      aif_prompt_value AIF_VPN_CLIENT_CIDR \
        "Point-to-site VPN client address pool" "172.31.240.0/24"
      if ! aif_validate_access_hub_cidr "$AIF_ACCESS_HUB_VNET_CIDR" ||
         ! aif_validate_network_plan \
           "$AIF_DEV_VNET_CIDR" \
           "$AIF_ACCESS_HUB_VNET_CIDR" \
           "$AIF_VPN_CLIENT_CIDR"; then
        aif_error "DEV, access-hub, and VPN client CIDRs must be valid, non-overlapping IPv4 ranges." >&2
        exit 1
      fi
    else
      AIF_ACCESS_HUB_MODE="integrated"
    fi
    aif_info "Standalone with its own access hub can be reached through Azure VPN Gateway or Azure Bastion."
    aif_info "The recommended setup enables an Entra-authenticated P2S VPN gateway and Bastion Developer. This does not create an admin VM."
    if [[ "$AIF_ACCESS_HUB_MODE" == "external" || "$AIF_ACCESS_HUB_MODE" == "e" ]]; then
      aif_info "Bastion Developer cannot traverse peering, so with an external hub it is placed in the DEV common VNet; with an integrated hub, that VNet is the hub."
    fi
    aif_prompt_yes_no AIF_SETUP_HUB_ACCESS \
      "Set up Azure VPN Gateway in the hub and Bastion Developer for DEV? (Y/n)" \
      "y"
    if [[ "$AIF_SETUP_HUB_ACCESS" == "true" ]]; then
      local configure_vpn_client_default="n"
      aif_is_windows && configure_vpn_client_default="y"
      aif_prompt_yes_no AIF_CONFIGURE_VPN_CLIENT \
        "Install and configure Azure VPN Client on this computer? (Y/n)" \
        "$configure_vpn_client_default"
    else
      AIF_CONFIGURE_VPN_CLIENT="false"
    fi
  else
    AIF_SETUP_HUB_ACCESS="false"
    AIF_CONFIGURE_VPN_CLIENT="false"
  fi

  AIF_HUB_SUBSCRIPTION_ID="${AIF_HUB_SUBSCRIPTION_ID:-}"
  AIF_HUB_RESOURCE_GROUP="${AIF_HUB_RESOURCE_GROUP:-}"
  AIF_HUB_VNET_NAME="${AIF_HUB_VNET_NAME:-}"
  AIF_HUB_VNET_RESOURCE_GROUP="${AIF_HUB_VNET_RESOURCE_GROUP:-}"
  if [[ "$AIF_TOPOLOGY" == "hs" ]]; then
    aif_prompt_value AIF_HUB_SUBSCRIPTION_ID "Hub subscription ID" ""
    aif_prompt_value AIF_HUB_RESOURCE_GROUP "Hub private-DNS resource group" ""
    aif_prompt_value AIF_HUB_VNET_NAME "Hub vNet name" ""
    aif_prompt_value AIF_HUB_VNET_RESOURCE_GROUP \
      "Hub vNet resource group" "$AIF_HUB_RESOURCE_GROUP"
  fi

  aif_section "02 / Azure scope and naming"
  aif_prompt_value AIF_TENANT_ID "Azure tenant ID" "$current_tenant"
  aif_prompt_value AIF_DEV_SUBSCRIPTION_ID "DEV subscription ID" "$current_subscription"
  if ! aif_validate_guid "$AIF_TENANT_ID" ||
     ! aif_validate_guid "$AIF_DEV_SUBSCRIPTION_ID"; then
    aif_error "Tenant and subscription IDs must be GUIDs." >&2
    exit 1
  fi
  if [[ "$AIF_TOPOLOGY" == "hs" ]] && ! aif_validate_guid "$AIF_HUB_SUBSCRIPTION_ID"; then
    aif_error "Hub subscription ID must be a GUID." >&2
    exit 1
  fi
  if [[ "$AIF_ACCESS_HUB_MODE" == "e" ]] &&
     ! aif_validate_guid "$AIF_ACCESS_HUB_SUBSCRIPTION_ID"; then
    aif_error "External access-hub subscription ID must be a GUID." >&2
    exit 1
  fi

  aif_prompt_value AIF_PREFIX "AI Factory naming prefix" "aif-"
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" && ! "$AIF_PREFIX" =~ ^[a-z0-9-]{2,16}$ ]]; then
    aif_error "Simple Mode prefix must be 2-16 lowercase letters, digits or hyphens." >&2
    exit 1
  fi
  AIF_PREFIX="${AIF_PREFIX,,}"
  [[ "$AIF_PREFIX" == *- ]] || AIF_PREFIX="${AIF_PREFIX}-"
  local prefix_max=16
  [[ "${AIF_SIMPLE_MODE:-false}" != "true" ]] || prefix_max=17
  if [[ ! "$AIF_PREFIX" =~ ^[a-z0-9-]{2,${prefix_max}}$ ]]; then
    aif_error "Prefix must contain only lowercase letters, digits, and hyphens." >&2
    exit 1
  fi
  aif_prompt_value AIF_SCALESET_SUFFIX "Scale-set number (001-999)" "001"
  aif_prompt_value AIF_PROJECT_NUMBER "First project number (001-999)" "001"
  if ! aif_validate_number_3 "$AIF_SCALESET_SUFFIX" ||
     ! aif_validate_number_3 "$AIF_PROJECT_NUMBER"; then
    aif_error "Scale-set and project numbers must be between 001 and 999." >&2
    exit 1
  fi
  printf -v AIF_SCALESET_SUFFIX '%03d' "$((10#$AIF_SCALESET_SUFFIX))"
  printf -v AIF_PROJECT_NUMBER '%03d' "$((10#$AIF_PROJECT_NUMBER))"
  AIF_SCALESET_SUFFIX_DASH="-$AIF_SCALESET_SUFFIX"
  if [[ "$AIF_ACCESS_HUB_MODE" == "e" ]]; then
    AIF_ACCESS_HUB_MODE="external"
    AIF_HUB_SUBSCRIPTION_ID="$AIF_ACCESS_HUB_SUBSCRIPTION_ID"
    AIF_HUB_RESOURCE_GROUP="$AIF_ACCESS_HUB_RESOURCE_GROUP"
    AIF_HUB_VNET_RESOURCE_GROUP="$AIF_ACCESS_HUB_RESOURCE_GROUP"
    AIF_HUB_VNET_NAME="${AIF_ACCESS_HUB_VNET_NAME:-vnet-aifactory-access-hub-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}}"
  elif [[ "$AIF_ACCESS_HUB_MODE" == "integrated" ]]; then
    AIF_HUB_SUBSCRIPTION_ID="$AIF_DEV_SUBSCRIPTION_ID"
    AIF_HUB_RESOURCE_GROUP="${AIF_PREFIX}esml-common-${AIF_LOCATION_SHORT}-dev${AIF_SCALESET_SUFFIX_DASH}"
    AIF_HUB_VNET_RESOURCE_GROUP="$AIF_HUB_RESOURCE_GROUP"
    AIF_HUB_VNET_NAME="vnt-esmlcmn-${AIF_LOCATION_SHORT}-dev-001"
    AIF_ACCESS_HUB_VNET_CIDR="$AIF_DEV_VNET_CIDR"
    AIF_VPN_CLIENT_CIDR="${AIF_VPN_CLIENT_CIDR:-172.31.240.0/24}"
    if ! aif_validate_network_plan "$AIF_DEV_VNET_CIDR" "$AIF_VPN_CLIENT_CIDR"; then
      aif_error "Integrated DEV and VPN client CIDRs must not overlap." >&2
      exit 1
    fi
  fi

  local prefix_compact="${AIF_PREFIX//-/}"
  AIF_BOOTSTRAP_RESOURCE_GROUP="${AIF_BOOTSTRAP_RESOURCE_GROUP:-rg-${AIF_PREFIX%-}-bootstrap-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}}"
  AIF_DEPLOYMENT_IDENTITY_NAME="${AIF_DEPLOYMENT_IDENTITY_NAME:-id-${AIF_PREFIX%-}-deploy-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}}"
  AIF_SEEDING_RESOURCE_GROUP="${AIF_SEEDING_RESOURCE_GROUP:-$AIF_BOOTSTRAP_RESOURCE_GROUP}"
  AIF_SEEDING_KEYVAULT_NAME="${AIF_SEEDING_KEYVAULT_NAME:-kv${prefix_compact}${AIF_LOCATION_SHORT}${AIF_SCALESET_SUFFIX}}"
  AIF_SEEDING_KEYVAULT_NAME="${AIF_SEEDING_KEYVAULT_NAME:0:24}"
  AIF_TEAM_GROUP_NAME="${AIF_TEAM_GROUP_NAME:-${AIF_PREFIX%-}prj${AIF_PROJECT_NUMBER}-team}"
  aif_prompt_value AIF_TEAM_GROUP_NAME "Entra security group for the initial team" "$AIF_TEAM_GROUP_NAME"
  aif_prompt_value AIF_TEAM_MEMBER_EMAIL "Initial team member" "$current_user"

  aif_section "03 / Seeding Key Vault"
  aif_info "v1.24 still requires a seeding Key Vault shell, but service-principal secrets are optional."
  aif_prompt_choice AIF_SEEDING_MODE \
    "Seeding Key Vault: create/ensure (c) or use existing (e)" "c" "c e"
  if [[ "$AIF_SEEDING_MODE" == "e" ]]; then
    AIF_SEEDING_RESOURCE_GROUP="$seeding_resource_group_input"
    AIF_SEEDING_KEYVAULT_NAME="$seeding_keyvault_name_input"
    aif_prompt_value AIF_SEEDING_RESOURCE_GROUP "Existing seeding Key Vault resource group" ""
    aif_prompt_value AIF_SEEDING_KEYVAULT_NAME "Existing seeding Key Vault name" ""
  fi
  aif_prompt_yes_no AIF_SEED_PROJECT_SP \
    "Create and seed an optional project automation service principal? (y/N)" "n"

  if [[ "$AIF_IDENTITY_MODE" == "mi" ]]; then
    aif_prompt_value AIF_MI_RESOURCE_ID "Existing user-assigned managed identity resource ID" ""
  elif [[ "$AIF_IDENTITY_MODE" == "sp" ]]; then
    aif_prompt_value AIF_SP_CLIENT_ID "Existing service-principal client ID" ""
    aif_prompt_secret AIF_SP_CLIENT_SECRET "Existing service-principal client secret"
  fi

  aif_section "04 / Orchestrator"
  if [[ "$AIF_ROUTE" == "ado" ]]; then
    ADO_ORGANIZATION="${ADO_ORGANIZATION:-}"
    ADO_PROJECT="${ADO_PROJECT:-}"
    ADO_REPOSITORY_NAME="${ADO_REPOSITORY_NAME:-$current_repo}"
    ADO_TENANT="${ADO_TENANT:-$AIF_TENANT_ID}"
    ADO_AUTH_METHOD="${ADO_AUTH_METHOD:-aad}"
    ADO_RUNNER_MODE="${ADO_RUNNER_MODE:-}"
    ADO_AGENT_POOL="${ADO_AGENT_POOL:-Default}"
    AZURE_DEVOPS_EXT_PAT="${AZURE_DEVOPS_EXT_PAT:-}"
    ADO_SERVICE_CONNECTION_NAME="${ADO_SERVICE_CONNECTION_NAME:-sc-${AIF_PREFIX%-}dev-${AIF_SCALESET_SUFFIX}}"
    aif_prompt_value ADO_ORGANIZATION "Azure DevOps organization name or URL" ""
    aif_prompt_value ADO_PROJECT "Azure DevOps project name" ""
    aif_prompt_value ADO_REPOSITORY_NAME "Azure DevOps repository name" \
      "${AIF_PREFIX%-}aifactory-${AIF_SCALESET_SUFFIX}"
    aif_prompt_value ADO_TENANT "Azure DevOps connected tenant ID" "$AIF_TENANT_ID"
    aif_prompt_choice ADO_AUTH_METHOD \
      "Azure DevOps authentication: Microsoft Entra (aad) or PAT (pat)" \
      "aad" "aad pat"
    if [[ "$ADO_AUTH_METHOD" == "pat" ]]; then
      aif_prompt_secret AZURE_DEVOPS_EXT_PAT "Azure DevOps PAT"
      export AZURE_DEVOPS_EXT_PAT
    fi
    aif_prompt_value ADO_SERVICE_CONNECTION_NAME "Azure DevOps service connection name" \
      "$ADO_SERVICE_CONNECTION_NAME"
    aif_prompt_choice ADO_RUNNER_MODE \
      "Project build agent: self-hosted admin VM (s) or Microsoft-hosted (h)" \
      "h" "s h"
    if [[ "$ADO_RUNNER_MODE" == "s" ]]; then
      aif_prompt_value ADO_AGENT_POOL "Azure DevOps agent pool" "Default"
      aif_prompt_value AIF_ADMIN_VM_SIZE \
        "Self-hosted admin VM size" \
        "$AIF_ADMIN_VM_SIZE"
      AIF_RUNNER_MODE="self-hosted"
      ADO_AGENT_NAME="dsvm-cmn-${AIF_LOCATION_SHORT}-dev-001"
    else
      AIF_RUNNER_MODE="microsoft-hosted"
      ADO_AGENT_NAME=""
    fi
    case "$ADO_ORGANIZATION" in
      http://*|https://*) ;;
      *) ADO_ORGANIZATION="https://dev.azure.com/$ADO_ORGANIZATION" ;;
    esac
    ADO_ORGANIZATION="${ADO_ORGANIZATION%/}"
  else
    AIF_RUNNER_MODE="github-hosted"
    ADO_AGENT_POOL=""
    ADO_AGENT_NAME=""
    local github_owner=""
    github_owner="$(gh api user --jq .login 2>/dev/null || true)"
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-$current_repo}"
    if [[ "$GITHUB_REPOSITORY" != */* ]]; then
      GITHUB_REPOSITORY="${github_owner:+$github_owner/}${AIF_PREFIX%-}aifactory-${AIF_SCALESET_SUFFIX}"
    fi
    aif_prompt_value GITHUB_REPOSITORY "GitHub repository (owner/name)" \
      "$GITHUB_REPOSITORY"
    if [[ ! "$GITHUB_REPOSITORY" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]]; then
      aif_error "GitHub repository must use owner/name format." >&2
      exit 1
    fi
  fi

  case "$AIF_NETWORK_MODE" in
    priv)
      AIF_ENABLE_PUBLIC_GENAI_ACCESS="false"
      AIF_ALLOW_PUBLIC_ACCESS_BEHIND_VNET="false"
      AIF_ENABLE_PUBLIC_PERIMETER="false"
      ;;
    h)
      AIF_ENABLE_PUBLIC_GENAI_ACCESS="true"
      AIF_ALLOW_PUBLIC_ACCESS_BEHIND_VNET="true"
      AIF_ENABLE_PUBLIC_PERIMETER="false"
      ;;
    pub)
      AIF_ENABLE_PUBLIC_GENAI_ACCESS="true"
      AIF_ALLOW_PUBLIC_ACCESS_BEHIND_VNET="true"
      AIF_ENABLE_PUBLIC_PERIMETER="true"
      ;;
  esac
  AIF_ADD_BASTION="false"

  # The initial bootstrap intentionally deploys DEV only. Stage/Prod can be added
  # later with the configuration wizard after separate CIDRs/subscriptions exist.
  AIF_STAGE_SUBSCRIPTION_ID="$AIF_DEV_SUBSCRIPTION_ID"
  AIF_PROD_SUBSCRIPTION_ID="$AIF_DEV_SUBSCRIPTION_ID"
}

aif_confirm_summary() {
  aif_section "05 / Review"
  aif_value "Route" "$AIF_ROUTE"
  aif_value "Topology" "$AIF_TOPOLOGY"
  aif_value "Network" "$AIF_NETWORK_MODE"
  aif_value "Identity" "$AIF_IDENTITY_MODE"
  aif_value "Tenant" "$AIF_TENANT_ID"
  aif_value "DEV subscription" "$AIF_DEV_SUBSCRIPTION_ID"
  aif_value "Region" "$AIF_LOCATION"
  aif_value "DEV vNet" "$AIF_DEV_VNET_CIDR"
  aif_value "Prefix" "$AIF_PREFIX"
  aif_value "Scale set" "$AIF_SCALESET_SUFFIX_DASH"
  aif_value "Project" "$AIF_PROJECT_NUMBER"
  aif_value "Build runner" "$AIF_RUNNER_MODE"
  [[ "$AIF_RUNNER_MODE" != "self-hosted" ]] ||
    aif_value "Admin VM size" "$AIF_ADMIN_VM_SIZE"
  if [[ "$AIF_TOPOLOGY" == "s" ]]; then
    aif_value "Hub VPN + DEV Bastion" "$AIF_SETUP_HUB_ACCESS"
    aif_value "Configure VPN client" "$AIF_CONFIGURE_VPN_CLIENT"
  fi
  aif_value "Team group" "$AIF_TEAM_GROUP_NAME"
  aif_value "Seeding vault" "$AIF_SEEDING_KEYVAULT_NAME"
  if [[ "$AIF_YES" == "true" ]]; then
    return
  fi
  local proceed=""
  aif_prompt_yes_no proceed "Apply this plan? (y/N)" "n"
  if [[ "$proceed" != "true" ]]; then
    aif_warn "No changes were made."
    exit 0
  fi
}

aif_ensure_azure_login() {
  aif_section "06 / Azure access"
  local current_tenant
  current_tenant="$(az account show --query tenantId --output tsv 2>/dev/null || true)"
  current_tenant="${current_tenant//$'\r'/}"
  if [[ "$current_tenant" != "$AIF_TENANT_ID" ]]; then
    if az account show \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --output none 2>/dev/null; then
      az account set --subscription "$AIF_DEV_SUBSCRIPTION_ID"
    else
      if [[ "$AIF_NON_INTERACTIVE" == "true" ]]; then
        aif_error "No Azure sign-in is available for the selected tenant/subscription. Sign in explicitly before Create." >&2
        exit 1
      fi
      aif_mutate az login --tenant "$AIF_TENANT_ID" --allow-no-subscriptions
    fi
  fi
  if [[ "$AIF_DRY_RUN" != "true" ]]; then
    local selected_tenant
    selected_tenant="$(az account show --subscription "$AIF_DEV_SUBSCRIPTION_ID" --query tenantId --output tsv)"
    selected_tenant="${selected_tenant//$'\r'/}"
    if [[ "${selected_tenant,,}" != "${AIF_TENANT_ID,,}" ]]; then
      aif_error "Selected subscription does not belong to the requested Azure tenant." >&2
      exit 1
    fi
    az account get-access-token --subscription "$AIF_DEV_SUBSCRIPTION_ID" --output none
    if [[ "$AIF_TOPOLOGY" == "hs" ]]; then
      az account show --subscription "$AIF_HUB_SUBSCRIPTION_ID" --output none
    fi
  fi
  aif_success "Azure tenant and subscription access confirmed."
}

aif_validate_admin_vm_size() {
  [[ "$AIF_RUNNER_MODE" == "self-hosted" ]] || return 0
  [[ "$AIF_DRY_RUN" != "true" ]] || return 0
  local supported
  supported="$(az vm list-sizes \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --location "$AIF_LOCATION" \
    --query "[?name=='$AIF_ADMIN_VM_SIZE'] | length(@)" \
    --output tsv \
    --only-show-errors)"
  supported="${supported//$'\r'/}"
  if [[ "$supported" != "1" ]]; then
    aif_error "Admin VM size '$AIF_ADMIN_VM_SIZE' is not supported in '$AIF_LOCATION'. Set AIF_ADMIN_VM_SIZE to a supported size." >&2
    exit 1
  fi
  aif_success "Admin VM size '$AIF_ADMIN_VM_SIZE' is supported in '$AIF_LOCATION'."
}

aif_ensure_ado_auth() {
  [[ "$AIF_ROUTE" == "ado" ]] || return 0
  if [[ "$ADO_AUTH_METHOD" == "pat" ]]; then
    return 0
  fi
  ADO_CONTEXT_SUBSCRIPTION_ID="$(az account list --all \
    --query "[?tenantId=='$ADO_TENANT'] | [0].id" \
    --output tsv)"
  ADO_CONTEXT_SUBSCRIPTION_ID="${ADO_CONTEXT_SUBSCRIPTION_ID//$'\r'/}"
  if [[ -n "$ADO_CONTEXT_SUBSCRIPTION_ID" ]]; then
    az account set --subscription "$ADO_CONTEXT_SUBSCRIPTION_ID"
  fi
  if az account get-access-token \
    --resource "$AIF_ADO_RESOURCE" \
    --tenant "$ADO_TENANT" \
    --output none 2>/dev/null; then
    :
  elif [[ "$AIF_NON_INTERACTIVE" == "true" ]]; then
    aif_error "No Microsoft Entra token is available for Azure DevOps tenant '$ADO_TENANT'." >&2
    aif_info "Sign in first or rerun with ADO_AUTH_METHOD=pat and AZURE_DEVOPS_EXT_PAT." >&2
    exit 1
  else
    aif_mutate az login --tenant "$ADO_TENANT" --allow-no-subscriptions
    ADO_CONTEXT_SUBSCRIPTION_ID="$(az account list --all \
      --query "[?tenantId=='$ADO_TENANT'] | [0].id" \
      --output tsv)"
    ADO_CONTEXT_SUBSCRIPTION_ID="${ADO_CONTEXT_SUBSCRIPTION_ID//$'\r'/}"
  fi
}

aif_use_ado_tenant() {
  if [[ "$AIF_ROUTE" == "ado" &&
        "$ADO_AUTH_METHOD" != "pat" &&
        -n "${ADO_CONTEXT_SUBSCRIPTION_ID:-}" ]]; then
    az account set --subscription "$ADO_CONTEXT_SUBSCRIPTION_ID"
  fi
}

aif_use_azure_tenant() {
  az account set --subscription "$AIF_DEV_SUBSCRIPTION_ID"
}

aif_register_resource_providers() {
  local subscription_id="$1"
  local providers=(
    Microsoft.Batch Microsoft.Capacity Microsoft.ChangeAnalysis
    Microsoft.CloudShell Microsoft.Compute Microsoft.Consumption
    Microsoft.ContainerInstance Microsoft.ContainerRegistry Microsoft.ContainerService
    Microsoft.CostManagement Microsoft.Databricks Microsoft.DataFactory
    Microsoft.DevTestLab Microsoft.EventGrid Microsoft.EventHub Microsoft.Features
    Microsoft.GuestConfiguration microsoft.insights Microsoft.KeyVault
    Microsoft.Kubernetes Microsoft.KubernetesConfiguration Microsoft.KubernetesRuntime
    Microsoft.MachineLearningServices Microsoft.ManagedIdentity Microsoft.ManagedServices
    Microsoft.Management Microsoft.MarketplaceNotifications Microsoft.MarketplaceOrdering
    Microsoft.Network Microsoft.Notebooks Microsoft.OperationalInsights
    Microsoft.OperationsManagement Microsoft.PolicyInsights Microsoft.Portal
    Microsoft.ResourceGraph Microsoft.ResourceHealth Microsoft.ResourceNotifications
    Microsoft.Resources Microsoft.Search Microsoft.Security Microsoft.SerialConsole
    Microsoft.SqlVirtualMachine Microsoft.Storage microsoft.support
    Microsoft.VirtualMachineImages Microsoft.App Microsoft.BotService
    Microsoft.CognitiveServices Microsoft.DocumentDB
    Microsoft.AppConfiguration Microsoft.DomainRegistration Microsoft.CertificateRegistration
    Microsoft.Web Microsoft.ApiManagement Microsoft.PowerPlatform Microsoft.Media
    Microsoft.Logic Microsoft.Cache Microsoft.DBforPostgreSQL Microsoft.Sql
    Microsoft.ServiceBus
    Microsoft.AlertsManagement
  )
  local required=(
    Microsoft.Resources Microsoft.Network Microsoft.Storage Microsoft.KeyVault
    Microsoft.ManagedIdentity Microsoft.CognitiveServices
    Microsoft.MachineLearningServices Microsoft.Databricks
    Microsoft.Search Microsoft.DocumentDB
    Microsoft.ContainerRegistry Microsoft.App Microsoft.BotService
    Microsoft.AppConfiguration Microsoft.Web
    Microsoft.OperationalInsights microsoft.insights
  )
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" ]]; then
    required=(
      Microsoft.Resources Microsoft.Network Microsoft.Storage Microsoft.KeyVault
      Microsoft.ManagedIdentity Microsoft.CognitiveServices Microsoft.Search
      Microsoft.ContainerRegistry Microsoft.OperationalInsights microsoft.insights
      Microsoft.PolicyInsights Microsoft.App
    )
    providers=("${required[@]}")
  fi
  local provider provider_error
  aif_info "Registering AI Factory resource providers in $subscription_id."
  for provider in "${providers[@]}"; do
    if [[ "$AIF_DRY_RUN" == "true" ]]; then
      aif_info "DRY-RUN: az provider register --namespace $provider --subscription $subscription_id"
    else
      if ! provider_error="$(az provider register \
        --namespace "$provider" \
        --subscription "$subscription_id" \
        --output none \
        --only-show-errors 2>&1)"; then
        aif_warn "Provider registration was not permitted or available: $provider"
      fi
    fi
  done
  if [[ "$AIF_DRY_RUN" != "true" ]]; then
    for provider in "${required[@]}"; do
      az provider register \
        --namespace "$provider" \
        --subscription "$subscription_id" \
        --wait \
        --output none \
        --only-show-errors
    done
  fi
}

aif_ensure_first_party_enterprise_apps() {
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" ]]; then
    AIF_AZURE_ML_PRINCIPAL_ID=""
    AIF_DATABRICKS_PRINCIPAL_ID=""
    aif_info "Simple Mode disables ML/Databricks/legacy Foundry Hub; no temporary workspaces or first-party apps are needed."
    return 0
  fi
  if [[ -n "$AIF_AZURE_ML_PRINCIPAL_ID" ||
        -n "$AIF_DATABRICKS_PRINCIPAL_ID" ]]; then
    if ! aif_validate_guid "$AIF_AZURE_ML_PRINCIPAL_ID" ||
       ! aif_validate_guid "$AIF_DATABRICKS_PRINCIPAL_ID"; then
      aif_error "Provide both existing Azure ML and Databricks enterprise-app object IDs as GUIDs." >&2
      exit 1
    fi
    aif_success "Using supplied Azure ML and Databricks enterprise-app object IDs; redundant Graph discovery was skipped."
    return 0
  fi
  local aml_app_id="0736f41a-0425-4b46-bdb5-1563eff02385"
  local databricks_app_id="2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
  AIF_AZURE_ML_PRINCIPAL_ID="$(az ad sp show \
    --id "$aml_app_id" \
    --query id \
    --output tsv 2>/dev/null || true)"
  AIF_DATABRICKS_PRINCIPAL_ID="$(az ad sp show \
    --id "$databricks_app_id" \
    --query id \
    --output tsv 2>/dev/null || true)"
  AIF_AZURE_ML_PRINCIPAL_ID="${AIF_AZURE_ML_PRINCIPAL_ID//$'\r'/}"
  AIF_DATABRICKS_PRINCIPAL_ID="${AIF_DATABRICKS_PRINCIPAL_ID//$'\r'/}"
  if [[ -n "$AIF_AZURE_ML_PRINCIPAL_ID" &&
        -n "$AIF_DATABRICKS_PRINCIPAL_ID" ]]; then
    aif_success "Azure Machine Learning and Azure Databricks enterprise applications exist."
    return
  fi
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    AIF_AZURE_ML_PRINCIPAL_ID="00000000-0000-0000-0000-000000000006"
    AIF_DATABRICKS_PRINCIPAL_ID="00000000-0000-0000-0000-000000000007"
    aif_info "DRY-RUN: create temporary Azure ML and Databricks workspaces, materialize both enterprise applications, then delete the temporary resources."
    return
  fi

  aif_section "09 / First-party enterprise applications"
  local timestamp bootstrap_rg managed_rg aml_name databricks_name
  timestamp="$(date -u +%H%M%S)"
  bootstrap_rg="rg-${AIF_PREFIX%-}app-bootstrap-${AIF_LOCATION_SHORT}-${timestamp}"
  managed_rg="rg-${AIF_PREFIX%-}dbx-managed-${AIF_LOCATION_SHORT}-${timestamp}"
  aml_name="aml-${AIF_PREFIX%-}bootstrap-${timestamp}"
  databricks_name="dbx-${AIF_PREFIX%-}bootstrap-${timestamp}"

  az group create \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --name "$bootstrap_rg" \
    --location "$AIF_LOCATION" \
    --tags Purpose=AIFactoryEnterpriseAppBootstrap \
    --output none
  AIF_TEMP_BOOTSTRAP_RG="$bootstrap_rg"
  AIF_TEMP_MANAGED_RG="$managed_rg"

  local bootstrap_status=0
  if [[ -z "$AIF_AZURE_ML_PRINCIPAL_ID" ]]; then
    if ! az extension show --name ml >/dev/null 2>&1; then
      az extension add --name ml --only-show-errors
    fi
    aif_info "Creating temporary Azure ML workspace '$aml_name'."
    if ! az ml workspace create \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$bootstrap_rg" \
      --name "$aml_name" \
      --location "$AIF_LOCATION" \
      --public-network-access Enabled \
      --output none; then
      aif_warn "Temporary Azure ML workspace deployment returned an error; checking whether it materialized the enterprise application."
    fi
  fi

  if [[ -z "$AIF_DATABRICKS_PRINCIPAL_ID" ]]; then
    local databricks_body="$AIF_STATE_DIR/databricks-bootstrap.json"
    "${AIF_PYTHON[@]}" - \
      "$databricks_body" "$AIF_LOCATION" \
      "/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$managed_rg" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(
        {
            "location": sys.argv[2],
            "sku": {"name": "premium"},
            "properties": {
                "managedResourceGroupId": sys.argv[3],
                "publicNetworkAccess": "Enabled",
                "requiredNsgRules": "AllRules",
            },
        },
        output,
    )
PY
    aif_info "Creating temporary Azure Databricks workspace '$databricks_name'."
    if ! az rest \
      --method put \
      --url "https://management.azure.com/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$bootstrap_rg/providers/Microsoft.Databricks/workspaces/$databricks_name?api-version=2024-05-01" \
      --body "@$databricks_body" \
      --output none; then
      aif_warn "Temporary Databricks workspace deployment returned an error; checking whether it materialized the enterprise application."
    fi
  fi

  local attempt
  for attempt in {1..60}; do
    AIF_AZURE_ML_PRINCIPAL_ID="$(az ad sp show \
      --id "$aml_app_id" \
      --query id \
      --output tsv 2>/dev/null || true)"
    AIF_DATABRICKS_PRINCIPAL_ID="$(az ad sp show \
      --id "$databricks_app_id" \
      --query id \
      --output tsv 2>/dev/null || true)"
    AIF_AZURE_ML_PRINCIPAL_ID="${AIF_AZURE_ML_PRINCIPAL_ID//$'\r'/}"
    AIF_DATABRICKS_PRINCIPAL_ID="${AIF_DATABRICKS_PRINCIPAL_ID//$'\r'/}"
    if [[ -n "$AIF_AZURE_ML_PRINCIPAL_ID" &&
          -n "$AIF_DATABRICKS_PRINCIPAL_ID" ]]; then
      break
    fi
    sleep 10
  done
  if [[ -z "$AIF_AZURE_ML_PRINCIPAL_ID" ||
        -z "$AIF_DATABRICKS_PRINCIPAL_ID" ]]; then
    bootstrap_status=1
  fi

  aif_info "Removing temporary enterprise-application bootstrap resources."
  az group delete \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --name "$bootstrap_rg" \
    --yes \
    --output none || bootstrap_status=1
  if [[ "$(az group exists \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --name "$managed_rg" \
    --output tsv)" == "true" ]]; then
    az group delete \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --name "$managed_rg" \
      --yes \
      --output none || bootstrap_status=1
  fi

  if [[ "$bootstrap_status" -ne 0 ]]; then
    aif_error "Could not materialize and clean up both first-party enterprise applications." >&2
    exit 1
  fi
  AIF_TEMP_BOOTSTRAP_RG=""
  AIF_TEMP_MANAGED_RG=""
  aif_success "Azure ML and Databricks enterprise applications are materialized; temporary resources were removed."
}

aif_ensure_role_assignment() {
  local principal_id="$1" principal_type="$2" role="$3" scope="$4"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: assign '$role' to $principal_id at $scope."
    return
  fi
  local existing
  existing="$(az role assignment list \
    --scope "$scope" \
    --role "$role" \
    --query "length([?principalId=='$principal_id'])" \
    --output tsv)"
  existing="${existing//$'\r'/}"
  if [[ "$existing" == "0" ]]; then
    local attempt error_output=""
    for attempt in 1 2 3 4 5; do
      if error_output="$(az role assignment create \
        --assignee-object-id "$principal_id" \
        --assignee-principal-type "$principal_type" \
        --role "$role" \
        --scope "$scope" \
        --output none 2>&1)"; then
        return
      fi
      if [[ "$attempt" -lt 5 && "$error_output" == *"PrincipalNotFound"* ]]; then
        sleep 10
        continue
      fi
      aif_error "Could not assign '$role' at '$scope': $error_output" >&2
      exit 1
    done
  fi
}

aif_ensure_target_repository() {
  aif_section "07 / Orchestrator repository"
  mkdir -p "$AIF_REPO_ROOT"
  if ! git -C "$AIF_REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    aif_mutate git -C "$AIF_REPO_ROOT" init -b main
  fi

  if [[ "$AIF_ROUTE" == "ado" ]]; then
    aif_use_ado_tenant
    if ! az extension show --name azure-devops >/dev/null 2>&1; then
      aif_mutate az extension add --name azure-devops --only-show-errors
    fi
    aif_mutate az devops configure \
      --defaults organization="$ADO_ORGANIZATION" project="$ADO_PROJECT"
    if ! az devops project show \
      --organization "$ADO_ORGANIZATION" \
      --project "$ADO_PROJECT" \
      --output none 2>/dev/null; then
      aif_mutate az devops project create \
        --organization "$ADO_ORGANIZATION" \
        --name "$ADO_PROJECT" \
        --visibility private \
        --output none
    fi
    if ! az repos show \
      --organization "$ADO_ORGANIZATION" \
      --project "$ADO_PROJECT" \
      --repository "$ADO_REPOSITORY_NAME" \
      --output none 2>/dev/null; then
      aif_mutate az repos create \
        --organization "$ADO_ORGANIZATION" \
        --project "$ADO_PROJECT" \
        --name "$ADO_REPOSITORY_NAME" \
        --output none
    fi
    if [[ "$AIF_DRY_RUN" != "true" ]]; then
      AIF_REMOTE_URL="$(az repos show \
        --organization "$ADO_ORGANIZATION" \
        --project "$ADO_PROJECT" \
        --repository "$ADO_REPOSITORY_NAME" \
        --query remoteUrl \
        --output tsv)"
      AIF_REMOTE_URL="${AIF_REMOTE_URL//$'\r'/}"
    else
      AIF_REMOTE_URL="$ADO_ORGANIZATION/$ADO_PROJECT/_git/$ADO_REPOSITORY_NAME"
    fi
  else
    gh auth status >/dev/null
    if ! gh repo view "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
      aif_mutate gh repo create "$GITHUB_REPOSITORY" --private
    fi
    AIF_REMOTE_URL="https://github.com/$GITHUB_REPOSITORY.git"
  fi

  local current_origin
  current_origin="$(git -C "$AIF_REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  if [[ -z "$current_origin" ]]; then
    aif_mutate git -C "$AIF_REPO_ROOT" remote add origin "$AIF_REMOTE_URL"
  else
    if [[ "$AIF_ROUTE" == "ado" ]]; then
      local ado_coordinates expected_organization
      ado_coordinates="$(aif_current_ado_coordinates | tr -d '\r')"
      mapfile -t ado_origin <<< "$ado_coordinates"
      expected_organization="${ADO_ORGANIZATION##*/}"
      if [[ "${ado_origin[0],,}" != "${expected_organization,,}" ||
            "${ado_origin[1],,}" != "${ADO_PROJECT,,}" ||
            "${ado_origin[2],,}" != "${ADO_REPOSITORY_NAME,,}" ]]; then
        aif_error "Existing origin '$current_origin' does not match Azure DevOps target '$expected_organization/$ADO_PROJECT/$ADO_REPOSITORY_NAME'." >&2
        exit 1
      fi
    else
      local current_slug
      current_slug="$(aif_current_origin_slug)"
      if [[ "${current_slug,,}" != "${GITHUB_REPOSITORY,,}" ]]; then
        aif_error "Existing origin '$current_origin' does not identify '$GITHUB_REPOSITORY'." >&2
        exit 1
      fi
    fi
  fi

  if [[ "$AIF_DRY_RUN" != "true" ]] &&
     git -C "$AIF_REPO_ROOT" rev-parse --verify HEAD >/dev/null 2>&1 &&
     [[ -n "$(git -C "$AIF_REPO_ROOT" status --porcelain)" ]]; then
    local stash_message="Before AI Factory scale-set creation $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git -C "$AIF_REPO_ROOT" stash push --include-untracked --message "$stash_message" >/dev/null
    AIF_STASH_CREATED="true"
    aif_success "Existing work protected in $(git -C "$AIF_REPO_ROOT" stash list -1 --format='%gd %s')."
  fi

  if [[ "$AIF_DRY_RUN" != "true" ]] &&
     git -C "$AIF_REPO_ROOT" ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
    git -C "$AIF_REPO_ROOT" checkout main
    git -C "$AIF_REPO_ROOT" pull --ff-only origin main
  else
    aif_mutate git -C "$AIF_REPO_ROOT" checkout -B main
  fi
}

aif_sync_submodule_and_templates() {
  aif_section "08 / Accelerator and templates"
  cd "$AIF_REPO_ROOT"
  if [[ -f .gitmodules ]] &&
     git config --file .gitmodules --get-regexp path 2>/dev/null |
       grep -q "azure-enterprise-scale-ml"; then
    aif_mutate git submodule sync --recursive
    aif_mutate git submodule update --init --recursive
  else
    aif_mutate git submodule add -b "$AIF_SUBMODULE_BRANCH" \
      "$AIF_SUBMODULE_URL" azure-enterprise-scale-ml
  fi
  aif_mutate git -C azure-enterprise-scale-ml fetch origin "$AIF_SUBMODULE_BRANCH"
  aif_mutate git -C azure-enterprise-scale-ml checkout "$AIF_SUBMODULE_BRANCH"
  aif_mutate git -C azure-enterprise-scale-ml pull --ff-only origin "$AIF_SUBMODULE_BRANCH"

  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" ]]; then
    "${AIF_PYTHON[@]}" "$AIF_SCALESET_LIB_DIR/aifactory_scaleset_config.py" \
      --verify-simple-mode-source "$AIF_REPO_ROOT/azure-enterprise-scale-ml"
  fi

  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: synchronize initial route templates."
    return
  fi

  cp azure-enterprise-scale-ml/bootstrap/01-aif-copy-aifactory-templates.sh .
  cp azure-enterprise-scale-ml/bootstrap/ADO-update-aifactory-and-run-project.sh .
  cp azure-enterprise-scale-ml/bootstrap/GH-update-aifactory-and-run-project.sh .
  cp azure-enterprise-scale-ml/bootstrap/ADO-create-new-aifactory-scaleset.sh .
  cp azure-enterprise-scale-ml/bootstrap/GHA-create-new-aifactory-scaleset.sh .
  cp azure-enterprise-scale-ml/bootstrap/ALL-create-new-aifactory-scaleset.sh .
  chmod +x ./*.sh

  if [[ ! -d aifactory ]]; then
    local existing_gitignore="$AIF_STATE_DIR/existing.gitignore"
    [[ ! -f .gitignore ]] || cp .gitignore "$existing_gitignore"
    bash ./01-aif-copy-aifactory-templates.sh
    if [[ -f "$existing_gitignore" ]]; then
      "${AIF_PYTHON[@]}" - "$existing_gitignore" .gitignore <<'PY'
import sys
from pathlib import Path

original_path, generated_path = map(Path, sys.argv[1:])
original = original_path.read_text(encoding="utf-8-sig").splitlines()
generated = generated_path.read_text(encoding="utf-8-sig").splitlines()
known = set(original)
missing = [line for line in generated if line and line not in known]
result = original
if missing:
    result += ["", "# AI Factory bootstrap exclusions", *missing]
generated_path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY
    fi
    mv aifactory-templates aifactory
    cp azure-enterprise-scale-ml/environment_setup/aifactory/variables.json \
      aifactory/variables.json
    if [[ "$AIF_ROUTE" == "gha" ]]; then
      mkdir -p .github/workflows
      cp azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template .env
      cp azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh \
        10-GH-create-or-update-github-variables.sh
      cp azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml \
        .github/workflows/infra-common.yml
      cp azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml \
        .github/workflows/infra-project.yml
      cp azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml \
        .github/workflows/infra-project-phase.yml
      chmod +x 10-GH-create-or-update-github-variables.sh
    fi
  else
    rm -rf -- aifactory-templates
    mkdir -p aifactory-templates/automation
    cp -r azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/automation/. \
      aifactory-templates/automation/
    if [[ "$AIF_ROUTE" == "ado" ]]; then
      cp azure-enterprise-scale-ml/bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh \
        03-ADO-YAML-bootstrap-files-no-var-overwrite.sh
      bash ./03-ADO-YAML-bootstrap-files-no-var-overwrite.sh
    else
      cp azure-enterprise-scale-ml/bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh \
        03-GH-bootstrap-files-no-env-overwrite.sh
      bash ./03-GH-bootstrap-files-no-env-overwrite.sh
    fi
  fi
  rm -rf -- aifactory-templates
}

aif_ensure_bootstrap_identity() {
  aif_section "09 / Deployment identity"
  aif_mutate az group create \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --name "$AIF_BOOTSTRAP_RESOURCE_GROUP" \
    --location "$AIF_LOCATION" \
    --tags Purpose=AIFactoryBootstrap \
    --output none

  if [[ "$AIF_IDENTITY_MODE" == "c" ]]; then
    if [[ "$AIF_DRY_RUN" != "true" ]] &&
       ! az identity show \
         --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
         --resource-group "$AIF_BOOTSTRAP_RESOURCE_GROUP" \
         --name "$AIF_DEPLOYMENT_IDENTITY_NAME" \
         --output none 2>/dev/null; then
      az identity create \
        --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
        --resource-group "$AIF_BOOTSTRAP_RESOURCE_GROUP" \
        --name "$AIF_DEPLOYMENT_IDENTITY_NAME" \
        --location "$AIF_LOCATION" \
        --output none
    fi
    AIF_MI_RESOURCE_ID="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$AIF_BOOTSTRAP_RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$AIF_DEPLOYMENT_IDENTITY_NAME"
    AIF_IDENTITY_SUBSCRIPTION_ID="$AIF_DEV_SUBSCRIPTION_ID"
    AIF_IDENTITY_RESOURCE_GROUP="$AIF_BOOTSTRAP_RESOURCE_GROUP"
    AIF_IDENTITY_NAME="$AIF_DEPLOYMENT_IDENTITY_NAME"
  elif [[ "$AIF_IDENTITY_MODE" == "mi" ]]; then
    if [[ "$AIF_DRY_RUN" != "true" ]]; then
      local identity_json identity_fields_output
      identity_json="$(az identity show --ids "$AIF_MI_RESOURCE_ID" --output json)"
      identity_fields_output="$(printf '%s' "$identity_json" | "${AIF_PYTHON[@]}" -c '
import json, sys
value = json.load(sys.stdin)
print(value["id"].split("/")[2])
print(value["resourceGroup"])
print(value["name"])
')"
      identity_fields_output="${identity_fields_output//$'\r'/}"
      mapfile -t identity_fields <<< "$identity_fields_output"
      AIF_IDENTITY_SUBSCRIPTION_ID="${identity_fields[0]}"
      AIF_IDENTITY_RESOURCE_GROUP="${identity_fields[1]}"
      AIF_IDENTITY_NAME="${identity_fields[2]}"
    fi
  fi

  if [[ "$AIF_IDENTITY_MODE" == "sp" ]]; then
    AIF_IDENTITY_CLIENT_ID="$AIF_SP_CLIENT_ID"
    if [[ "$AIF_DRY_RUN" != "true" ]]; then
      AIF_IDENTITY_PRINCIPAL_ID="$(az ad sp show --id "$AIF_SP_CLIENT_ID" --query id --output tsv)"
      AIF_IDENTITY_PRINCIPAL_ID="${AIF_IDENTITY_PRINCIPAL_ID//$'\r'/}"
    else
      AIF_IDENTITY_PRINCIPAL_ID="00000000-0000-0000-0000-000000000001"
    fi
  else
    if [[ "$AIF_DRY_RUN" != "true" ]]; then
      local identity_values_output
      identity_values_output="$(az identity show \
        --ids "$AIF_MI_RESOURCE_ID" \
        --query '[clientId,principalId]' \
        --output tsv)"
      identity_values_output="${identity_values_output//$'\r'/}"
      mapfile -t identity_values <<< "$identity_values_output"
      AIF_IDENTITY_CLIENT_ID="${identity_values[0]}"
      AIF_IDENTITY_PRINCIPAL_ID="${identity_values[1]}"
    else
      AIF_IDENTITY_CLIENT_ID="00000000-0000-0000-0000-000000000002"
      AIF_IDENTITY_PRINCIPAL_ID="00000000-0000-0000-0000-000000000003"
    fi
  fi

  local role scope
  scope="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID"
  for role in Contributor "User Access Administrator"; do
    aif_ensure_role_assignment \
      "$AIF_IDENTITY_PRINCIPAL_ID" ServicePrincipal "$role" "$scope"
  done
  if [[ "$AIF_TOPOLOGY" == "hs" || "$AIF_ACCESS_HUB_MODE" == "external" ]]; then
    aif_ensure_role_assignment \
      "$AIF_IDENTITY_PRINCIPAL_ID" \
      ServicePrincipal \
      "Private DNS Zone Contributor" \
      "/subscriptions/$AIF_HUB_SUBSCRIPTION_ID/resourceGroups/$AIF_HUB_RESOURCE_GROUP"
  fi
  aif_success "Deployment identity is ready."
}

aif_ensure_seeding_keyvault() {
  aif_section "10 / Seeding Key Vault"
  if [[ "$AIF_SEEDING_MODE" == "c" ]]; then
    aif_mutate az group create \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --name "$AIF_SEEDING_RESOURCE_GROUP" \
      --location "$AIF_LOCATION" \
      --tags Purpose=AIFactorySeeding \
      --output none
    if [[ "$AIF_DRY_RUN" != "true" ]] &&
       ! az keyvault show \
         --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
         --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
         --name "$AIF_SEEDING_KEYVAULT_NAME" \
         --output none 2>/dev/null; then
      az keyvault create \
        --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
        --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
        --name "$AIF_SEEDING_KEYVAULT_NAME" \
        --location "$AIF_LOCATION" \
        --enable-rbac-authorization true \
        --enable-purge-protection true \
        --retention-days 7 \
        --output none
    fi
  elif [[ "$AIF_DRY_RUN" != "true" ]]; then
    az keyvault show \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
      --name "$AIF_SEEDING_KEYVAULT_NAME" \
      --output none
  fi
  aif_mutate az keyvault update \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
    --name "$AIF_SEEDING_KEYVAULT_NAME" \
    --enabled-for-template-deployment true \
    --output none

  AIF_SEEDING_SUBSCRIPTION_ID="$AIF_DEV_SUBSCRIPTION_ID"
  local kv_scope="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$AIF_SEEDING_RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$AIF_SEEDING_KEYVAULT_NAME"
  if [[ "$AIF_DRY_RUN" == "true" ]] ||
     [[ "$(az keyvault show \
       --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
       --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
       --name "$AIF_SEEDING_KEYVAULT_NAME" \
       --query properties.enableRbacAuthorization \
       --output tsv)" == "true" ]]; then
    aif_ensure_role_assignment \
      "$AIF_IDENTITY_PRINCIPAL_ID" ServicePrincipal "Key Vault Secrets User" "$kv_scope"
  else
    aif_mutate az keyvault set-policy \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
      --name "$AIF_SEEDING_KEYVAULT_NAME" \
      --object-id "$AIF_IDENTITY_PRINCIPAL_ID" \
      --secret-permissions get list \
      --output none
  fi
  aif_success "Seeding Key Vault is ready; project-SP secrets remain optional."
}

aif_ensure_team_group() {
  aif_section "11 / Entra team"
  if [[ -n "$AIF_TEAM_GROUP_ID" ]]; then
    if ! aif_validate_guid "$AIF_TEAM_GROUP_ID"; then
      aif_error "AIF_TEAM_GROUP_ID must be an existing Entra group object-ID GUID." >&2
      exit 1
    fi
    aif_success "Using supplied Entra team group '$AIF_TEAM_GROUP_ID'; redundant Graph discovery and membership mutation were skipped."
    return 0
  fi
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    AIF_TEAM_GROUP_ID="00000000-0000-0000-0000-000000000004"
    aif_info "DRY-RUN: create/verify group '$AIF_TEAM_GROUP_NAME' and add '$AIF_TEAM_MEMBER_EMAIL'."
    return
  fi
  aif_use_azure_tenant
  local group_ids_output
  group_ids_output="$(az ad group list \
    --filter "displayName eq '$AIF_TEAM_GROUP_NAME'" \
    --query '[].id' \
    --output tsv)"
  group_ids_output="${group_ids_output//$'\r'/}"
  mapfile -t group_ids <<< "$group_ids_output"
  if [[ -z "$group_ids_output" ]]; then
    group_ids=()
  fi
  if (( ${#group_ids[@]} > 1 )); then
    aif_error "Multiple Entra groups have display name '$AIF_TEAM_GROUP_NAME'." >&2
    exit 1
  elif (( ${#group_ids[@]} == 1 )); then
    AIF_TEAM_GROUP_ID="${group_ids[0]}"
  else
    local nickname
    nickname="$(printf '%s' "$AIF_TEAM_GROUP_NAME" | tr -cd '[:alnum:]_-')"
    AIF_TEAM_GROUP_ID="$(az ad group create \
      --display-name "$AIF_TEAM_GROUP_NAME" \
      --mail-nickname "${nickname:0:64}" \
      --description "AI Factory scale set $AIF_SCALESET_SUFFIX project $AIF_PROJECT_NUMBER team" \
      --query id \
      --output tsv)"
    AIF_TEAM_GROUP_ID="${AIF_TEAM_GROUP_ID//$'\r'/}"
  fi
  local member_id
  member_id="$(az ad user show --id "$AIF_TEAM_MEMBER_EMAIL" --query id --output tsv)"
  member_id="${member_id//$'\r'/}"
  if [[ "$(az ad group member check \
    --group "$AIF_TEAM_GROUP_ID" \
    --member-id "$member_id" \
    --query value \
    --output tsv)" != "true" ]]; then
    az ad group member add --group "$AIF_TEAM_GROUP_ID" --member-id "$member_id"
  fi
  aif_success "Team group '$AIF_TEAM_GROUP_NAME' contains '$AIF_TEAM_MEMBER_EMAIL'."
}

aif_set_keyvault_secret() {
  local name="$1" mode="$2" value="$3"
  local attempt output=""
  local -a args=(
    keyvault secret set
    --subscription "$AIF_DEV_SUBSCRIPTION_ID"
    --vault-name "$AIF_SEEDING_KEYVAULT_NAME"
    --name "$name"
    --output none
  )
  if [[ "$mode" == "file" ]]; then
    args+=(--file "$value")
  else
    args+=(--value "$value")
  fi
  for attempt in 1 2 3 4 5 6; do
    if output="$(az "${args[@]}" 2>&1)"; then
      return
    fi
    if [[ "$attempt" -lt 6 &&
          ( "$output" == *"Forbidden"* || "$output" == *"does not have secrets set permission"* ) ]]; then
      sleep 10
      continue
    fi
    aif_error "Could not set Key Vault secret '$name': $output" >&2
    exit 1
  done
}

aif_seed_optional_project_sp() {
  AIF_PROJECT_SP_APP_SECRET=""
  AIF_PROJECT_SP_OID_SECRET=""
  AIF_PROJECT_SP_SECRET_SECRET=""
  if [[ "$AIF_SEED_PROJECT_SP" != "true" ]]; then
    return
  fi
  local sp_name="esml-project${AIF_PROJECT_NUMBER}-sp"
  AIF_PROJECT_SP_APP_SECRET="esml-project${AIF_PROJECT_NUMBER}-sp-id"
  AIF_PROJECT_SP_OID_SECRET="esml-project${AIF_PROJECT_NUMBER}-sp-oid"
  AIF_PROJECT_SP_SECRET_SECRET="esml-project${AIF_PROJECT_NUMBER}-sp-secret"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: create '$sp_name' and seed its app ID, object ID, and secret."
    return
  fi
  local signed_in_user kv_scope sp_json app_id password object_id
  signed_in_user="$(az ad signed-in-user show --query id --output tsv)"
  signed_in_user="${signed_in_user//$'\r'/}"
  kv_scope="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$AIF_SEEDING_RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$AIF_SEEDING_KEYVAULT_NAME"
  if [[ "$(az keyvault show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
    --name "$AIF_SEEDING_KEYVAULT_NAME" \
    --query properties.enableRbacAuthorization \
    --output tsv)" == "true" ]]; then
    aif_ensure_role_assignment \
      "$signed_in_user" User "Key Vault Secrets Officer" "$kv_scope"
  else
    az keyvault set-policy \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
      --name "$AIF_SEEDING_KEYVAULT_NAME" \
      --object-id "$signed_in_user" \
      --secret-permissions get list set \
      --output none
  fi
  sp_json="$(az ad sp create-for-rbac \
    --name "$sp_name" \
    --query '{appId:appId,password:password}' \
    --output json)"
  app_id="$(printf '%s' "$sp_json" | "${AIF_PYTHON[@]}" -c 'import json,sys; print(json.load(sys.stdin)["appId"])')"
  password="$(printf '%s' "$sp_json" | "${AIF_PYTHON[@]}" -c 'import json,sys; print(json.load(sys.stdin)["password"])')"
  object_id="$(az ad sp show --id "$app_id" --query id --output tsv)"
  object_id="${object_id//$'\r'/}"
  aif_set_keyvault_secret "$AIF_PROJECT_SP_APP_SECRET" value "$app_id"
  aif_set_keyvault_secret "$AIF_PROJECT_SP_OID_SECRET" value "$object_id"
  local secret_file="$AIF_STATE_DIR/project-sp-secret"
  printf '%s' "$password" > "$secret_file"
  chmod 600 "$secret_file"
  aif_set_keyvault_secret "$AIF_PROJECT_SP_SECRET_SECRET" file "$secret_file"
  rm -f -- "$secret_file"
  unset password sp_json
}

aif_prepare_hub_dns() {
  [[ "$AIF_TOPOLOGY" == "hs" || "$AIF_ACCESS_HUB_MODE" == "external" ||
     "${AIF_SIMPLE_COMMON_READY:-false}" == "true" ]] || return 0
  aif_section "12 / Hub private DNS"
  AIF_PRIVATE_DNS_CONFIG="$AIF_STATE_DIR/private-dns-config.json"
  "${AIF_PYTHON[@]}" \
    "$AIF_SCALESET_LIB_DIR/aifactory_private_dns.py" \
    --subscription-id "$AIF_HUB_SUBSCRIPTION_ID" \
    --resource-group "$AIF_HUB_RESOURCE_GROUP" \
    --location "$AIF_LOCATION" \
    --location-short "$AIF_LOCATION_SHORT" \
    --output "$AIF_PRIVATE_DNS_CONFIG"
  local private_dns_zones
  private_dns_zones="$("${AIF_PYTHON[@]}" -c '
import json
import sys
print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))["zones"], separators=(",", ":")))
' "$AIF_PRIVATE_DNS_CONFIG")"
  private_dns_zones="${private_dns_zones//$'\r'/}"
  if [[ "$AIF_DRY_RUN" != "true" ]]; then
    az provider register \
      --namespace Microsoft.Network \
      --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
      --wait \
      --output none \
      --only-show-errors
    az network vnet show \
      --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
      --resource-group "$AIF_HUB_VNET_RESOURCE_GROUP" \
      --name "$AIF_HUB_VNET_NAME" \
      --output none
  fi
  aif_mutate az group create \
    --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
    --name "$AIF_HUB_RESOURCE_GROUP" \
    --location "$AIF_LOCATION" \
    --output none
  aif_mutate az deployment group create \
    --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
    --resource-group "$AIF_HUB_RESOURCE_GROUP" \
    --name "aifactory-private-dns-$AIF_SCALESET_SUFFIX" \
    --template-file "$AIF_REPO_ROOT/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/createPrivateDnsZones.bicep" \
    --parameters location="$AIF_LOCATION" \
      privDnsSubscription="$AIF_HUB_SUBSCRIPTION_ID" \
      privDnsResourceGroup="$AIF_HUB_RESOURCE_GROUP" \
      vNetName="$AIF_HUB_VNET_NAME" \
      vNetResourceGroup="$AIF_HUB_VNET_RESOURCE_GROUP" \
      allGlobal=true \
      "privateLinksDnsZones=$private_dns_zones" \
    --no-prompt true \
    --output none
}

aif_ensure_private_dns_policy_assignment() {
  [[ "$AIF_TOPOLOGY" == "hs" || "$AIF_ACCESS_HUB_MODE" == "external" ||
     "${AIF_SIMPLE_COMMON_READY:-false}" == "true" ]] || return 0
  aif_section "13 / Spoke private-DNS policy"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: deploy the regional private-DNS initiative in DEV and assign its managed identity access to central DNS."
    return 0
  fi
  local spoke_scope="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID"
  local definition_id="$spoke_scope/providers/Microsoft.Authorization/policySetDefinitions/Deploy-Private-DNS-Zones"
  local assignment_name="aifactory-central-private-dns"
  local assignment_params="$AIF_STATE_DIR/private-dns-assignment-parameters.json"
  "${AIF_PYTHON[@]}" - "$AIF_PRIVATE_DNS_CONFIG" "$assignment_params" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
with open(sys.argv[2], "w", encoding="utf-8") as output:
    json.dump(value["assignmentParameters"], output, indent=2)
PY

  aif_use_azure_tenant
  az deployment sub create \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --name "aifactory-private-dns-initiative" \
    --location "$AIF_LOCATION" \
    --template-file "$AIF_REPO_ROOT/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/esml-util/28-Initiatives.bicep" \
    --parameters \
      location="$AIF_LOCATION" \
      scope="$spoke_scope" \
      includeCostOptimization=false \
    --output none

  if az policy assignment show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --scope "$spoke_scope" \
    --name "$assignment_name" \
    --output none 2>/dev/null; then
    local actual_definition
    actual_definition="$(az policy assignment show \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --scope "$spoke_scope" \
      --name "$assignment_name" \
      --query policyDefinitionId \
      --output tsv)"
    actual_definition="${actual_definition//$'\r'/}"
    if [[ "${actual_definition,,}" != "${definition_id,,}" ]]; then
      aif_error "Policy assignment '$assignment_name' targets '$actual_definition', not '$definition_id'." >&2
      exit 1
    fi
    az policy assignment update \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --scope "$spoke_scope" \
      --name "$assignment_name" \
      --params "@$assignment_params" \
      --enforcement-mode Default \
      --output none
  else
    az policy assignment create \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --scope "$spoke_scope" \
      --name "$assignment_name" \
      --display-name "AI Factory - configure central private DNS zone groups" \
      --policy-set-definition "$definition_id" \
      --location "$AIF_LOCATION" \
      --mi-system-assigned \
      --identity-scope "/subscriptions/$AIF_HUB_SUBSCRIPTION_ID" \
      --role "Network Contributor" \
      --params "@$assignment_params" \
      --enforcement-mode Default \
      --output none
  fi
  local policy_principal_id
  policy_principal_id="$(az policy assignment show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --scope "$spoke_scope" \
    --name "$assignment_name" \
    --query identity.principalId \
    --output tsv)"
  policy_principal_id="${policy_principal_id//$'\r'/}"
  if [[ -z "$policy_principal_id" ]]; then
    aif_error "Private-DNS policy assignment has no system-assigned managed identity." >&2
    exit 1
  fi
  aif_ensure_role_assignment \
    "$policy_principal_id" ServicePrincipal "Network Contributor" "$spoke_scope"
  aif_ensure_role_assignment \
    "$policy_principal_id" ServicePrincipal "Network Contributor" \
    "/subscriptions/$AIF_HUB_SUBSCRIPTION_ID"
  az policy state trigger-scan \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --no-wait
  AIF_PRIVATE_DNS_POLICY_ASSIGNMENT_NAME="$assignment_name"
  aif_success "Private-DNS initiative is assigned to the DEV spoke subscription."
}

aif_last_subnet() {
  "${AIF_PYTHON[@]}" - "$1" "$2" <<'PY' | tr -d '\r'
import ipaddress
import sys

network = ipaddress.ip_network(sys.argv[1], strict=True)
print(list(network.subnets(new_prefix=int(sys.argv[2])))[-1])
PY
}

aif_resolver_subnet() {
  "${AIF_PYTHON[@]}" - "$1" "$2" <<'PY' | tr -d '\r'
import ipaddress
import sys

network = ipaddress.ip_network(sys.argv[1], strict=True)
subnets = list(network.subnets(new_prefix=28))
index = 16 if sys.argv[2] == "integrated" else 0
if len(subnets) <= index:
    raise SystemExit(f"{network} is too small for the DNS resolver subnet")
print(subnets[index])
PY
}

aif_ensure_dns_private_resolver() {
  local mode="$1" hub_subscription="$2" hub_resource_group="$3"
  local hub_vnet="$4" hub_cidr="$5"
  local resolver_subnet resolver_name inbound_name
  resolver_subnet="$(aif_resolver_subnet "$hub_cidr" "$mode")"
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" && "$mode" == "integrated" ]]; then
    resolver_subnet="$AIF_SIMPLE_RESOLVER_SUBNET"
  fi
  resolver_name="dnspr-aifactory-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}"
  inbound_name="inbound-aifactory-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}"
  if ! az network vnet subnet show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --vnet-name "$hub_vnet" \
    --name snet-dns-private-resolver \
    --output none 2>/dev/null; then
    az network vnet subnet create \
      --subscription "$hub_subscription" \
      --resource-group "$hub_resource_group" \
      --vnet-name "$hub_vnet" \
      --name snet-dns-private-resolver \
      --address-prefixes "$resolver_subnet" \
      --delegations Microsoft.Network/dnsResolvers \
      --output none
  fi
  local vnet_id subnet_id resolver_url inbound_url resolver_body inbound_body
  vnet_id="$(az network vnet show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$hub_vnet" \
    --query id \
    --output tsv)"
  vnet_id="${vnet_id//$'\r'/}"
  subnet_id="$vnet_id/subnets/snet-dns-private-resolver"
  resolver_url="https://management.azure.com/subscriptions/$hub_subscription/resourceGroups/$hub_resource_group/providers/Microsoft.Network/dnsResolvers/$resolver_name"
  inbound_url="$resolver_url/inboundEndpoints/$inbound_name"
  resolver_body="$AIF_STATE_DIR/dns-resolver.json"
  inbound_body="$AIF_STATE_DIR/dns-resolver-inbound.json"
  "${AIF_PYTHON[@]}" - \
    "$resolver_body" "$inbound_body" "$AIF_LOCATION" "$vnet_id" "$subnet_id" <<'PY'
import json
import sys

json.dump(
    {
        "location": sys.argv[3],
        "properties": {"virtualNetwork": {"id": sys.argv[4]}},
    },
    open(sys.argv[1], "w", encoding="utf-8"),
)
json.dump(
    {
        "location": sys.argv[3],
        "properties": {
            "ipConfigurations": [
                {
                    "privateIpAllocationMethod": "Dynamic",
                    "subnet": {"id": sys.argv[5]},
                }
            ]
        },
    },
    open(sys.argv[2], "w", encoding="utf-8"),
)
PY
  az rest \
    --method put \
    --url "$resolver_url?api-version=2025-05-01" \
    --body "@$resolver_body" \
    --output none
  az rest \
    --method put \
    --url "$inbound_url?api-version=2025-05-01" \
    --body "@$inbound_body" \
    --output none

  local inbound_state="" inbound_ip="" attempt
  for attempt in {1..90}; do
    local -a inbound_values=()
    mapfile -t inbound_values < <(az rest \
      --method get \
      --url "$inbound_url?api-version=2025-05-01" \
      --query '[properties.provisioningState, properties.ipConfigurations[0].privateIpAddress]' \
      --output tsv 2>/dev/null | tr -d '\r' || true)
    inbound_state="${inbound_values[0]:-}"
    inbound_ip="${inbound_values[1]:-}"
    [[ "$inbound_state" != "Failed" ]] ||
      { aif_error "DNS Private Resolver inbound endpoint failed."; exit 1; }
    [[ "$inbound_state" == "Succeeded" && -n "$inbound_ip" ]] && break
    sleep 10
  done
  if [[ "$inbound_state" != "Succeeded" || -z "$inbound_ip" ]]; then
    aif_error "DNS Private Resolver inbound endpoint did not become ready." >&2
    exit 1
  fi
  az network vnet update \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$hub_vnet" \
    --dns-servers "$inbound_ip" \
    --output none
  AIF_DNS_RESOLVER_INBOUND_IP="$inbound_ip"
  aif_success "DNS Private Resolver inbound endpoint is available at $inbound_ip."
}

aif_ensure_hub_dns_forwarder() {
  local mode="$1"
  aif_section "12a / Hub DNS forwarder"
  aif_info "The hub DNS forwarder gives VPN clients and peered AI Factory VNets a routable DNS endpoint for central private DNS zones."
  aif_info "It uses an Azure DNS Private Resolver inbound endpoint; clients must not use Azure's non-routable 168.63.129.16 address or a hosts file."
  aif_ensure_dns_private_resolver \
    "$mode" \
    "$AIF_HUB_SUBSCRIPTION_ID" \
    "$AIF_HUB_RESOURCE_GROUP" \
    "$AIF_HUB_VNET_NAME" \
    "$AIF_ACCESS_HUB_VNET_CIDR"
}

aif_create_vpn_public_ip() {
  local subscription="$1"
  local resource_group="$2"
  local public_ip_name="$3"
  local create_error="$AIF_STATE_DIR/vpn-public-ip-create.err"

  if az network public-ip create \
    --subscription "$subscription" \
    --resource-group "$resource_group" \
    --name "$public_ip_name" \
    --location "$AIF_LOCATION" \
    --allocation-method Static \
    --sku Standard \
    --version IPv4 \
    --zone 1 2 3 \
    --output none \
    --only-show-errors 2>"$create_error"; then
    rm -f -- "$create_error"
    return 0
  fi
  if ! grep -qF "Microsoft.Network/AllowBringYourOwnPublicIpAddress" "$create_error"; then
    cat "$create_error" >&2
    rm -f -- "$create_error"
    return 1
  fi

  aif_warn "The subscription policy requires the Microsoft.Network/AllowBringYourOwnPublicIpAddress feature; registering it and retrying."
  az feature register \
    --subscription "$subscription" \
    --namespace Microsoft.Network \
    --name AllowBringYourOwnPublicIpAddress \
    --output none
  local attempt feature_state=""
  for ((attempt = 0; attempt < 60; attempt++)); do
    feature_state="$(az feature show \
      --subscription "$subscription" \
      --namespace Microsoft.Network \
      --name AllowBringYourOwnPublicIpAddress \
      --query properties.state \
      --output tsv)"
    feature_state="${feature_state//$'\r'/}"
    [[ "$feature_state" == "Registered" ]] && break
    sleep 10
  done
  if [[ "$feature_state" != "Registered" ]]; then
    aif_error "Microsoft.Network/AllowBringYourOwnPublicIpAddress did not become registered." >&2
    rm -f -- "$create_error"
    return 1
  fi
  az provider register \
    --subscription "$subscription" \
    --namespace Microsoft.Network \
    --wait \
    --output none \
    --only-show-errors
  rm -f -- "$create_error"
  az network public-ip create \
    --subscription "$subscription" \
    --resource-group "$resource_group" \
    --name "$public_ip_name" \
    --location "$AIF_LOCATION" \
    --allocation-method Static \
    --sku Standard \
    --version IPv4 \
    --zone 1 2 3 \
    --output none \
    --only-show-errors
}

aif_ensure_access_hub_vnet() {
  local mode="$1"
  local hub_subscription hub_resource_group hub_vnet hub_cidr
  hub_subscription="$AIF_HUB_SUBSCRIPTION_ID"
  hub_resource_group="$AIF_HUB_RESOURCE_GROUP"
  hub_vnet="$AIF_HUB_VNET_NAME"
  hub_cidr="$AIF_ACCESS_HUB_VNET_CIDR"
  aif_use_azure_tenant
  az provider register \
    --namespace Microsoft.Network \
    --subscription "$hub_subscription" \
    --wait \
    --output none \
    --only-show-errors
  az group create \
    --subscription "$hub_subscription" \
    --name "$hub_resource_group" \
    --location "$AIF_LOCATION" \
    --tags Purpose=AIFactoryConnectivity \
    --output none

  if [[ "$mode" == "external" ]]; then
    if ! az network vnet show \
      --subscription "$hub_subscription" \
      --resource-group "$hub_resource_group" \
      --name "$hub_vnet" \
      --output none 2>/dev/null; then
      az network vnet create \
        --subscription "$hub_subscription" \
        --resource-group "$hub_resource_group" \
        --name "$hub_vnet" \
        --location "$AIF_LOCATION" \
        --address-prefixes "$hub_cidr" \
        --tags Purpose=AIFactoryConnectivity \
        --output none
    fi
  else
    az network vnet show \
      --subscription "$hub_subscription" \
      --resource-group "$hub_resource_group" \
      --name "$hub_vnet" \
      --output none
  fi
  local actual_hub_prefixes
  actual_hub_prefixes="$(az network vnet show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$hub_vnet" \
    --query 'addressSpace.addressPrefixes' \
    --output tsv)"
  actual_hub_prefixes="${actual_hub_prefixes//$'\r'/}"
  if ! grep -qxF "$hub_cidr" <<< "$actual_hub_prefixes"; then
    aif_error "Access-hub VNet '$hub_vnet' does not contain configured CIDR '$hub_cidr'." >&2
    exit 1
  fi
}

aif_ensure_vpn_access_hub() {
  local mode="$1"
  local hub_subscription hub_resource_group hub_vnet hub_cidr
  hub_subscription="$AIF_HUB_SUBSCRIPTION_ID"
  hub_resource_group="$AIF_HUB_RESOURCE_GROUP"
  hub_vnet="$AIF_HUB_VNET_NAME"
  hub_cidr="$AIF_ACCESS_HUB_VNET_CIDR"
  local gateway_subnet gateway_name public_ip_name
  gateway_subnet="$(aif_last_subnet "$hub_cidr" 27)"
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" && "$mode" == "integrated" ]]; then
    gateway_subnet="$AIF_SIMPLE_GATEWAY_SUBNET"
  fi
  gateway_name="vpngw-aifactory-access-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}"
  public_ip_name="${gateway_name}-pip"

  aif_ensure_access_hub_vnet "$mode"

  if ! az network vnet subnet show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --vnet-name "$hub_vnet" \
    --name GatewaySubnet \
    --output none 2>/dev/null; then
    az network vnet subnet create \
      --subscription "$hub_subscription" \
      --resource-group "$hub_resource_group" \
      --vnet-name "$hub_vnet" \
      --name GatewaySubnet \
      --address-prefixes "$gateway_subnet" \
      --output none
  fi
  local actual_gateway_subnet
  actual_gateway_subnet="$(az network vnet subnet show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --vnet-name "$hub_vnet" \
    --name GatewaySubnet \
    --query addressPrefix \
    --output tsv)"
  actual_gateway_subnet="${actual_gateway_subnet//$'\r'/}"
  if [[ "$actual_gateway_subnet" != "$gateway_subnet" ]]; then
    aif_error "GatewaySubnet is '$actual_gateway_subnet'; expected '$gateway_subnet'." >&2
    exit 1
  fi
  if az network public-ip show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$public_ip_name" \
    --output none 2>/dev/null; then
    local public_ip_zones public_ip_binding
    public_ip_zones="$(az network public-ip show \
      --subscription "$hub_subscription" \
      --resource-group "$hub_resource_group" \
      --name "$public_ip_name" \
      --query 'zones[]' \
      --output tsv)"
    public_ip_zones="${public_ip_zones//$'\r'/}"
    if [[ -z "$public_ip_zones" ]]; then
      public_ip_binding="$(az network public-ip show \
        --subscription "$hub_subscription" \
        --resource-group "$hub_resource_group" \
        --name "$public_ip_name" \
        --query ipConfiguration.id \
        --output tsv)"
      public_ip_binding="${public_ip_binding//$'\r'/}"
      if [[ -n "$public_ip_binding" ]]; then
        aif_error "VPN public IP '$public_ip_name' has no availability zones and is already attached to '$public_ip_binding'." >&2
        exit 1
      fi
      aif_warn "Recreating VPN public IP '$public_ip_name' with availability zones required by the AZ gateway SKU."
      az network public-ip delete \
        --subscription "$hub_subscription" \
        --resource-group "$hub_resource_group" \
        --name "$public_ip_name"
    fi
  fi
  if ! az network public-ip show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$public_ip_name" \
    --output none 2>/dev/null; then
    aif_create_vpn_public_ip \
      "$hub_subscription" \
      "$hub_resource_group" \
      "$public_ip_name"
  fi

  if ! az network vnet-gateway show \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$gateway_name" \
    --output none 2>/dev/null; then
    aif_info "Creating VPN gateway '$gateway_name'. This normally takes 30-45 minutes."
    az network vnet-gateway create \
      --subscription "$hub_subscription" \
      --resource-group "$hub_resource_group" \
      --name "$gateway_name" \
      --location "$AIF_LOCATION" \
      --vnet "$hub_vnet" \
      --gateway-type Vpn \
      --vpn-type RouteBased \
      --sku VpnGw1AZ \
      --vpn-gateway-generation Generation1 \
      --public-ip-addresses "$public_ip_name" \
      --no-wait
  fi
  az network vnet-gateway wait \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$gateway_name" \
    --created \
    --interval 30 \
    --timeout 5400
  az network vnet-gateway update \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$gateway_name" \
    --address-prefixes "$AIF_VPN_CLIENT_CIDR" \
    --client-protocol OpenVPN \
    --vpn-auth-type AAD \
    --aad-tenant "https://login.microsoftonline.com/$AIF_TENANT_ID" \
    --aad-audience "c632b3df-fb67-4d84-bdcf-b95ad541b5c8" \
    --aad-issuer "https://sts.windows.net/$AIF_TENANT_ID/" \
    --custom-routes "$AIF_DEV_VNET_CIDR" \
    --output none
  az network vnet-gateway wait \
    --subscription "$hub_subscription" \
    --resource-group "$hub_resource_group" \
    --name "$gateway_name" \
    --updated \
    --interval 30 \
    --timeout 3600
  AIF_VPN_GATEWAY_NAME="$gateway_name"
  aif_success "Point-to-site VPN gateway '$gateway_name' is ready."
}

aif_ensure_bastion_developer() {
  [[ "$AIF_SETUP_HUB_ACCESS" == "true" ]] || return 0
  local subscription="$1" resource_group="$2" vnet_name="$3"
  local bastion_name="bastion-${AIF_PREFIX%-}-${AIF_LOCATION_SHORT}-dev-${AIF_SCALESET_SUFFIX}"
  local bastion_sku=""

  if az network bastion show \
    --subscription "$subscription" \
    --resource-group "$resource_group" \
    --name "$bastion_name" \
    --output none 2>/dev/null; then
    bastion_sku="$(az network bastion show \
      --subscription "$subscription" \
      --resource-group "$resource_group" \
      --name "$bastion_name" \
      --query sku.name \
      --output tsv)"
    bastion_sku="${bastion_sku//$'\r'/}"
    aif_success "Azure Bastion '$bastion_name' already exists with SKU '$bastion_sku'."
    return 0
  fi

  if ! az network bastion create \
    --subscription "$subscription" \
    --resource-group "$resource_group" \
    --name "$bastion_name" \
    --location "$AIF_LOCATION" \
    --sku Developer \
    --vnet-name "$vnet_name" \
    --no-wait \
    --output none; then
    aif_error "Bastion Developer could not be created in '$AIF_LOCATION'. No paid SKU fallback was attempted; select a supported region or use Advanced Mode." >&2
    exit 1
  fi
  az network bastion wait \
    --subscription "$subscription" \
    --resource-group "$resource_group" \
    --name "$bastion_name" \
    --created \
    --interval 10 \
    --timeout 900
  aif_success "Azure Bastion Developer '$bastion_name' is ready. No admin VM is included unless separately enabled."
}

aif_configure_windows_vpn_client() {
  [[ "$AIF_CONFIGURE_VPN_CLIENT" == "true" || "${AIF_SIMPLE_MODE:-false}" == "true" ]] || return 0
  if [[ "$AIF_CONFIGURE_VPN_CLIENT" == "true" ]]; then
    if ! aif_is_windows; then
      aif_error "Azure VPN Client installation and profile import are supported only from Windows Git Bash." >&2
      exit 1
    fi

    aif_section "16 / Azure VPN Client"
    if ! powershell.exe -NoProfile -NonInteractive -Command \
      "if (Get-AppxPackage -Name Microsoft.AzureVpn -ErrorAction SilentlyContinue) { exit 0 }; exit 1"; then
      if ! command -v winget.exe >/dev/null 2>&1; then
        aif_error "Azure VPN Client is missing and winget.exe is not available." >&2
        exit 1
      fi
      aif_info "Installing Microsoft Azure VPN Client for the current Windows user."
      winget.exe install \
        --id Microsoft.AzureVPNClient \
        --exact \
        --source winget \
        --silent \
        --accept-package-agreements \
        --accept-source-agreements \
        --disable-interactivity
    fi
    if ! powershell.exe -NoProfile -NonInteractive -Command \
      "if (Get-AppxPackage -Name Microsoft.AzureVpn -ErrorAction SilentlyContinue) { exit 0 }; exit 1"; then
      aif_error "Microsoft Azure VPN Client installation could not be verified." >&2
      exit 1
    fi
  fi

  local profile_url="" attempt
  for ((attempt = 0; attempt < 30; attempt++)); do
    profile_url="$(az network vnet-gateway vpn-client generate \
      --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
      --resource-group "$AIF_HUB_RESOURCE_GROUP" \
      --name "$AIF_VPN_GATEWAY_NAME" \
      --processor-architecture Amd64 \
      --output tsv 2>/dev/null || true)"
    profile_url="${profile_url//$'\r'/}"
    [[ "$profile_url" == https://* ]] && break
    sleep 10
  done
  if [[ "$profile_url" != https://* ]]; then
    aif_error "Azure did not generate a VPN client configuration package." >&2
    exit 1
  fi

  local package_path="$AIF_STATE_DIR/vpn-client.zip"
  local extract_path="$AIF_STATE_DIR/vpn-client"
  local source_profile="$AIF_STATE_DIR/source-azurevpnconfig.xml"
  local prepared_profile="$AIF_STATE_DIR/aifactory-azurevpnconfig.xml"
  curl --fail --location --silent --show-error \
    "$profile_url" \
    --output "$package_path"
  "${AIF_PYTHON[@]}" - "$package_path" "$extract_path" "$source_profile" <<'PY'
import pathlib
import shutil
import sys
import zipfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
output = pathlib.Path(sys.argv[3])
destination.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as package:
    root = destination.resolve()
    for item in package.infolist():
        target = (destination / item.filename).resolve()
        if root not in target.parents and target != root:
            raise SystemExit(f"Unsafe path in VPN client package: {item.filename}")
    package.extractall(destination)

profiles = sorted(
    path
    for path in destination.rglob("azurevpnconfig*.xml")
    if path.parent.name.lower() == "azurevpn"
)
if not profiles:
    raise SystemExit("The VPN client package has no Azure VPN Client profile.")
preferred = next(
    (path for path in profiles if "aad" in path.name.lower()),
    profiles[0],
)
shutil.copy2(preferred, output)
PY

  local profile_name="AI Factory ${AIF_PREFIX%-}-${AIF_SCALESET_SUFFIX}"
  "${AIF_PYTHON[@]}" \
    "$AIF_SCALESET_LIB_DIR/aifactory_vpn_profile.py" \
    --input "$source_profile" \
    --output "$prepared_profile" \
    --name "$profile_name"

  if [[ "$AIF_CONFIGURE_VPN_CLIENT" != "true" ]]; then
    local artifact_dir="$AIF_REPO_ROOT/.aifactory-access"
    mkdir -p "$artifact_dir"
    chmod 700 "$artifact_dir"
    cp -- "$prepared_profile" "$artifact_dir/azurevpnconfig.xml"
    chmod 600 "$artifact_dir/azurevpnconfig.xml"
    aif_success "VPN profile saved to .aifactory-access/azurevpnconfig.xml (git-ignored). Install/import/connect manually; no VPN client was installed."
    return 0
  fi

  local local_state_windows local_state profile_file profile_basename pbk
  local_state_windows="$(powershell.exe -NoProfile -NonInteractive -Command \
    "[Environment]::ExpandEnvironmentVariables('%LOCALAPPDATA%\Packages\Microsoft.AzureVpn_8wekyb3d8bbwe\LocalState')")"
  local_state_windows="${local_state_windows//$'\r'/}"
  local_state="$(cygpath -u "$local_state_windows")"
  mkdir -p "$local_state"
  profile_basename="azurevpnconfig.xml"
  profile_file="$local_state/$profile_basename"
  pbk="$local_state/rasphone.pbk"
  if [[ -f "$pbk" ]] && grep -Fqx "[$profile_name]" "$pbk"; then
    aif_success "Azure VPN Client profile '$profile_name' is already configured."
    return 0
  fi
  cp -f -- "$prepared_profile" "$profile_file"

  if ! command -v AzureVpn.exe >/dev/null 2>&1; then
    aif_error "The AzureVpn.exe application alias is unavailable after installation." >&2
    exit 1
  fi
  (cd "$local_state" && AzureVpn.exe -i "$profile_basename")
  for ((attempt = 0; attempt < 30; attempt++)); do
    if [[ -f "$pbk" ]] && grep -Fqx "[$profile_name]" "$pbk"; then
      aif_success "Azure VPN Client profile '$profile_name' is configured."
      return 0
    fi
    sleep 2
  done
  aif_error "Azure VPN Client did not persist profile '$profile_name'." >&2
  exit 1
}

aif_prepare_external_access_hub() {
  [[ "$AIF_ACCESS_HUB_MODE" == "external" ]] || return 0
  aif_section "12 / External AI Factory access hub"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: create/reconcile the external access-hub VNet."
    aif_info "DRY-RUN: create/reconcile the hub Azure DNS Private Resolver inbound endpoint used as the private-DNS forwarder."
    if [[ "$AIF_SETUP_HUB_ACCESS" == "true" ]]; then
      aif_info "DRY-RUN: create/reconcile GatewaySubnet, VpnGw1AZ, and Entra-authenticated P2S configuration."
    fi
    return 0
  fi
  aif_ensure_access_hub_vnet external
  aif_ensure_hub_dns_forwarder external
  if [[ "$AIF_SETUP_HUB_ACCESS" == "true" ]]; then
    aif_ensure_vpn_access_hub external
  fi
}

aif_write_state_and_configure() {
  local state_file="$AIF_STATE_DIR/config.json"
  "${AIF_PYTHON[@]}" - "$state_file" \
    "$AIF_TOPOLOGY" "$AIF_ACCESS_HUB_MODE" "$AIF_NETWORK_MODE" "$AIF_TENANT_ID" \
    "$AIF_DEV_SUBSCRIPTION_ID" "$AIF_STAGE_SUBSCRIPTION_ID" "$AIF_PROD_SUBSCRIPTION_ID" \
    "$AIF_LOCATION" "$AIF_LOCATION_SHORT" "$AIF_DEV_VNET_CIDR" \
    "$AIF_PREFIX" "$AIF_SCALESET_SUFFIX_DASH" "$AIF_PROJECT_NUMBER" \
    "$AIF_TEAM_GROUP_ID" "$AIF_TEAM_GROUP_NAME" "$AIF_IP_ALLOWLIST" \
    "$AIF_SEEDING_SUBSCRIPTION_ID" "$AIF_SEEDING_RESOURCE_GROUP" "$AIF_SEEDING_KEYVAULT_NAME" \
    "$AIF_ENABLE_PUBLIC_GENAI_ACCESS" "$AIF_ALLOW_PUBLIC_ACCESS_BEHIND_VNET" \
    "$AIF_ENABLE_PUBLIC_PERIMETER" "$AIF_ADD_BASTION" \
    "$AIF_HUB_SUBSCRIPTION_ID" "$AIF_HUB_RESOURCE_GROUP" \
    "$AIF_PROJECT_SP_APP_SECRET" "$AIF_PROJECT_SP_OID_SECRET" "$AIF_PROJECT_SP_SECRET_SECRET" \
    "${AIF_AZURE_ML_PRINCIPAL_ID:-}" "${AIF_DATABRICKS_PRINCIPAL_ID:-}" \
    "${ADO_TENANT:-}" "${ADO_SERVICE_CONNECTION_NAME:-}" \
    "${GITHUB_REPOSITORY:-}" "${AIF_OIDC_CLIENT_ID:-}" \
    "$AIF_RUNNER_MODE" "${ADO_AGENT_POOL:-}" "${ADO_AGENT_NAME:-}" \
    "$AIF_ADMIN_VM_SIZE" "${AIF_SIMPLE_MODE:-false}" "${AIF_COST_CENTER:-}" \
    "$AIF_TEAM_MEMBER_EMAIL" <<'PY'
import json
import sys

keys = (
    "topology", "access_hub_mode", "network_mode", "tenant_id",
    "dev_subscription_id", "stage_subscription_id", "prod_subscription_id",
    "location", "location_short", "dev_vnet_cidr",
    "prefix", "scaleset_suffix", "project_number",
    "team_group_id", "team_group_name", "ip_allowlist",
    "seeding_subscription_id", "seeding_resource_group", "seeding_keyvault_name",
    "enable_public_genai_access", "allow_public_access_behind_vnet",
    "enable_public_perimeter", "add_bastion",
    "hub_subscription_id", "hub_resource_group",
    "project_sp_app_secret", "project_sp_oid_secret", "project_sp_secret_secret",
    "azure_ml_principal_id", "databricks_principal_id",
    "ado_tenant_id", "ado_service_connection",
    "github_repository", "oidc_client_id",
    "runner_mode", "ado_agent_pool", "ado_agent_name", "admin_vm_size",
    "simple_mode", "cost_center", "team_member_email",
)
values = dict(zip(keys, sys.argv[2:]))
values["dev_service_connection"] = values["ado_service_connection"]
values["stage_service_connection"] = values["ado_service_connection"]
values["prod_service_connection"] = values["ado_service_connection"]
values["project_sp_secret_names"] = {
    "app_id": values.pop("project_sp_app_secret"),
    "object_id": values.pop("project_sp_oid_secret"),
    "secret": values.pop("project_sp_secret_secret"),
}
with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(values, output, indent=2)
    output.write("\n")
PY
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: apply collected values to route configuration."
    return
  fi
  "${AIF_PYTHON[@]}" \
    "$AIF_REPO_ROOT/azure-enterprise-scale-ml/bootstrap/lib/aifactory_scaleset_config.py" \
    --route "$AIF_ROUTE" \
    --repo-root "$AIF_REPO_ROOT" \
    --state-file "$state_file"
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" ]]; then
    grep -Fqx '/.aifactory-access/' "$AIF_REPO_ROOT/.gitignore" 2>/dev/null ||
      printf '\n/.aifactory-access/\n' >> "$AIF_REPO_ROOT/.gitignore"
  fi
}

aif_urlencode() {
  "${AIF_PYTHON[@]}" -c \
    'import sys; from urllib.parse import quote; print(quote(sys.argv[1], safe=""))' "$1" |
    tr -d '\r'
}

aif_ado_api() {
  local method="$1" url="$2" input_file="${3:-}"
  local auth_header
  if [[ "$ADO_AUTH_METHOD" == "pat" ]]; then
    auth_header="$(AZURE_DEVOPS_EXT_PAT="$AZURE_DEVOPS_EXT_PAT" "${AIF_PYTHON[@]}" -c '
import base64
import os
print("Basic " + base64.b64encode((":" + os.environ["AZURE_DEVOPS_EXT_PAT"]).encode()).decode())
')"
  else
    local token
    token="$(az account get-access-token \
      --resource "$AIF_ADO_RESOURCE" \
      --tenant "$ADO_TENANT" \
      --query accessToken \
      --output tsv)"
    token="${token//$'\r'/}"
    auth_header="Bearer $token"
  fi
  ADO_AUTH_HEADER="$auth_header" "${AIF_PYTHON[@]}" - "$method" "$url" "$input_file" <<'PY'
import os
import sys
import urllib.error
import urllib.request

method, url, input_file = sys.argv[1:4]
data = open(input_file, "rb").read() if input_file else None
request = urllib.request.Request(
    url,
    data=data,
    method=method,
    headers={
        "Accept": "application/json",
        "Authorization": os.environ["ADO_AUTH_HEADER"],
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(request) as response:
        sys.stdout.buffer.write(response.read())
except urllib.error.HTTPError as error:
    body = error.read().decode("utf-8", errors="replace")
    print(f"Azure DevOps API HTTP {error.code}: {body}", file=sys.stderr)
    raise SystemExit(1)
PY
}

aif_ensure_ado_federated_credential() {
  local issuer="$1" subject="$2"
  local credential_name="ado-${AIF_SCALESET_SUFFIX}-dev"
  local existing_values=""
  if existing_values="$(az identity federated-credential show \
    --subscription "$AIF_IDENTITY_SUBSCRIPTION_ID" \
    --resource-group "$AIF_IDENTITY_RESOURCE_GROUP" \
    --identity-name "$AIF_IDENTITY_NAME" \
    --name "$credential_name" \
    --query '[issuer,subject]' \
    --output tsv 2>/dev/null)"; then
    local existing_issuer existing_subject
    local -a existing_federation=()
    existing_values="${existing_values//$'\r'/}"
    mapfile -t existing_federation <<< "$existing_values"
    existing_issuer="${existing_federation[0]:-}"
    existing_subject="${existing_federation[1]:-}"
    if [[ "$existing_issuer" != "$issuer" || "$existing_subject" != "$subject" ]]; then
      aif_warn "Reconciling federated credential '$credential_name' with the current Azure DevOps service connection."
      az identity federated-credential update \
        --subscription "$AIF_IDENTITY_SUBSCRIPTION_ID" \
        --resource-group "$AIF_IDENTITY_RESOURCE_GROUP" \
        --identity-name "$AIF_IDENTITY_NAME" \
        --name "$credential_name" \
        --issuer "$issuer" \
        --subject "$subject" \
        --audiences api://AzureADTokenExchange \
        --output none
    fi
    return
  fi
  az identity federated-credential create \
    --subscription "$AIF_IDENTITY_SUBSCRIPTION_ID" \
    --resource-group "$AIF_IDENTITY_RESOURCE_GROUP" \
    --identity-name "$AIF_IDENTITY_NAME" \
    --name "$credential_name" \
    --issuer "$issuer" \
    --subject "$subject" \
    --audiences api://AzureADTokenExchange \
    --output none
}

aif_ensure_ado_service_connection() {
  local project_encoded endpoint_name_encoded endpoints_file endpoint_file
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  endpoint_name_encoded="$(aif_urlencode "$ADO_SERVICE_CONNECTION_NAME")"
  endpoints_file="$AIF_STATE_DIR/endpoints.json"
  endpoint_file="$AIF_STATE_DIR/endpoint.json"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    AIF_ADO_ENDPOINT_ID="00000000-0000-0000-0000-000000000005"
    aif_info "DRY-RUN: create/reuse Azure DevOps service connection '$ADO_SERVICE_CONNECTION_NAME'."
    return
  fi
  AIF_ADO_PROJECT_ID="$(az devops project show \
    --organization "$ADO_ORGANIZATION" \
    --project "$ADO_PROJECT" \
    --query id \
    --output tsv)"
  AIF_ADO_PROJECT_ID="${AIF_ADO_PROJECT_ID//$'\r'/}"
  aif_ado_api GET \
    "$ADO_ORGANIZATION/$project_encoded/_apis/serviceendpoint/endpoints?endpointNames=$endpoint_name_encoded&api-version=7.1" \
    > "$endpoints_file"
  local existing_endpoint_values
  existing_endpoint_values="$("${AIF_PYTHON[@]}" - \
    "$endpoints_file" "$AIF_DEV_SUBSCRIPTION_ID" "$AIF_TENANT_ID" \
    "$AIF_IDENTITY_CLIENT_ID" "$AIF_IDENTITY_MODE" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
values = payload.get("value", [])
if len(values) > 1:
    raise SystemExit("Multiple service connections have the requested name")
if values:
    endpoint = values[0]
    parameters = endpoint.get("authorization", {}).get("parameters", {})
    expected_scheme = "ServicePrincipal" if sys.argv[5] == "sp" else "WorkloadIdentityFederation"
    actual = {
        "subscription": str(endpoint.get("data", {}).get("subscriptionId", "")),
        "tenant": str(parameters.get("tenantid", "")),
        "client": str(parameters.get("serviceprincipalid", "")),
        "scheme": str(endpoint.get("authorization", {}).get("scheme", "")),
    }
    expected = {
        "subscription": sys.argv[2],
        "tenant": sys.argv[3],
        "client": sys.argv[4],
        "scheme": expected_scheme,
    }
    mismatches = [
        key for key in expected
        if actual[key].lower() != expected[key].lower()
    ]
    if mismatches:
        raise SystemExit(
            "Existing service connection does not match requested "
            + ", ".join(mismatches)
        )
    print(endpoint["id"])
    print(parameters.get("workloadIdentityFederationIssuer", ""))
    print(parameters.get("workloadIdentityFederationSubject", ""))
PY
)"
  existing_endpoint_values="${existing_endpoint_values//$'\r'/}"
  mapfile -t existing_endpoint <<< "$existing_endpoint_values"
  AIF_ADO_ENDPOINT_ID="${existing_endpoint[0]:-}"
  if [[ -n "$AIF_ADO_ENDPOINT_ID" ]]; then
    if [[ "$AIF_IDENTITY_MODE" != "sp" ]]; then
      local existing_issuer="${existing_endpoint[1]:-}"
      local existing_subject="${existing_endpoint[2]:-}"
      if [[ -z "$existing_issuer" || -z "$existing_subject" ]]; then
        aif_error "Existing service connection is missing federation issuer/subject metadata." >&2
        exit 1
      fi
      aif_ensure_ado_federated_credential "$existing_issuer" "$existing_subject"
    fi
    aif_success "Using existing service connection '$ADO_SERVICE_CONNECTION_NAME'."
    return
  fi

  local subscription_name="$AIF_DEV_SUBSCRIPTION_ID"
  subscription_name="$(az account show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --query name \
    --output tsv)"
  subscription_name="${subscription_name//$'\r'/}"
  ENDPOINT_SECRET="${AIF_SP_CLIENT_SECRET:-}" "${AIF_PYTHON[@]}" - \
    "$endpoint_file" "$AIF_DEV_SUBSCRIPTION_ID" "$subscription_name" \
    "$AIF_TENANT_ID" "$AIF_IDENTITY_CLIENT_ID" "$ADO_SERVICE_CONNECTION_NAME" \
    "$AIF_ADO_PROJECT_ID" "$ADO_PROJECT" "$AIF_IDENTITY_MODE" <<'PY'
import json
import os
import sys

(
    output, subscription_id, subscription_name, tenant_id, client_id,
    endpoint_name, project_id, project_name, identity_mode,
) = sys.argv[1:]
authorization = {
    "parameters": {"tenantid": tenant_id, "serviceprincipalid": client_id},
    "scheme": "WorkloadIdentityFederation",
}
if identity_mode == "sp":
    authorization = {
        "parameters": {
            "tenantid": tenant_id,
            "serviceprincipalid": client_id,
            "authenticationType": "spnKey",
            "serviceprincipalkey": os.environ["ENDPOINT_SECRET"],
        },
        "scheme": "ServicePrincipal",
    }
payload = {
    "data": {
        "subscriptionId": subscription_id,
        "subscriptionName": subscription_name,
        "environment": "AzureCloud",
        "scopeLevel": "Subscription",
        "creationMode": "Manual",
    },
    "name": endpoint_name,
    "type": "AzureRM",
    "url": "https://management.azure.com/",
    "authorization": authorization,
    "isShared": False,
    "isReady": True,
    "serviceEndpointProjectReferences": [{
        "projectReference": {"id": project_id, "name": project_name},
        "name": endpoint_name,
        "description": "AI Factory deployment identity",
    }],
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
  chmod 600 "$endpoint_file"
  aif_ado_api POST \
    "$ADO_ORGANIZATION/_apis/serviceendpoint/endpoints?api-version=7.1" \
    "$endpoint_file" > "$AIF_STATE_DIR/endpoint-response.json"
  local endpoint_values_output
  endpoint_values_output="$("${AIF_PYTHON[@]}" - "$AIF_STATE_DIR/endpoint-response.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
parameters = value.get("authorization", {}).get("parameters", {})
print(value["id"])
print(parameters.get("workloadIdentityFederationIssuer", ""))
print(parameters.get("workloadIdentityFederationSubject", ""))
PY
)"
  endpoint_values_output="${endpoint_values_output//$'\r'/}"
  mapfile -t endpoint_values <<< "$endpoint_values_output"
  AIF_ADO_ENDPOINT_ID="${endpoint_values[0]}"
  if [[ "$AIF_IDENTITY_MODE" != "sp" ]]; then
    local issuer="${endpoint_values[1]:-}" subject="${endpoint_values[2]:-}"
    if [[ -z "$issuer" || -z "$subject" ]]; then
      aif_error "Azure DevOps did not return managed-identity federation metadata." >&2
      exit 1
    fi
    aif_ensure_ado_federated_credential "$issuer" "$subject"
  fi
}

aif_ensure_ado_environment() {
  local name="$1" project_encoded response
  [[ "$AIF_DRY_RUN" != "true" ]] || return 0
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  response="$(aif_ado_api GET \
    "$ADO_ORGANIZATION/$project_encoded/_apis/distributedtask/environments?name=$name&api-version=7.1-preview.1")"
  if [[ "$(printf '%s' "$response" | "${AIF_PYTHON[@]}" -c 'import json,sys; print(json.load(sys.stdin).get("count", 0))')" == "0" ]]; then
    "${AIF_PYTHON[@]}" - "$AIF_STATE_DIR/environment.json" "$name" <<'PY'
import json, sys
json.dump({"name": sys.argv[2], "description": "AI Factory deployment environment"}, open(sys.argv[1], "w"))
PY
    aif_ado_api POST \
      "$ADO_ORGANIZATION/$project_encoded/_apis/distributedtask/environments?api-version=7.1-preview.1" \
      "$AIF_STATE_DIR/environment.json" >/dev/null
  fi
}

aif_authorize_ado_environment() {
  local name="$1"
  shift
  [[ "$AIF_DRY_RUN" != "true" ]] || return 0
  local project_encoded name_encoded response environment_id body
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  name_encoded="$(aif_urlencode "$name")"
  response="$(aif_ado_api GET \
    "$ADO_ORGANIZATION/$project_encoded/_apis/distributedtask/environments?name=$name_encoded&api-version=7.1")"
  environment_id="$(printf '%s' "$response" | "${AIF_PYTHON[@]}" -c '
import json
import sys

expected = sys.argv[1].lower()
matches = [
    item for item in json.load(sys.stdin).get("value", [])
    if str(item.get("name", "")).lower() == expected
]
if len(matches) != 1:
    raise SystemExit(
        f"Expected one Azure DevOps environment named {sys.argv[1]!r}; "
        f"found {len(matches)}"
    )
print(matches[0]["id"])
' "$name")"
  environment_id="${environment_id//$'\r'/}"
  body="$AIF_STATE_DIR/environment-permission-$environment_id.json"
  "${AIF_PYTHON[@]}" - "$body" "$@" <<'PY'
import json
import sys

json.dump(
    {
        "pipelines": [
            {"id": int(pipeline_id), "authorized": True}
            for pipeline_id in sys.argv[2:]
        ]
    },
    open(sys.argv[1], "w", encoding="utf-8"),
)
PY
  aif_ado_api PATCH \
    "$ADO_ORGANIZATION/$project_encoded/_apis/pipelines/pipelinePermissions/environment/$environment_id?api-version=7.1-preview.1" \
    "$body" >/dev/null
}

aif_ensure_ado_pipeline() {
  local name="$1" yaml_path="$2"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    echo 1
    return
  fi
  local pipeline_id="" pipeline_values_output=""
  if pipeline_values_output="$(az pipelines show \
    --organization "$ADO_ORGANIZATION" \
    --project "$ADO_PROJECT" \
    --name "$name" \
    --query '[id,repository.name,process.yamlFilename,repository.defaultBranch]' \
    --output tsv 2>/dev/null)"; then
    local -a pipeline_values=()
    local expected_path actual_repository actual_path branch
    pipeline_values_output="${pipeline_values_output//$'\r'/}"
    mapfile -t pipeline_values <<< "$pipeline_values_output"
    pipeline_id="${pipeline_values[0]:-}"
    actual_repository="${pipeline_values[1]:-}"
    actual_path="${pipeline_values[2]:-}"
    branch="${pipeline_values[3]:-}"
    expected_path="${yaml_path//\\//}"
    expected_path="${expected_path#/}"
    actual_path="${actual_path//\\//}"
    actual_path="${actual_path#/}"
    branch="${branch#refs/heads/}"
    if [[ "${actual_repository,,}" != "${ADO_REPOSITORY_NAME,,}" ||
          "${actual_path,,}" != "${expected_path,,}" ||
          "${branch,,}" != "main" ]]; then
      aif_error "Existing pipeline name is bound to a different repository, branch, or YAML path: repository='$actual_repository', branch='$branch', path='$actual_path'." >&2
      exit 1
    fi
  else
    pipeline_id="$(az pipelines create \
      --organization "$ADO_ORGANIZATION" \
      --project "$ADO_PROJECT" \
      --name "$name" \
      --repository "$ADO_REPOSITORY_NAME" \
      --repository-type tfsgit \
      --branch main \
      --yaml-path "$yaml_path" \
      --skip-first-run true \
      --query id \
      --output tsv)"
  fi
  if [[ -z "$pipeline_id" ]]; then
    aif_error "Azure DevOps did not return an ID for pipeline '$name'." >&2
    exit 1
  fi
  echo "$pipeline_id"
}

aif_authorize_ado_pipeline() {
  local pipeline_id="$1" project_encoded body
  body="$AIF_STATE_DIR/permission-$pipeline_id.json"
  [[ "$AIF_DRY_RUN" != "true" ]] || return 0
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  "${AIF_PYTHON[@]}" - "$body" "$pipeline_id" <<'PY'
import json, sys
json.dump({"pipelines": [{"id": int(sys.argv[2]), "authorized": True}]}, open(sys.argv[1], "w"))
PY
  aif_ado_api PATCH \
    "$ADO_ORGANIZATION/$project_encoded/_apis/pipelines/pipelinePermissions/endpoint/$AIF_ADO_ENDPOINT_ID?api-version=7.1-preview.1" \
    "$body" >/dev/null
}

aif_wait_ado_run() {
  local pipeline_id="$1" run_id="$2" project_encoded
  [[ "$AIF_NO_WAIT" != "true" ]] || return 0
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  while true; do
    local response status result
    response="$(aif_ado_api GET \
      "$ADO_ORGANIZATION/$project_encoded/_apis/pipelines/$pipeline_id/runs/$run_id?api-version=7.1")"
    read -r status result < <(printf '%s' "$response" | "${AIF_PYTHON[@]}" -c '
import json, sys
value = json.load(sys.stdin)
print(value.get("state") or value.get("status") or "", value.get("result") or "")
')
    [[ "$status" == "completed" ]] || { sleep 20; continue; }
    if [[ "$result" != "succeeded" ]]; then
      aif_error "Azure DevOps run $run_id completed with result: ${result:-unknown}." >&2
      exit 1
    fi
    return
  done
}

aif_run_ado_pipeline() {
  local pipeline_id="$1" kind="$2" project_encoded body
  body="$AIF_STATE_DIR/run-$kind.json"
  [[ "$AIF_DRY_RUN" != "true" ]] || { aif_info "DRY-RUN: dispatch ADO $kind pipeline."; return 0; }
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  "${AIF_PYTHON[@]}" - "$body" "$kind" "$AIF_RUNNER_MODE" <<'PY'
import json, sys
kind = sys.argv[2]
request = {
    "resources": {"repositories": {"self": {"refName": "refs/heads/main"}}},
    "stagesToSkip": ["Stage", "Prod"] if kind == "common" else ["Stage_GenAI_Project", "Prod_GenAI_Project"],
}
if kind == "project":
    request["templateParameters"] = {
        "configFile": "aifactory/variables.json",
        "runnerSelection": sys.argv[3],
        "useJsonConfigOverride": True,
    }
json.dump(request, open(sys.argv[1], "w"))
PY
  local response run_id run_url
  response="$(aif_ado_api POST \
    "$ADO_ORGANIZATION/$project_encoded/_apis/pipelines/$pipeline_id/runs?api-version=7.1" \
    "$body")"
  read -r run_id run_url < <(printf '%s' "$response" | "${AIF_PYTHON[@]}" -c '
import json, sys
value = json.load(sys.stdin)
print(value["id"], value.get("_links", {}).get("web", {}).get("href", ""))
')
  aif_value "ADO $kind run" "$run_id"
  [[ -z "$run_url" ]] || aif_value "Open" "$run_url"
  aif_wait_ado_run "$pipeline_id" "$run_id"
}

aif_configure_ado() {
  aif_section "13 / Azure DevOps automation"
  aif_use_ado_tenant
  aif_ensure_ado_service_connection
}

aif_configure_github_identity() {
  aif_section "13 / GitHub deployment identity"
  [[ "$AIF_DRY_RUN" != "true" ]] || return 0
  gh api --method PUT "repos/$GITHUB_REPOSITORY/environments/dev" >/dev/null
  if [[ "$AIF_IDENTITY_MODE" == "sp" ]]; then
    if gh secret list --repo "$GITHUB_REPOSITORY" --env dev |
       awk '$1 == "AZURE_CLIENT_ID" { found=1 } END { exit !found }'; then
      gh secret delete AZURE_CLIENT_ID --repo "$GITHUB_REPOSITORY" --env dev
    fi
    AZURE_CLIENT_ID="$AIF_IDENTITY_CLIENT_ID" \
    AZURE_CLIENT_SECRET="$AIF_SP_CLIENT_SECRET" \
    AZURE_SUBSCRIPTION_ID="$AIF_DEV_SUBSCRIPTION_ID" \
    AZURE_TENANT_ID="$AIF_TENANT_ID" \
      "${AIF_PYTHON[@]}" - <<'PY' |
import json
import os
print(json.dumps({
    "clientId": os.environ["AZURE_CLIENT_ID"],
    "clientSecret": os.environ["AZURE_CLIENT_SECRET"],
    "subscriptionId": os.environ["AZURE_SUBSCRIPTION_ID"],
    "tenantId": os.environ["AZURE_TENANT_ID"],
}))
PY
        gh secret set AZURE_CREDENTIALS \
          --repo "$GITHUB_REPOSITORY" \
          --env dev
  else
    local credential_name="github-${AIF_SCALESET_SUFFIX}-dev"
    local subject="repo:$GITHUB_REPOSITORY:environment:dev"
    if ! az identity federated-credential show \
      --subscription "$AIF_IDENTITY_SUBSCRIPTION_ID" \
      --resource-group "$AIF_IDENTITY_RESOURCE_GROUP" \
      --identity-name "$AIF_IDENTITY_NAME" \
      --name "$credential_name" \
      --output none 2>/dev/null; then
      az identity federated-credential create \
        --subscription "$AIF_IDENTITY_SUBSCRIPTION_ID" \
        --resource-group "$AIF_IDENTITY_RESOURCE_GROUP" \
        --identity-name "$AIF_IDENTITY_NAME" \
        --name "$credential_name" \
        --issuer "https://token.actions.githubusercontent.com" \
        --subject "$subject" \
        --audiences api://AzureADTokenExchange \
        --output none
    fi
    gh secret set AZURE_CLIENT_ID \
      --repo "$GITHUB_REPOSITORY" \
      --env dev \
      --body "$AIF_IDENTITY_CLIENT_ID"
  fi
}

aif_publish_github_configuration() {
  [[ "$AIF_DRY_RUN" != "true" ]] || return 0
  cd "$AIF_REPO_ROOT"
  printf 'd\n\n\nn\n' | bash ./10-GH-create-or-update-github-variables.sh
  gh secret set AIFACTORY_CONFIG_JSON \
    --repo "$GITHUB_REPOSITORY" \
    --env dev \
    < aifactory/variables.json
  local stale_variable
  for stale_variable in \
    COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID \
    COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET \
    INPUT_COMMON_SPID_KEY \
    INPUT_COMMON_SP_SECRET_KEY \
    COMMON_SERVICE_PRINCIPLE_OID_KEY; do
    if gh variable get "$stale_variable" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
      gh variable delete "$stale_variable" --repo "$GITHUB_REPOSITORY"
    fi
  done
  if [[ "$AIF_SEED_PROJECT_SP" != "true" ]]; then
    for stale_variable in \
      PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID \
      PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID \
      PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S; do
      if gh variable get "$stale_variable" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
        gh variable delete "$stale_variable" --repo "$GITHUB_REPOSITORY"
      fi
    done
  fi
  if [[ "$AIF_IDENTITY_MODE" != "sp" ]]; then
    if gh secret list --repo "$GITHUB_REPOSITORY" --env dev |
       awk '$1 == "AZURE_CREDENTIALS" { found=1 } END { exit !found }'; then
      gh secret delete AZURE_CREDENTIALS \
        --repo "$GITHUB_REPOSITORY" \
        --env dev
    fi
  fi
  aif_verify_github_configuration
}

aif_verify_github_configuration() {
  local actual
  actual="$(gh variable get AZURE_SUBSCRIPTION_ID \
    --repo "$GITHUB_REPOSITORY" --env dev)"
  [[ "$actual" == "$AIF_DEV_SUBSCRIPTION_ID" ]] ||
    { aif_error "GitHub dev/AZURE_SUBSCRIPTION_ID was not updated."; exit 1; }
  actual="$(gh variable get AIFACTORY_LOCATION \
    --repo "$GITHUB_REPOSITORY" --env dev)"
  [[ "$actual" == "$AIF_LOCATION" ]] ||
    { aif_error "GitHub dev/AIFACTORY_LOCATION was not updated."; exit 1; }
  actual="$(gh variable get AIFACTORY_PREFIX --repo "$GITHUB_REPOSITORY")"
  [[ "$actual" == "$AIF_PREFIX" ]] ||
    { aif_error "GitHub AIFACTORY_PREFIX was not updated."; exit 1; }
  actual="$(gh variable get PROJECT_NUMBER --repo "$GITHUB_REPOSITORY")"
  [[ "$actual" == "$AIF_PROJECT_NUMBER" ]] ||
    { aif_error "GitHub PROJECT_NUMBER was not updated."; exit 1; }
  local -A expected_network_values=(
    [ADD_BASTION_HOST]="$AIF_ADD_BASTION"
    [ENABLE_ADMIN_VM]="$AIF_ADD_BASTION"
    [CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB]="$([[ "$AIF_TOPOLOGY" == "hs" ]] && echo true || echo false)"
    [ENABLE_PUBLIC_GENAI_ACCESS]="$AIF_ENABLE_PUBLIC_GENAI_ACCESS"
    [ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET]="$AIF_ALLOW_PUBLIC_ACCESS_BEHIND_VNET"
    [ENABLE_PUBLIC_ACCESS_WITH_PERIMETER]="$AIF_ENABLE_PUBLIC_PERIMETER"
  )
  local variable_name expected_value
  for variable_name in "${!expected_network_values[@]}"; do
    expected_value="${expected_network_values[$variable_name]}"
    actual="$(gh variable get "$variable_name" --repo "$GITHUB_REPOSITORY")"
    if [[ "$actual" != "$expected_value" ]]; then
      aif_error "GitHub $variable_name was not updated." >&2
      exit 1
    fi
  done

  local required_secrets=(
    TENANT_ID
    AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID
    AIFACTORY_CONFIG_JSON
  )
  if [[ "$AIF_IDENTITY_MODE" == "sp" ]]; then
    required_secrets+=(AZURE_CREDENTIALS)
  else
    required_secrets+=(AZURE_CLIENT_ID)
  fi
  local secret_names required_secret
  secret_names="$(gh secret list --repo "$GITHUB_REPOSITORY" --env dev | awk '{print $1}')"
  for required_secret in "${required_secrets[@]}"; do
    if ! grep -qxF "$required_secret" <<< "$secret_names"; then
      aif_error "GitHub environment secret '$required_secret' is missing." >&2
      exit 1
    fi
  done
}

aif_commit_and_push() {
  aif_section "14 / Check in automation"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: stage generated AI Factory files, commit, and push main."
    return
  fi
  cd "$AIF_REPO_ROOT"
  local paths=(
    .gitmodules .gitignore azure-enterprise-scale-ml aifactory
    aifactory-usecase-code .github
    01-aif-copy-aifactory-templates.sh
    03-ADO-YAML-bootstrap-files-no-var-overwrite.sh
    03-GH-bootstrap-files-no-env-overwrite.sh
    10-GH-create-or-update-github-variables.sh
    ADO-update-aifactory-and-run-project.sh
    GH-update-aifactory-and-run-project.sh
    ADO-create-new-aifactory-scaleset.sh
    GHA-create-new-aifactory-scaleset.sh
    ALL-create-new-aifactory-scaleset.sh
  )
  local existing=() path
  for path in "${paths[@]}"; do
    [[ -e "$path" ]] && existing+=("$path")
  done
  git add -- "${existing[@]}"
  if [[ "$AIF_ROUTE" == "gha" ]]; then
    git rm --cached --ignore-unmatch .env aifactory/variables.json >/dev/null 2>&1 || true
    local exclude_file
    exclude_file="$(git rev-parse --git-path info/exclude)"
    mkdir -p "$(dirname "$exclude_file")"
    for path in .env aifactory/variables.json; do
      grep -qxF "/$path" "$exclude_file" 2>/dev/null || printf '/%s\n' "$path" >> "$exclude_file"
    done
  fi
  if ! git diff --cached --quiet; then
    git commit \
      -m "Bootstrap AI Factory scale set $AIF_SCALESET_SUFFIX_DASH" \
      -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
  fi
  git push --set-upstream origin main
}

aif_find_github_run() {
  local workflow="$1" dispatched_at="$2"
  local run_id="" head_sha threshold
  head_sha="$(git -C "$AIF_REPO_ROOT" rev-parse HEAD)"
  threshold="$("${AIF_PYTHON[@]}" - "$dispatched_at" <<'PY'
from datetime import datetime, timedelta, timezone
import sys

value = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
print((value - timedelta(minutes=2)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"
  for _ in {1..30}; do
    run_id="$(gh run list \
      --repo "$GITHUB_REPOSITORY" \
      --workflow "$workflow" \
      --branch main \
      --event workflow_dispatch \
      --limit 10 \
      --json databaseId,createdAt,headSha \
      --jq "[.[] | select(.headSha == \"$head_sha\" and .createdAt >= \"$threshold\")][0].databaseId // \"\"")"
    [[ -n "$run_id" ]] && break
    sleep 2
  done
  [[ -n "$run_id" ]] || return 1
  echo "$run_id"
}

aif_run_github_workflow() {
  local workflow="$1" kind="$2" dispatched_at run_id
  shift 2
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: dispatch GitHub $kind workflow."
    return
  fi
  dispatched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  gh workflow run "$workflow" \
    --repo "$GITHUB_REPOSITORY" \
    --ref main \
    "$@"
  if ! run_id="$(aif_find_github_run "$workflow" "$dispatched_at")"; then
    aif_error "The $kind workflow was dispatched, but its run could not be correlated to commit $(git -C "$AIF_REPO_ROOT" rev-parse --short HEAD)." >&2
    exit 1
  fi
  aif_value "GitHub $kind run" "$run_id"
  if [[ "$AIF_NO_WAIT" != "true" ]]; then
    gh run watch "$run_id" --repo "$GITHUB_REPOSITORY" --exit-status
  fi
}

aif_ensure_ado_self_hosted_agent() {
  [[ "$AIF_RUNNER_MODE" == "self-hosted" ]] || return 0
  aif_section "16 / Self-hosted Azure Pipelines agent"

  local pool_encoded pools_file pool_id agent_encoded agents_file
  pool_encoded="$(aif_urlencode "$ADO_AGENT_POOL")"
  pools_file="$AIF_STATE_DIR/agent-pools.json"
  aif_ado_api GET \
    "$ADO_ORGANIZATION/_apis/distributedtask/pools?poolName=$pool_encoded&actionFilter=manage&api-version=7.1" \
    > "$pools_file"
  pool_id="$("${AIF_PYTHON[@]}" - "$pools_file" "$ADO_AGENT_POOL" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
pools = value.get("value", [])
if len(pools) != 1:
    raise SystemExit(
        f"Expected one manageable Azure DevOps agent pool named {sys.argv[2]!r}; "
        f"found {len(pools)}"
    )
if pools[0].get("isHosted"):
    raise SystemExit(f"Agent pool {sys.argv[2]!r} is Microsoft-hosted")
print(pools[0]["id"])
PY
)"
  pool_id="${pool_id//$'\r'/}"
  agent_encoded="$(aif_urlencode "$ADO_AGENT_NAME")"
  agents_file="$AIF_STATE_DIR/agents.json"
  aif_ado_api GET \
    "$ADO_ORGANIZATION/_apis/distributedtask/pools/$pool_id/agents?agentName=$agent_encoded&includeCapabilities=true&api-version=7.1" \
    > "$agents_file"
  if "${AIF_PYTHON[@]}" - "$agents_file" <<'PY'
import json
import sys

agents = json.load(open(sys.argv[1], encoding="utf-8")).get("value", [])
raise SystemExit(0 if len(agents) == 1 and agents[0].get("enabled") and agents[0].get("status") == "online" else 1)
PY
  then
    aif_success "Azure Pipelines agent '$ADO_AGENT_NAME' is already online in '$ADO_AGENT_POOL'."
    return
  fi

  local common_rg="${AIF_PREFIX}esml-common-${AIF_LOCATION_SHORT}-dev${AIF_SCALESET_SUFFIX_DASH}"
  aif_use_azure_tenant
  az vm show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$common_rg" \
    --name "$ADO_AGENT_NAME" \
    --output none
  local power_state
  power_state="$(az vm get-instance-view \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$common_rg" \
    --name "$ADO_AGENT_NAME" \
    --query "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]" \
    --output tsv)"
  power_state="${power_state//$'\r'/}"
  if [[ "$power_state" != "PowerState/running" ]]; then
    az vm start \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$common_rg" \
      --name "$ADO_AGENT_NAME" \
      --output none
  fi

  local packages_file package_url ado_token script_file run_command_body
  packages_file="$AIF_STATE_DIR/agent-packages.json"
  aif_ado_api GET \
    "$ADO_ORGANIZATION/_apis/distributedtask/packages/agent?platform=win-x64&top=1&api-version=7.1" \
    > "$packages_file"
  package_url="$("${AIF_PYTHON[@]}" - "$packages_file" <<'PY'
import json
import sys

packages = json.load(open(sys.argv[1], encoding="utf-8")).get("value", [])
if not packages:
    raise SystemExit("Azure DevOps returned no Windows x64 agent package")
print(packages[0]["downloadUrl"])
PY
)"
  package_url="${package_url//$'\r'/}"
  if [[ "$ADO_AUTH_METHOD" == "pat" ]]; then
    ado_token="$AZURE_DEVOPS_EXT_PAT"
  else
    ado_token="$(az account get-access-token \
      --resource "$AIF_ADO_RESOURCE" \
      --tenant "$ADO_TENANT" \
      --query accessToken \
      --output tsv)"
    ado_token="${ado_token//$'\r'/}"
  fi
  script_file="$AIF_STATE_DIR/register-ado-agent.ps1"
  run_command_body="$AIF_STATE_DIR/agent-run-command.json"
  cat > "$script_file" <<'POWERSHELL'
param(
  [Parameter(Mandatory = $true)][string] $AdoToken,
  [Parameter(Mandatory = $true)][string] $AdoUrl,
  [Parameter(Mandatory = $true)][string] $AgentPool,
  [Parameter(Mandatory = $true)][string] $AgentName,
  [Parameter(Mandatory = $true)][string] $PackageUrl
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$agentRoot = 'C:\aifactory-agent'
$archive = Join-Path $env:TEMP 'azure-pipelines-agent.zip'

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Path $agentRoot -Force | Out-Null
$configured = Test-Path (Join-Path $agentRoot '.agent')
if ($configured) {
  Get-Service -Name 'vstsagent*' -ErrorAction SilentlyContinue |
    Stop-Service -Force -ErrorAction SilentlyContinue
  Push-Location $agentRoot
  & .\config.cmd remove --unattended --auth pat --token $AdoToken
  if ($LASTEXITCODE -ne 0) {
    throw "Existing Azure Pipelines agent removal failed with exit code $LASTEXITCODE."
  }
  Pop-Location
  Get-ChildItem -LiteralPath $agentRoot -Force | Remove-Item -Recurse -Force
}

Invoke-WebRequest -Uri $PackageUrl -OutFile $archive -UseBasicParsing
Expand-Archive -LiteralPath $archive -DestinationPath $agentRoot -Force
Remove-Item -LiteralPath $archive -Force

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
  [Environment]::GetEnvironmentVariable('Path', 'User')
$missing = @('az', 'bash', 'git', 'python') | Where-Object {
  -not (Get-Command $_ -ErrorAction SilentlyContinue)
}
if ($missing -and (Get-Command choco -ErrorAction SilentlyContinue)) {
  if ($missing -contains 'git' -or $missing -contains 'bash') {
    choco install git -y --no-progress
  }
  if ($missing -contains 'az') {
    choco install azure-cli -y --no-progress
  }
  if ($missing -contains 'python') {
    choco install python -y --no-progress
  }
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
    [Environment]::GetEnvironmentVariable('Path', 'User')
}
$missing = @('az', 'bash', 'git', 'python') | Where-Object {
  -not (Get-Command $_ -ErrorAction SilentlyContinue)
}
if ($missing) {
  throw "Required agent commands are missing: $($missing -join ', ')."
}

Push-Location $agentRoot
& .\config.cmd `
  --unattended `
  --url $AdoUrl `
  --auth pat `
  --token $AdoToken `
  --pool $AgentPool `
  --agent $AgentName `
  --replace `
  --runAsService `
  --windowsLogonAccount 'NT AUTHORITY\SYSTEM' `
  --work '_work'
if ($LASTEXITCODE -ne 0) {
  throw "Azure Pipelines agent configuration failed with exit code $LASTEXITCODE."
}
Get-Service -Name 'vstsagent*' | Start-Service
Pop-Location
POWERSHELL
  ADO_TOKEN_FOR_VM="$ado_token" "${AIF_PYTHON[@]}" - \
    "$run_command_body" "$script_file" "$AIF_LOCATION" \
    "$ADO_ORGANIZATION" "$ADO_AGENT_POOL" "$ADO_AGENT_NAME" "$package_url" <<'PY'
import json
import os
import sys

with open(sys.argv[2], encoding="utf-8") as script_file:
    script = script_file.read()
body = {
    "location": sys.argv[3],
    "properties": {
        "source": {"script": script},
        "parameters": [
            {"name": "AdoUrl", "value": sys.argv[4]},
            {"name": "AgentPool", "value": sys.argv[5]},
            {"name": "AgentName", "value": sys.argv[6]},
            {"name": "PackageUrl", "value": sys.argv[7]},
        ],
        "protectedParameters": [
            {"name": "AdoToken", "value": os.environ["ADO_TOKEN_FOR_VM"]}
        ],
        "asyncExecution": False,
        "timeoutInSeconds": 1800,
        "treatFailureAsDeploymentFailure": True,
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(body, output)
PY
  unset ado_token
  chmod 600 "$run_command_body"

  local run_command_url
  run_command_url="https://management.azure.com/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$common_rg/providers/Microsoft.Compute/virtualMachines/$ADO_AGENT_NAME/runCommands/register-aifactory-ado-agent"
  az rest \
    --method put \
    --url "$run_command_url?api-version=2023-03-01" \
    --body "@$run_command_body" \
    --output none
  rm -f -- "$run_command_body"

  local execution_state="" exit_code=""
  for attempt in {1..180}; do
    local -a execution_values=()
    mapfile -t execution_values < <(az rest \
      --method get \
      --url "$run_command_url?api-version=2023-03-01&%24expand=instanceView" \
      --query '[properties.instanceView.executionState, properties.instanceView.exitCode]' \
      --output tsv 2>/dev/null | tr -d '\r' || true)
    execution_state="${execution_values[0]:-}"
    exit_code="${execution_values[1]:-}"
    case "$execution_state" in
      Succeeded) break ;;
      Failed|Canceled|TimedOut)
        aif_error "Agent registration Run Command ended as $execution_state with exit code ${exit_code:-unknown}." >&2
        exit 1
        ;;
    esac
    sleep 10
  done
  if [[ "$execution_state" != "Succeeded" || "$exit_code" != "0" ]]; then
    aif_error "Agent registration Run Command did not complete successfully." >&2
    exit 1
  fi

  for attempt in {1..60}; do
    aif_ado_api GET \
      "$ADO_ORGANIZATION/_apis/distributedtask/pools/$pool_id/agents?agentName=$agent_encoded&includeCapabilities=true&api-version=7.1" \
      > "$agents_file"
    if "${AIF_PYTHON[@]}" - "$agents_file" <<'PY'
import json
import sys

agents = json.load(open(sys.argv[1], encoding="utf-8")).get("value", [])
raise SystemExit(0 if len(agents) == 1 and agents[0].get("enabled") and agents[0].get("status") == "online" else 1)
PY
    then
      az rest \
        --method delete \
        --url "$run_command_url?api-version=2023-03-01" \
        --output none
      aif_success "Azure Pipelines agent '$ADO_AGENT_NAME' is online in '$ADO_AGENT_POOL'."
      return
    fi
    sleep 10
  done
  aif_error "Azure Pipelines agent '$ADO_AGENT_NAME' did not become online." >&2
  exit 1
}

aif_validate_simple_new_scope() {
  [[ "${AIF_SIMPLE_MODE:-false}" == "true" ]] || return 0
  local resource_group
  for resource_group in "$AIF_BOOTSTRAP_RESOURCE_GROUP" \
    "${AIF_PREFIX}esml-common-${AIF_LOCATION_SHORT}-dev${AIF_SCALESET_SUFFIX_DASH}"; do
    if [[ "$(az group exists --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --name "$resource_group" --output tsv | tr -d '\r')" == "true" ]]; then
      aif_error "Simple Mode requires a fresh scale set; '$resource_group' already exists. Use Advanced Mode to inspect/resume, or choose a new prefix." >&2
      exit 1
    fi
  done
}

aif_prepare_simple_integrated_subnets() {
  local existing_file="$AIF_STATE_DIR/simple-existing-subnets.json" plan
  az network vnet subnet list \
    --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
    --resource-group "$AIF_HUB_RESOURCE_GROUP" \
    --vnet-name "$AIF_HUB_VNET_NAME" \
    --output json > "$existing_file"
  plan="$("${AIF_PYTHON[@]}" "$AIF_SCALESET_LIB_DIR/aifactory_scaleset_config.py" \
    --simple-mode-hub-subnets "$existing_file")"
  AIF_SIMPLE_GATEWAY_SUBNET="$("${AIF_PYTHON[@]}" -c 'import json,sys; print(json.loads(sys.argv[1])["GatewaySubnet"])' "$plan" | tr -d '\r')"
  AIF_SIMPLE_RESOLVER_SUBNET="$("${AIF_PYTHON[@]}" -c 'import json,sys; print(json.loads(sys.argv[1])["snet-dns-private-resolver"])' "$plan" | tr -d '\r')"
}

aif_ensure_simple_hub_artifacts() {
  AIF_SIMPLE_COMMON_READY="true"
  aif_prepare_hub_dns
  aif_ensure_private_dns_policy_assignment
  az network ip-group create \
    --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
    --resource-group "$AIF_HUB_RESOURCE_GROUP" \
    --name "ipg-aifactory-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}" \
    --location "$AIF_LOCATION" \
    --ip-addresses "$AIF_DEV_VNET_CIDR" "$AIF_VPN_CLIENT_CIDR" \
    --tags CostCenter="$AIF_COST_CENTER" Purpose=AIFactoryAccessInventory \
    --output none
}

aif_ensure_private_network_access() {
  local common_rg common_vnet common_subnet
  common_rg="${AIF_PREFIX}esml-common-${AIF_LOCATION_SHORT}-dev${AIF_SCALESET_SUFFIX_DASH}"
  common_vnet="vnt-esmlcmn-${AIF_LOCATION_SHORT}-dev-001"
  common_subnet="snet-esml-cmn-001"
  aif_use_azure_tenant
  local spoke_vnet_id
  spoke_vnet_id="$(az network vnet show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$common_rg" \
    --name "$common_vnet" \
    --query id \
    --output tsv)"
  spoke_vnet_id="${spoke_vnet_id//$'\r'/}"

  if [[ "$AIF_TOPOLOGY" == "hs" || "$AIF_ACCESS_HUB_MODE" == "external" ]]; then
    local hub_vnet_id
    hub_vnet_id="$(az network vnet show \
      --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
      --resource-group "$AIF_HUB_VNET_RESOURCE_GROUP" \
      --name "$AIF_HUB_VNET_NAME" \
      --query id \
      --output tsv)"
    hub_vnet_id="${hub_vnet_id//$'\r'/}"

    if az network vnet peering show \
      --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
      --resource-group "$AIF_HUB_VNET_RESOURCE_GROUP" \
      --vnet-name "$AIF_HUB_VNET_NAME" \
      --name "hub-to-${AIF_PREFIX%-}-dev-${AIF_SCALESET_SUFFIX}" \
      --output none 2>/dev/null; then
      az network vnet peering update \
        --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
        --resource-group "$AIF_HUB_VNET_RESOURCE_GROUP" \
        --vnet-name "$AIF_HUB_VNET_NAME" \
        --name "hub-to-${AIF_PREFIX%-}-dev-${AIF_SCALESET_SUFFIX}" \
        --allow-vnet-access true \
        --allow-forwarded-traffic true \
        --allow-gateway-transit true \
        --output none
    else
      az network vnet peering create \
        --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
        --resource-group "$AIF_HUB_VNET_RESOURCE_GROUP" \
        --vnet-name "$AIF_HUB_VNET_NAME" \
        --name "hub-to-${AIF_PREFIX%-}-dev-${AIF_SCALESET_SUFFIX}" \
        --remote-vnet "$spoke_vnet_id" \
        --allow-vnet-access true \
        --allow-forwarded-traffic true \
        --allow-gateway-transit true \
        --output none
    fi
    if az network vnet peering show \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$common_rg" \
      --vnet-name "$common_vnet" \
      --name "spoke-to-aifactory-access-hub" \
      --output none 2>/dev/null; then
      az network vnet peering update \
        --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
        --resource-group "$common_rg" \
        --vnet-name "$common_vnet" \
        --name "spoke-to-aifactory-access-hub" \
        --allow-vnet-access true \
        --allow-forwarded-traffic true \
        --use-remote-gateways true \
        --output none
    else
      az network vnet peering create \
        --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
        --resource-group "$common_rg" \
        --vnet-name "$common_vnet" \
        --name "spoke-to-aifactory-access-hub" \
        --remote-vnet "$hub_vnet_id" \
        --allow-vnet-access true \
        --allow-forwarded-traffic true \
        --use-remote-gateways true \
        --output none
    fi

    local zone link_name
    link_name="link-${AIF_PREFIX%-}-dev-${AIF_SCALESET_SUFFIX}"
    while IFS= read -r zone; do
      [[ -n "$zone" ]] || continue
      if ! az network private-dns link vnet show \
        --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
        --resource-group "$AIF_HUB_RESOURCE_GROUP" \
        --zone-name "$zone" \
        --name "$link_name" \
        --output none 2>/dev/null; then
        az network private-dns link vnet create \
          --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
          --resource-group "$AIF_HUB_RESOURCE_GROUP" \
          --zone-name "$zone" \
          --name "$link_name" \
          --virtual-network "$spoke_vnet_id" \
          --registration-enabled false \
          --output none
      fi
    done < <(az network private-dns zone list \
      --subscription "$AIF_HUB_SUBSCRIPTION_ID" \
      --resource-group "$AIF_HUB_RESOURCE_GROUP" \
      --query '[].name' \
      --output tsv)
  elif [[ "$AIF_ACCESS_HUB_MODE" == "integrated" ]]; then
    if [[ "${AIF_SIMPLE_MODE:-false}" == "true" ]]; then
      aif_prepare_simple_integrated_subnets
      aif_ensure_bastion_developer "$AIF_DEV_SUBSCRIPTION_ID" "$common_rg" "$common_vnet"
      aif_ensure_simple_hub_artifacts
    fi
    aif_ensure_hub_dns_forwarder integrated
    if [[ "$AIF_SETUP_HUB_ACCESS" == "true" ]]; then
      aif_ensure_vpn_access_hub integrated
    fi
  fi
  if [[ "${AIF_SIMPLE_MODE:-false}" != "true" ]]; then
    aif_ensure_bastion_developer \
      "$AIF_DEV_SUBSCRIPTION_ID" \
      "$common_rg" \
      "$common_vnet"
  fi

  local seeding_kv_id seeding_pe_name zone_id
  seeding_kv_id="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$AIF_SEEDING_RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$AIF_SEEDING_KEYVAULT_NAME"
  seeding_pe_name="pend-${AIF_SEEDING_KEYVAULT_NAME}-to-${common_vnet}"
  if ! az network private-endpoint show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$common_rg" \
    --name "$seeding_pe_name" \
    --output none 2>/dev/null; then
    az network private-endpoint create \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$common_rg" \
      --name "$seeding_pe_name" \
      --location "$AIF_LOCATION" \
      --vnet-name "$common_vnet" \
      --subnet "$common_subnet" \
      --private-connection-resource-id "$seeding_kv_id" \
      --group-id vault \
      --connection-name "${seeding_pe_name}-connection" \
      --output none
  fi
  if [[ "$AIF_TOPOLOGY" == "hs" || "$AIF_ACCESS_HUB_MODE" == "external" ]]; then
    zone_id="/subscriptions/$AIF_HUB_SUBSCRIPTION_ID/resourceGroups/$AIF_HUB_RESOURCE_GROUP/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
  else
    zone_id="/subscriptions/$AIF_DEV_SUBSCRIPTION_ID/resourceGroups/$common_rg/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
  fi
  if ! az network private-endpoint dns-zone-group show \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$common_rg" \
    --endpoint-name "$seeding_pe_name" \
    --name aifactory-seeding-keyvault \
    --output none 2>/dev/null; then
    az network private-endpoint dns-zone-group create \
      --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
      --resource-group "$common_rg" \
      --endpoint-name "$seeding_pe_name" \
      --name aifactory-seeding-keyvault \
      --zone-name vaultcore \
      --private-dns-zone "$zone_id" \
      --output none
  fi
  az keyvault update \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --resource-group "$AIF_SEEDING_RESOURCE_GROUP" \
    --name "$AIF_SEEDING_KEYVAULT_NAME" \
    --public-network-access Disabled \
    --output none
  aif_configure_windows_vpn_client
  aif_success "Private access infrastructure and seeding Key Vault endpoint are ready. VPN connection is a separate user action."
}

aif_deploy_ado() {
  aif_use_ado_tenant
  local common_pipeline project_pipeline
  for environment_name in Dev Stage Prod; do
    aif_ensure_ado_environment "$environment_name"
  done
  common_pipeline="$(aif_ensure_ado_pipeline \
    "infra-aifactory-common-${AIF_PREFIX%-}-${AIF_SCALESET_SUFFIX}" \
    aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/infra-aifactory-common.yaml)"
  project_pipeline="$(aif_ensure_ado_pipeline \
    "infra-project-genai-${AIF_PREFIX%-}-${AIF_SCALESET_SUFFIX}" \
    aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml)"
  aif_authorize_ado_pipeline "$common_pipeline"
  aif_authorize_ado_pipeline "$project_pipeline"
  for environment_name in Dev Stage Prod; do
    aif_authorize_ado_environment \
      "$environment_name" \
      "$common_pipeline" \
      "$project_pipeline"
  done
  aif_run_ado_pipeline "$common_pipeline" common
  if [[ "$AIF_NO_WAIT" == "true" ]]; then
    aif_warn "Common deployment was dispatched. Re-run without --no-wait to verify it and start the project."
    return 0
  fi
  aif_verify_common_resource_group
  aif_ensure_private_network_access
  aif_ensure_ado_self_hosted_agent
  aif_run_ado_pipeline "$project_pipeline" project
}

aif_deploy_github() {
  aif_run_github_workflow infra-common.yml common \
    --raw-field deploy_dev=true \
    --raw-field deploy_stage=false \
    --raw-field deploy_prod=false
  if [[ "$AIF_NO_WAIT" == "true" ]]; then
    aif_warn "Common deployment was dispatched. Re-run without --no-wait to verify it and start the project."
    return 0
  fi
  aif_verify_common_resource_group
  aif_ensure_private_network_access
  aif_run_github_workflow infra-project.yml project \
    --raw-field environment=dev \
    --raw-field config_file=aifactory/variables.json \
    --raw-field runner_selection=github-hosted \
    --raw-field self_hosted_runner_label=
}

aif_verify_common_resource_group() {
  [[ "$AIF_NO_WAIT" != "true" && "$AIF_DRY_RUN" != "true" ]] || return 0
  local common_rg="${AIF_PREFIX}esml-common-${AIF_LOCATION_SHORT}-dev${AIF_SCALESET_SUFFIX_DASH}"
  if [[ "$(az group exists \
    --subscription "$AIF_DEV_SUBSCRIPTION_ID" \
    --name "$common_rg" \
    --output tsv)" != "true" ]]; then
    aif_error "Common pipeline completed but expected resource group '$common_rg' was not found." >&2
    exit 1
  fi
  aif_success "Common resource group '$common_rg' exists."
}

aif_scaleset_main() {
  AIF_ROUTE="$1"
  AIF_ENTRYPOINT="$2"
  shift 2
  AIF_REPO_ROOT="${AIFACTORY_REPO_ROOT:-}"
  AIF_DRY_RUN="${AIF_DRY_RUN:-false}"
  AIF_PREPARE_ONLY="${AIF_PREPARE_ONLY:-false}"
  AIF_NO_WAIT="${AIF_NO_WAIT:-false}"
  AIF_NON_INTERACTIVE="${AIF_NON_INTERACTIVE:-false}"
  AIF_YES="${AIF_YES:-false}"
  AIF_STASH_CREATED="false"
  while (( $# )); do
    case "$1" in
      --repo-root)
        [[ $# -ge 2 ]] || { aif_scaleset_usage; exit 1; }
        AIF_REPO_ROOT="$2"
        shift 2
        ;;
      --dry-run) AIF_DRY_RUN="true"; shift ;;
      --prepare-only) AIF_PREPARE_ONLY="true"; shift ;;
      --no-wait) AIF_NO_WAIT="true"; shift ;;
      --non-interactive) AIF_NON_INTERACTIVE="true"; shift ;;
      --yes) AIF_YES="true"; shift ;;
      --help|-h) aif_scaleset_usage; return ;;
      *) aif_error "Unknown option: $1"; aif_scaleset_usage; exit 1 ;;
    esac
  done

  local entry_dir ui_library
  entry_dir="$(cd "$(dirname "$AIF_ENTRYPOINT")" && pwd)"
  for ui_library in \
    "$entry_dir/ui/terminal.sh" \
    "$entry_dir/azure-enterprise-scale-ml/bootstrap/ui/terminal.sh" \
    "$entry_dir/../ui/terminal.sh"; do
    [[ ! -f "$ui_library" ]] || break
  done
  if [[ ! -f "$ui_library" ]]; then
    printf 'ERROR: bootstrap/ui/terminal.sh is required.\n' >&2
    exit 1
  fi
  # shellcheck source=../ui/terminal.sh
  source "$ui_library"
  aif_banner "${AIF_ROUTE^^} / CREATE AI FACTORY SCALE SET" \
    "Prepare subscription, identity, access, automation, common resources, and project."

  aif_require_command bash
  aif_require_command git
  aif_require_command az
  aif_require_command realpath
  [[ "$AIF_ROUTE" != "gha" ]] || aif_require_command gh
  aif_python
  aif_simple_mode_defaults
  if [[ "$AIF_ROUTE" == "gha" && "${AIF_SIMPLE_MODE:-false}" == "true" ]]; then
    if ! gh auth status >/dev/null 2>&1; then
      aif_error "GitHub CLI is not authenticated. Sign in explicitly before Create." >&2
      exit 1
    fi
  fi
  aif_resolve_repo_root
  if [[ "${AIF_SIMPLE_MODE:-false}" == "true" && -d "$AIF_REPO_ROOT" &&
        -n "$(find "$AIF_REPO_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    aif_error "Simple Mode requires a new empty target folder; existing repositories are never modified." >&2
    exit 1
  fi
  local state_parent="$HOME/.aifactory-create-state"
  mkdir -p "$state_parent"
  AIF_STATE_DIR="$(mktemp -d "$state_parent/run.XXXXXX")"
  trap aif_cleanup EXIT INT TERM
  aif_value "Target repo" "$AIF_REPO_ROOT"

  aif_collect_answers
  aif_confirm_summary
  aif_ensure_azure_login
  aif_validate_admin_vm_size
  [[ "$AIF_ROUTE" != "ado" ]] || aif_ensure_ado_auth
  aif_ensure_target_repository
  aif_sync_submodule_and_templates
  aif_validate_simple_new_scope
  aif_register_resource_providers "$AIF_DEV_SUBSCRIPTION_ID"
  aif_use_azure_tenant
  aif_ensure_first_party_enterprise_apps
  aif_prepare_external_access_hub
  aif_prepare_hub_dns
  aif_ensure_bootstrap_identity
  aif_ensure_seeding_keyvault
  aif_ensure_team_group
  aif_seed_optional_project_sp
  aif_ensure_private_dns_policy_assignment
  if [[ "$AIF_ROUTE" == "ado" ]]; then
    aif_configure_ado
  else
    AIF_OIDC_CLIENT_ID=""
    [[ "$AIF_IDENTITY_MODE" == "sp" ]] || AIF_OIDC_CLIENT_ID="$AIF_IDENTITY_CLIENT_ID"
    aif_configure_github_identity
  fi
  aif_write_state_and_configure
  [[ "$AIF_ROUTE" != "gha" ]] || aif_publish_github_configuration
  aif_commit_and_push

  if [[ "$AIF_PREPARE_ONLY" == "true" ]]; then
    aif_complete "AI Factory prerequisites and automation are prepared."
    return
  fi
  aif_section "15 / Common and project deployment"
  if [[ "$AIF_ROUTE" == "ado" ]]; then
    aif_deploy_ado
  else
    aif_deploy_github
  fi
  if [[ "$AIF_STASH_CREATED" == "true" ]]; then
    aif_warn "Pre-existing work remains protected in the latest target-repository stash."
  fi
  aif_complete "AI Factory DEV scale set and project deployment completed."
}
