#!/usr/bin/env bash

set -euo pipefail

readonly AIF_SUBMODULE_URL="https://github.com/jostrm/azure-enterprise-scale-ml"
readonly AIF_SUBMODULE_BRANCH="${AIF_SUBMODULE_BRANCH:-release/v1.24}"
readonly AIF_ADO_RESOURCE="https://app.vssps.visualstudio.com/"

aif_scaleset_usage() {
  cat <<'EOF'
Usage: ADO-create-new-aifactory-scaleset.sh [options]
       GHA-create-new-aifactory-scaleset.sh [options]

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
EOF
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
  aif_prompt_choice "$variable_name" "$prompt" "$default_value" "y yes n no"
  case "$output" in
    y|yes) output="true" ;;
    *) output="false" ;;
  esac
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
if network.version != 4 or network.prefixlen > 18:
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

aif_resolve_repo_root() {
  if [[ -n "$AIF_REPO_ROOT" ]]; then
    AIF_REPO_ROOT="$(cd "$AIF_REPO_ROOT" 2>/dev/null && pwd)"
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
  [[ "$current_user" == *@* ]] || current_user=""
  current_repo="$(aif_current_origin_slug)"

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
  AIF_IP_ALLOWLIST="${AIF_IP_ALLOWLIST:-}"
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

  aif_section "01 / Architecture and networking"
  aif_prompt_choice AIF_TOPOLOGY \
    "Topology: standalone (s) or hub/spoke with central DNS (hs)" "s" "s hs"
  aif_prompt_choice AIF_NETWORK_MODE \
    "Networking: private (priv), hybrid/IP allowlist (h), or public perimeter (pub)" \
    "priv" "priv h pub"
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
  aif_prompt_value AIF_DEV_VNET_CIDR "DEV vNet CIDR (/16 or /18)" "172.16.0.0/18"
  if ! aif_validate_cidr "$AIF_DEV_VNET_CIDR"; then
    aif_error "DEV vNet CIDR must be a canonical IPv4 /16-/18 range." >&2
    exit 1
  fi

  if [[ "$AIF_NETWORK_MODE" == "h" ]]; then
    aif_prompt_value AIF_IP_ALLOWLIST "Client IPv4 address/range allowlist (comma-separated)" ""
    if ! aif_validate_ip_allowlist "$AIF_IP_ALLOWLIST"; then
      aif_error "The client IP allowlist contains an invalid IPv4 address or range." >&2
      exit 1
    fi
  fi

  AIF_HUB_SUBSCRIPTION_ID="${AIF_HUB_SUBSCRIPTION_ID:-}"
  AIF_HUB_RESOURCE_GROUP="${AIF_HUB_RESOURCE_GROUP:-}"
  AIF_HUB_VNET_NAME="${AIF_HUB_VNET_NAME:-}"
  AIF_HUB_VNET_RESOURCE_GROUP="${AIF_HUB_VNET_RESOURCE_GROUP:-}"
  AIF_HUB_DNS_POLICY_READY="${AIF_HUB_DNS_POLICY_READY:-}"
  if [[ "$AIF_TOPOLOGY" == "hs" ]]; then
    aif_prompt_value AIF_HUB_SUBSCRIPTION_ID "Hub subscription ID" ""
    aif_prompt_value AIF_HUB_RESOURCE_GROUP "Hub private-DNS resource group" ""
    aif_prompt_value AIF_HUB_VNET_NAME "Hub vNet name" ""
    aif_prompt_value AIF_HUB_VNET_RESOURCE_GROUP \
      "Hub vNet resource group" "$AIF_HUB_RESOURCE_GROUP"
    aif_prompt_yes_no AIF_HUB_DNS_POLICY_READY \
      "Is the private-endpoint DNS-zone-group policy assigned to the landing-zone subscriptions? (y/N)" \
      "n"
    if [[ "$AIF_HUB_DNS_POLICY_READY" != "true" ]]; then
      aif_error "Hub/spoke requires the central private-DNS policy before deployment." >&2
      aif_info "See documentation/v2/10-19/14-networking-privateDNS.md." >&2
      exit 1
    fi
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

  aif_prompt_value AIF_PREFIX "AI Factory naming prefix" "aif-"
  AIF_PREFIX="${AIF_PREFIX,,}"
  [[ "$AIF_PREFIX" == *- ]] || AIF_PREFIX="${AIF_PREFIX}-"
  if [[ ! "$AIF_PREFIX" =~ ^[a-z0-9-]{2,16}$ ]]; then
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

  local prefix_compact="${AIF_PREFIX//-/}"
  AIF_BOOTSTRAP_RESOURCE_GROUP="${AIF_BOOTSTRAP_RESOURCE_GROUP:-rg-${AIF_PREFIX%-}bootstrap-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}}"
  AIF_DEPLOYMENT_IDENTITY_NAME="${AIF_DEPLOYMENT_IDENTITY_NAME:-id-${AIF_PREFIX%-}deploy-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}}"
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
    elif [[ "${ADO_TENANT,,}" != "${AIF_TENANT_ID,,}" ]]; then
      aif_error "Cross-tenant Azure DevOps requires PAT authentication." >&2
      exit 1
    fi
    aif_prompt_value ADO_SERVICE_CONNECTION_NAME "Azure DevOps service connection name" \
      "$ADO_SERVICE_CONNECTION_NAME"
    case "$ADO_ORGANIZATION" in
      http://*|https://*) ;;
      *) ADO_ORGANIZATION="https://dev.azure.com/$ADO_ORGANIZATION" ;;
    esac
    ADO_ORGANIZATION="${ADO_ORGANIZATION%/}"
  else
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
  if [[ "$AIF_TOPOLOGY" == "s" && "$AIF_NETWORK_MODE" == "priv" ]]; then
    aif_prompt_yes_no AIF_ADD_BASTION \
      "Create Azure Bastion for private standalone access? (Y/n)" "y"
  else
    AIF_ADD_BASTION="false"
  fi

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
  if [[ "$current_tenant" != "$AIF_TENANT_ID" ]]; then
    aif_mutate az login --tenant "$AIF_TENANT_ID" --allow-no-subscriptions
  fi
  if [[ "$AIF_DRY_RUN" != "true" ]]; then
    az account show --subscription "$AIF_DEV_SUBSCRIPTION_ID" --output none
    if [[ "$AIF_TOPOLOGY" == "hs" ]]; then
      az account show --subscription "$AIF_HUB_SUBSCRIPTION_ID" --output none
    fi
  fi
  aif_success "Azure tenant and subscription access confirmed."
}

