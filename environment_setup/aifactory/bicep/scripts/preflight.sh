#!/usr/bin/env bash
# =============================================================================
# preflight.sh - AI Factory pre-deployment validation (quota + policy + region)
# =============================================================================
# Read-only checks run "early" in the ADO / GitHub Actions pipelines (and
# locally) to FAIL FAST with a clear reason BEFORE any Bicep deployment starts.
#
# What it checks (per target subscription + region):
#   1. Azure AI Search SKU quota         (Microsoft.Search usages REST)
#   2. Model deployment quota            (az cognitiveservices usage list)
#   3. Cognitive Services quota headroom (Microsoft.CognitiveServices usages)
#   4. Elasticsearch policy / RP block   (deny-policy heuristic + RP state)
#   5. Resource provider registration    (only for SELECTED services)
#   6. Provider-region support           (selected resource types in region)
#   7. Lists ALL policy assignments on the subscription (informational)
#
# Settings are read (in priority order) from:
#   1. CLI flags / PREFLIGHT_* env vars (explicit override)
#   2. Already-exported pipeline variables
#        - ADO  variables.yaml names (lowerCamel: admin_location, enableAISearch...)
#        - GitHub .env names         (UPPER_SNAKE: AIFACTORY_LOCATION, ENABLE_AI_SEARCH...)
#   3. A --variables-yaml file (ADO route) or --env-file (.env, GitHub route)
#   4. Built-in defaults
#
# Exit codes:
#   0  no FAIL findings (deploy may proceed)            -> pipeline continues
#   1  one or more FAIL findings                        -> pipeline ABORTS
#   2  warnings only AND --strict was supplied          -> pipeline ABORTS
#
# Portability: pure bash, runs on Linux agents AND Git Bash on Windows agents.
# All `az` calls are addressed by name / use https:// URLs only, so Git Bash
# never path-mangles a leading-slash argument (the same trap fixed elsewhere
# in this scripts/ folder). NEVER pass `--scope /subscriptions/...` here.
# =============================================================================

set -uo pipefail

# -----------------------------------------------------------------------------
# 0. Defaults / flags
# -----------------------------------------------------------------------------
STRICT="false"
# WARN_ONLY: when true, FAIL findings are reported but DO NOT abort the pipeline
# (the task still succeeds, exit 0). Temporary safety valve while the preflight
# checks are being tuned so a false-positive cannot block deployments.
# Override via env PREFLIGHT_WARN_ONLY=false or flag --no-warn-only to re-enable hard failures.
WARN_ONLY="${PREFLIGHT_WARN_ONLY:-true}"
SKIP="${PREFLIGHT_SKIP:-false}"
# SKIP_AZURE: run only the static config checks (no `az` calls at all).
SKIP_AZURE="${PREFLIGHT_SKIP_AZURE_LOOKUPS:-false}"
# SKIP_REGIONAL: run config + policy + RP-registration but skip the live
# regional-readiness block (provider/region support, VM SKU, quotas, DB regions).
SKIP_REGIONAL="${LZ_PREFLIGHT_REGIONAL_SKIP:-false}"
ENV_FILE=""
VARS_YAML=""
ONLY_ENV=""               # restrict to a single env: dev|test|prod
OVERRIDE_SUB=""           # restrict to a single subscription id
OVERRIDE_LOCATION=""
REPO_ROOT=""

usage() {
  cat <<'EOF'
Usage: preflight.sh [options]
  --env-file <path>        Path to GitHub-route .env file (UPPER_SNAKE keys)
  --variables-yaml <path>  Path to ADO-route variables.yaml (lowerCamel keys)
  --root <path>            Repo root to auto-detect .env / variables.yaml
  --environment <env>      Check only one of: dev | test | prod
  --subscription <id>      Check only this subscription id (single env)
  --location <region>      Override Azure region (e.g. eastus2)
  --strict                 Treat WARN-only result as failure (exit 2)
  --warn-only              Report FAILs but never abort the task (exit 0) [default]
  --no-warn-only           Enforce hard failures: any FAIL aborts (exit 1)
  --skip-azure-lookups     Skip every check that needs an 'az' call (config-only)
  --skip-regional          Skip only the live regional-readiness block (quotas, provider/region)
  --skip                   Skip all checks and exit 0 (escape hatch)
  -h | --help              Show this help
Environment escape hatches:
  PREFLIGHT_SKIP=true                  bypass everything
  PREFLIGHT_SKIP_AZURE_LOOKUPS=true    config-only (no az calls)
  LZ_PREFLIGHT_REGIONAL_SKIP=true      skip regional readiness only
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file)        ENV_FILE="${2:-}"; shift 2;;
    --variables-yaml)  VARS_YAML="${2:-}"; shift 2;;
    --root)            REPO_ROOT="${2:-}"; shift 2;;
    --environment)     ONLY_ENV="$(printf '%s' "${2:-}" | tr '[:upper:]' '[:lower:]')"; shift 2;;
    --subscription)    OVERRIDE_SUB="${2:-}"; shift 2;;
    --location)        OVERRIDE_LOCATION="${2:-}"; shift 2;;
    --strict)          STRICT="true"; shift;;
    --warn-only)       WARN_ONLY="true"; shift;;
    --no-warn-only)    WARN_ONLY="false"; shift;;
    --skip-azure-lookups) SKIP_AZURE="true"; shift;;
    --skip-regional)   SKIP_REGIONAL="true"; shift;;
    --skip)            SKIP="true"; shift;;
    -h|--help)         usage; exit 0;;
    *) echo "WARN: unknown argument '$1' (ignored)" >&2; shift;;
  esac
done

# stage label from pipeline (ADO sets dev_test_prod; mirror as ONLY_ENV)
if [ -z "$ONLY_ENV" ] && [ -n "${dev_test_prod:-}" ]; then
  ONLY_ENV="$(printf '%s' "$dev_test_prod" | tr '[:upper:]' '[:lower:]')"
  [ "$ONLY_ENV" = "stage" ] && ONLY_ENV="test"
fi
# single-subscription override from pipeline stage variable
if [ -z "$OVERRIDE_SUB" ] && [ -n "${dev_test_prod_sub_id:-}" ]; then
  OVERRIDE_SUB="$dev_test_prod_sub_id"
fi

# -----------------------------------------------------------------------------
# 1. CI annotation helpers (surface WHY in the ADO / GitHub UI)
# -----------------------------------------------------------------------------
IS_ADO="false"; IS_GH="false"
[ -n "${TF_BUILD:-}" ] || [ -n "${SYSTEM_TEAMPROJECT:-}" ] && IS_ADO="true"
[ -n "${GITHUB_ACTIONS:-}" ] && IS_GH="true"

ci_error() { # $1 = message
  if [ "$IS_ADO" = "true" ]; then echo "##vso[task.logissue type=error]$1";
  elif [ "$IS_GH" = "true" ]; then echo "::error::$1"; fi
}
ci_warning() {
  if [ "$IS_ADO" = "true" ]; then echo "##vso[task.logissue type=warning]$1";
  elif [ "$IS_GH" = "true" ]; then echo "::warning::$1"; fi
}

# -----------------------------------------------------------------------------
# 2. Findings accumulator
# -----------------------------------------------------------------------------
FAIL_COUNT=0
WARN_COUNT=0
FINDINGS=()   # "SEVERITY|CODE|MESSAGE|HINT"

add_finding() { # $1 sev  $2 code  $3 msg  $4 hint
  FINDINGS+=("$1|$2|$3|${4:-}")
  case "$1" in
    # In WARN_ONLY mode a FAIL is still counted (for the summary) but surfaced as a
    # warning annotation so it never marks the CI task red / blocks the pipeline.
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1));
          if [ "$WARN_ONLY" = "true" ]; then ci_warning "[$2] $3 (WARN_ONLY)"; else ci_error "[$2] $3"; fi;;
    WARN) WARN_COUNT=$((WARN_COUNT + 1)); ci_warning "[$2] $3";;
  esac
}

