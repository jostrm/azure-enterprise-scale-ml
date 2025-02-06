
#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SCRIPT_DIR/.github/workflows/"

# .ENV file & 03a-GH-create-or-update-github-variables.sh
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template" "$SCRIPT_DIR/.env"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh" "$SCRIPT_DIR/10-GH-create-or-update-github-variables.sh"

# YAML - Common -> aifactory-templates + .gihub/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml" "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-common.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml" "$SCRIPT_DIR/.github/workflows/infra-common.yml"

# YAML - infra-project-esml.yml -> aifactory-templates + .gihub/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-esml.yml" "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-project-esml.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-esml.yml" "$SCRIPT_DIR/.github/workflows/infra-project-esml.yml"

# YAML - infra-project-genai.yml -> aifactory-templates + .gihub/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-genai.yml" "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-project-genai.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-genai.yml" "$SCRIPT_DIR/.github/workflows/infra-project-genai.yml"

# YAML - infra-add-project-member.yml -> aifactory-templates + .gihub/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-add-project-member.yml" "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-add-project-member.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-add-project-member.yml" "$SCRIPT_DIR/.github/workflows/infra-add-project-member.yml"

# YAML - infra-add-core-member.yml -> aifactory-templates + .gihub/workflows
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-add-core-member.yml" "$SCRIPT_DIR/aifactory-templates/esml-infra/github-actions/bicep/infra-add-core-member.yml"
cp "$SCRIPT_DIR/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-add-core-member.yml" "$SCRIPT_DIR/.github/workflows/infra-add-core-member.yml"

echo -e "${GREEN}Success! ${NC}"