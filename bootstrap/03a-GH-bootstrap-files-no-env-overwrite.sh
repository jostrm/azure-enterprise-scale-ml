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
aif_require_legacy_workspace "$AIF_UI_DIR" || exit 1
aif_banner "GITHUB / REFRESH" "Update workflows; preserve your active configuration."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SCRIPT_DIR/.github/workflows/"

# Check if the directory exists
if [ -d "$SCRIPT_DIR/aifactory/esml-infra/github-actions/bicep/" ]; then
  # Delete all files in the directory
  rm -rf "$SCRIPT_DIR/aifactory/esml-infra/github-actions/bicep/"
fi
# Create the directory if it does not exist
mkdir -p "$SCRIPT_DIR/aifactory/esml-infra/github-actions/bicep/"

# .ENV file & 03a-GH-create-or-update-github-variables.sh
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template" "$SCRIPT_DIR/.env.template"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh" "$SCRIPT_DIR/10-GH-create-or-update-github-variables.sh"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/variables.json" "$SCRIPT_DIR/aifactory/variables-template.json"

# YAML - Common -> aifactory + .gihub/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml" "$SCRIPT_DIR/aifactory/esml-infra/github-actions/bicep/infra-common.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml" "$SCRIPT_DIR/.github/workflows/infra-common.yml"

# YAML - infra-project.yml -> aifactory + .github/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml" "$SCRIPT_DIR/aifactory/esml-infra/github-actions/bicep/infra-project.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml" "$SCRIPT_DIR/.github/workflows/infra-project.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml" "$SCRIPT_DIR/aifactory/esml-infra/github-actions/bicep/infra-project-phase.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml" "$SCRIPT_DIR/.github/workflows/infra-project-phase.yml"

# Automation (core-team runbooks, FinOps showback/token reports) -> aifactory/automation
mkdir -p "$SCRIPT_DIR/aifactory/automation/"
cp -r "$SCRIPT_DIR/aifactory-templates/automation/." "$SCRIPT_DIR/aifactory/automation/"

aif_complete "Workflows refreshed. Active configuration preserved."

aif_section "Next / Merge configuration changes"
aif_info "Use this prompt with GitHub Copilot:"
printf '\n'
aif_info "Compare the .env file at root, with the newer .env.template. Copy all values from .env into the new template .env.template. If some variables are similar but not exact, try to map these since they may be renamed. There may possible be more variables in .env.template. After this, then rename .env to .env.bak and .env.template to .env"