# -----------------------------------------------------------------------------
# 3. Skip / login guards
# -----------------------------------------------------------------------------
if [ "$SKIP" = "true" ]; then
  echo "preflight: PREFLIGHT_SKIP/--skip set -> skipping all checks (exit 0)."
  exit 0
fi

if ! command -v az >/dev/null 2>&1; then
  echo "preflight: Azure CLI ('az') not found -> skipping Azure checks (non-blocking)."
  exit 0
fi
if ! az account show --output none 2>/dev/null; then
  echo "preflight: not logged in to Azure ('az account show' failed) -> skipping Azure checks (non-blocking)."
  exit 0
fi

# Azure CLI ships with Python, so one of these is virtually always present.
PYBIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -z "$PYBIN" ]; then
  echo "preflight: no python/python3 interpreter found -> skipping Azure checks (non-blocking)."
  exit 0
fi

# -----------------------------------------------------------------------------
# 4. Settings file auto-detection + parsers
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [ -z "$REPO_ROOT" ]; then
  # default working dir of the pipeline checkout
  REPO_ROOT="${SYSTEM_DEFAULTWORKINGDIRECTORY:-${GITHUB_WORKSPACE:-$PWD}}"
fi

if [ -z "$ENV_FILE" ] && [ -z "$VARS_YAML" ]; then
  # GitHub route prefers .env at repo root; ADO route uses variables.yaml.
  for c in "$REPO_ROOT/.env" "$PWD/.env"; do
    [ -f "$c" ] && { ENV_FILE="$c"; break; }
  done
  if [ -z "$ENV_FILE" ]; then
    for c in \
      "$REPO_ROOT/aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml" \
      "$REPO_ROOT/variables.yaml" \
      "$PWD/variables.yaml"; do
      [ -f "$c" ] && { VARS_YAML="$c"; break; }
    done
  fi
fi
[ -n "$ENV_FILE" ]  && echo "preflight: using .env settings file        : $ENV_FILE"
[ -n "$VARS_YAML" ] && echo "preflight: using variables.yaml settings file: $VARS_YAML"

# Read a value from a quoted/bare .env line: KEY="value" | KEY=value
dotenv_get() { # $1 = KEY
  [ -n "$ENV_FILE" ] || return 0
  local line val
  line="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -n1)"
  [ -n "$line" ] || return 0
  val="${line#*=}"
  val="${val%%#*}"                       # strip trailing comment
  val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  val="${val%\"}"; val="${val#\"}"        # strip surrounding double quotes
  val="${val%\'}"; val="${val#\'}"        # strip surrounding single quotes
  printf '%s' "$val"
}

# Read a value from a variables.yaml line: key: "value"  # comment
yaml_get() { # $1 = key
  [ -n "$VARS_YAML" ] || return 0
  local line val
  line="$(grep -E "^[[:space:]]*$1[[:space:]]*:" "$VARS_YAML" 2>/dev/null | head -n1)"
  [ -n "$line" ] || return 0
  val="${line#*:}"
  # quoted value -> take inside the first quote pair
  if printf '%s' "$val" | grep -q '"'; then
    val="$(printf '%s' "$val" | sed -E 's/^[^"]*"([^"]*)".*$/\1/')"
  else
    val="${val%%#*}"
    val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  fi
  printf '%s' "$val"
}

# Resolve a logical setting: env(camel) -> env(UPPER) -> yaml(camel) -> dotenv(UPPER) -> default
getval() { # $1 camel  $2 UPPER  $3 default
  local camel="$1" upper="$2" def="$3" v=""
  v="$(printenv "$camel" 2>/dev/null || true)"; [ -n "$v" ] && { printf '%s' "$v"; return; }
  v="$(printenv "$upper" 2>/dev/null || true)"; [ -n "$v" ] && { printf '%s' "$v"; return; }
  v="$(yaml_get "$camel")";                     [ -n "$v" ] && { printf '%s' "$v"; return; }
  v="$(dotenv_get "$upper")";                   [ -n "$v" ] && { printf '%s' "$v"; return; }
  printf '%s' "$def"
}

