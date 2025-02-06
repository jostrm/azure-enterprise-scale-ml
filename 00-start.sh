#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Instructions: 
## 1)Run this file from your own parent repository, not from the azure-enterprise-scale-ml repository.
### Example ./enterprise-scale-ml/00-start.sh
## 2) Then you will have the files below in your repository, to run directory, as ./01-aif-copy-aifactory-templates.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prompt user for orchestrator choice
echo -e "${YELLOW}Do you want to use Azure DevOps or GitHub as an orchestrator, to run the IaC pipelines? (Enter 'a' or 'g')${NC}"
read -p "Orchestrator: " orchestrator

if [[ "$orchestrator" == "a" ]]; then
    echo -e "${GREEN}You have chosen Azure DevOps.${NC}"
    
    # Deleting Github BOOTSTRAP files
    rm "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    rm "$SCRIPT_DIR/../02-GH-bootstrap-files.sh"
    rm "$SCRIPT_DIR/../03-GH-bootstrap-files-no-env-overwrite.sh"
    
    # Delete the Github files, the bootstrap creates
    rm "$SCRIPT_DIR/../10-GH-create-or-update-github-variables.sh"
    rm "$SCRIPT_DIR/../.env.template"

    # Delete Github files in .github/workflows
    # YAML - Common -> aifactory-templates + .github/workflows
    #rm "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-common.yml"
    rm "$SCRIPT_DIR/.github/workflows/infra-common.yml"

    # YAML - infra-project-esml.yml -> aifactory-templates + .github/workflows
    #rm "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-project-esml.yml"
    rm "$SCRIPT_DIR/.github/workflows/infra-project-esml.yml"

    # YAML - infra-project-genai.yml -> aifactory-templates + .github/workflows
    #rm "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-project-genai.yml"
    rm "$SCRIPT_DIR/.github/workflows/infra-project-genai.yml"

    # YAML - infra-add-project-member.yml -> aifactory-templates + .github/workflows
    #rm "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-add-project-member.yml"
    rm "$SCRIPT_DIR/.github/workflows/infra-add-project-member.yml"

    # YAML - infra-add-core-member.yml -> aifactory-templates + .github/workflows
    #rm "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-add-core-member.yml"
    rm "$SCRIPT_DIR/.github/workflows/infra-add-core-member.yml"

    # Copy aZURE DEVOPS template file and bootstrap files
    cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    cp "$SCRIPT_DIR/bootstrap/02b-ADO-YAML-bootstrap-files.sh" "$SCRIPT_DIR/../02-ADO-YAML-bootstrap-files.sh"
    cp "$SCRIPT_DIR/bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh" "$SCRIPT_DIR/../03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"

elif [[ "$orchestrator" == "g" ]]; then
    echo -e "${GREEN}You have chosen GitHub.${NC}"
    
    # Deleting Azure Devops files
    rm "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    rm "$SCRIPT_DIR/../02-ADO-YAML-bootstrap-files.sh"
    rm "$SCRIPT_DIR/../03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"

    # Delete the Azure Devops  files, the bootstrap creates
    rm "$SCRIPT_DIR/../10-GH-create-or-update-github-variables.sh"
    rm "$SCRIPT_DIR/../.env.template"

    # Creating GitHub files
    cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
    cp "$SCRIPT_DIR/bootstrap/02a-GH-bootstrap-files.sh" "$SCRIPT_DIR/../02-GH-bootstrap-files.sh"
    cp "$SCRIPT_DIR/bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh" "$SCRIPT_DIR/../03-GH-bootstrap-files-no-env-overwrite.sh"
else
    echo -e "${RED}Invalid choice. Please run the script again and enter a valid option.${NC}"
    exit 1
fi

