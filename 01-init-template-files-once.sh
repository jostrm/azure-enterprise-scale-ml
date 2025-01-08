#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

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
init_parameters=true
init_esml_util=true
################### VARIABLES ###################
try
(   # open a subshell !!!
    
    if ! submodule_exists "$submodule_name"; then
        git submodule add https://github.com/jostrm/azure-enterprise-scale-ml || throw $AlreadyInIndex
    else
        echo "Submodule $submodule_name already exists"
        if submodule_initialized "$submodule_path" && submodule_on_main "$submodule_path"; then
            echo "Submodule is already updated and on the main branch"
        else
            echo "Updating submodule and checking out main branch"
            git submodule update --init --recursive
            #git submodule foreach 'git checkout main'
            git submodule foreach 'git checkout main || git checkout -b main origin/main'
        fi
    fi
    
    echo -e "${GREEN}01. Success! ${NC}"
    
    echo "finished") # make sure to clear $ex_code, otherwise catch * will run # echo "finished" does the trick for this example
# directly after closing the subshell you need to connect a group to the catch using ||
catch || {
    # now you can handle
    echo $ex_code
    case $ex_code in
        $AlreadyInIndex)
            echo "submodule already exists in the index - now updating instead of adding"
            git submodule update --init --recursive
            echo "HEAD position was 00fc174 fix, switched to branch 'main'"
            git submodule foreach 'git checkout main'
            echo -e "${GREEN}01. Success! ${NC}"
        ;;
        $AnotherException)
            echo "AnotherException was thrown"
        ;;
        *)
            echo "An unexpected exception was thrown"
            throw $ex_code # you can rethrow the "exception" causing the script to exit if not caught
        ;;
    esac
}

# 02. Copy template files to the new repository
echo -e "${YELLOW}02. COPY TEMPLATE files (Azure Devops pipeline, GHA workflow, Bicep Variable file, environment file) to your repo ${NC}"

# Define the directory within the current directory
current_dir=$(pwd)
aif_dir="$current_dir/aifactory"

# Create the temporary directory
rm -rf "$aif_dir"
mkdir -p "$aif_dir"

# Copy template files
start_dir="azure-enterprise-scale-ml"

## TEMPLATES: DataOps, MLOps, GenAIOps
if [ "$copy_notebooks" = true ]; then
    mkdir -p "$aif_dir/mlops/01_template_v14/"
    cp "$start_dir/mlops/01_template_v14/" "$aif_dir/mlops/01_template_v14/" -r # mlops

    mkdir -p "$aif_dir/dataops/adf/"
    cp "$start_dir/adf/v1_3/" "$aif_dir/dataops/adf/" -r
    
    mkdir -p "$aif_dir/notebook_aml_v1_templates/"
    cp "$start_dir/notebook_templates/1_quickstart/" "$aif_dir/notebook_aml_v1_templates/" -r
    
    mkdir -p "$aif_dir/notebook_aml_v2_examples/"
    cp "$start_dir/notebook_templates/notebook_aml_sdkv2_versus_sdkv1/" "$aif_dir/notebook_aml_v2_examples/" -r

    mkdir -p "$aif_dir/notebook_aml_v2_examples/model_diabetes/"
    cp "$start_dir/notebook_templates/model_diabetes/" "$aif_dir/notebook_aml_v2_examples/model_diabetes/" -r

    mkdir -p "$aif_dir/notebook_databricks/"
    cp "$start_dir/notebook_templates/notebook_databricks/" "$aif_dir/notebook_databricks/" -r
fi

if [ "$init_parameters" = true ]; then
    ## PARAMETERS - BICEP/TERRAFORM/ADO/GHA
    cp "$start_dir/environment_setup/aifactory/parameters/" "$aif_dir/parameters/" -r
fi

if [ "$init_esml_util" = true ]; then
    ## Util (Bicep, Powershell, Azure CLI)
    cp "$start_dir/environment_setup/aifactory/bicep/esml-util/" "$aif_dir/esml-util/" -r
fi

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
mkdir -p "$aif_dir/esml-infra/azure_dashboards/"
cp "$start_dir/environment_setup/aifactory/azure_dashboards" "$aif_dir/esml-infra/azure_dashboards/" -r

echo -e "${GREEN}02. Success! ${NC}"