is_true() { case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in true|1|yes|y) return 0;; *) return 1;; esac; }
lc() { printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'; }

# -----------------------------------------------------------------------------
# 5. Resolve settings (shared across environments)
# -----------------------------------------------------------------------------
LOCATION="$OVERRIDE_LOCATION"
[ -n "$LOCATION" ] || LOCATION="$(getval admin_location AIFACTORY_LOCATION eastus2)"

ONLY_DEV="$(getval aifactory_common_only_dev_environment AIFACTORY_COMMON_ONLY_DEV_ENVIRONMENT false)"

ENABLE_AI_SEARCH="$(getval enableAISearch ENABLE_AI_SEARCH true)"
AI_SEARCH_TIER="$(getval admin_aiSearchTier ADMIN_AI_SEARCH_TIER basic)"
ENABLE_AI_FOUNDRY="$(getval enableAIFoundry ENABLE_AI_FOUNDRY true)"
ENABLE_AOAI="$(getval enableAzureOpenAI ENABLE_AZURE_OPENAI false)"
ENABLE_COSMOS="$(getval enableCosmosDB ENABLE_COSMOS_DB false)"
ENABLE_ELASTIC="$(getval enableElasticsearch ENABLE_ELASTICSEARCH false)"

# Model deployments
DEPLOY_GPTX="$(getval deployModel_gpt_X DEPLOY_MODEL_GPT_X false)"
GPTX_NAME="$(getval modelGPTXName MODEL_GPTX_NAME gpt-4o)"
GPTX_SKU="$(getval modelGPTXSku MODEL_GPTX_SKU DataZoneStandard)"
GPTX_CAP="$(getval modelGPTXCapacity MODEL_GPTX_CAPACITY 30)"

DEPLOY_GPT4O="$(getval deployModel_gpt_4o DEPLOY_MODEL_GPT_4O false)"
DEPLOY_EMB3L="$(getval deployModel_text_embedding_3_large DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE false)"
DEPLOY_EMB3S="$(getval deployModel_text_embedding_3_small DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL false)"
DEPLOY_ADA="$(getval deployModel_text_embedding_ada_002 DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002 false)"
DEFAULT_SKU="$(getval default_model_sku DEFAULT_MODEL_SKU Standard)"
DEFAULT_GPT_CAP="$(getval default_gpt_capacity DEFAULT_GPT_CAPACITY 40)"
DEFAULT_EMB_CAP="$(getval default_embedding_capacity DEFAULT_EMBEDDING_CAPACITY 25)"

# Build the list of "name|sku|capacity" model deployments that are enabled.
MODELS=()
is_true "$DEPLOY_GPTX"  && MODELS+=("$GPTX_NAME|$GPTX_SKU|$GPTX_CAP")
is_true "$DEPLOY_GPT4O" && MODELS+=("gpt-4o|$DEFAULT_SKU|$DEFAULT_GPT_CAP")
is_true "$DEPLOY_EMB3L" && MODELS+=("text-embedding-3-large|$DEFAULT_SKU|$DEFAULT_EMB_CAP")
is_true "$DEPLOY_EMB3S" && MODELS+=("text-embedding-3-small|$DEFAULT_SKU|$DEFAULT_EMB_CAP")
is_true "$DEPLOY_ADA"   && MODELS+=("text-embedding-ada-002|$DEFAULT_SKU|$DEFAULT_EMB_CAP")

# --- Networking CIDRs (common vNet + subnets; XX is substituted per environment) ---
COMMON_VNET_CIDR="$(getval common_vnet_cidr COMMON_VNET_CIDR 172.16.0.0/16)"
COMMON_SUBNET_CIDR="$(getval common_subnet_cidr COMMON_SUBNET_CIDR 172.16.XX.0/26)"
COMMON_SUBNET_SCORING_CIDR="$(getval common_subnet_scoring_cidr COMMON_SUBNET_SCORING_CIDR 172.16.XX.64/26)"
COMMON_PBI_SUBNET_CIDR="$(getval common_pbi_subnet_cidr COMMON_PBI_SUBNET_CIDR 172.16.XX.128/26)"
COMMON_BASTION_SUBNET_CIDR="$(getval common_bastion_subnet_cidr COMMON_BASTION_SUBNET_CIDR 172.16.XX.192/26)"
DEV_CIDR_RANGE="$(getval dev_cidr_range DEV_CIDR_RANGE 61)"
TEST_CIDR_RANGE="$(getval test_cidr_range TEST_CIDR_RANGE 62)"
PROD_CIDR_RANGE="$(getval prod_cidr_range PROD_CIDR_RANGE 63)"

# --- BYO subnets ---
BYO_SUBNETS="$(getval BYO_subnets BYO_SUBNETS false)"
SUBNET_COMMON="$(getval subnetCommon SUBNET_COMMON '')"
SUBNET_COMMON_SCORING="$(getval subnetCommonScoring SUBNET_COMMON_SCORING '')"
SUBNET_COMMON_PBI="$(getval subnetCommonPowerbiGw SUBNET_COMMON_POWERBI_GW '')"
SUBNET_PROJ_GENAI="$(getval subnetProjGenAI SUBNET_PROJ_GENAI '')"
SUBNET_PROJ_AKS="$(getval subnetProjAKS SUBNET_PROJ_AKS '')"
SUBNET_PROJ_AKS2="$(getval subnetProjAKS2 SUBNET_PROJ_AKS2 '')"
SUBNET_PROJ_ACA="$(getval subnetProjACA SUBNET_PROJ_ACA '')"
SUBNET_PROJ_ACA2="$(getval subnetProjACA2 SUBNET_PROJ_ACA2 '')"
SUBNET_PROJ_WEBAPP="$(getval subnetProjWebapp SUBNET_PROJ_WEBAPP '')"
SUBNET_PROJ_DBX_PUB="$(getval subnetProjDatabricksPublic SUBNET_PROJ_DBX_PUBLIC '')"
SUBNET_PROJ_DBX_PRIV="$(getval subnetProjDatabricksPrivate SUBNET_PROJ_DBX_PRIVATE '')"

# --- BYO App Service Environment v3 ---
BYO_ASEV3="$(getval byoASEv3 BYO_ASEV3 false)"
BYO_ASE_ID="$(getval byoAseFullResourceId BYO_ASE_FULL_RESOURCE_ID '')"
BYO_ASE_PLAN_ID="$(getval byoAseAppServicePlanResourceId BYO_ASE_APP_SERVICE_PLAN_RESOURCE_ID '')"

# --- AKS networking ---
AKS_PRIVATE_CLUSTER="$(getval aksEnablePrivateCluster AKS_ENABLE_PRIVATE_CLUSTER false)"
AKS_OUTBOUND_TYPE="$(getval aksOutboundType AKS_OUTBOUND_TYPE loadBalancer)"
AKS_PRIVATE_DNS="$(getval aksPrivateDNSZone AKS_PRIVATE_DNS_ZONE system)"
AKS_FW_IP="$(getval aksAzureFirewallPrivateIp AKS_AZURE_FIREWALL_PRIVATE_IP '')"

# --- Additional service enables (DB / app / regional readiness) ---
ENABLE_REDIS="$(getval enableRedisCache ENABLE_REDIS_CACHE false)"
ENABLE_POSTGRES="$(getval enablePostgreSQL ENABLE_POSTGRESQL false)"
ENABLE_SQLDB="$(getval enableSQLDatabase ENABLE_SQL_DATABASE false)"
ENABLE_WEBAPP="$(getval enableWebApp ENABLE_WEB_APP false)"
ENABLE_FUNCTION="$(getval enableFunction ENABLE_FUNCTION false)"
ENABLE_DATABRICKS="$(getval enableDatabricks ENABLE_DATABRICKS false)"
ENABLE_AKS="$(getval enableAKS ENABLE_AKS false)"
ENABLE_AKS_AML="$(getval enableAksForAzureML ENABLE_AKS_FOR_AZURE_ML false)"
DISABLE_AGENT_NET_INJ="$(getval disableAgentNetworkInjection DISABLE_AGENT_NETWORK_INJECTION false)"

# --- Security: IP allow-lists ---
PROJECT_IP_WHITELIST="$(getval project_IP_whitelist PROJECT_IP_WHITELIST '')"
ACR_IP_WHITELIST="$(getval acr_IP_whitelist ACR_IP_WHITELIST '')"

# -----------------------------------------------------------------------------
# 6. Build the list of subscriptions/environments to check
# -----------------------------------------------------------------------------
DEV_SUB="$(getval dev_sub_id DEV_SUBSCRIPTION_ID '')"
TEST_SUB="$(getval test_sub_id STAGE_SUBSCRIPTION_ID '')"
PROD_SUB="$(getval prod_sub_id PROD_SUBSCRIPTION_ID '')"

# is this a real subscription id (not a <todo> placeholder)?
valid_sub() { case "$(lc "${1:-}")" in ''|*'<todo>'*|*todo*|'-') return 1;; *) return 0;; esac; }

TARGETS=()  # "env|subId"
if [ -n "$OVERRIDE_SUB" ] && valid_sub "$OVERRIDE_SUB"; then
  TARGETS+=("${ONLY_ENV:-current}|$OVERRIDE_SUB")
else
  add_target() { # $1 env  $2 sub
    [ -n "$ONLY_ENV" ] && [ "$ONLY_ENV" != "$1" ] && return 0
    valid_sub "$2" || return 0
    # de-dup identical subscription ids
    local t; for t in "${TARGETS[@]:-}"; do [ "${t#*|}" = "$2" ] && return 0; done
    TARGETS+=("$1|$2")
  }
  add_target dev "$DEV_SUB"
  if ! is_true "$ONLY_DEV"; then
    add_target test "$TEST_SUB"
    add_target prod "$PROD_SUB"
  fi
fi

if [ "${#TARGETS[@]}" -eq 0 ]; then
  add_finding WARN NO_SUBSCRIPTION \
    "No valid subscription id resolved from settings (env vars / .env / variables.yaml)." \
    "Set dev_sub_id (ADO) or DEV_SUBSCRIPTION_ID (.env), or pass --subscription <id>."
fi

# -----------------------------------------------------------------------------
# 7. Check functions (all read-only)
# -----------------------------------------------------------------------------
norm_loc() { printf '%s' "$(lc "${1:-}" | tr -cd 'a-z0-9')"; }

# Run an `az` command with retries on TRANSIENT failures (GatewayTimeout, 429,
# 5xx, throttling, connection resets). On success: AZ_OUT holds stdout and
# AZ_TRANSIENT is empty. If a transient failure survives all retries:
# AZ_TRANSIENT=1 so the caller can emit a non-blocking "cannot validate right
# now" WARN instead of a misleading hard FAIL. Read-only (GET/list calls only).
# Tunables: PREFLIGHT_AZ_RETRIES (default 3), PREFLIGHT_AZ_BACKOFF (default 3s).
AZ_OUT=""
AZ_TRANSIENT=""
az_capture() { # args: az subcommand + flags
  local attempts="${PREFLIGHT_AZ_RETRIES:-3}" backoff="${PREFLIGHT_AZ_BACKOFF:-3}" i=1 errf emsg rc
  AZ_OUT=""; AZ_TRANSIENT=""
  while :; do
    errf="$(mktemp 2>/dev/null || printf '%s' "${TMPDIR:-/tmp}/pf_az.$$.$i")"
    AZ_OUT="$(az "$@" 2>"$errf")"; rc=$?
    emsg="$(cat "$errf" 2>/dev/null)"; rm -f "$errf" 2>/dev/null
    if [ "$rc" -eq 0 ] && [ -n "$AZ_OUT" ]; then return 0; fi
    if printf '%s' "$emsg" | grep -qiE 'gateway.?timeout|timed?.?out|throttl|too many requests|\b(429|500|502|503|504)\b|temporarily unavailable|service unavailable|connection reset'; then
      if [ "$i" -ge "$attempts" ]; then AZ_TRANSIENT=1; return 1; fi
      sleep "$(( i * backoff ))"; i=$((i + 1)); continue
    fi
    # Non-transient (auth/not-found/empty-with-no-error) -> let the caller decide.
    return "$rc"
  done
}