aif_ensure_ado_auth() {
  [[ "$AIF_ROUTE" == "ado" ]] || return 0
  if [[ "$ADO_AUTH_METHOD" == "pat" ]]; then
    return 0
  fi
  if az account get-access-token \
    --resource "$AIF_ADO_RESOURCE" \
    --tenant "$ADO_TENANT" \
    --output none 2>/dev/null; then
    return 0
  fi
  if [[ "$AIF_NON_INTERACTIVE" == "true" ]]; then
    aif_error "No Microsoft Entra token is available for Azure DevOps tenant '$ADO_TENANT'." >&2
    aif_info "Sign in first or rerun with ADO_AUTH_METHOD=pat and AZURE_DEVOPS_EXT_PAT." >&2
    exit 1
  fi
  aif_mutate az login --tenant "$ADO_TENANT" --allow-no-subscriptions
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
    Microsoft.MachineLearningServices Microsoft.Search Microsoft.DocumentDB
    Microsoft.ContainerRegistry Microsoft.App Microsoft.BotService
    Microsoft.AppConfiguration Microsoft.Web
    Microsoft.OperationalInsights microsoft.insights
  )
  local provider
  aif_info "Registering AI Factory resource providers in $subscription_id."
  for provider in "${providers[@]}"; do
    if [[ "$AIF_DRY_RUN" == "true" ]]; then
      aif_info "DRY-RUN: az provider register --namespace $provider --subscription $subscription_id"
    else
      az provider register \
        --namespace "$provider" \
        --subscription "$subscription_id" \
        --output none \
        --only-show-errors || aif_warn "Provider registration request failed: $provider"
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

