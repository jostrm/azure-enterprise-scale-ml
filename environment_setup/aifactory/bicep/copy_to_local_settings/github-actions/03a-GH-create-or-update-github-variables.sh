#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Verify gh is available and authenticated
if ! command -v gh >/dev/null 2>&1; then
  echo -e "${RED}Error: GitHub CLI (gh) not found. Install it first.${NC}"
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo -e "${RED}Error: GitHub CLI not authenticated. Run 'gh auth login' first.${NC}"
  exit 1
fi

# Load .env file
if [ -f .env ]; then
  set -o allexport
  source .env
  set +o allexport
else
  echo "Error: .env file not found."
  exit 1
fi

if [ -z "$GITHUB_NEW_REPO" ]; then
  echo -e "${RED}Error: GITHUB_NEW_REPO is not set in .env. Example: org/repo or user/repo.${NC}"
  exit 1
fi

# DIRECTORIES
current_dir=$(pwd)

# Rate limit safety: track operations and pause mid-way
op_counter=0
rate_limit_pause_after=50
rate_limit_pause_after_2=85
rate_limit_sleep_seconds=30
rate_limit_sleep_seconds_2=30
start_from_op=1  # QUICK UPDATE TIP: Run script once and note operation number at "QUICK UPDATE SECTION" message, then set this to that number
run_current_op=true

increment_counter() {
  op_counter=$((op_counter + 1))
  echo -e "${YELLOW}[${op_counter}] Processing: $1${NC}"
  if [[ $op_counter -lt $start_from_op ]]; then
    echo -e "${YELLOW}Skipping operation ${op_counter} (waiting to start at ${start_from_op})${NC}"
    run_current_op=false
    return
  fi

  run_current_op=true

  if [[ $op_counter -eq $rate_limit_pause_after ]]; then
    echo -e "${YELLOW}Hit ${rate_limit_pause_after} operations. Sleeping ${rate_limit_sleep_seconds}s to avoid GitHub secondary rate limits...${NC}"
    sleep "$rate_limit_sleep_seconds"
  elif [[ $op_counter -eq $rate_limit_pause_after_2 ]]; then
    echo -e "${YELLOW}Hit ${rate_limit_pause_after_2} operations. Sleeping ${rate_limit_sleep_seconds_2}s to avoid GitHub secondary rate limits...${NC}"
    sleep "$rate_limit_sleep_seconds_2"
  fi
}

# Function to check if a variable exists
check_variable_exists() {
  gh api repos/$GITHUB_NEW_REPO/environments/$1/variables/$2 > /dev/null 2>&1
}

# Function to create or update a variable
create_or_update_variable() {
  local env=$1
  local name=$2
  local value=$3
  # Check if the value is empty
  if [[ -z "$value" ]]; then
    # #echo -e "${RED}Error: Variable '$name' for environment '$env' has an empty value. Skipping.${NC}"
    echo -e "${YELLOW}Skipping variable '$name' for environment '$env' because the value is empty.${NC}"
    return
  fi

  increment_counter "variable $env/$name"
  if [[ "$run_current_op" != "true" ]]; then
    return
  fi
  if check_variable_exists $env $name; then
    gh api --method PATCH -H "Accept: application/vnd.github+json" repos/$GITHUB_NEW_REPO/environments/$env/variables/$name -f value="$value"
  else
    gh api --method POST -H "Accept: application/vnd.github+json" repos/$GITHUB_NEW_REPO/environments/$env/variables -f name=$name -f value="$value"
  fi
}

# Function to check if a secret exists
check_secret_exists() {
  gh secret list --repo $GITHUB_NEW_REPO --env $1 | grep -q $2
}

# Function to create or update a secret
create_or_update_secret() {
  local env=$1
  local name=$2
  local value=$3
  increment_counter "secret $env/$name"
  if [[ "$run_current_op" != "true" ]]; then
    return
  fi
  if check_secret_exists $env $name; then
    gh secret set $name --repo $GITHUB_NEW_REPO --env $env --body "$value"
  else
    gh secret set $name --repo $GITHUB_NEW_REPO --env $env --body "$value"
  fi
}

