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

################ EDIT THIS #################
env="dev"
aiFactorySalt="$AIFACTORY_SALT" # Set this in your .env file:  Your unique salt for AIFactory, look at a resource such as keyvault, to find the 5 characters.
############################ DO NOT EDIT BELOW

# Prompt for SAS token
read -p "Enter SAS token (leave empty to use EntraID auth. NB! Storage Blob Data Owner is needed. Sets ACL): " sas_token

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

echo -e "${GREEN}Datalake Name: $STORAGE_ACCOUNT_NAME ${NC}"

# Variables
ZIP_FILE="azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/lake/esml_lake.zip"
CONTAINER_NAME="lake3"

# Unzip the folder
unzip "$ZIP_FILE" -d "$UNZIP_DIR"

echo -e "${GREEN}Datalake Name: $STORAGE_ACCOUNT_NAME ${NC}"

# Check if SAS token is provided
if [ -z "$sas_token" ]; then
  echo -e "${YELLOW}No SAS token provided. Using EntraID auth.${NC}"

  # Login to Azure and set the subscription
  az login
  if [ $? -eq 0 ]; then
    az account set --subscription "$DEV_SUBSCRIPTION_ID"
    if [ $? -eq 0 ]; then
      echo -e "${GREEN}UNZIP_DIR: $UNZIP_DIR ${NC}"

      # Upload the folder structure and content to Azure Storage
      az storage blob upload-batch -d "$CONTAINER_NAME" --account-name "$STORAGE_ACCOUNT_NAME" -s "$UNZIP_DIR" --auth-mode login

      echo -e "${GREEN}Upload complete! ${NC}"
    else
      echo -e "${RED}Failed to set the subscription. ${NC}"
      exit 1
    fi
  else
    echo -e "${RED}Azure login failed. ${NC}"
    exit 1
  fi
else
  echo -e "${GREEN}Using SAS token for authentication. ${NC}"

  # Upload the folder structure and content to Azure Storage using SAS token
  az storage blob upload-batch -d "$CONTAINER_NAME" --account-name "$STORAGE_ACCOUNT_NAME" -s "$UNZIP_DIR" --sas-token "$sas_token"

  echo -e "${GREEN}Upload complete! ${NC}"
fi