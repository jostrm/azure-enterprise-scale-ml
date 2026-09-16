#!/bin/bash
set -euo pipefail

AIF_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$AIF_UI_DIR/bootstrap/ui/terminal.sh" ]]; then
    printf 'ERROR: AI Factory terminal library is missing from bootstrap/ui.\n' >&2
    exit 1
fi
source "$AIF_UI_DIR/bootstrap/ui/terminal.sh"
source "$AIF_UI_DIR/bootstrap/lib/layout_router.sh"
aif_banner "LAUNCH CONTROL" "Your platform. Your orchestrator. One AI Factory."

# Defaults
TARGET_REPO="${GH_TARGET_REPO:-githuborg/enterprise-scale-aifactory-001}"

# Instructions: 
## 1)Run this file from your own parent repository, not from the azure-enterprise-scale-ml repository. Example ./enterprise-scale-ml/00-start.sh
## 2) Then you will have the files below in your repository, to run directory, as ./01-aif-copy-aifactory-templates.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Opt-in refresh: never enter the legacy cleanup, prompt or dispatch paths.
if [[ "${1:-}" == "--no-delete" ]]; then
    [[ "$#" -eq 1 ]] || { aif_error "Usage: $0 [--no-delete]"; exit 2; }
    bundle="$(aif_launcher_bundle_source "$SCRIPT_DIR/bootstrap")"
    registered=false
    if aif_registered_layout_root "$SCRIPT_DIR/.." >/dev/null; then
        registered=true
    else
        status=$?
        [[ "$status" -ne 2 ]] || exit 2
        aif_require_legacy_workspace "$SCRIPT_DIR/.." || exit 1
        aif_require_legacy_workspace "$PWD" || exit 1
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
        aif_error "Python 3 is required for --no-delete."
        exit 1
    fi
    PYTHONDONTWRITEBYTECODE=1 "${python_command[@]}" "$bundle/lib/bootstrap_no_delete.py" \
        bundle --source "$bundle" --root "$SCRIPT_DIR/.."
    aif_complete "Installed both ADO and GHA bootstrap helpers without deleting files or dispatching workflows."
    aif_info "Existing .gitignore is preserved; review tracking rules before staging the installed bundle."
    if [[ "$registered" == "true" ]]; then
        aif_info "Registered layout: use ADO/GHA-azurefactory.sh with a reviewed manifest. Template copy remains blocked."
    else
        aif_info "From your repository root: bash ./01-aif-copy-aifactory-templates.sh --no-delete"
        aif_info "Then, only to initialize register storage: bash ./01-aif-copy-aifactory-templates.sh --init-azurefactory"
        aif_info "Do not run legacy 02/03 bootstrap helpers for this register-only setup."
    fi
    exit 0
fi

# Install the complete control bundle from one reviewed source tree.
aif_restore_launcher_bundle "$SCRIPT_DIR/bootstrap" "$SCRIPT_DIR/.."

if aif_registered_layout_root "$SCRIPT_DIR/.." >/dev/null; then
    aif_complete "Installed dual-layout launchers. Use ADO/GHA-azurefactory.sh with a reviewed manifest."
    exit 0
fi
aif_require_legacy_workspace "$AIF_UI_DIR/.." || exit 1
aif_require_legacy_workspace "$PWD" || exit 1

gh_ok() {
    if ! command -v gh >/dev/null 2>&1; then
        aif_error "GitHub CLI (gh) is not installed. Skipping workflow dispatch."
        return 1
    fi
    if ! gh auth status >/dev/null 2>&1; then
        aif_error "GitHub CLI is not authenticated. Run 'gh auth login' first."
        return 1
    fi
    return 0
}

dispatch_common() {
    local deploy_stage="$1" deploy_prod="$2"
    gh workflow run ".github/workflows/infra-common.yml" \
        --repo "$TARGET_REPO" \
        --raw-field deploy_dev=true \
        --raw-field deploy_stage="$deploy_stage" \
        --raw-field deploy_prod="$deploy_prod"
}

dispatch_project() {
    local env_name="$1"
    gh workflow run ".github/workflows/infra-project.yml" \
        --repo "$TARGET_REPO" \
        --raw-field environment="$env_name"
}

# Prompt user for orchestrator choice
aif_section "Choose your orchestrator"
aif_value "[a]" "Azure DevOps / YAML pipelines"
aif_value "[g]" "GitHub / Actions workflows"
aif_info "Do you want to use Azure DevOps or GitHub as an orchestrator, to run the IaC pipelines? (Enter 'a' or 'g')"
read -p "$(aif_prompt "Orchestrator: ")" orchestrator

