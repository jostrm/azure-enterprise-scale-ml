#!/bin/bash

AIF_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for AIF_UI_LIBRARY in "$AIF_UI_DIR/ui/terminal.sh" "$AIF_UI_DIR/azure-enterprise-scale-ml/bootstrap/ui/terminal.sh"; do
    [[ ! -f "$AIF_UI_LIBRARY" ]] || break
done
if [[ ! -f "$AIF_UI_LIBRARY" ]]; then
    printf 'ERROR: AI Factory terminal library is missing. Copy bootstrap/ui alongside this script.\n' >&2
    exit 1
fi
source "$AIF_UI_LIBRARY"
aif_banner "DATA LAKE / INITIALIZE" "Upload the AI Factory lake structure."

# Load .env file
if [ -f .env ]; then
  set -o allexport
  source .env
  set -o allexport -
else
  aif_error ".env file not found."
  exit 1
fi

################ EDIT THIS #################
env="dev"
aiFactorySalt="$AIFACTORY_SALT" # Set this in your .env file:  Your unique salt for AIFactory, look at a resource such as keyvault, to find the 5 characters.
############################ DO NOT EDIT BELOW

# Prompt for SAS token
read -p "$(aif_prompt "Enter SAS token (leave empty to use EntraID auth. NB! Storage Blob Data Owner is needed. Sets ACL): ")" sas_token

# DIRECTORIES
current_dir=$(pwd)
UNZIP_DIR="../temp_aifactory_lake"

# Create the temporary directory
rm -rf "$UNZIP_DIR"
mkdir -p "$UNZIP_DIR"

# Ensure the temporary directory is removed on script exit
trap "rm -rf $UNZIP_DIR" EXIT

# Variables
commonLakeNamePrefixMax8chars="$LAKE_PREFIX"
resourceSuffix="001"
STORAGE_ACCOUNT_NAME="${commonLakeNamePrefixMax8chars}${aiFactorySalt}esml${resourceSuffix}${env}" # Construct datalakeName

aif_value "Data lake" "$STORAGE_ACCOUNT_NAME"

# Variables
ZIP_FILE="azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/lake/esml_lake.zip"
CONTAINER_NAME="lake3"

# Unzip the folder
unzip "$ZIP_FILE" -d "$UNZIP_DIR"

aif_section "Upload lake structure"

# Check if SAS token is provided
if [ -z "$sas_token" ]; then
  aif_info "No SAS token provided. Using EntraID auth."

  # Login to Azure and set the subscription
  az login
  if [ $? -eq 0 ]; then
    az account set --subscription "$DEV_SUBSCRIPTION_ID"
    if [ $? -eq 0 ]; then
      aif_value "Source" "$UNZIP_DIR"

      # Upload the folder structure and content to Azure Storage
      az storage blob upload-batch -d "$CONTAINER_NAME" --account-name "$STORAGE_ACCOUNT_NAME" -s "$UNZIP_DIR" --auth-mode login

      aif_complete "Upload command finished. Review the Azure CLI result above."
    else
      aif_error "Failed to set the subscription. "
      exit 1
    fi
  else
    aif_error "Azure login failed. "
    exit 1
  fi
else
  aif_info "Using SAS token for authentication. "

  # Upload the folder structure and content to Azure Storage using SAS token
  az storage blob upload-batch -d "$CONTAINER_NAME" --account-name "$STORAGE_ACCOUNT_NAME" -s "$UNZIP_DIR" --sas-token "$sas_token"

  aif_complete "Upload command finished. Review the Azure CLI result above."
fi