# Repo-level variable helper (used to offload common flags and reduce env var count)
create_or_update_repo_variable() {
  local name=$1
  local value=$2
  if [[ -z "$value" ]]; then
    echo -e "${YELLOW}Skipping repo variable '$name' because the value is empty.${NC}"
    return
  fi
  gh variable set "$name" --repo "$GITHUB_NEW_REPO" --body "$value"
}

# Prompt user for environment to run (default DEV) to avoid unnecessary rate-limited calls
echo -e "${YELLOW}Select environment to run (d=DEV, s=STAGE, p=PROD, a=ALL). Default is DEV:${NC}"
read -p "env [d/s/p/a]: " env_choice
case "${env_choice,,}" in
  a|all)  selected_environments=("dev" "stage" "prod") ;;
  s|stage) selected_environments=("stage") ;;
  p|prod)  selected_environments=("prod") ;;
  d|dev|"") selected_environments=("dev") ;;
  *) echo -e "${YELLOW}Unrecognized choice. Defaulting to DEV.${NC}"; selected_environments=("dev") ;;
esac

# Prompt for optional resume position
echo -e "${YELLOW}Optional: resume from operation number (1-based). Leave empty to start from 1.${NC}"
echo -e "${YELLOW}TIP: Set to 82 to update Project number and ENABLE_ flags.${NC}"
read -p "start_from_op: " start_from_input
if [[ -n "$start_from_input" && "$start_from_input" =~ ^[0-9]+$ ]]; then
  start_from_op=$start_from_input
  echo -e "${YELLOW}Will start executing at operation ${start_from_op}.${NC}"
else
  start_from_op=1
fi

# Prompt user for orchestrator choice
echo -e "${YELLOW}Do you want to overwrite AZURE_CREDENTIALS with dummy value? Usually only the 1st time this is needed, to create the variable in Github (Enter 'y' or 'n')${NC}"
read -p "overwrite_azure_credential: " overwrite_azure_credential

echo -e "${YELLOW}Bootstraps config from .env as Github environment variables and secrets. ${NC}"

# Get the GitHub CLI version
gh_version=$(gh --version | grep -oP '\d+\.\d+\.\d+' | head -n 1)

# Helper to get AZURE_ENV_NAME per environment
get_azure_env_name() {
  case "$1" in
    dev) echo "dev" ;;
    stage) echo "test" ;;
    prod) echo "prod" ;;
  esac
}

# Optional (v1.23+): service enable flags and BYO customization variables.
# If a value is empty, it will be skipped.
service_and_byo_vars=(
  "UPDATE_AI_FOUNDRY"
  "FOUNDRY_DEPLOYMENT_TYPE"
  "DISABLE_AGENT_NETWORK_INJECTION"

  "ADMIN_AISEARCH_TIER"

  "VNET_RESOURCE_GROUP_PARAM"
  "VNET_NAME_FULL_PARAM"
  "SUBNET_COMMON"
  "SUBNET_COMMON_SCORING"
  "SUBNET_COMMON_POWERBI_GW"
  "SUBNET_PROJ_GENAI"
  "SUBNET_PROJ_AKS"
  "SUBNET_PROJ_AKS2"
  "SUBNET_PROJ_ACA"
  "SUBNET_PROJ_ACA2"
  "SUBNET_PROJ_DATABRICKS_PUBLIC"
  "SUBNET_PROJ_DATABRICKS_PRIVATE"
  "BYO_ASEV3"
  "BYO_ASE_FULL_RESOURCE_ID"
  "BYO_ASE_APP_SERVICE_PLAN_RESOURCE_ID"
  "DEPLOY_MODEL_GPT_X"
  "MODEL_GPTX_NAME"
  "MODEL_GPTX_VERSION"
  "MODEL_GPTX_SKU"
  "MODEL_GPTX_CAPACITY"
  "DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002"
  "DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE"
  "DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL"
  "DEFAULT_EMBEDDING_CAPACITY"
  "DEPLOY_MODEL_GPT_4O_MINI"
  "DEFAULT_GPT_4O_MINI_VERSION"
  "DEPLOY_MODEL_GPT_4O"
  "DEFAULT_GPT_4O_VERSION"
  "DEFAULT_GPT_CAPACITY"
  "DEFAULT_MODEL_SKU"

  "COSMOS_KIND"
  "POSTGRES_ADMIN_EMAILS"

  "FUNCTION_RUNTIME"
  "FUNCTION_VERSION"
  "WEBAPP_RUNTIME"
  "WEBAPP_RUNTIME_VERSION"
  "ASE_SKU"
  "ASE_SKU_CODE"
  "ASE_SKU_WORKERS"

  "ACA_W_REGISTRY_IMAGE"

  "FOUNDRY_API_MANAGEMENT_RESOURCE_ID"


  # Low priority: run all ADD_* last
  "DEBUG_DISABLE_05_BUILD_ACR_IMAGE"
  "DEBUG_DISABLE_61_FOUNDATION"
  "DEBUG_DISABLE_62_CORE_INFRASTRUCTURE"
  "DEBUG_DISABLE_63_COGNITIVE_SERVICES"
  "DEBUG_DISABLE_64_DATABASES"
  "DEBUG_DISABLE_65_COMPUTE_SERVICES"
  "DEBUG_DISABLE_66_AI_PLATFORM"
  "DEBUG_DISABLE_67_ML_PLATFORM"
  "DEBUG_DISABLE_68_INTEGRATION"
  "DEBUG_DISABLE_69_AIFOUNDRY_2025"
  "DEBUG_DISABLE_100_RBAC_SECURITY"
  "DEBUG_DISABLE_10_AIFACTORY_DASHBOARDS"
  "ADD_AI_FOUNDRY_HUB"
  "ADD_AI_FOUNDRY"
  "ADD_AI_SEARCH"
  "ADD_AZURE_MACHINE_LEARNING"
)