aif_ensure_role_assignment() {
  local principal_id="$1" principal_type="$2" role="$3" scope="$4"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: assign '$role' to $principal_id at $scope."
    return
  fi
  local existing
  existing="$(az role assignment list \
    --assignee "$principal_id" \
    --scope "$scope" \
    --role "$role" \
    --query 'length(@)' \
    --output tsv)"
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
      ado_coordinates="$(aif_current_ado_coordinates)"
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

  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    aif_info "DRY-RUN: synchronize initial route templates."
    return
  fi

  cp azure-enterprise-scale-ml/bootstrap/01-aif-copy-aifactory-templates.sh .
  cp azure-enterprise-scale-ml/bootstrap/ADO-update-aifactory-and-run-project.sh .
  cp azure-enterprise-scale-ml/bootstrap/GH-update-aifactory-and-run-project.sh .
  cp azure-enterprise-scale-ml/bootstrap/ADO-create-new-aifactory-scaleset.sh .
  cp azure-enterprise-scale-ml/bootstrap/GHA-create-new-aifactory-scaleset.sh .
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
      mapfile -t identity_values <<< "$identity_values_output"
      read -r AIF_IDENTITY_CLIENT_ID AIF_IDENTITY_PRINCIPAL_ID <<< "${identity_values[0]}"
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
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    AIF_TEAM_GROUP_ID="00000000-0000-0000-0000-000000000004"
    aif_info "DRY-RUN: create/verify group '$AIF_TEAM_GROUP_NAME' and add '$AIF_TEAM_MEMBER_EMAIL'."
    return
  fi
  local group_ids_output
  group_ids_output="$(az ad group list \
    --filter "displayName eq '$AIF_TEAM_GROUP_NAME'" \
    --query '[].id' \
    --output tsv)"
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
  fi
  local member_id
  member_id="$(az ad user show --id "$AIF_TEAM_MEMBER_EMAIL" --query id --output tsv)"
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
  [[ "$AIF_TOPOLOGY" == "hs" ]] || return 0
  aif_section "12 / Hub private DNS"
  local private_dns_zones
  private_dns_zones="$("${AIF_PYTHON[@]}" - "$AIF_LOCATION" <<'PY'
import json
import sys

location = sys.argv[1]
names = [
    "privatelink.blob.core.windows.net",
    "privatelink.file.core.windows.net",
    "privatelink.dfs.core.windows.net",
    "privatelink.queue.core.windows.net",
    "privatelink.table.core.windows.net",
    "privatelink.azurecr.io",
    f"{location}.data.privatelink.azurecr.io",
    "privatelink.vaultcore.azure.net",
    "privatelink.api.azureml.ms",
    "privatelink.notebooks.azure.net",
    "privatelink.datafactory.azure.net",
    "privatelink.adf.azure.com",
    "privatelink.openai.azure.com",
    "privatelink.search.windows.net",
    "privatelink.azurewebsites.net",
    "privatelink.documents.azure.com",
    "privatelink.cognitiveservices.azure.com",
    "privatelink.azuredatabricks.net",
    "privatelink.servicebus.windows.net",
    "privatelink.eventgrid.azure.net",
    "privatelink.monitor.azure.com",
    "privatelink.oms.opinsights.azure.com",
    "privatelink.ods.opinsights.azure.com",
    "privatelink.agentsvc.azure-automation.net",
    "privatelink.services.ai.azure.com",
    f"privatelink.{location}.azurecontainerapps.io",
    "privatelink.redis.cache.windows.net",
    "privatelink.postgres.database.azure.com",
    "privatelink.database.windows.net",
    "privatelink.mongo.cosmos.azure.com",
    "privatelink.azure-api.net",
]
print(json.dumps([{"name": name} for name in names], separators=(",", ":")))
PY
)"
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

