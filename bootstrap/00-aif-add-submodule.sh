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
init_parameters=false
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