# Repo-scoped variables to reduce env variable count (applied once per repo)
repo_level_vars=(
  "ENABLE_DEFENDER_FOR_AI_SUB_LEVEL"
  "ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL"
  "CMK"
  "CMK_KEY_NAME"
  "CMK_KEY_VERSION"
  "ADMIN_AISEARCH_TIER"
  "PROJECT_PREFIX"
  "PROJECT_SUFFIX"
  "UPDATE_KEYVAULT_RBAC"
  "AIFACTORY_COMMON_ONLY_DEV_ENVIRONMENT"
  "ADMIN_USERNAME"
  "ADMIN_HYBRID_BENEFIT"
  "ADMIN_COMMON_RESOURCE_SUFFIX"
  "ADMIN_PRJ_RESOURCE_SUFFIX"
  "VNET_RESOURCE_GROUP_BASE"
  "VNET_NAME_BASE"
  "SUBNET_COMMON_BASE"
  "COMMON_VNET_CIDR"
  "COMMON_SUBNET_CIDR"
  "COMMON_SUBNET_SCORING_CIDR"
  "COMMON_PBI_SUBNET_NAME"
  "COMMON_PBI_SUBNET_CIDR"
  "COMMON_BASTION_SUBNET_NAME"
  "COMMON_BASTION_SUBNET_CIDR"
  "DISABLE_WHITELISTING_FOR_BUILD_AGENTS"
  "USE_COMMON_ACR_OVERRIDE"
  "ACR_IP_WHITELIST"
  "ACR_ADMIN_USER_ENABLED"
  "ACR_DEDICATED"
  "ACR_SKU"
  # === RBAC: Contributor role override ===
  "BYO_CONTRIBUTOR_ROLE_ID"
  # === Complete mode vs Incremental mode ===
  "ENABLE_DELETE_FOR_DISABLED_RESOURCES"
  "DELETE_ALL_SERVICES_FOR_PROJECT"
  # All ENABLE_* flags moved to repo-level
  "ENABLE_AI_SERVICES"
  "ENABLE_AI_FOUNDRY_HUB"
  "ENABLE_AI_FOUNDRY"
  "ENABLE_AFOUNDRY_CAPHOST"
  "ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2"
  "ENABLE_DATAFACTORY"
  "ENABLE_DATAFACTORY_COMMON"
  "ENABLE_AZURE_MACHINE_LEARNING"
  "ENABLE_AKS_FOR_AZURE_ML"
  "ENABLE_DATABRICKS"
  "ENABLE_AI_SEARCH"
  "ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK"
  "ENABLE_AZURE_OPENAI"
  "ENABLE_AZURE_AI_VISION"
  "ENABLE_AZURE_SPEECH"
  "ENABLE_AI_DOC_INTELLIGENCE"
  "ENABLE_BING"
  "ENABLE_BING_CUSTOM_SEARCH"
  "ENABLE_CONTENT_SAFETY"
  "ENABLE_COSMOS_DB"
  "ENABLE_POSTGRESQL"
  "ENABLE_REDIS_CACHE"
  "ENABLE_SQL_DATABASE"
  "ENABLE_FUNCTION"
  "ENABLE_WEBAPP"
  "ENABLE_CONTAINER_APPS"
  "ENABLE_APPINSIGHTS_DASHBOARD"
  "ENABLE_LOGIC_APPS"
  "ENABLE_EVENT_HUBS"
  "ENABLE_BOT_SERVICE"
  "NETWORKING_GENAI_PRIVATE_PRIVATE_UI"
  "DEV_NETWORK_ENV"
  "STAGE_NETWORK_ENV"
  "PROD_NETWORK_ENV"
  "AKS_OUTBOUND_TYPE"
  "AKS_PRIVATE_DNS_ZONE"
  "AKS_AZURE_FIREWALL_PRIVATE_IP"
  "ADMIN_AKS_GPU_SKU_DEV_OVERRIDE"
  "ADMIN_AKS_GPU_SKU_TEST_PROD_OVERRIDE"
  "ADMIN_AKS_NODES_DEV_OVERRIDE"
  "ADMIN_AKS_NODES_TEST_PROD_OVERRIDE"
  "ADMIN_AKS_VERSION_OVERRIDE"
  "ADMIN_AML_CLUSTER_MAX_NODES_DEV_OVERRIDE"
  "ADMIN_AML_CLUSTER_MAX_NODES_TEST_PROD_OVERRIDE"
  "ADMIN_AML_CLUSTER_SKU_DEV_OVERRIDE"
  "ADMIN_AML_CLUSTER_SKU_TEST_PROD_OVERRIDE"
  "ADMIN_AML_COMPUTE_INSTANCE_DEV_SKU_OVERRIDE"
  "ADMIN_AML_COMPUTE_INSTANCE_TEST_PROD_SKU_OVERRIDE"
  "TAGS"
  "SERVICE_SETTING_DEPLOY_PROJECT_VM"
  "DEBUG_DISABLE_VALIDATION_TASKS"
  "ADMIN_AI_SEARCH_TIER"
  "INPUT_COMMON_SPID_KEY"
  "INPUT_COMMON_SPSECRET_KEY"
  "INPUT_COMMON_SP_SECRET_KEY"
  "COMMON_SERVICE_PRINCIPLE_OID_KEY"
)

