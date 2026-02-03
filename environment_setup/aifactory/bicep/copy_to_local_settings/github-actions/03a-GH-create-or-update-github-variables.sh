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
  set -o allexport -
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
  if check_secret_exists $env $name; then
    gh secret set $name --repo $GITHUB_NEW_REPO --env $env --body "$value"
  else
    gh secret set $name --repo $GITHUB_NEW_REPO --env $env --body "$value"
  fi
}

# Prompt user for orchestrator choice
echo -e "${YELLOW}Do you want to overwrite AZURE_CREDENTIALS with dummy value? Usually only the 1st time this is needed, to create the variable in Github (Enter 'y' or 'n')${NC}"
read -p "overwrite_azure_credential: " overwrite_azure_credential

echo -e "${YELLOW}Bootstraps config from .env as Github environment variables and secrets. ${NC}"

# Get the GitHub CLI version
gh_version=$(gh --version | grep -oP '\d+\.\d+\.\d+' | head -n 1)

# Define environments
environments=("dev" "stage" "prod")

# Optional (v1.23+): service enable flags and BYO customization variables.
# If a value is empty, it will be skipped.
service_and_byo_vars=(
  "ENABLE_DEFENDER_FOR_AI_SUB_LEVEL"
  "ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL"
  "CMK"
  "CMK_KEY_NAME"
  "CMK_KEY_VERSION"
  "UPDATE_KEYVAULT_RBAC"

  "ENABLE_AI_SERVICES"
  "ENABLE_AI_FOUNDRY_HUB"
  "ADD_AI_FOUNDRY_HUB"
  "ENABLE_AI_FOUNDRY"
  "UPDATE_AI_FOUNDRY"
  "ADD_AI_FOUNDRY"
  "ENABLE_AFOUNDRY_CAPHOST"
  "FOUNDRY_DEPLOYMENT_TYPE"
  "ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2"
  "DISABLE_AGENT_NETWORK_INJECTION"

  "ADMIN_AISEARCH_TIER"

  "AIFACTORY_COMMON_ONLY_DEV_ENVIRONMENT"
  "ADMIN_COMMON_RESOURCE_SUFFIX"
  "ADMIN_PRJ_RESOURCE_SUFFIX"
  "DISABLE_WHITELISTING_FOR_BUILD_AGENTS"
  "USE_COMMON_ACR_OVERRIDE"
  "COMMON_RESOURCE_GROUP_PARAM"
  "DATALAKE_NAME_PARAM"
  "KV_NAME_FROM_COMMON_PARAM"
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
  "NETWORKING_GENAI_PRIVATE_PRIVATE_UI"
  "DEV_BYO_VNET_NAME"
  "DEV_BYO_VNET_RG"
  "STAGE_BYO_VNET_NAME"
  "STAGE_BYO_VNET_RG"
  "PROD_BYO_VNET_NAME"
  "PROD_BYO_VNET_RG"
  "DEV_VNET_IP_RANGE"
  "DEV_SNET_CMN_IP_RANGE"
  "DEV_SNET_CMN_INFERENCE_IP_RANGE"
  "DEV_SNET_POWERBI_IP_RANGE"
  "DEV_SNET_BASTION_IP_RANGE"
  "STAGE_SNET_CMN_IP_RANGE"
  "STAGE_SNET_CMN_INFERENCE_IP_RANGE"
  "STAGE_SNET_POWERBI_IP_RANGE"
  "STAGE_SNET_BASTION_IP_RANGE"
  "STAGE_VNET_IP_RANGE"
  "PROD_SNET_CMN_IP_RANGE"
  "PROD_SNET_CMN_INFERENCE_IP_RANGE"
  "PROD_SNET_POWERBI_IP_RANGE"
  "PROD_SNET_BASTION_IP_RANGE"
  "PROD_VNET_IP_RANGE"
  "NETWORK_ENV_STAGE"
  "NETWORK_ENV_PROD"
  "DEV_NETWORK_ENV"
  "STAGE_NETWORK_ENV"
  "PROD_NETWORK_ENV"
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
  "DEBUG_ENABLE_CLEANING"
  "ENABLE_RETRIES"
  "RETRY_MINUTES"
  "RETRY_MINUTES_EXTENDED"
  "MAX_RETRY_ATTEMPTS"

  "ENABLE_DATAFACTORY"
  "ENABLE_DATAFACTORY_COMMON"
  "ENABLE_AZURE_MACHINE_LEARNING"
  "ADD_AZURE_MACHINE_LEARNING"

  "ENABLE_AKS_FOR_AZURE_ML"
  "AKS_OUTBOUND_TYPE"
  "AKS_PRIVATE_DNS_ZONE"
  "AKS_AZURE_FIREWALL_PRIVATE_IP"

  "ENABLE_DATABRICKS"

  "ENABLE_AI_SEARCH"
  "ADD_AI_SEARCH"
  "ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK"
  "ENABLE_AZURE_OPENAI"
  "ENABLE_AZURE_AI_VISION"
  "ENABLE_AZURE_SPEECH"
  "ENABLE_AI_DOC_INTELLIGENCE"
  "ENABLE_BING"
  "ENABLE_BING_CUSTOM_SEARCH"
  "BING_CUSTOM_SEARCH_SKU"
  "ENABLE_CONTENT_SAFETY"

  "ENABLE_COSMOS_DB"
  "COSMOS_KIND"
  "ENABLE_POSTGRESQL"
  "POSTGRES_ADMIN_EMAILS"
  "ENABLE_REDIS_CACHE"
  "ENABLE_SQL_DATABASE"

  "ENABLE_FUNCTION"
  "FUNCTION_RUNTIME"
  "FUNCTION_VERSION"
  "ENABLE_WEBAPP"
  "WEBAPP_RUNTIME"
  "WEBAPP_RUNTIME_VERSION"
  "ASE_SKU"
  "ASE_SKU_CODE"
  "ASE_SKU_WORKERS"

  "ENABLE_CONTAINER_APPS"
  "ENABLE_APPINSIGHTS_DASHBOARD"
  "ACA_W_REGISTRY_IMAGE"

  "ENABLE_LOGIC_APPS"
  "ENABLE_EVENT_HUBS"
  "ENABLE_BOT_SERVICE"
  "FOUNDRY_API_MANAGEMENT_RESOURCE_ID"

  "PROJECT_PREFIX"
  "PROJECT_SUFFIX"
)

