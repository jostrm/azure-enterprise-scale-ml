#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Load .env file
if [ -f .env ]; then
  set -o allexport
  source .env
  set -o allexport -
else
  echo "Error: .env file not found."
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
echo -e "${YELLOW}Do you want to use overwrite AZURE_CREDENTIALS with dummy value? Usually only the 1st time this is needed, to create the variable in Github (Enter 'y' or 'n')${NC}"
read -p "overwrite_azure_credential: " overwrite_azure_credential

echo -e "${YELLOW}Bootstraps config from .env as Github environment variables and secrets. ${NC}"

# Get the GitHub CLI version
gh_version=$(gh --version | grep -oP '\d+\.\d+\.\d+' | head -n 1)

# Define environments
environments=("dev" "stage" "prod")

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
    create_or_update_variable $env "RUN_JOB1_NETWORKING" "true"

    # Global: Secrets
    create_or_update_secret $env "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID" "$AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID"
    
    # Project Specifics (1st project bootstrap): 
    create_or_update_secret $env "PROJECT_MEMBERS" "$PROJECT_MEMBERS"
    create_or_update_secret $env "PROJECT_MEMBERS_IP_ADDRESS" "$PROJECT_MEMBERS_IP_ADDRESS"
done

# DEV variables
create_or_update_variable "dev" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
create_or_update_variable "dev" "AZURE_SUBSCRIPTION_ID" "$DEV_SUBSCRIPTION_ID"
create_or_update_variable "dev" "AIFACTORY_CIDR_XX" "$DEV_CIDR_RANGE"
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

# STAGE: Secrets
#create_or_update_secret "stage" "AZURE_SUBSCRIPTION_ID" "$STAGE_SUBSCRIPTION_ID"
if [[ "$overwrite_azure_credential" == "y" ]]; then
  create_or_update_secret "stage" "AZURE_CREDENTIALS" "replace_with_stage_sp_credentials"
fi
# PROD variables
create_or_update_variable "prod" "AZURE_LOCATION" "$AIFACTORY_LOCATION"
create_or_update_variable "prod" "AZURE_SUBSCRIPTION_ID" "$PROD_SUBSCRIPTION_ID"
create_or_update_variable "prod" "AIFACTORY_CIDR_XX" "$PROD_CIDR_RANGE"

# PROD: Secrets
#create_or_update_secret "prod" "AZURE_SUBSCRIPTION_ID" "$PROD_SUBSCRIPTION_ID"
if [[ "$overwrite_azure_credential" == "y" ]]; then
  create_or_update_secret "prod" "AZURE_CREDENTIALS" "replace_with_prod_sp_credentials"
fi