#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

################### VARIABLES ###################
copy_notebooks=false
init_parameters=false
init_esml_util=false
################### VARIABLES ###################

# 02. Copy template files to the new repository
echo -e "${YELLOW}02. COPY TEMPLATE files (Azure Devops pipeline, GHA workflow, Bicep Variable file, environment file) to your repo ${NC}"

# Define the directory within the current directory
current_dir=$(pwd)
aif_dir="$current_dir/aifactory-templates"

# Create the temporary directory
rm -rf "$aif_dir"
mkdir -p "$aif_dir"

# Copy template files
start_dir="azure-enterprise-scale-ml"

## TEMPLATES: infra orchestration (pipelines) - ADO (Bicep)
mkdir -p "$aif_dir/esml-infra/azure-devops/bicep/classic/"
cp "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/" "$aif_dir/esml-infra/azure-devops/bicep/classic/" -r

mkdir -p "$aif_dir/esml-infra/azure-devops/bicep/yaml/"
cp "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/" "$aif_dir/esml-infra/azure-devops/bicep/yaml/" -r

## TEMPLATES: infra orchestration (pipelines) - GHA(Bicep, Terraform)
mkdir -p "$aif_dir/esml-infra/github-actions/bicep/"
cp "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/" "$aif_dir/esml-infra/github-actions/bicep/" -r

mkdir -p "$aif_dir/esml-infra/github-actions/terraform/"
cp "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/" "$aif_dir/esml-infra/github-actions/terraform/" -r

## Azure Dashboards
mkdir -p "$aif_dir/azure_dashboards/"
cp "$start_dir/environment_setup/aifactory/azure_dashboards" "$aif_dir/esml-infra/azure_dashboards/" -r

echo -e "${GREEN}02. Success! ${NC}"
