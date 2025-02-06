#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if the directory exists, if not, create it
if [ ! -d "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/variables/" ]; then
  mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/variables/"
fi

# Check if the directory exists
if [ -d "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/" ]; then
  # Delete all files in the directory
  rm -rf "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/"
fi

# Create the directory if it does not exist
mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/"

# Check if the directory exists
if [ -d "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/" ]; then
  # Delete all files in the directory
  rm -rf "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/"
fi

# Create the directory if it does not exist
mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/"

# variables.yaml -> variables-template.yaml
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml" "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"

# Copy the YAML files:esml-infra-common, 
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/" "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/" -r
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/" "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/" -r
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md" "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/readme.md"