check_ai_search_quota() { # $1 subId
  is_true "$ENABLE_AI_SEARCH" || return 0
  local sub="$1" sku url payload limit cur avail
  sku="$(lc "$AI_SEARCH_TIER")"
  url="https://management.azure.com/subscriptions/$sub/providers/Microsoft.Search/locations/$LOCATION/usages?api-version=2025-05-01"
  az_capture rest --method get --url "$url" -o json; payload="$AZ_OUT"
  if [ -n "$AZ_TRANSIENT" ]; then
    add_finding WARN SEARCH_QUOTA_UNVALIDATED "Cannot validate Azure AI Search quota in '$LOCATION' at this moment (transient Azure error/timeout after retries)." \
      "Re-run preflight shortly. Manual check: az rest --method get --url '$url'"
    return 0
  fi
  if [ -z "$payload" ]; then
    add_finding WARN SEARCH_QUOTA_LOOKUP "Could not read Azure AI Search usage for '$LOCATION' (sub $sub)." \
      "Verify Microsoft.Search is registered and the identity has Reader on the subscription."
    return 0
  fi
  # find usage entry whose name.value matches the sku (case-insensitive)
  read -r limit cur < <(printf '%s' "$payload" | az_jq_search "$sku")
  if [ -z "${limit:-}" ]; then
    add_finding WARN SEARCH_SKU_UNAVAILABLE "Azure AI Search SKU '$AI_SEARCH_TIER' is not listed for '$LOCATION'." \
      "Pick a supported SKU/region for Azure AI Search."
    return 0
  fi
  avail=$((limit - cur))
  if [ "$limit" -le 0 ] || [ "$avail" -le 0 ]; then
    add_finding FAIL SEARCH_QUOTA_AT_LIMIT \
      "Azure AI Search SKU '$AI_SEARCH_TIER' quota in '$LOCATION' is exhausted (used $cur of $limit)." \
      "Request a quota increase or pick another region/SKU."
  else
    echo "  [OK] AI Search '$AI_SEARCH_TIER' in $LOCATION: $avail of $limit available."
  fi
}

# helper: parse Microsoft.Search usages JSON via az/python and emit "limit currentValue"
az_jq_search() { # stdin=json  $1=sku(lower)
  local _in; _in="$(cat)"
  PF_JSON="$_in" "$PYBIN" - "$1" <<'PY' 2>/dev/null || true
import os, sys, json
sku = sys.argv[1].lower()
try:
    data = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception:
    sys.exit(0)
for it in data.get("value", []):
    name = (it.get("name") or {})
    val = str(name.get("value", "")).lower()
    if val == sku:
        print(int(it.get("limit", 0)), int(it.get("currentValue", 0)))
        break
PY
}

check_model_quota() { # $1 subId
  [ "${#MODELS[@]}" -gt 0 ] || return 0
  local sub="$1" usage failures="" m name sku cap qn line limit cur avail
  az_capture cognitiveservices usage list --location "$LOCATION" -o json; usage="$AZ_OUT"
  if [ -n "$AZ_TRANSIENT" ]; then
    add_finding WARN MODEL_QUOTA_UNVALIDATED "Cannot validate AI model quota in '$LOCATION' at this moment (transient Azure error/timeout after retries)." \
      "Re-run preflight shortly. Manual check: az cognitiveservices usage list --location $LOCATION"
    return 0
  fi
  if [ -z "$usage" ]; then
    add_finding WARN MODEL_QUOTA_LOOKUP "Could not read Cognitive Services usage/quota for '$LOCATION' (sub $sub)." \
      "Run: az cognitiveservices usage list --location $LOCATION ; verify Microsoft.CognitiveServices is registered."
    return 0
  fi
  for m in "${MODELS[@]}"; do
    name="${m%%|*}"; cap="${m##*|}"; sku="${m#*|}"; sku="${sku%|*}"
    qn="OpenAI.$sku.$name"
    line="$(printf '%s' "$usage" | az_jq_model "$qn")"
    if [ -z "$line" ]; then
      failures="$failures No quota entry '$qn'."
      continue
    fi
    limit="$(printf '%s' "$line" | awk '{print $1}')"
    cur="$(printf '%s' "$line" | awk '{print $2}')"
    avail=$(( ${limit%.*} - ${cur%.*} ))
    if [ "$avail" -lt "${cap%.*}" ]; then
      failures="$failures $qn needs $cap, $avail available (used ${cur%.*}/${limit%.*})."
    else
      echo "  [OK] Model quota $qn in $LOCATION: $avail available (need $cap)."
    fi
  done
  if [ -n "$failures" ]; then
    add_finding FAIL MODEL_QUOTA_INSUFFICIENT "Insufficient AI model quota in '$LOCATION':$failures" \
      "Request a quota increase (https://aka.ms/oai/quotaincrease), reduce capacity, or pick a region with quota."
  fi
}

# helper: from cognitiveservices usage JSON find name.value==quotaName -> "limit currentValue"
az_jq_model() { # stdin=json  $1=quotaName
  local _in; _in="$(cat)"
  PF_JSON="$_in" "$PYBIN" - "$1" <<'PY' 2>/dev/null || true
import os, sys, json
qn = sys.argv[1]
try:
    data = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception:
    sys.exit(0)
for it in data:
    name = (it.get("name") or {})
    if str(name.get("value", "")) == qn:
        print(float(it.get("limit", 0)), float(it.get("currentValue", 0)))
        break
PY
}

check_cs_headroom() { # $1 subId
  is_true "$ENABLE_AI_FOUNDRY" || is_true "$ENABLE_AOAI" || [ "${#MODELS[@]}" -gt 0 ] || return 0
  local sub="$1" url payload res
  url="https://management.azure.com/subscriptions/$sub/providers/Microsoft.CognitiveServices/locations/$LOCATION/usages?api-version=2023-05-01"
  az_capture rest --method get --url "$url" -o json; payload="$AZ_OUT"
  if [ -n "$AZ_TRANSIENT" ]; then
    add_finding WARN CS_QUOTA_UNVALIDATED "Cannot validate Cognitive Services quota in '$LOCATION' at this moment (transient Azure error/timeout after retries)." \
      "Re-run preflight shortly."
    return 0
  fi
  [ -n "$payload" ] || { add_finding WARN CS_QUOTA_LOOKUP "Could not read Cognitive Services usage for '$LOCATION'." \
      "Verify Microsoft.CognitiveServices is registered and identity has Reader."; return 0; }
  res="$(PF_JSON="$payload" "$PYBIN" - <<'PY' 2>/dev/null
import os, sys, json
try: data = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception: sys.exit(0)
items = data.get("value", [])
if not items: sys.exit(0)
headroom = any(float(i.get("limit",0)) > float(i.get("currentValue",0)) for i in items)
tight = any((float(i.get("limit",0))>0 and (float(i.get("limit",0))-float(i.get("currentValue",0)))/float(i.get("limit",0))<0.1) for i in items)
print(("HEADROOM" if headroom else "FULL"), ("TIGHT" if tight else "OK"))
PY
)"
  case "$res" in
    "FULL "*) add_finding FAIL CS_QUOTA_AT_LIMIT "Cognitive Services quota in '$LOCATION' is fully consumed across all metrics." \
                "Request a quota increase (https://aka.ms/oai/quotaincrease) or pick another region.";;
    *TIGHT)   add_finding WARN CS_QUOTA_TIGHT "Cognitive Services quota in '$LOCATION' is within 10% of the limit on a metric.";;
  esac
}