# Apply repo-level variables once to reduce environment-level count
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}GitHub Variables Update Script${NC}"
echo -e "${GREEN}================================================${NC}"
echo -e "${YELLOW}TIP: To quickly update frequently-changed variables only:${NC}"
echo -e "${YELLOW}  - Edit this script and set start_from_op to the appropriate number${NC}"
echo -e "${YELLOW}  - Frequently updated variables are processed LAST in each environment:${NC}"
echo -e "${YELLOW}    • PROJECT_NUMBER, PROJECT_MEMBERS, PROJECT_MEMBERS_EMAILS${NC}"
echo -e "${YELLOW}    • PROJECT_IP_WHITELIST, PROJECT_MEMBERS_IP_ADDRESS${NC}"
echo -e "${YELLOW}    • TAGS_PROJECT${NC}"
echo -e "${YELLOW}    • All ENABLE_* flags${NC}"
echo -e "${YELLOW}  - Watch the [operation_number] output to find the right start_from_op${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

for var_name in "${repo_level_vars[@]}"; do
  var_value="${!var_name}"
  # Strip outer single quotes from TAGS and TAGS_PROJECT
  if [[ "$var_name" == "TAGS" || "$var_name" == "TAGS_PROJECT" ]]; then
    var_value="${var_value#\'}"
    var_value="${var_value%\'}"
  fi
  create_or_update_repo_variable "$var_name" "$var_value"
done

for env in "${selected_environments[@]}"; do
  gh api --method PUT -H "Accept: application/vnd.github+json" repos/$GITHUB_NEW_REPO/environments/$env
  create_or_update_variable "$env" "AZURE_ENV_NAME" "$(get_azure_env_name "$env")"
done