aif_write_state_and_configure() {
  local state_file="$AIF_STATE_DIR/config.json"
  "${AIF_PYTHON[@]}" - "$state_file" \
    "$AIF_TOPOLOGY" "$AIF_NETWORK_MODE" "$AIF_TENANT_ID" \
    "$AIF_DEV_SUBSCRIPTION_ID" "$AIF_STAGE_SUBSCRIPTION_ID" "$AIF_PROD_SUBSCRIPTION_ID" \
    "$AIF_LOCATION" "$AIF_LOCATION_SHORT" "$AIF_DEV_VNET_CIDR" \
    "$AIF_PREFIX" "$AIF_SCALESET_SUFFIX_DASH" "$AIF_PROJECT_NUMBER" \
    "$AIF_TEAM_GROUP_ID" "$AIF_TEAM_GROUP_NAME" "$AIF_IP_ALLOWLIST" \
    "$AIF_SEEDING_SUBSCRIPTION_ID" "$AIF_SEEDING_RESOURCE_GROUP" "$AIF_SEEDING_KEYVAULT_NAME" \
    "$AIF_ENABLE_PUBLIC_GENAI_ACCESS" "$AIF_ALLOW_PUBLIC_ACCESS_BEHIND_VNET" \
    "$AIF_ENABLE_PUBLIC_PERIMETER" "$AIF_ADD_BASTION" \
    "$AIF_HUB_SUBSCRIPTION_ID" "$AIF_HUB_RESOURCE_GROUP" \
    "$AIF_PROJECT_SP_APP_SECRET" "$AIF_PROJECT_SP_OID_SECRET" "$AIF_PROJECT_SP_SECRET_SECRET" \
    "${AIF_AZURE_ML_PRINCIPAL_ID:-}" \
    "${ADO_TENANT:-}" "${ADO_SERVICE_CONNECTION_NAME:-}" \
    "${GITHUB_REPOSITORY:-}" "${AIF_OIDC_CLIENT_ID:-}" <<'PY'
import json
import sys

keys = (
    "topology", "network_mode", "tenant_id",
    "dev_subscription_id", "stage_subscription_id", "prod_subscription_id",
    "location", "location_short", "dev_vnet_cidr",
    "prefix", "scaleset_suffix", "project_number",
    "team_group_id", "team_group_name", "ip_allowlist",
    "seeding_subscription_id", "seeding_resource_group", "seeding_keyvault_name",
    "enable_public_genai_access", "allow_public_access_behind_vnet",
    "enable_public_perimeter", "add_bastion",
    "hub_subscription_id", "hub_resource_group",
    "project_sp_app_secret", "project_sp_oid_secret", "project_sp_secret_secret",
    "azure_ml_principal_id", "ado_tenant_id", "ado_service_connection",
    "github_repository", "oidc_client_id",
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
}

aif_urlencode() {
  "${AIF_PYTHON[@]}" -c \
    'import sys; from urllib.parse import quote; print(quote(sys.argv[1], safe=""))' "$1"
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
    read -r existing_issuer existing_subject <<< "$existing_values"
    if [[ "$existing_issuer" != "$issuer" || "$existing_subject" != "$subject" ]]; then
      aif_error "Federated credential '$credential_name' exists with a different issuer or subject." >&2
      exit 1
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

aif_ensure_ado_pipeline() {
  local name="$1" yaml_path="$2"
  if [[ "$AIF_DRY_RUN" == "true" ]]; then
    echo 1
    return
  fi
  local pipeline_id pipeline_json=""
  if pipeline_json="$(az pipelines show \
    --organization "$ADO_ORGANIZATION" \
    --project "$ADO_PROJECT" \
    --name "$name" \
    --output json 2>/dev/null)"; then
    local pipeline_file="$AIF_STATE_DIR/pipeline-$name.json"
    printf '%s' "$pipeline_json" > "$pipeline_file"
    pipeline_id="$("${AIF_PYTHON[@]}" - \
      "$pipeline_file" "$ADO_REPOSITORY_NAME" "$yaml_path" <<'PY'
import json
import sys
from pathlib import PurePosixPath

expected_repository = sys.argv[2].lower()
expected_path = str(PurePosixPath(sys.argv[3].replace("\\", "/"))).lstrip("/").lower()
pipeline = json.load(open(sys.argv[1], encoding="utf-8"))
repository = pipeline.get("repository") or {}
process = pipeline.get("process") or pipeline.get("configuration") or {}
actual_repository = str(repository.get("name") or "").lower()
actual_path = str(
    process.get("yamlFilename") or process.get("path") or ""
).replace("\\", "/").lstrip("/").lower()
branch = str(repository.get("defaultBranch") or "").removeprefix("refs/heads/").lower()
if actual_repository != expected_repository or actual_path != expected_path or branch != "main":
    raise SystemExit(
        "Existing pipeline name is bound to a different repository, branch, or YAML path: "
        f"repository={actual_repository!r}, branch={branch!r}, path={actual_path!r}"
    )
print(pipeline["id"])
PY
)"
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
  echo "$pipeline_id"
}

aif_authorize_ado_pipeline() {
  local pipeline_id="$1" project_encoded body="$AIF_STATE_DIR/permission-$pipeline_id.json"
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
  local pipeline_id="$1" kind="$2" project_encoded body="$AIF_STATE_DIR/run-$kind.json"
  [[ "$AIF_DRY_RUN" != "true" ]] || { aif_info "DRY-RUN: dispatch ADO $kind pipeline."; return 0; }
  project_encoded="$(aif_urlencode "$ADO_PROJECT")"
  "${AIF_PYTHON[@]}" - "$body" "$kind" <<'PY'
import json, sys
kind = sys.argv[2]
request = {
    "resources": {"repositories": {"self": {"refName": "refs/heads/main"}}},
    "stagesToSkip": ["Stage", "Prod"] if kind == "common" else ["Stage_GenAI_Project", "Prod_GenAI_Project"],
}
if kind == "project":
    request["templateParameters"] = {
        "configFile": "aifactory/variables.json",
        "runnerSelection": "microsoft-hosted",
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

aif_deploy_ado() {
  local common_pipeline project_pipeline
  for environment_name in Dev Stage Prod; do
    aif_ensure_ado_environment "$environment_name"
  done
  common_pipeline="$(aif_ensure_ado_pipeline \
    infra-aifactory-common \
    aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/infra-aifactory-common.yaml)"
  project_pipeline="$(aif_ensure_ado_pipeline \
    infra-project-genai \
    aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml)"
  aif_authorize_ado_pipeline "$common_pipeline"
  aif_authorize_ado_pipeline "$project_pipeline"
  aif_run_ado_pipeline "$common_pipeline" common
  if [[ "$AIF_NO_WAIT" == "true" ]]; then
    aif_warn "Common deployment was dispatched. Re-run without --no-wait to verify it and start the project."
    return 0
  fi
  aif_verify_common_resource_group
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
  [[ "$AIF_ROUTE" != "gha" ]] || aif_require_command gh
  aif_python
  aif_resolve_repo_root
  local state_parent="$HOME/.aifactory-create-state"
  mkdir -p "$state_parent"
  AIF_STATE_DIR="$(mktemp -d "$state_parent/run.XXXXXX")"
  trap 'rm -rf -- "$AIF_STATE_DIR"' EXIT
  aif_value "Target repo" "$AIF_REPO_ROOT"

  aif_collect_answers
  aif_confirm_summary
  aif_ensure_azure_login
  aif_ensure_ado_auth
  aif_ensure_target_repository
  aif_sync_submodule_and_templates
  aif_register_resource_providers "$AIF_DEV_SUBSCRIPTION_ID"
  aif_ensure_bootstrap_identity
  aif_ensure_seeding_keyvault
  aif_ensure_team_group
  aif_seed_optional_project_sp
  aif_prepare_hub_dns
  if [[ "$AIF_DRY_RUN" != "true" ]]; then
    AIF_AZURE_ML_PRINCIPAL_ID="$(az ad sp show \
      --id 0736f41a-0425-4b46-bdb5-1563eff02385 \
      --query id \
      --output tsv)"
  else
    AIF_AZURE_ML_PRINCIPAL_ID=""
  fi
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