list_policy_assignments() { # $1 subId  (informational + elastic deny heuristic)
  local sub="$1" json count
  # NOTE: omit --scope to stay at the default subscription scope -> avoids a
  # leading-slash /subscriptions/... arg that Git Bash on Windows mangles.
  json="$(az policy assignment list -o json 2>/dev/null)"
  if [ -z "$json" ]; then
    add_finding WARN POLICY_LOOKUP "Could not list policy assignments for subscription $sub." \
      "Verify the identity has Microsoft.Authorization/policyAssignments/read."
    return 0
  fi
  count="$(PF_JSON="$json" "$PYBIN" - <<'PY' 2>/dev/null
import os, json
try: data = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception: data = []
names = [ (a.get("displayName") or a.get("name") or "?") for a in data ]
print(len(names))
for n in names: print("    - "+str(n))
PY
)"
  [ -n "$count" ] || count=0
  echo "  Policy assignments on subscription $sub:"
  [ "$count" = "${count%%$'\n'*}" ] || printf '%s\n' "${count#*$'\n'}"
  echo "  (${count%%$'\n'*} policy assignment(s) total)"
}

check_elasticsearch_block() { # $1 subId
  is_true "$ENABLE_ELASTIC" || return 0
  local sub="$1" state json blocked
  # 1) Microsoft.Elastic resource provider must be registerable/registered.
  state="$(az provider show --namespace Microsoft.Elastic --query 'registrationState' -o tsv 2>/dev/null)"
  if [ -n "$state" ] && [ "$state" != "Registered" ] && [ "$state" != "Registering" ]; then
    add_finding FAIL ELASTIC_RP_NOT_REGISTERED \
      "enableElasticsearch=true but provider 'Microsoft.Elastic' is '$state' (sub $sub)." \
      "Run: az provider register --namespace Microsoft.Elastic --wait (requires permission; may be blocked by policy)."
  fi
  # 2) Deny-policy heuristic: any assignment whose definition denies the Elastic
  #    resource type / Marketplace offer would block the deployment.
  json="$(az policy assignment list -o json 2>/dev/null)"
  blocked="$(PF_JSON="$json" "$PYBIN" - <<'PY' 2>/dev/null
import os, sys, json
try: data = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception: sys.exit(0)
hits=[]
for a in data:
    blob = json.dumps(a).lower()
    if "elastic" in blob and ("deny" in blob or "notallowed" in blob or "restrict" in blob):
        hits.append(a.get("displayName") or a.get("name") or "?")
for h in hits: print(h)
PY
)"
  if [ -n "$blocked" ]; then
    add_finding FAIL ELASTIC_POLICY_DENY \
      "Azure Policy appears to deny Elasticsearch (Microsoft.Elastic) on sub $sub: $(printf '%s' "$blocked" | tr '\n' ';')" \
      "Request a policy exemption, or set enableElasticsearch=false."
  fi
}

check_resource_providers() { # $1 subId
  local sub="$1" ns state reason sel entry
  # Precompute "selected" booleans (avoids fragile nested command substitution).
  local sel_cs=false sel_search=false sel_cosmos=false sel_elastic=false
  if is_true "$ENABLE_AI_FOUNDRY" || is_true "$ENABLE_AOAI" || [ "${#MODELS[@]}" -gt 0 ]; then sel_cs=true; fi
  is_true "$ENABLE_AI_SEARCH" && sel_search=true
  is_true "$ENABLE_COSMOS"    && sel_cosmos=true
  is_true "$ENABLE_ELASTIC"   && sel_elastic=true
  # namespace|reason|selected(true/false)
  local rps=(
    "Microsoft.CognitiveServices|AI Foundry / Azure OpenAI / models|$sel_cs"
    "Microsoft.Search|Azure AI Search|$sel_search"
    "Microsoft.DocumentDB|Azure Cosmos DB|$sel_cosmos"
    "Microsoft.Elastic|Elasticsearch|$sel_elastic"
    "Microsoft.KeyVault|Key Vault (always)|true"
    "Microsoft.Storage|Storage (always)|true"
    "Microsoft.Network|Networking (always)|true"
  )
  for entry in "${rps[@]}"; do
    ns="${entry%%|*}"; reason="$(printf '%s' "$entry" | cut -d'|' -f2)"; sel="${entry##*|}"
    state="$(az provider show --namespace "$ns" --query 'registrationState' -o tsv 2>/dev/null)"
    if [ -z "$state" ]; then
      add_finding WARN RP_LOOKUP_FAILED "Could not read registration state for provider '$ns' ($reason)." \
        "Run: az provider show --namespace $ns --query registrationState -o tsv"
      continue
    fi
    [ "$state" = "Registered" ] && continue
    if [ "$state" = "Registering" ]; then
      add_finding WARN RP_REGISTERING "Provider '$ns' is '$state' — wait until 'Registered' before deploying."
    elif [ "$sel" = "true" ]; then
      add_finding FAIL RP_NOT_REGISTERED "Provider '$ns' is '$state', not 'Registered'. Used for: $reason." \
        "Run: az provider register --namespace $ns --wait"
    else
      add_finding WARN RP_NOT_REGISTERED_OPTIONAL "Provider '$ns' is '$state' (only needed if you enable: $reason)."
    fi
  done
}

# =============================================================================
# 7b. STATIC config / BYO / networking / observability / security checks
#     (no Azure calls; subscription-independent; run once)
# =============================================================================

# A value is "unset" if empty or still holding a <todo>/<optional> placeholder
# token. Note: <xxx> and <network_env> are legitimate pipeline templating tokens
# (substituted at deploy time) and are NOT treated as unset here.
is_unset_placeholder() {
  case "$(lc "${1:-}")" in
    ''|*'<todo>'*|*'<optional>'*) return 0;;
    *) return 1;;
  esac
}

# Substitute the literal token XX with an environment octet value (e.g. 61).
sub_xx() { printf '%s' "${1//XX/$2}"; }

# --- Config: scan variables.yaml for unresolved <todo>/<optional> placeholders.
# Severity is taken from the FIRST <mandatory>/<optional> tag in each line's
# comment: <mandatory> + placeholder value -> FAIL, <optional> + placeholder -> WARN.
check_config_placeholders() {
  if [ -z "$VARS_YAML" ]; then
    echo "  (no variables.yaml resolved; placeholder scan skipped — .env route uses a different convention)"
    return 0
  fi
  local out fails warns
  out="$("$PYBIN" - "$VARS_YAML" <<'PY' 2>/dev/null
import sys, re
path = sys.argv[1]
try:
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
except Exception:
    sys.exit(0)
for line in lines:
    s = line.strip()
    if not s or s.startswith('#'):
        continue
    m = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.*)$', line)
    if not m:
        continue
    key, rest = m.group(1), m.group(2)
    ci = rest.find(' #')
    val = rest[:ci] if ci >= 0 else rest
    comment = rest[ci+2:] if ci >= 0 else ''
    val = val.strip().strip('"').strip("'")
    low = val.lower()
    if '<todo>' not in low and '<optional>' not in low:
        continue
    tm = re.search(r'<(mandatory|optional)>', comment, re.I)
    tag = tm.group(1).lower() if tm else 'optional'
    sev = 'FAIL' if tag == 'mandatory' else 'WARN'
    print(sev + '\t' + key + '="' + val + '"')
PY
)"
  fails="$(printf '%s\n' "$out" | sed -n 's/^FAIL\t//p')"
  warns="$(printf '%s\n' "$out" | sed -n 's/^WARN\t//p')"
  if [ -n "$fails" ]; then
    add_finding FAIL CONFIG_MANDATORY_UNSET \
      "Mandatory settings still contain <todo> placeholders: $(printf '%s' "$fails" | tr '\n' ';')" \
      "Replace each <todo> value in variables.yaml with a real value before deploying."
  fi
  if [ -n "$warns" ]; then
    add_finding WARN CONFIG_OPTIONAL_UNSET \
      "Optional settings still contain placeholders (set only if you use the related feature): $(printf '%s' "$warns" | tr '\n' ';')" \
      "These are non-blocking unless the related enable* flag is true."
  fi
  [ -z "$fails$warns" ] && echo "  [OK] No <todo>/<optional> placeholder values found in variables.yaml."
}