# AI Factory globals: variables and secrets
for env in "${selected_environments[@]}"; do
    echo -e "${YELLOW}Setting variables and secrets for environment: $env${NC}"
    
    # Global: Variables
    create_or_update_variable $env "AIFACTORY_LOCATION" "$AIFACTORY_LOCATION"
    create_or_update_variable $env "AIFACTORY_LOCATION_SHORT" "$AIFACTORY_LOCATION_SHORT"
    create_or_update_variable $env "AIFACTORY_SUFFIX" "$AIFACTORY_SUFFIX"
    create_or_update_variable $env "AIFACTORY_PREFIX" "$AIFACTORY_PREFIX"
    create_or_update_variable $env "TENANT_AZUREML_OID" "$TENANT_AZUREML_OID"
    create_or_update_variable $env "LAKE_PREFIX" "$LAKE_PREFIX"
    create_or_update_variable $env "AISEARCH_SEMANTIC_TIER" "$AISEARCH_SEMANTIC_TIER"

    #RBAC model
    create_or_update_variable $env "USE_AD_GROUPS" "$USE_AD_GROUPS"
    create_or_update_variable $env "GROUPS_PROJECT_MEMBERS_ESML" "$GROUPS_PROJECT_MEMBERS_ESML"
    create_or_update_variable $env "GROUPS_PROJECT_MEMBERS_GENAI_1" "$GROUPS_PROJECT_MEMBERS_GENAI_1"
    create_or_update_variable $env "GROUPS_CORETEAM_MEMBERS" "$GROUPS_CORETEAM_MEMBERS"

    # Other
    create_or_update_variable $env "KEYVAULT_SOFT_DELETE" "$KEYVAULT_SOFT_DELETE"
    
    # Cost optimization
    create_or_update_variable $env "USE_COMMON_ACR_FOR_PROJECTS" "$USE_COMMON_ACR_FOR_PROJECTS"

    # Seeding keyvault
    create_or_update_variable $env "AIFACTORY_SEEDING_KEYVAULT_NAME" "$AIFACTORY_SEEDING_KEYVAULT_NAME"
    create_or_update_variable $env "AIFACTORY_SEEDING_KEYVAULT_RG" "$AIFACTORY_SEEDING_KEYVAULT_RG"
    create_or_update_variable $env "COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID" "$COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID"
    create_or_update_variable $env "COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET" "$COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET"
    create_or_update_variable $env "INPUT_COMMON_SPID_KEY" "$INPUT_COMMON_SPID_KEY"
    create_or_update_variable $env "INPUT_COMMON_SPSECRET_KEY" "$INPUT_COMMON_SPSECRET_KEY"
    create_or_update_variable $env "INPUT_COMMON_SP_SECRET_KEY" "$INPUT_COMMON_SP_SECRET_KEY"
    create_or_update_variable $env "COMMON_SERVICE_PRINCIPLE_OID_KEY" "$COMMON_SERVICE_PRINCIPLE_OID_KEY"

    # Networking
    create_or_update_variable $env "AIFACTORY_LOCATION_SHORT" "$AIFACTORY_LOCATION_SHORT"
    
    # Project specific settings, for all environments
    create_or_update_variable $env "PROJECT_TYPE" "$PROJECT_TYPE"
    create_or_update_variable $env "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID" "$PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID"
    create_or_update_variable $env "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID" "$PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID"
    create_or_update_variable $env "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S" "$PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S"

    # Misc
    create_or_update_variable $env "RUN_JOB1_NETWORKING" "$RUN_JOB1_NETWORKING"

    # Global: Secrets
    create_or_update_secret $env "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID" "$AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID"
    
    # Project Specifics (1st project bootstrap): 
    create_or_update_secret $env "TENANT_ID" "$TENANT_ID"
    # Variables: 
    create_or_update_variable $env "BYO_SUBNETS" "$BYO_SUBNETS"
    create_or_update_variable $env "AIFACTORY_VERSION_MAJOR" "$AIFACTORY_VERSION_MAJOR"
    create_or_update_variable $env "AIFACTORY_VERSION_MINOR" "$AIFACTORY_VERSION_MINOR"
    create_or_update_variable $env "AIFACTORY_SALT" "$AIFACTORY_SALT"
    create_or_update_variable $env "AIFACTORY_SALT_RANDOM" "$AIFACTORY_SALT_RANDOM"

    # ========================================================================
    # FREQUENTLY UPDATED VARIABLES - Positioned last for quick start_from_op
    # ========================================================================
    echo -e "${GREEN}>>> QUICK UPDATE SECTION for $env - Note the operation number above! <<<${NC}"
    # Project-specific variables (moved to end for quick updates)
    create_or_update_variable $env "PROJECT_NUMBER" "$PROJECT_NUMBER"
    create_or_update_variable $env "PROJECT_MEMBERS_EMAILS" "$PROJECT_MEMBERS_EMAILS"
    create_or_update_variable $env "PROJECT_IP_WHITELIST" "$PROJECT_IP_WHITELIST"
    create_or_update_variable $env "TAGS_PROJECT" "$TAGS_PROJECT"
    
    # Project member secrets
    create_or_update_secret $env "PROJECT_MEMBERS" "$PROJECT_MEMBERS"
    create_or_update_secret $env "PROJECT_MEMBERS_IP_ADDRESS" "$PROJECT_MEMBERS_IP_ADDRESS"

    # v1.23+ enable flags + BYO customization variables (includes all ENABLE_* flags)
    for var_name in "${service_and_byo_vars[@]}"; do
      create_or_update_variable "$env" "$var_name" "${!var_name}"
    done