gh api --method PUT -H "Accept: application/vnd.github+json" repos/$GITHUB_NEW_REPO/environments/dev
create_or_update_variable "dev" "AZURE_ENV_NAME" "dev"

gh api --method PUT -H "Accept: application/vnd.github+json" repos/$GITHUB_NEW_REPO/environments/stage
create_or_update_variable "stage" "AZURE_ENV_NAME" "test"

gh api --method PUT -H "Accept: application/vnd.github+json" repos/$GITHUB_NEW_REPO/environments/prod
create_or_update_variable "prod" "AZURE_ENV_NAME" "prod"

# AI Factory globals: variables and secrets
for env in "${environments[@]}"; do
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

    # Networking
    create_or_update_variable $env "AIFACTORY_LOCATION_SHORT" "$AIFACTORY_LOCATION_SHORT"
    
    # Project specific settings, for all environments
    create_or_update_variable $env "PROJECT_MEMBERS_EMAILS" "$PROJECT_MEMBERS_EMAILS"
    create_or_update_variable $env "PROJECT_TYPE" "$PROJECT_TYPE"
    create_or_update_variable $env "PROJECT_NUMBER" "$PROJECT_NUMBER"
    create_or_update_variable $env "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID" "$PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID"
    create_or_update_variable $env "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID" "$PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID"
    create_or_update_variable $env "PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S" "$PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S"

    # Misc
    create_or_update_variable $env "RUN_JOB1_NETWORKING" "$RUN_JOB1_NETWORKING"

    # Global: Secrets
    create_or_update_secret $env "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID" "$AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID"
    
    # Project Specifics (1st project bootstrap): 
    create_or_update_secret $env "PROJECT_MEMBERS" "$PROJECT_MEMBERS"
    create_or_update_secret $env "PROJECT_MEMBERS_IP_ADDRESS" "$PROJECT_MEMBERS_IP_ADDRESS"
    create_or_update_secret $env "TENANT_ID" "$TENANT_ID"
    # Variables: 
    create_or_update_variable $env "BYO_SUBNETS" "$BYO_SUBNETS"
    create_or_update_variable $env "AIFACTORY_VERSION_MAJOR" "$AIFACTORY_VERSION_MAJOR"
    create_or_update_variable $env "AIFACTORY_VERSION_MINOR" "$AIFACTORY_VERSION_MINOR"
    create_or_update_variable $env "AIFACTORY_SALT" "$AIFACTORY_SALT"
    create_or_update_variable $env "AIFACTORY_SALT_RANDOM" "$AIFACTORY_SALT_RANDOM"

    # v1.23+ enable flags + BYO customization variables
    for var_name in "${service_and_byo_vars[@]}"; do
      create_or_update_variable "$env" "$var_name" "${!var_name}"
    done
done

# DEV variables
create_or_update_variable "dev" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
create_or_update_variable "dev" "AZURE_SUBSCRIPTION_ID" "$DEV_SUBSCRIPTION_ID"
create_or_update_variable "dev" "AIFACTORY_CIDR_XX" "$DEV_CIDR_RANGE"
create_or_update_variable "dev" "NETWORK_ENV" "$DEV_NETWORK_ENV"

create_or_update_variable "dev" "GH_CLI_VERSION" "$gh_version"

# DEV: Secrets
#create_or_update_secret "dev" "AZURE_SUBSCRIPTION_ID" "$DEV_SUBSCRIPTION_ID"
if [[ "$overwrite_azure_credential" == "y" ]]; then
  create_or_update_secret "dev" "AZURE_CREDENTIALS" "replace_with_dev_sp_credentials"
fi

# STAGE variables
create_or_update_variable "stage" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
create_or_update_variable "stage" "AZURE_SUBSCRIPTION_ID" "$STAGE_SUBSCRIPTION_ID"
create_or_update_variable "stage" "AIFACTORY_CIDR_XX" "$STAGE_CIDR_RANGE"
create_or_update_variable "stage" "NETWORK_ENV" "$STAGE_NETWORK_ENV"

# STAGE: Secrets
#create_or_update_secret "stage" "AZURE_SUBSCRIPTION_ID" "$STAGE_SUBSCRIPTION_ID"
if [[ "$overwrite_azure_credential" == "y" ]]; then
  create_or_update_secret "stage" "AZURE_CREDENTIALS" "replace_with_stage_sp_credentials"
fi
# PROD variables
create_or_update_variable "prod" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
create_or_update_variable "prod" "AZURE_SUBSCRIPTION_ID" "$PROD_SUBSCRIPTION_ID"
create_or_update_variable "prod" "AIFACTORY_CIDR_XX" "$PROD_CIDR_RANGE"
create_or_update_variable "prod" "NETWORK_ENV" "$PROD_NETWORK_ENV"

# PROD: Secrets
#create_or_update_secret "prod" "AZURE_SUBSCRIPTION_ID" "$PROD_SUBSCRIPTION_ID"
if [[ "$overwrite_azure_credential" == "y" ]]; then
  create_or_update_secret "prod" "AZURE_CREDENTIALS" "replace_with_prod_sp_credentials"
fi