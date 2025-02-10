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
aiFactorySalt="$LAKE_PREFIX" # Set this in your .env file:  Your unique salt for AIFactory, look at a resource such as keyvault, to find the 5 characters.
############################ DO NOT EDIT BELOW

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
commonResourceSuffix="$AIFACTORY_SUFFIX"
commonResourceSuffix="${commonResourceSuffix//-/}" # Replace '-' with '' in commonResourceSuffix
STORAGE_ACCOUNT_NAME="${commonLakeNamePrefixMax8chars}${aiFactorySalt}esml${commonResourceSuffix}${env}" # Construct datalakeName

echo -e "${GREEN}Datalake Name: $STORAGE_ACCOUNT_NAME ${NC}"

# Variables
ZIP_FILE="azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/lake/esml_lake.zip"
CONTAINER_NAME="lake3"

echo -e "${GREEN}UNZIP_DIR: $UNZIP_DIR ${NC}"

# Unzip the folder
unzip "$ZIP_FILE" -d "$UNZIP_DIR"

# Upload the folder structure and content to Azure Storage
az storage blob upload-batch -d "$CONTAINER_NAME" --account-name "$STORAGE_ACCOUNT_NAME" -s "$UNZIP_DIR" --auth-mode login
# az storage blob upload-batch -d "$CONTAINER_NAME" --account-name "$STORAGE_ACCOUNT_NAME" -s "$UNZIP_DIR" --sas-token "<TODO>"

echo -e "${GREEN}Upload complete! ${NC}"