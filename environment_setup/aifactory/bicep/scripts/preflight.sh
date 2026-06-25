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
SKIP="${PREFLIGHT_SKIP:-false}"
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
  --skip                   Skip all checks and exit 0 (escape hatch)
  -h | --help              Show this help
Environment escape hatch: set PREFLIGHT_SKIP=true to bypass.
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
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)); ci_error  "[$2] $3";;
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

check_ai_search_quota() { # $1 subId
  is_true "$ENABLE_AI_SEARCH" || return 0
  local sub="$1" sku url payload limit cur avail
  sku="$(lc "$AI_SEARCH_TIER")"
  url="https://management.azure.com/subscriptions/$sub/providers/Microsoft.Search/locations/$LOCATION/usages?api-version=2025-05-01"
  payload="$(az rest --method get --url "$url" -o json 2>/dev/null)"
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
  "$PYBIN" - "$1" <<'PY' 2>/dev/null || true
import sys, json
sku = sys.argv[1].lower()
try:
    data = json.load(sys.stdin)
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
  usage="$(az cognitiveservices usage list --location "$LOCATION" -o json 2>/dev/null)"
  if [ -z "$usage" ]; then
    add_finding WARN MODEL_QUOTA_LOOKUP "Could not read Cognitive Services usage/quota for '$LOCATION' (sub $sub)." \
      "Run: az cognitiveservices usage list --location $LOCATION ; verify Microsoft.CognitiveServices is registered."
    return 0
  fi
  for m in "${MODELS[@]}"; do
    name="${m%%|*}"; sku="$(printf '%s' "$m" | cut -d'|' -f2)"; cap="${m##*|}"
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
  "$PYBIN" - "$1" <<'PY' 2>/dev/null || true
import sys, json
qn = sys.argv[1]
try:
    data = json.load(sys.stdin)
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
  payload="$(az rest --method get --url "$url" -o json 2>/dev/null)"
  [ -n "$payload" ] || { add_finding WARN CS_QUOTA_LOOKUP "Could not read Cognitive Services usage for '$LOCATION'." \
      "Verify Microsoft.CognitiveServices is registered and identity has Reader."; return 0; }
  res="$(printf '%s' "$payload" | "$PYBIN" - <<'PY' 2>/dev/null || true
import sys, json
try: data = json.load(sys.stdin)
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
  count="$(printf '%s' "$json" | "$PYBIN" - <<'PY' 2>/dev/null || echo 0
import sys, json
try: data = json.load(sys.stdin)
except Exception: data = []
names = [ (a.get("displayName") or a.get("name") or "?") for a in data ]
print(len(names))
for n in names: print("    - "+str(n))
PY
)"
  echo "  Policy assignments on subscription $sub:"
  printf '%s\n' "$count" | tail -n +2
  echo "  ($(printf '%s' "$count" | head -n1) policy assignment(s) total)"
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
  blocked="$(printf '%s' "$json" | "$PYBIN" - <<'PY' 2>/dev/null || true
import sys, json
try: data = json.load(sys.stdin)
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

# -----------------------------------------------------------------------------
# 8. Run checks per target subscription
# -----------------------------------------------------------------------------
echo "============================================================"
echo " AI Factory PREFLIGHT"
echo "   region            : $LOCATION"
echo "   only-dev          : $ONLY_DEV"
echo "   AI Search         : enabled=$ENABLE_AI_SEARCH tier=$AI_SEARCH_TIER"
echo "   AI Foundry        : $ENABLE_AI_FOUNDRY   Azure OpenAI: $ENABLE_AOAI"
echo "   Cosmos DB         : $ENABLE_COSMOS       Elasticsearch: $ENABLE_ELASTIC"
echo "   model deployments : ${#MODELS[@]} -> ${MODELS[*]:-none}"
echo "   target envs       : ${TARGETS[*]:-none}"
echo "============================================================"

for t in "${TARGETS[@]:-}"; do
  [ -n "$t" ] || continue
  envname="${t%%|*}"; sub="${t#*|}"
  echo ""
  echo "--- [$envname] subscription $sub ----------------------------------------"
  if ! az account set --subscription "$sub" 2>/dev/null; then
    add_finding WARN SUB_NO_ACCESS \
      "Cannot select subscription $sub for env '$envname' (no access from this identity) — skipped." \
      "This is expected when a dev service connection cannot read test/prod. Run preflight from each environment's pipeline stage."
    continue
  fi
  list_policy_assignments "$sub"
  check_resource_providers "$sub"
  check_ai_search_quota "$sub"
  check_model_quota "$sub"
  check_cs_headroom "$sub"
  check_elasticsearch_block "$sub"
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