# --- BYO: when BYO_subnets=true, the subnet-name variables must be set
# (non-empty, no <todo>/<optional>), honoring each variable's own condition.
check_byo_subnets() {
  if ! is_true "$BYO_SUBNETS"; then
    echo "  BYO_subnets=false -> AI Factory creates subnets from CIDR (no BYO subnet name check)."
    return 0
  fi
  local missing=""
  _need() { # $1 varname  $2 value  $3 condition-true?
    [ "$3" = "true" ] || return 0
    is_unset_placeholder "$2" && missing="$missing $1"
  }
  _need subnetCommon          "$SUBNET_COMMON"          true
  _need subnetCommonScoring   "$SUBNET_COMMON_SCORING"  true
  _need subnetCommonPowerbiGw "$SUBNET_COMMON_PBI"      true
  _need subnetProjGenAI       "$SUBNET_PROJ_GENAI"      true
  _need subnetProjAKS         "$SUBNET_PROJ_AKS"        true
  _need subnetProjAKS2        "$SUBNET_PROJ_AKS2"       true
  _need subnetProjACA         "$SUBNET_PROJ_ACA"        true
  # subnetProjACA2: required if enableAIFoundry AND agent network injection ON (disable=false)
  local aca2_req="false"
  if is_true "$ENABLE_AI_FOUNDRY" && ! is_true "$DISABLE_AGENT_NET_INJ"; then aca2_req="true"; fi
  _need subnetProjACA2        "$SUBNET_PROJ_ACA2"       "$aca2_req"
  # subnetProjWebapp: required if Web App OR Function enabled
  local webapp_req="false"
  if is_true "$ENABLE_WEBAPP" || is_true "$ENABLE_FUNCTION"; then webapp_req="true"; fi
  _need subnetProjWebapp      "$SUBNET_PROJ_WEBAPP"     "$webapp_req"
  # Databricks subnets: required if Databricks enabled
  local dbx_req="false"; is_true "$ENABLE_DATABRICKS" && dbx_req="true"
  _need subnetProjDatabricksPublic  "$SUBNET_PROJ_DBX_PUB"  "$dbx_req"
  _need subnetProjDatabricksPrivate "$SUBNET_PROJ_DBX_PRIV" "$dbx_req"

  if [ -n "$missing" ]; then
    add_finding FAIL BYO_SUBNETS_UNSET \
      "BYO_subnets=true but these required subnet name(s) are empty or still a <todo>/<optional> placeholder:$missing" \
      "Set the listed subnetProj*/subnetCommon* variables to existing subnet names in your vNet (per the comments in variables.yaml)."
  else
    echo "  [OK] BYO_subnets=true and all required subnet name variables are set."
  fi
}

# --- BYO: App Service Environment v3. If byoASEv3=true, byoAseFullResourceId
# must be set and must NOT start with '/' (a leading slash is mis-parsed).
check_byo_ase() {
  if ! is_true "$BYO_ASEV3"; then
    echo "  byoASEv3=false -> no BYO App Service Environment check."
    return 0
  fi
  if is_unset_placeholder "$BYO_ASE_ID"; then
    add_finding FAIL BYO_ASE_ID_UNSET \
      "byoASEv3=true but byoAseFullResourceId is empty or a placeholder." \
      "Set the full ARM resource ID of the existing ASEv3 WITHOUT a leading '/' (e.g. 'subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/hostingEnvironments/<name>')."
  elif [ "${BYO_ASE_ID#/}" != "$BYO_ASE_ID" ]; then
    add_finding FAIL BYO_ASE_ID_LEADING_SLASH \
      "byoAseFullResourceId starts with '/': '$BYO_ASE_ID'. A leading slash is mis-parsed by the pipeline." \
      "Remove the leading '/' so it begins with 'subscriptions/...'."
  else
    echo "  [OK] byoAseFullResourceId is set and has no leading slash."
  fi
  if is_unset_placeholder "$BYO_ASE_PLAN_ID"; then
    echo "  (byoAseAppServicePlanResourceId empty — allowed.)"
  fi
}

# --- Networking: CIDR sanity for the common vNet + subnets and the per-env octet ranges.
check_cidr_sanity() {
  # 1) dev/test/prod octet ranges must be distinct integers 0-255.
  local r bad_range=""
  for r in "$DEV_CIDR_RANGE" "$TEST_CIDR_RANGE" "$PROD_CIDR_RANGE"; do
    case "$r" in ''|*[!0-9]*) bad_range="$bad_range $r";; *) [ "$r" -ge 0 ] && [ "$r" -le 255 ] || bad_range="$bad_range $r";; esac
  done
  if [ -n "$bad_range" ]; then
    add_finding FAIL CIDR_RANGE_INVALID "dev/test/prod_cidr_range must be integers 0-255 (bad:$bad_range)." \
      "Set each *_cidr_range to a distinct octet value 0-255."
  elif [ "$DEV_CIDR_RANGE" = "$TEST_CIDR_RANGE" ] || [ "$DEV_CIDR_RANGE" = "$PROD_CIDR_RANGE" ] || [ "$TEST_CIDR_RANGE" = "$PROD_CIDR_RANGE" ]; then
    add_finding FAIL CIDR_RANGE_CONFLICT \
      "dev/test/prod_cidr_range must be distinct (dev=$DEV_CIDR_RANGE test=$TEST_CIDR_RANGE prod=$PROD_CIDR_RANGE)." \
      "Pick non-conflicting octet values per environment."
  else
    echo "  [OK] dev/test/prod_cidr_range are distinct ($DEV_CIDR_RANGE/$TEST_CIDR_RANGE/$PROD_CIDR_RANGE)."
  fi

  # 2) common vNet + subnets (substituting XX with the DEV octet) must be valid,
  #    inside the vNet, non-overlapping, and meet Azure minimum sizes.
  local out _cidr_data
  _cidr_data="$(printf 'VNET|%s\ncommon|%s|28\nscoring|%s|28\npbi|%s|28\nbastion|%s|26\n' \
      "$COMMON_VNET_CIDR" \
      "$(sub_xx "$COMMON_SUBNET_CIDR" "$DEV_CIDR_RANGE")" \
      "$(sub_xx "$COMMON_SUBNET_SCORING_CIDR" "$DEV_CIDR_RANGE")" \
      "$(sub_xx "$COMMON_PBI_SUBNET_CIDR" "$DEV_CIDR_RANGE")" \
      "$(sub_xx "$COMMON_BASTION_SUBNET_CIDR" "$DEV_CIDR_RANGE")")"
  out="$(PF_CIDR="$_cidr_data" "$PYBIN" - <<'PY' 2>/dev/null
import os, sys, ipaddress
vnet = None
subs = []
for line in os.environ.get("PF_CIDR", "").splitlines():
    line = line.strip()
    if not line:
        continue
    p = line.split('|')
    if p[0] == 'VNET':
        vnet = p[1]; continue
    minp = int(p[2]) if len(p) > 2 and p[2] else None
    subs.append((p[0], p[1], minp))
def emit(sev, code, msg): print(sev + '\t' + code + '\t' + msg)
try:
    vn = ipaddress.ip_network(vnet, strict=False)
except Exception:
    emit('FAIL', 'CIDR_VNET_BAD', 'common_vnet_cidr is not a valid CIDR: ' + str(vnet)); sys.exit(0)
