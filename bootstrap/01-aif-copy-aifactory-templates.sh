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
layout_mode="--auto"
no_delete=false
mode_selected=false
for argument in "$@"; do
    case "$argument" in
        --no-delete)
            [[ "$no_delete" == "false" ]] || { aif_error "Duplicate --no-delete"; exit 2; }
            no_delete=true
            ;;
        --auto|--legacy-templates|--init-azurefactory)
            [[ "$mode_selected" == "false" ]] || { aif_error "Select only one layout mode"; exit 2; }
            layout_mode="$argument"
            mode_selected=true
            ;;
        *)
            aif_error "Usage: $0 [--auto|--init-azurefactory|--legacy-templates] [--no-delete]" >&2
            exit 2
            ;;
    esac
done
if [[ "$layout_mode" != "--init-azurefactory" ]]; then
    aif_require_legacy_workspace "$PWD" || exit 1
    if [[ -e "$PWD/azurefactory" || -L "$PWD/azurefactory" ]]; then
        aif_error "An azurefactory folder exists. Template copy refuses mixed/new roots; use a separate legacy workspace." >&2
        exit 2
    fi
fi
if [[ "$layout_mode" != "--legacy-templates" || "$no_delete" == "true" ]]; then
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
# Check the distributable inputs before replacing any existing template copies.
start_dir="azure-enterprise-scale-ml"
api_source="$start_dir/environment_setup"
api_assets=(
    "azurefactory-cli/.gitignore"
    "azurefactory-cli/readme.md"
    "azurefactory-cli/pyproject.toml"
    "azurefactory-cli/setup.py"
    "azurefactory-cli/src/azurefactory"
    "azurefactory-cli/tests"
    "install_config_wizard/api-usage-examples/.gitignore"
    "install_config_wizard/api-usage-examples/readme.md"
    "install_config_wizard/api-usage-examples/scenarios.json"
    "install_config_wizard/api-usage-examples/python"
    "install_config_wizard/api-usage-examples/powershell"
    "install_config_wizard/api-usage-examples/node"
    "install_config_wizard/api-usage-examples/requests"
    "install_config_wizard/api-usage-examples/tests"
)
for api_asset in "${api_assets[@]}"; do
    api_path="$api_source/$api_asset"
    case "$api_asset" in
        */.gitignore|*.md|*.toml|*.json|*/setup.py) api_type="-f" ;;
        *) api_type="-d" ;;
    esac
    if [[ -L "$api_path" ]] || ! test "$api_type" "$api_path"; then
        aif_error "CLI/API source is missing or linked: $api_path. Update the shared submodule before copying templates." >&2
        exit 1
    fi
done
if [[ "$no_delete" == "true" ]]; then
    safe_copier="$(dirname "$initializer")/bootstrap_no_delete.py"
    [[ -f "$safe_copier" ]] || { aif_error "Missing bootstrap/lib/bootstrap_no_delete.py"; exit 1; }
    PYTHONDONTWRITEBYTECODE=1 "${python_command[@]}" "$safe_copier" templates \
        --source "$PWD/$start_dir" --root "$PWD" --layout-mode="${layout_mode#--}" \
        --api-assets "${api_assets[@]}" || exit 1
    aif_complete "Non-deleting template refresh finished. Existing configuration and .gitignore are preserved."
    aif_info "No factory was registered. To initialize separately: bash ./01-aif-copy-aifactory-templates.sh --init-azurefactory"
    aif_info "Old files not present in the source remain; review them before using templates."
    exit 0
fi
if ! command -v find >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
    aif_error "The find and tar utilities are required to copy CLI/API sources without local runtime artifacts." >&2
    exit 1
fi
aif_banner "TEMPLATE SYNC" "Infrastructure / Automation / Use-case code / CLI and API"

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
aif_step "02/06" "Azure DevOps pipelines and GitHub workflows"

mkdir -p "$aif_dir/esml-infra/azure-devops/bicep/yaml/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/"* "$aif_dir/esml-infra/azure-devops/bicep/yaml/"

## TEMPLATES: infra orchestration (pipelines) - GHA(Bicep, Terraform)
mkdir -p "$aif_dir/esml-infra/github-actions/bicep/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"* "$aif_dir/esml-infra/github-actions/bicep/"

mkdir -p "$aif_dir/esml-infra/github-actions/terraform/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"* "$aif_dir/esml-infra/github-actions/terraform/"

## TEMPLATES: automation (core-team runbooks, FinOps showback/token reports, etc.)
aif_step "03/06" "Automation and Azure dashboards"
mkdir -p "$aif_dir/automation/"
cp -r "$start_dir/environment_setup/aifactory/bicep/copy_to_local_settings/automation/." "$aif_dir/automation/"

## Azure Dashboards
mkdir -p "$aif_dir/esml-infra/azure_dashboards/"
cp -r "$start_dir/environment_setup/aifactory/azure_dashboards/." "$aif_dir/esml-infra/azure_dashboards/"

## UseCase Code - Copy to root level (including dotfiles like .env.template)
aif_step "04/06" "Use-case code and environment templates"
usecase_code_dir="$current_dir/aifactory-usecase-code"
rm -rf "$usecase_code_dir"
mkdir -p "$usecase_code_dir"
cp -r "$start_dir/usecase_code/." "$usecase_code_dir/"

# Git Ignore
cp "$start_dir/bootstrap/.gitignore.template" "$start_dir/../.gitignore"

## CLI and API examples keep the same relative layout as environment_setup.
aif_step "05/06" "Azure Factory CLI, Python SDK and API usage examples"
if ! (
    set -o pipefail
    cd "$api_source" || exit 1
    find "${api_assets[@]}" \
        \( -type d \( -name '.*' -o -name '__pycache__' -o -name 'node_modules' \
            -o -name 'build' -o -name 'dist' -o -name 'venv' -o -name '*.egg-info' \) -prune \) -o \
        \( -type f \( -name '*.py' -o -name '*.mjs' -o -name '*.ps1' -o -name '*.json' \
            -o -name '*.toml' -o -name '*.md' -o -name '.gitignore' \) \
            \( ! -name '.*' -o -name '.gitignore' \) \
            ! -name '*.receipt.json' ! -name '*.review.json' ! -name '*.private.json' -print0 \) |
        tar -cf - --null -T - |
        tar -xf - -C "$aif_dir"
); then
    aif_error "CLI/API template copy failed. Resolve the file error and rerun; no API operation was started." >&2
    exit 1
fi

## Config wizard placeholder
aif_step "06/06" "Configuration wizard directory"
mkdir -p "$aif_dir/config-wizard"
echo "# Placeholder folder for the AI Factory configuration wizard" > "$aif_dir/config-wizard/readme.md"

aif_complete "Template copy finished."
