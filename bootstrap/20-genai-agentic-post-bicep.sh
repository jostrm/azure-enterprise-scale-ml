#!/bin/bash

set -e

AIF_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for AIF_UI_LIBRARY in "$AIF_UI_DIR/ui/terminal.sh" "$AIF_UI_DIR/azure-enterprise-scale-ml/bootstrap/ui/terminal.sh"; do
    [[ ! -f "$AIF_UI_LIBRARY" ]] || break
done
if [[ ! -f "$AIF_UI_LIBRARY" ]]; then
    printf 'ERROR: AI Factory terminal library is missing. Copy bootstrap/ui alongside this script.\n' >&2
    exit 1
fi
source "$AIF_UI_LIBRARY"
aif_banner "GENAI / POST-PROVISION" "Configure the app, notebooks and search data."

# Output environment variables to .env file using azd env get-values
# azd env get-values > .env

# Load variables from .env file
if [ -f .env ]; then
    source .env
else
    aif_error ".env file not found!"
    exit 1
fi

# Retrieve service names, resource group name, and other values from environment variables
resourceGroupName=$AZURE_RESOURCE_GROUP
searchService=$AZURE_SEARCH_NAME
openAiService=$AZURE_OPENAI_NAME
subscriptionId=$AZURE_SUBSCRIPTION_ID

# Ensure all required environment variables are set
if [ -z "$resourceGroupName" ] || [ -z "$searchService" ] || [ -z "$openAiService" ] || [ -z "$subscriptionId" ]; then
    aif_error "One or more required environment variables are not set."
    aif_info "Ensure that AZURE_RESOURCE_GROUP, AZURE_SEARCH_NAME, AZURE_OPENAI_NAME, AZURE_SUBSCRIPTION_ID are set."
    exit 1
fi

# Set additional environment variables expected by app
# TODO: Standardize these and remove need for setting here
azd env set AZURE_OPENAI_API_VERSION 2024-08-01-preview
azd env set AZURE_SEARCH_ENDPOINT $AZURE_SEARCH_ENDPOINT
azd env set REACT_APP_API_BASE_URL $WEB_SERVICE_ACA_URI

# Setup to run notebooks
# Retrieve the internalId of the Cognitive Services account
INTERNAL_ID=$(az cognitiveservices account show \
    --name ${AZURE_OPENAI_NAME} \
    -g ${AZURE_RESOURCE_GROUP} \
--query "properties.internalId" -o tsv)

# Construct the URL
COGNITIVE_SERVICE_URL="https://oai.azure.com/portal/${INTERNAL_ID}?tenantid=${AZURE_TENANT_ID}"

aif_success "01 / Application environment configured."

# Setup to run notebooks
aif_section "02 / Notebook dependencies"
aif_info 'Installing dependencies from requirements.txt'
python3 -m pip install -r src/api/requirements.txt > /dev/null
python3 -m pip install ipython ipykernel > /dev/null      # Install ipython and ipykernel
ipython kernel install --name=python3 --user > /dev/null # Configure the IPython kernel
jupyter kernelspec list > /dev/null                      # Verify kernelspec list isn't empty
aif_success "Notebook environment ready."

aif_section "03 / Populate search data"
jupyter nbconvert --execute --to python --ExecutePreprocessor.timeout=-1 data/create-azure-search.ipynb > /dev/null

aif_success "Search data populated."

aif_value "Web app" "$WEB_SERVICE_ACA_URI"
aif_complete "Post-provisioning complete."