done

if [[ " ${selected_environments[*]} " == *" dev "* ]]; then
  create_or_update_variable "dev" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
  create_or_update_variable "dev" "AZURE_SUBSCRIPTION_ID" "$DEV_SUBSCRIPTION_ID"
  create_or_update_variable "dev" "CIDR_RANGE" "$DEV_CIDR_RANGE"
  create_or_update_variable "dev" "DEV_CIDR_RANGE" "$DEV_CIDR_RANGE"
  create_or_update_variable "dev" "AIFACTORY_CIDR_XX" "$DEV_CIDR_RANGE"
  create_or_update_variable "dev" "DEV_NETWORK_ENV" "$DEV_NETWORK_ENV"
  create_or_update_variable "dev" "NETWORK_ENV" "$DEV_NETWORK_ENV"
  if [[ "$overwrite_azure_credential" == "y" ]]; then
    create_or_update_secret "dev" "AZURE_CREDENTIALS" "replace_with_dev_sp_credentials"
  fi
fi

if [[ " ${selected_environments[*]} " == *" stage "* ]]; then
  create_or_update_variable "stage" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
  create_or_update_variable "stage" "AZURE_SUBSCRIPTION_ID" "$STAGE_SUBSCRIPTION_ID"
  create_or_update_variable "stage" "CIDR_RANGE" "$STAGE_CIDR_RANGE"
  create_or_update_variable "stage" "STAGE_CIDR_RANGE" "$STAGE_CIDR_RANGE"
  create_or_update_variable "stage" "AIFACTORY_CIDR_XX" "$STAGE_CIDR_RANGE"
  create_or_update_variable "stage" "STAGE_NETWORK_ENV" "$STAGE_NETWORK_ENV"
  create_or_update_variable "stage" "NETWORK_ENV" "$STAGE_NETWORK_ENV"
  if [[ "$overwrite_azure_credential" == "y" ]]; then
    create_or_update_secret "stage" "AZURE_CREDENTIALS" "replace_with_stage_sp_credentials"
  fi
fi

if [[ " ${selected_environments[*]} " == *" prod "* ]]; then
  create_or_update_variable "prod" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
  create_or_update_variable "prod" "AZURE_SUBSCRIPTION_ID" "$PROD_SUBSCRIPTION_ID"
  create_or_update_variable "prod" "CIDR_RANGE" "$PROD_CIDR_RANGE"
  create_or_update_variable "prod" "PROD_CIDR_RANGE" "$PROD_CIDR_RANGE"
  create_or_update_variable "prod" "AIFACTORY_CIDR_XX" "$PROD_CIDR_RANGE"
  create_or_update_variable "prod" "PROD_NETWORK_ENV" "$PROD_NETWORK_ENV"
  create_or_update_variable "prod" "NETWORK_ENV" "$PROD_NETWORK_ENV"
  if [[ "$overwrite_azure_credential" == "y" ]]; then
    create_or_update_secret "prod" "AZURE_CREDENTIALS" "replace_with_prod_sp_credentials"
  fi
fi