#!/bin/bash

AIF_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for AIF_UI_LIBRARY in "$AIF_UI_DIR/ui/terminal.sh" "$AIF_UI_DIR/azure-enterprise-scale-ml/bootstrap/ui/terminal.sh"; do
    [[ ! -f "$AIF_UI_LIBRARY" ]] || break
done
if [[ ! -f "$AIF_UI_LIBRARY" ]]; then
    # This entrypoint can be downloaded before the submodule (and shared theme) exists.
    printf 'INFO: Shared theme not installed yet; using plain-text bootstrap output.\n' >&2
    aif_banner() { printf '\n  // AI FACTORY / %s\n  %s\n\n' "$1" "$2"; }
    aif_info() { printf '  [INFO] %s\n' "$*"; }
    aif_success() { printf '  [OK] %s\n' "$*"; }
    aif_error() { printf '  [ERROR] %s\n' "$*"; }
    aif_value() { printf '  %s: %s\n' "$1" "$2"; }
else
    source "$AIF_UI_LIBRARY"
fi
aif_banner "SUBMODULE SETUP" "Connect your repository to AI Factory."

function try()
{
    [[ $- = *e* ]]; SAVED_OPT_E=$?
    set +e
}

function throw()
{
    exit $1
}

function catch()
{
    export ex_code=$?
    (( $SAVED_OPT_E )) && set +e
    return $ex_code
}

function throwErrors()
{
    set -e
}

function ignoreErrors()
{
    set +e
}

submodule_exists() {
    git config --file .gitmodules --get-regexp path | grep -q "^submodule\.$1\.path"
}
submodule_initialized() {
    git submodule status "$1" &> /dev/null
}

submodule_on_main() {
    git -C "$1" symbolic-ref --short HEAD | grep -q "^main$"
}

export AlreadyInIndex=100
export AnotherException=101
submodule_name="azure-enterprise-scale-ml"
submodule_path="azure-enterprise-scale-ml"  # Replace with the actual path to your submodule

################### VARIABLES ###################
copy_notebooks=false
init_parameters=false
init_esml_util=true
################### VARIABLES ###################
try
(   # open a subshell !!!
    
    if ! submodule_exists "$submodule_name"; then
        git submodule add https://github.com/jostrm/azure-enterprise-scale-ml || throw $AlreadyInIndex
    else
        aif_info "Submodule $submodule_name already exists"
        if submodule_initialized "$submodule_path" && submodule_on_main "$submodule_path"; then
            aif_info "Submodule is already updated and on the main branch"
        else
            aif_info "Updating submodule and checking out main branch"
            git submodule update --init --recursive
            #git submodule foreach 'git checkout main'
            git submodule foreach 'git checkout main || git checkout -b main origin/main'
        fi
    fi
    
    aif_success "Submodule setup complete."
    
    aif_info "Ready to copy templates.") # Preserve the successful subshell status for catch.
# directly after closing the subshell you need to connect a group to the catch using ||
catch || {
    # now you can handle
    aif_value "Exit code" "$ex_code"
    case $ex_code in
        $AlreadyInIndex)
            aif_info "submodule already exists in the index - now updating instead of adding"
            git submodule update --init --recursive
            aif_info "HEAD position was 00fc174 fix, switched to branch 'main'"
            git submodule foreach 'git checkout main'
            aif_success "Submodule setup complete."
        ;;
        $AnotherException)
            aif_error "AnotherException was thrown"
        ;;
        *)
            aif_error "An unexpected exception was thrown"
            throw $ex_code # you can rethrow the "exception" causing the script to exit if not caught
        ;;
    esac
}