nets = []
for role, cidr, minp in subs:
    try:
        n = ipaddress.ip_network(cidr, strict=False)
    except Exception:
        emit('FAIL', 'CIDR_SUBNET_BAD', role + ' subnet is not a valid CIDR: ' + cidr); continue
    nets.append((role, n, cidr))
    if not n.subnet_of(vn):
        emit('FAIL', 'CIDR_SUBNET_OUTSIDE', role + ' (' + cidr + ') is not inside common_vnet_cidr (' + vnet + ').')
    if minp is not None and n.prefixlen > minp:
        emit('FAIL', 'CIDR_SUBNET_TOO_SMALL', role + ' (' + cidr + ') is /' + str(n.prefixlen) + '; Azure needs at least /' + str(minp) + ' here.')
for i in range(len(nets)):
    for j in range(i+1, len(nets)):
        if nets[i][1].overlaps(nets[j][1]):
            emit('FAIL', 'CIDR_SUBNET_OVERLAP', nets[i][0] + ' (' + nets[i][2] + ') overlaps ' + nets[j][0] + ' (' + nets[j][2] + ').')
PY
)"
  local had=""
  while IFS="$(printf '\t')" read -r sev code msg; do
    [ -n "$sev" ] || continue
    had="1"
    case "$sev" in FAIL|WARN) add_finding "$sev" "$code" "$msg";; esac
  done <<EOF
$out
EOF
  [ -z "$had" ] && echo "  [OK] common vNet/subnets valid, inside vNet, non-overlapping, sized OK (DEV octet $DEV_CIDR_RANGE)."
}

# --- Networking: AKS with userDefinedRouting requires a firewall IP and a
# non-'system' private DNS zone.
check_aks_networking() {
  if ! is_true "$ENABLE_AKS" && ! is_true "$ENABLE_AKS_AML"; then
    echo "  AKS not enabled -> no AKS networking check."
    return 0
  fi
  if [ "$(lc "$AKS_OUTBOUND_TYPE")" != "userdefinedrouting" ]; then
    echo "  [OK] aksOutboundType='$AKS_OUTBOUND_TYPE' (no UDR-specific requirements)."
    return 0
  fi
  local ok="1"
  if is_unset_placeholder "$AKS_FW_IP"; then
    add_finding FAIL AKS_UDR_NO_FW_IP \
      "aksOutboundType=userDefinedRouting but aksAzureFirewallPrivateIp is empty." \
      "Set aksAzureFirewallPrivateIp to an IP within the Azure Firewall subnet range."
    ok=""
  elif ! printf '%s' "$AKS_FW_IP" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
    add_finding FAIL AKS_UDR_FW_IP_BAD \
      "aksAzureFirewallPrivateIp '$AKS_FW_IP' is not a valid IPv4 address." \
      "Provide a single IPv4 within the Azure Firewall subnet range."
    ok=""
  fi
  if [ "$(lc "$AKS_PRIVATE_DNS")" = "system" ]; then
    add_finding FAIL AKS_UDR_DNS_SYSTEM \
      "aksOutboundType=userDefinedRouting requires aksPrivateDNSZone NOT be 'system'." \
      "Set aksPrivateDNSZone to 'none' or to a full private DNS zone resource ID."
    ok=""
  fi
  [ -n "$ok" ] && echo "  [OK] AKS UDR config: firewall IP set and aksPrivateDNSZone='$AKS_PRIVATE_DNS'."
}

# --- Observability: split-brain check for any BYO App Insights / Log Analytics
# overrides (only fires if those override variables exist in this settings set).
check_observability() {
  local appi law conn mixed
  appi="$(getval existingApplicationInsightsResourceId EXISTING_APPLICATION_INSIGHTS_RESOURCE_ID '')"
  law="$(getval existingLogAnalyticsWorkspaceResourceId EXISTING_LOG_ANALYTICS_WORKSPACE_RESOURCE_ID '')"
  conn="$(getval existingApplicationInsightsConnectionString EXISTING_APPLICATION_INSIGHTS_CONNECTION_STRING '')"
  mixed="$(getval allowMixedObservabilityWorkspaces ALLOW_MIXED_OBSERVABILITY_WORKSPACES false)"
  if is_unset_placeholder "$appi"; then
    echo "  (no BYO Application Insights override configured — nothing to validate.)"
    return 0
  fi
  if is_unset_placeholder "$conn"; then
    add_finding FAIL APPI_NO_CONNSTR \
      "existingApplicationInsightsResourceId is set but the connection string is empty." \
      "Set EXISTING_APPLICATION_INSIGHTS_CONNECTION_STRING (az monitor app-insights component show ... --query connectionString -o tsv)."
  fi
  if is_unset_placeholder "$law" && ! is_true "$mixed"; then
    add_finding FAIL APPI_NO_LAW \
      "existingApplicationInsightsResourceId is set without a matching existingLogAnalyticsWorkspaceResourceId." \
      "Also set the backing Log Analytics workspace, or set allowMixedObservabilityWorkspaces=true if intentional."
  fi
}

# --- Security: validate IP allow-lists (reject malformed CIDRs, warn on 0.0.0.0/0).
_validate_ip_list() { # $1 name  $2 csv
  if is_unset_placeholder "$2"; then
    echo "  $1: empty (no IP restriction configured)."
    return 0
  fi
  local oldifs="$IFS" e ok="1"
  IFS=','
  for e in $2; do
    e="$(printf '%s' "$e" | tr -d '[:space:]')"
    [ -n "$e" ] || continue
    if [ "$e" = "0.0.0.0/0" ] || [ "$e" = "0.0.0.0" ]; then
      add_finding WARN IP_ANY "$1 contains '$e' — equivalent to no restriction." "Tighten to specific developer/runner CIDRs."
      ok=""
    elif ! printf '%s' "$e" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$'; then
      add_finding FAIL IP_FORMAT "$1 entry '$e' is not a valid IPv4 address/CIDR." "Use X.X.X.X or X.X.X.X/Y, comma-separated, no spaces."
      ok=""
    fi
  done
  IFS="$oldifs"
  [ -n "$ok" ] && echo "  [OK] $1 entries look valid."
}
check_security_ip() {
  _validate_ip_list "project_IP_whitelist" "$PROJECT_IP_WHITELIST"
  _validate_ip_list "acr_IP_whitelist" "$ACR_IP_WHITELIST"
}

# =============================================================================
# 7c. LIVE regional-readiness helpers (provider/region support + DB regions)
# =============================================================================

# Echoes YES | NO | RT_MISSING | UNREG:<state> | "" (unknown) for provider+rt in $LOCATION.
_provider_region_status() { # $1 ns  $2 resourceType
  az_capture provider show --namespace "$1" -o json
  [ -n "$AZ_TRANSIENT" ] && { echo "TRANSIENT"; return; }
  [ -z "$AZ_OUT" ] && { echo ""; return; }
  PF_JSON="$AZ_OUT" "$PYBIN" - "$2" "$LOCATION" <<'PY' 2>/dev/null
import os, sys, json, re
rt_want = sys.argv[1]
loc = re.sub(r'[^a-z0-9]', '', sys.argv[2].lower())
try:
    d = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception:
    print(""); sys.exit(0)
state = str(d.get("registrationState", ""))
if state and state != "Registered":
    print("UNREG:" + state); sys.exit(0)
for rt in d.get("resourceTypes", []):
    if rt.get("resourceType") == rt_want:
        locs = [re.sub(r'[^a-z0-9]', '', str(x).lower()) for x in rt.get("locations", [])]
        print("YES" if loc in locs else "NO"); sys.exit(0)
print("RT_MISSING")
PY
}

