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
aif_banner "AZURE DEVOPS / REFRESH" "Update pipelines; preserve your active configuration."

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

if [ -d "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/aifactory-governance/" ]; then
  # Delete all files in the directory
  rm -rf "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/aifactory-governance/"
fi

# Create the directory if it does not exist
mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/"
mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/aifactory-governance/"

# Check if the directory exists
if [ -d "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/" ]; then
  # Delete all files in the directory
  rm -rf "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/"
fi

# Create the directory if it does not exist
mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/"

# variables.yaml -> variables-template.yaml
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml" "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables-template.yaml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/variables.json" "$SCRIPT_DIR/aifactory/variables-template.json"

# Copy the YAML files:esml-infra-common, 
cp -r "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/aifactory-governance/." "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/aifactory-governance/"
cp -r "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/." "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/"
cp -r "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/." "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md" "$SCRIPT_DIR/aifactory/esml-infra/azure-devops/bicep/yaml/readme.md"

# Automation (core-team runbooks, FinOps showback/token reports) -> aifactory/automation
mkdir -p "$SCRIPT_DIR/aifactory/automation/"
cp -r "$SCRIPT_DIR/aifactory-templates/automation/." "$SCRIPT_DIR/aifactory/automation/"

aif_section "Next / Merge configuration changes"
aif_info "Use this prompt with GitHub Copilot:"
printf '\n'
aif_info "Compare the variables.yaml under my folder aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml with the newer variables-template.yaml in same folder. Copy all values from variables.yaml into the new template variables-template.yaml. If some variables are similar but not exact, try to map these simce they may be renamed. There may possible be more variables in variables-template.yaml. After this then rename variables.yaml to variables.bak and variables-template.yaml to variables.yaml"
