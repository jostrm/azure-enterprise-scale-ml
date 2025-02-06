#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# variables.yaml -> variables-template.yaml
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml" "$SCRIPT_DIR/aifactory-templates/esml-infra/azure-devops/yaml/variables/variables-template.yaml"

# Copy the YAML files:esml-infra-common, 
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/" "$SCRIPT_DIR/aifactory-templates/esml-infra/azure-devops/yaml/esml-infra-common/" -r
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/" "$SCRIPT_DIR/aifactory-templates/esml-infra/azure-devops/yaml/esml-infra-project/" -r