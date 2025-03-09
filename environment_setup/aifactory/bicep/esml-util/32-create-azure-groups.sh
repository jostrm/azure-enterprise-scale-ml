#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}AUDIENCE:${NC} Microsoft Entra Admin - to bootstrap with Persona AD-groups, and add info to Seeding keyvault with group ObjectIDs \n "
echo -e "${YELLOW}WHAT:${NC} Script will create Entra ID Security groups, per project, per persona. It will save this info (Group ObjectId)  in seeding keyvault as secrets with secret name:${GREEN} group-prjXXX-pYYY ${NC} \n "
echo -e "${YELLOW}HOW:${NC} First time, once, choose core-team, to create these groups once. Then choose esml or genai-1, to create groups for each project.\n "
echo -e "${YELLOW}BEFORE RUNNING SCRIPT:${NC} Be sure to set Azure CLI to correct: Tenant, and set Azure Subscription where your Seeding keyvault resides.\n "

if [ -z "$SEEDING_KEYVAULT_NAME" ]; then
    read -p "Please enter your Azure SEEDING_KEYVAULT_NAME (will be used to save group ObjectIDs) " SEEDING_KEYVAULT_NAME
fi

# Prompt for TENANT_ID if not set
#if [ -z "$TENANT_ID" ]; then
#    read -p "Enter your Azure Tenant ID: " TENANT_ID
#fi

#echo -e "${YELLOW}Logging in to Azure...${NC}"
#az login --tenant $TENANT_ID

# Function to create a security group
create_group() {
    local group_name=$1
    local group_description=$2

    echo "Creating group $group_name with description $group_description..."
    #az ad group create --display-name "$group_name" --mail-nickname "$group_name" --description "$group_description"
    #group_id=$(az ad group show --group "$group_name" --query objectId -o tsv)
    group_id=$(az ad group create --display-name "$group_name" --mail-nickname "$group_name" --description "$group_description" --query id -o tsv)
    
    if [ -z "$group_id" ]; then
        echo -e "${RED}Failed to retrieve Object ID for group $group_name. Please check the Azure CLI output for errors.${NC}"
        exit 1
    fi

    echo "Created group $group_name with Object ID $group_id"

    if [ -n "$SEEDING_KEYVAULT_NAME" ]; then
        store_group_id_in_keyvault "$group_name" "$group_id"
    else
        echo -e "${YELLOW}SEEDING_KEYVAULT_NAME is not set. Skipping storing Object ID in Key Vault.${NC}"
    fi
}

# Function to store group Object ID in Azure Key Vault
store_group_id_in_keyvault() {
    local group_name=$1
    local group_id=$2

    if [[ $group_name =~ (prj[0-9]{3}).*(p[0-9]{3}) ]]; then
        local secret_name="group-${BASH_REMATCH[1]}-${BASH_REMATCH[2]}"
        az keyvault secret set --vault-name $SEEDING_KEYVAULT_NAME --name ${secret_name} --value ${group_id}
        #az keyvault secret set --vault-name $KEY_VAULT_NAME --name ${SP_KV_APP_ID} --value $APP_ID
        echo "Stored Object ID $group_id in Key Vault as secret $secret_name"
    fi
}

# Function to generate group names and descriptions based on project number
generate_group_info() {
    local project_number=$1
    local persona_number=$2
    local persona_name=$3

    # Pad project number with leading zeros to ensure it is three digits
    local padded_project_number=$(printf "%03d" $project_number)

    local group_name="aif001sdc_prj${padded_project_number}_team_${persona_name}_p${persona_number}"
    local group_description="${persona_name}"

    echo "$group_name" "$group_description"
}

# Main script
read -p "Enter project type (esml, genai-1, core-team): " project_type

if [ "$project_type" == "esml" ] || [ "$project_type" == "genai-1" ]; then
    read -p "Enter project number (1,2,3): " project_number
fi

# Define personas for each project type
declare -A personas_project_esml=(
    ["001"]="team_lead"
    ["002"]="team_member_ds"
    ["003"]="team_member_fend"
)

declare -A personas_project_genai_1=(
    ["011"]="team_lead"
    ["012"]="genai_team_member_aifoundry"
    ["013"]="genai_team_member_agentic"
    ["014"]="genai_team_member_dataops"
    ["015"]="team_member_fend"
)

declare -A personas_core_team=(
    ["080"]="coreteam_admin"
    ["081"]="coreteam_dataops"
    ["082"]="coreteam_dataops_fabric"
)

# Create groups based on project type and number
if [ "$project_type" == "esml" ]; then
    for persona_number in "${!personas_project_esml[@]}"; do
        persona_name=${personas_project_esml[$persona_number]}
        read group_name group_description < <(generate_group_info "$project_number" "$persona_number" "$persona_name")
        create_group "$group_name" "$group_description"
    done
elif [ "$project_type" == "genai-1" ]; then
    for persona_number in "${!personas_project_genai_1[@]}"; do
        persona_name=${personas_project_genai_1[$persona_number]}
        read group_name group_description < <(generate_group_info "$project_number" "$persona_number" "$persona_name")
        create_group "$group_name" "$group_description"
    done
elif [ "$project_type" == "core-team" ]; then
    for persona_number in "${!personas_core_team[@]}"; do
        persona_name=${personas_core_team[$persona_number]}
        read group_name group_description < <(generate_group_info "000" "$persona_number" "$persona_name")
        create_group "$group_name" "$group_description"
    done
else
    echo "Invalid project type. Please enter esml, genai-1, or core-team."
    exit 1
fi

echo "Groups created successfully."
echo -e "${YELLOW}Groups ObjectID saved in seeding keyvault as secreted with secret nanme:${GREEN} group-prjXXX-pYYY ${NC} \n "