if [[ "$orchestrator" == "a" ]]; then
    aif_success "You have chosen Azure DevOps."
    aif_section "Cleaning potential old bootstrap files"
    
    # Delete potential Github BOOTSTRAP files,silent error if not exists
    rm -f "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    rm -f "$SCRIPT_DIR/../02-GH-bootstrap-files.sh"
    rm -f "$SCRIPT_DIR/../03-GH-bootstrap-files-no-env-overwrite.sh"
    
    # Delete potential the Github files, the bootstrap creates
    rm -f "$SCRIPT_DIR/../10-GH-create-or-update-github-variables.sh"
    rm -f "$SCRIPT_DIR/../.env.template"

    # Delete Github files in .github/workflows
    # YAML - Common -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-common.yml"

    # YAML - infra-project-esml.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-project-esml.yml"

    # YAML - infra-project.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-project.yml"
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-project-phase.yml"

    # Back-compat cleanup (older name)
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-project-genai.yml"

    # YAML - infra-add-project-member.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-add-project-member.yml"

    # YAML - infra-add-core-member.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-add-core-member.yml"

    aif_section "Copying new bootstrap files, to root of repository"

    # Copy AZURE DEVOPS template file and bootstrap files, to root of repository
    cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    cp "$SCRIPT_DIR/bootstrap/02b-ADO-YAML-bootstrap-files.sh" "$SCRIPT_DIR/../02-ADO-YAML-bootstrap-files.sh"
    cp "$SCRIPT_DIR/bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh" "$SCRIPT_DIR/../03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"
    
    # Common
    cp "$SCRIPT_DIR/bootstrap/11-ESML-upload-lake-structure.sh" "$SCRIPT_DIR/../11-ESML-upload-lake-structure.sh"
    
    aif_success "Finished!"
    aif_info "New setup: Run ADO-create-new-aifactory-scaleset.sh"
    aif_info "Manual setup: Run 01-aif-copy-aifactory-templates.sh"

    # Check if the directory exists, if not, create it
    if [ -d "$SCRIPT_DIR/../.github/workflows/" ]; then
        aif_info "Do you also want to remove the GITHUB folder (the workflows for AIFactory is removed) (Enter 'y' or 'n')"
        read -r -p "$(aif_prompt "Delete .github/workflows folder: ")" workflowsdelete || workflowsdelete="n"
        if [[ "$workflowsdelete" == "y" ]]; then
            aif_info "Deleting .github/workflows folder"
            rm -rf "$SCRIPT_DIR/../.github/workflows"
            rm -rf "$SCRIPT_DIR/../.github"
            aif_success "Finished!"
        else
            aif_info "Did not delete the folder."
        fi    
    fi

elif [[ "$orchestrator" == "g" ]]; then
    aif_success "You have chosen GitHub."
    aif_section "Cleaning potential old bootstrap files"
    
    # Deleting potetoil Azure Devops files, silent error if not exists
    rm -f "$SCRIPT_DIR/../02-ADO-YAML-bootstrap-files.sh"
    rm -f "$SCRIPT_DIR/../03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"

    # Delete potentially old Github bootstrap files, from earlier runs, silent error if not exists
    rm -f "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    rm -f "$SCRIPT_DIR/../10-GH-create-or-update-github-variables.sh"
    rm -f "$SCRIPT_DIR/../.env.template"

    aif_section "Copying new bootstrap files, to root of repository"

    # Creating GitHub files,  to root of repository
    cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    cp "$SCRIPT_DIR/bootstrap/02a-GH-bootstrap-files.sh" "$SCRIPT_DIR/../02-GH-bootstrap-files.sh"
    cp "$SCRIPT_DIR/bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh" "$SCRIPT_DIR/../03-GH-bootstrap-files-no-env-overwrite.sh"
    # Common
    cp "$SCRIPT_DIR/bootstrap/11-ESML-upload-lake-structure.sh" "$SCRIPT_DIR/../11-ESML-upload-lake-structure.sh"
    #cp "$SCRIPT_DIR/bootstrap/12-GENAI-update-ip-rule-ux.sh" "$SCRIPT_DIR/../12-GENAI-update-ip-rule-ux.sh"
    #cp "$SCRIPT_DIR/bootstrap/13-ESML-update-ip-rule-ux.sh" "$SCRIPT_DIR/../13-ESML-update-ip-rule-ux.sh"

    aif_success "Finished!"
    aif_info "New setup: Run GHA-create-new-aifactory-scaleset.sh"
    aif_info "Manual setup: Run 01-aif-copy-aifactory-templates.sh"
    aif_info "Next step 2nd time: If this is not your first time, you may Run ADO-update-aifactory-and-run-project.sh, if you already have a common and project repository, and want to run the IaC pipelines automatically."
    
else
    aif_error "Invalid choice. Please run the script again and enter a valid option."
    exit 1
fi
