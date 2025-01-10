#!/bin/bash

# Get ObjectID
# az ad sp show --id AppId --query id -o tsv

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 1) EDIT Variables ONCE ################### 
SUBSCRIPTION_ID="<your-key-vault-name>" # Seeding keyvault
KEY_VAULT_NAME="<your-key-vault-name>" # Seeding keyvault
TENANT_ID="<your-tenant-id>" # Seeding keyvault
USER_EMAIL="<your-user-email-with-entraID-access-to-create-ServicePrinciples-And-Store-Secrets>"
SERVICE_PRINCIPAL_NAME_TEMPLATE="<service-principal-name-template-[XXX]>" # User either [XXX] or [Y] somewhere: "esml-project[XXX]-sp", "esml-deployment-project[Y]"

# 2) EDIT Variables FOR EACH new service principle ################### 
PROJECT_NUMBER_XXX="001" # A string with three characters: 001, 023, 123

# 3* OPTIONAL Variable: Only need to set if using [Y] in SERVICE_PRINCIPAL_NAME_TEMPLATE
PROJECT_NUMBER_Y="" # A string number between 1-999. Example: "2" 

# EDIT END

##################### DO NOT CHANGE ANYTHING BELOW #####################
# Template Names
SP_NAME_TEMPLATE="esml-projectXXX-sp-id"
SP_KV_ID_TEMPLATE="esml-projectXXX-sp-id"
SP_KV_OID_TEMPLATE="esml-projectXXX-sp-oid"
SP_KV_SECRET_TEMPLATE="esml-projectXXX-sp-secret"

# Replace "XXX" with the value in PROJECT_NUMBER_XXX
SERVICE_PRINCIPAL_NAME=""

if [[ $SERVICE_PRINCIPAL_NAME_TEMPLATE == *"[XXX]"* ]]; then
    echo "SERVICE_PRINCIPAL_NAME_TEMPLATE contains [XXX]"
    SERVICE_PRINCIPAL_NAME=$(echo $SERVICE_PRINCIPAL_NAME_TEMPLATE | sed "s/\[XXX\]/$PROJECT_NUMBER_XXX/")
elif [[ $SERVICE_PRINCIPAL_NAME_TEMPLATE == *"[Y]"* ]]; then
    echo "SERVICE_PRINCIPAL_NAME_TEMPLATE does not contains [Y]"
    SERVICE_PRINCIPAL_NAME=$(echo $SERVICE_PRINCIPAL_NAME_TEMPLATE | sed "s/\[Y\]/$PROJECT_NUMBER_XXX/")
fi

SP_KV_APP_ID=$(echo $SP_KV_ID_TEMPLATE | sed "s/XXX/$PROJECT_NUMBER_XXX/")
SP_KV_OID=$(echo $SP_KV_OID_TEMPLATE | sed "s/XXX/$PROJECT_NUMBER_XXX/")
SP_KV_SECRET=$(echo $SP_KV_SECRET_TEMPLATE | sed "s/XXX/$PROJECT_NUMBER_XXX/")

echo -e "${YELLOW}SERVICE_PRINCIPAL_NAME${NC} to be created is: ${GREEN}"$SERVICE_PRINCIPAL_NAME"${NC}"
echo -e "${YELLOW}APP ID name as KV SECRET${NC} in seeding keyvault will have the name: ${GREEN}"$SP_KV_APP_ID"${NC}"
echo -e "${YELLOW}OBJECT ID NAME as KV SECRET${NC} in seeding keyvault will have the name: ${GREEN}"$SP_KV_OID"${NC}"
echo -e "${YELLOW}SECRET NAME as KV SECRET${NC} in seeding keyvault will have the name: ${GREEN}"$SP_KV_SECRET"${NC}"
echo -e "${GREEN}Note: If exists: ${NC}If Service principla already exists, then ObjectID will be updated in seeding keyvault.${NC}"

# Prompt the user for confirmation
read -p "Continue (Y/n)? " choice
if [[ "$choice" == "n" || "$choice" == "N" ]]; then
    echo "Exiting script."
    exit 1
fi

# Login to Azure with EntraID user
echo -e "${YELLOW}Logging in to Azure...${NC}"
az login --tenant $TENANT_ID
az account set --subscription $SUBSCRIPTION_ID
#az account get-access-token

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to login to Azure${NC}"
    exit 1
fi

echo -e "${YELLOW}Checking if service principal exists...${NC}"
SP_EXISTS=$(az ad sp list --display-name "$SERVICE_PRINCIPAL_NAME" --query "[].appId" -o tsv)
APP_ID="not set"
OBJECT_ID="not set"
PASSWORD="not set"

if [ -z "$SP_EXISTS" ]; then
    echo -e "${YELLOW}Service principal does NOT exist${NC}"
    # Create service principal
    echo -e "${YELLOW}Creating service principal...${NC}"
    
    SP_OUTPUT=$(az ad sp create-for-rbac --name "$SERVICE_PRINCIPAL_NAME" --query "{appId: appId, password: password}" -o json)

    if [ $? -ne 0 ]; then
        echo -e "${RED}Failed to create service principal${NC}"
        exit 1
    fi
    # Echo all
    echo $SP_OUTPUT

    # Extract values
    APP_ID=$(echo $SP_OUTPUT | grep -oP '(?<="appId": ")[^"]*')
    PASSWORD=$(echo $SP_OUTPUT | grep -oP '(?<="password": ")[^"]*')
    OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

    echo -e "${GREEN}Storing values (APP_ID, OID, SECRET) in Seeding Key Vault...${NC}"
    #Print APP_ID
    echo -e "${GREEN}APP_ID: {$APP_ID} ${NC}"
    echo -e "${GREEN}OBJECT_ID: {$OBJECT_ID} ${NC}"
    #echo -e "${GREEN}PASSWORD: {$PASSWORD} ${NC}"

    az keyvault secret set --vault-name $KEY_VAULT_NAME --name ${SP_KV_APP_ID} --value $APP_ID
    az keyvault secret set --vault-name $KEY_VAULT_NAME --name ${SP_KV_OID} --value $OBJECT_ID
    az keyvault secret set --vault-name $KEY_VAULT_NAME --name ${SP_KV_SECRET} --value $PASSWORD > /dev/null

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Service principal credentials stored in Key Vault successfully${NC}"
    else
        echo -e "${RED}Failed to store credentials in Key Vault${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Service principal already exists. Now updating OBJECT_ID in Seeding Keyvault${NC}"
    APP_ID=$SP_EXISTS
    OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

    #Print APP_ID
    echo -e "${GREEN}APP_ID: {$APP_ID} ${NC}"
    echo -e "${GREEN}OBJECT_ID: {$OBJECT_ID} ${NC}"
    #echo -e "${GREEN}PASSWORD: {$PASSWORD} ${NC}"
    
    az keyvault secret set --vault-name $KEY_VAULT_NAME --name ${SP_KV_OID} --value $OBJECT_ID
    az keyvault secret set --vault-name $KEY_VAULT_NAME --name ${SP_KV_APP_ID} --value $APP_ID
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Service principal credentials stored in Key Vault successfully${NC}"
    else
        echo -e "${RED}Failed to store credentials in Key Vault${NC}"
        exit 1
    fi
fi

# Set logo URL for the service principal
$LOGO_URL = './images/sp-aifactory-house.png'
echo -e "${YELLOW}Setting logo URL for the service principal...${NC}"
az ad sp update --id $APP_ID --set appLogoUrl=$LOGO_URL

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Logo URL set successfully${NC}"
else
    echo -e "${RED}Failed to set logo URL${NC}"
    exit 1
fi