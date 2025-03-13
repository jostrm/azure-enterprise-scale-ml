#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Instructions: 
## 1)Run this file from your own parent repository, not from the azure-enterprise-scale-ml repository. Example ./enterprise-scale-ml/00-start.sh
## 2) Then you will have the files below in your repository, to run directory, as ./01-aif-copy-aifactory-templates.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prompt user for orchestrator choice
echo -e "${YELLOW}Do you want to use Azure DevOps or GitHub as an orchestrator, to run the IaC pipelines? (Enter 'a' or 'g')${NC}"
read -p "Orchestrator: " orchestrator

if [[ "$orchestrator" == "a" ]]; then
    echo -e "${GREEN}You have chosen Azure DevOps.${NC}"
    echo -e "${YELLOW}Cleaning potential old bootstrap files${NC}"
    
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

    # YAML - infra-project-genai.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-project-genai.yml"

    # YAML - infra-add-project-member.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-add-project-member.yml"

    # YAML - infra-add-core-member.yml -> aifactory-templates + .github/workflows
    rm -f "$SCRIPT_DIR/../.github/workflows/infra-add-core-member.yml"

    echo -e "${YELLOW}Copying new bootstrap files, to root of repository${NC}"

    # Copy AZURE DEVOPS template file and bootstrap files, to root of repository
    cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    cp "$SCRIPT_DIR/bootstrap/02b-ADO-YAML-bootstrap-files.sh" "$SCRIPT_DIR/../02-ADO-YAML-bootstrap-files.sh"
    cp "$SCRIPT_DIR/bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh" "$SCRIPT_DIR/../03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"
    
    # Common
    cp "$SCRIPT_DIR/bootstrap/11-ESML-upload-lake-structure.sh" "$SCRIPT_DIR/../11-ESML-upload-lake-structure.sh"
    cp "$SCRIPT_DIR/environment_setup/aifactory/bicep/esml-util/001-update-ip-rule-ux.sh" "$SCRIPT_DIR/../12-GENAI-update-ip-rule-ux.sh"
    
    echo -e "${GREEN}Finished!${NC}"
    echo -e "${GREEN}Next step: Run 01-aif-copy-aifactory-templates.sh${NC}"

    # Check if the directory exists, if not, create it
    if [ -d "$SCRIPT_DIR/../.github/workflows/" ]; then
        echo -e "${YELLOW}Do you also want to remove the GITHUB folder (the workflows for AIFactory is removed) (Enter 'y' or 'n')${NC}"
        read -p "Delete .github/workflows folder: " workflowsdelete
        if [[ "$workflowsdelete" == "y" ]]; then
            echo -e "${YELLOW}Deleting .github/workflows folder${NC}"
            rm -rf "$SCRIPT_DIR/../.github/workflows"
            rm -rf "$SCRIPT_DIR/../.github"
            echo -e "${GREEN}Finished!${NC}"
        else
            echo -e "${GREEN}Did not delete the folder.${NC}"
        fi    
    fi

elif [[ "$orchestrator" == "g" ]]; then
    echo -e "${GREEN}You have chosen GitHub.${NC}"
    echo -e "${YELLOW}Cleaning potential old bootstrap files${NC}"
    
    # Deleting potetoil Azure Devops files, silent error if not exists
    rm -f "$SCRIPT_DIR/../02-ADO-YAML-bootstrap-files.sh"
    rm -f "$SCRIPT_DIR/../03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"

    # Delete potentially old Github bootstrap files, from earlier runs, silent error if not exists
    rm -f "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    rm -f "$SCRIPT_DIR/../10-GH-create-or-update-github-variables.sh"
    rm -f "$SCRIPT_DIR/../.env.template"

    echo -e "${YELLOW}Copying new bootstrap files, to root of repository${NC}"

    # Creating GitHub files,  to root of repository
    cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    cp "$SCRIPT_DIR/bootstrap/02a-GH-bootstrap-files.sh" "$SCRIPT_DIR/../02-GH-bootstrap-files.sh"
    cp "$SCRIPT_DIR/bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh" "$SCRIPT_DIR/../03-GH-bootstrap-files-no-env-overwrite.sh"
    # Common
    cp "$SCRIPT_DIR/bootstrap/11-ESML-upload-lake-structure.sh" "$SCRIPT_DIR/../11-ESML-upload-lake-structure.sh"
    cp "$SCRIPT_DIR/environment_setup/aifactory/bicep/esml-util/001-update-ip-rule-ux.sh" "$SCRIPT_DIR/../12-GENAI-update-ip-rule-ux.sh"

    echo -e "${GREEN}Finished!${NC}"
    echo -e "${GREEN}Next step: Run 01-aif-copy-aifactory-templates.sh${NC}"
else
    echo -e "${RED}Invalid choice. Please run the script again and enter a valid option.${NC}"
    exit 1
fi