check_provider_region() { # $1 ns  $2 rt  $3 display  $4 codePrefix
  local res; res="$(_provider_region_status "$1" "$2")"
  case "$res" in
    YES)        echo "  [OK] $3 supported in $LOCATION." ;;
    NO)         add_finding FAIL "${4}_NOT_IN_REGION" "$3 is not listed as supported in region '$LOCATION' for this subscription." "Pick a supported region or disable this service." ;;
    UNREG:*)    add_finding FAIL "${4}_PROVIDER_UNREG" "Provider $1 ($3) is '${res#UNREG:}', not 'Registered'." "Run: az provider register --namespace $1 --wait" ;;
    RT_MISSING) add_finding WARN "${4}_RT_MISSING" "Provider $1 did not report resource type $2 ($3)." ;;
    TRANSIENT)  add_finding WARN "${4}_REGION_UNVALIDATED" "Cannot validate $3 region support in '$LOCATION' at this moment (transient Azure error/timeout)." "Re-run preflight shortly." ;;
    *)          add_finding WARN "${4}_PROVIDER_LOOKUP" "Could not query provider $1 for $3." "Ensure 'az' is logged in and the provider is registered." ;;
  esac
}

check_cosmos_region() {
  is_true "$ENABLE_COSMOS" || return 0
  az_capture cosmosdb locations show --location "$LOCATION" \
    --query "{online:properties.status, az:properties.isSubscriptionRegionAccessAllowedForAz}" -o json
  if [ -n "$AZ_TRANSIENT" ]; then
    add_finding WARN COSMOS_REGION_UNVALIDATED "Cannot validate Cosmos DB region '$LOCATION' at this moment (transient Azure error/timeout)." "Re-run preflight shortly."
    return 0
  fi
  if [ -z "$AZ_OUT" ]; then
    add_finding WARN COSMOS_LOC_LOOKUP "Could not read Cosmos DB region metadata for '$LOCATION'."
    return 0
  fi
  local res; res="$(PF_JSON="$AZ_OUT" "$PYBIN" - <<'PY' 2>/dev/null
import os, sys, json
try: d = json.loads(os.environ.get("PF_JSON", "") or "")
except Exception: sys.exit(0)
online = str(d.get("online", "") or "")
az = bool(d.get("az"))
print(("ONLINE" if (not online or online == "Online") else "STATUS:" + online), ("AZ" if az else "NOAZ"))
PY
)"
  case "$res" in
    "STATUS:"*" "*) add_finding FAIL COSMOS_NOT_ONLINE "Cosmos DB region '$LOCATION' status is '${res%% *}', not 'Online'." "Pick a different region for Cosmos DB." ;;
    *NOAZ) add_finding WARN COSMOS_NO_AZ "Cosmos DB Availability-Zone support is not enabled for your subscription in '$LOCATION'." "Pick an AZ-capable region if zonal redundancy is required." ;;
    *) echo "  [OK] Cosmos DB region '$LOCATION' is Online (AZ supported)." ;;
  esac
}

# -----------------------------------------------------------------------------
# 8. Run checks per target subscription
# -----------------------------------------------------------------------------
echo "============================================================"
echo "   AI Factory PREFLIGHT"
echo "   region            : $LOCATION"
echo "   only-dev          : $ONLY_DEV"
echo "   AI Search         : enabled=$ENABLE_AI_SEARCH tier=$AI_SEARCH_TIER"
echo "   AI Foundry        : $ENABLE_AI_FOUNDRY   Azure OpenAI: $ENABLE_AOAI"
echo "   Cosmos DB         : $ENABLE_COSMOS       Elasticsearch: $ENABLE_ELASTIC"
echo "   model deployments : ${#MODELS[@]} -> ${MODELS[*]:-none}"
echo "   target envs       : ${TARGETS[*]:-none}"
echo "============================================================"

# --- Static config categories (subscription-independent; run once) -----------
echo ""
echo "=== Config: variables.yaml placeholders ==="
check_config_placeholders
echo ""
echo "=== BYO: subnets & App Service Environment ==="
check_byo_subnets
check_byo_ase
echo ""
echo "=== Networking: CIDR sanity & AKS ==="
check_cidr_sanity
check_aks_networking
echo ""
echo "=== Observability ==="
check_observability
echo ""
echo "=== Security: IP allow-lists ==="
check_security_ip

if [ "$SKIP_AZURE" = "true" ]; then
  echo ""
  echo "(Azure lookups skipped: --skip-azure-lookups / PREFLIGHT_SKIP_AZURE_LOOKUPS — only static config checks ran.)"
fi

for t in "${TARGETS[@]:-}"; do
  [ -n "$t" ] || continue
  [ "$SKIP_AZURE" = "true" ] && break
  envname="${t%%|*}"; sub="${t#*|}"
  echo ""
  echo "--- [$envname] subscription $sub ----------------------------------------"
  if ! az account set --subscription "$sub" 2>/dev/null; then
    add_finding WARN SUB_NO_ACCESS \
      "Cannot select subscription $sub for env '$envname' (no access from this identity) — skipped." \
      "This is expected when a dev service connection cannot read test/prod. Run preflight from each environment's pipeline stage."
    continue
  fi

  echo "=== Networking: policy & resource providers ==="
  list_policy_assignments "$sub"
  check_resource_providers "$sub"
  check_elasticsearch_block "$sub"

  if [ "$SKIP_REGIONAL" = "true" ]; then
    echo ""
    echo "(Regional readiness skipped: --skip-regional / LZ_PREFLIGHT_REGIONAL_SKIP.)"
    continue
  fi

  echo ""
  echo "=== Regional readiness: provider/region support ==="
  is_true "$ENABLE_AI_SEARCH"  && check_provider_region Microsoft.Search           searchServices    "Azure AI Search"            SEARCH
  is_true "$ENABLE_COSMOS"     && check_provider_region Microsoft.DocumentDB        databaseAccounts  "Azure Cosmos DB"            COSMOS
  is_true "$ENABLE_AI_FOUNDRY" && check_provider_region Microsoft.CognitiveServices accounts          "Azure AI Foundry / OpenAI"  COGSVC
  is_true "$ENABLE_WEBAPP" || is_true "$ENABLE_FUNCTION" && check_provider_region Microsoft.Web sites "Azure App Service / Functions" WEB
  is_true "$ENABLE_REDIS"     && check_provider_region Microsoft.Cache            Redis             "Azure Cache for Redis"          REDIS
  is_true "$ENABLE_POSTGRES"  && check_provider_region Microsoft.DBforPostgreSQL  flexibleServers   "Azure Database for PostgreSQL"  POSTGRES
  is_true "$ENABLE_SQLDB"     && check_provider_region Microsoft.Sql              servers           "Azure SQL Database"             SQL
  is_true "$ENABLE_ELASTIC"   && check_provider_region Microsoft.Elastic          monitors          "Elasticsearch (Elastic Cloud)"  ELASTIC

  echo ""
  echo "=== Regional readiness: quotas & service availability ==="
  check_ai_search_quota "$sub"
  check_model_quota "$sub"
  check_cs_headroom "$sub"
  check_cosmos_region
done


# -----------------------------------------------------------------------------
# 9. Report + exit
# -----------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " PREFLIGHT RESULT: ${FAIL_COUNT} FAIL / ${WARN_COUNT} WARN"
echo "============================================================"
if [ "${#FINDINGS[@]}" -gt 0 ]; then
  for f in "${FINDINGS[@]}"; do
    sev="${f%%|*}"; rest="${f#*|}"; code="${rest%%|*}"; rest="${rest#*|}"; msg="${rest%%|*}"; hint="${rest#*|}"
    echo " [$sev] $code: $msg"
    [ -n "$hint" ] && echo "         hint: $hint"
  done
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
  if [ "$WARN_ONLY" = "true" ]; then
    echo ""
    echo "preflight found $FAIL_COUNT issue(s) but WARN_ONLY=true -> NOT failing the task (exit 0)."
    echo "Review the findings above. Set PREFLIGHT_WARN_ONLY=false (or pass --no-warn-only) to enforce hard failures."
    exit 0
  fi
  echo ""
  echo "preflight FAILED with $FAIL_COUNT blocking finding(s). Aborting deployment."
  exit 1
fi
if [ "$WARN_COUNT" -gt 0 ] && [ "$STRICT" = "true" ]; then
  echo ""
  echo "preflight: warnings present and --strict set. Aborting deployment."
  exit 2
fi
echo ""
echo "preflight passed. Deployment may proceed."
exit 0
