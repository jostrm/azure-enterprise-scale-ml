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

# New storage initialization never enters the legacy copier (which replaces folders).
layout_mode="${1:---auto}"
if [[ "$#" -gt 1 || ( "$layout_mode" != "--auto" && "$layout_mode" != "--legacy-templates" &&
                     "$layout_mode" != "--init-azurefactory" ) ]]; then
    aif_error "Usage: $0 [--auto|--init-azurefactory|--legacy-templates]" >&2
    exit 2
fi
if [[ "$layout_mode" != "--init-azurefactory" ]]; then
    aif_require_legacy_workspace "$PWD" || exit 1
    if [[ -e "$PWD/azurefactory" || -L "$PWD/azurefactory" ]]; then
        aif_error "An azurefactory folder exists. Template copy refuses mixed/new roots; use a separate legacy workspace." >&2
        exit 2
    fi
fi
if [[ "$layout_mode" != "--legacy-templates" ]]; then
    for initializer in "$AIF_UI_DIR/lib/initialize_azurefactory.py" \
                       "$AIF_UI_DIR/azure-enterprise-scale-ml/bootstrap/lib/initialize_azurefactory.py"; do
        [[ ! -f "$initializer" ]] || break
    done
    if [[ ! -f "$initializer" ]]; then
        aif_error "azurefactory/register.json initializer is missing. Update the shared bootstrap/lib and bootstrap/templates together." >&2
        exit 1
    fi
    if [[ -n "${AIFACTORY_PYTHON:-}" ]]; then
        python_command=("$AIFACTORY_PYTHON")
    elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
        python_command=(python3)
    elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
        python_command=(python)
    elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
        python_command=(py -3)
    else
        aif_error "Python 3 is required to initialize azurefactory/register.json safely." >&2
        exit 1
    fi
    if [[ "$layout_mode" == "--init-azurefactory" ]]; then
        exec "${python_command[@]}" "$initializer" --root "$PWD/azurefactory"
    fi
fi
if [[ -L "$PWD/aifactory" || ( -e "$PWD/aifactory" && ! -d "$PWD/aifactory" ) ]]; then
    aif_error "A symbolic-link or non-directory aifactory is not a legacy bootstrap destination." >&2
    exit 1
fi
aif_banner "TEMPLATE SYNC" "Infrastructure / Automation / Use-case code"

################### VARIABLES ###################
copy_notebooks=false
init_esml_util=false
################### VARIABLES ###################
# 02. Copy template files to the new repository
aif_section "01 / Prepare template destination"

# Define the directory within the current directory.
current_dir=$(pwd)
aif_dir="$current_dir/aifactory-templates"

# Keep the inactive starter intact on template-sync reruns.
if [[ "$layout_mode" == "--auto" ]]; then
    mkdir -p "$aif_dir" || exit 1
    "${python_command[@]}" "$initializer" --stage-template --root "$aif_dir/azurefactory" || exit 1
    for template_path in "$aif_dir"/* "$aif_dir"/.[!.]* "$aif_dir"/..?*; do
        [[ -e "$template_path" || -L "$template_path" ]] || continue
        [[ "${template_path##*/}" != "azurefactory" ]] || continue
        rm -rf -- "$template_path"
    done
else
    # Legacy create moves this directory to aifactory; do not nest catalog storage there.
    rm -rf "$aif_dir"
    mkdir -p "$aif_dir"
fi

# Copy template files
start_dir="azure-enterprise-scale-ml"

## TEMPLATES: DataOps, MLOps, GenAIOps
if [ "$copy_notebooks" = true ]; then
    mkdir -p "$aif_dir/mlops/01_template_v14/"
    cp -r "$start_dir/mlops/01_template_v14/." "$aif_dir/mlops/01_template_v14/" # mlops

    mkdir -p "$aif_dir/dataops/adf/"
    cp -r "$start_dir/adf/v1_3/." "$aif_dir/dataops/adf/"
    
    mkdir -p "$aif_dir/notebook_aml_v1_templates/"
    cp -r "$start_dir/notebook_templates/1_quickstart/." "$aif_dir/notebook_aml_v1_templates/"
    
    mkdir -p "$aif_dir/notebook_aml_v2_examples/"
    cp -r "$start_dir/notebook_templates/notebook_aml_sdkv2_versus_sdkv1/." "$aif_dir/notebook_aml_v2_examples/"

    mkdir -p "$aif_dir/notebook_aml_v2_examples/model_diabetes/"
    cp -r "$start_dir/notebook_templates/model_diabetes/." "$aif_dir/notebook_aml_v2_examples/model_diabetes/"

    mkdir -p "$aif_dir/notebook_databricks/"
    cp -r "$start_dir/notebook_templates/notebook_databricks/." "$aif_dir/notebook_databricks/"
fi

if [ "$init_esml_util" = true ]; then
    ## Util (Bicep, Powershell, Azure CLI)
    cp -r "$start_dir/environment_setup/aifactory/bicep/esml-util/." "$aif_dir/esml-util/"
fi

## TEMPLATES: infra orchestration (pipelines) - ADO (Bicep)
aif_step "02/05" "Azure DevOps pipelines and GitHub workflows"

mkdir -p "$aif_dir/esml-infra/azure-devops/bicep/yaml/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/"* "$aif_dir/esml-infra/azure-devops/bicep/yaml/"

## TEMPLATES: infra orchestration (pipelines) - GHA(Bicep, Terraform)
mkdir -p "$aif_dir/esml-infra/github-actions/bicep/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"* "$aif_dir/esml-infra/github-actions/bicep/"

mkdir -p "$aif_dir/esml-infra/github-actions/terraform/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"* "$aif_dir/esml-infra/github-actions/terraform/"

## TEMPLATES: automation (core-team runbooks, FinOps showback/token reports, etc.)
aif_step "03/05" "Automation and Azure dashboards"
mkdir -p "$aif_dir/automation/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/automation/." "$aif_dir/automation/"

## Azure Dashboards
mkdir -p "$aif_dir/esml-infra/azure_dashboards/"
cp -r "$start_dir/environment_setup/aifactory/azure_dashboards/." "$aif_dir/esml-infra/azure_dashboards/"

## UseCase Code - Copy to root level (including dotfiles like .env.template)
aif_step "04/05" "Use-case code and environment templates"
usecase_code_dir="$current_dir/aifactory-usecase-code"
rm -rf "$usecase_code_dir"
mkdir -p "$usecase_code_dir"
cp -r "$start_dir/usecase_code/." "$usecase_code_dir/"

# Git Ignore
cp "$start_dir/bootstrap/.gitignore.template" "$start_dir/../.gitignore"

## Config wizard placeholder
aif_step "05/05" "Configuration wizard directory"
mkdir -p "$aif_dir/config-wizard"
echo "# Placeholder folder for the AI Factory configuration wizard" > "$aif_dir/config-wizard/readme.md"

aif_complete "Template copy finished."
