#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color


# Static - EDIT THIS ONCE
prefix="acme-1-" # Prefix for AI Factory common resource group. Examples: ["acme-ai-","acme-"" "mrvel-1-", "contoso-", "ms-ai-"]
region="sdc" #short name for location, e.g. eus2, weu
env="dev" # dev, test, prod
rg_instance_suffix="-001" # -001 (The suffix on your AIFactory Common resource group and suffix on project resource group)
resource_suffix="-001" # -001 (The suffix on your resources inside of project resource group, such as Azure AI Foundry, in your project resource group)
salt="abcde" # 5 chars. replace with your own salt, see keyvault name or aiservices name as example. Should be 5 characters 'asdfg' in the resource name
# Static - EDIT THIS ONCE, END 

echo -e "${GREEN}NB! This is for AI Project type: GenAI-1  with Azure AI Foundry (GenAIOps) ${NC}"

# Dynamic
read -p "Enter the old IP address (leave blank if you dont know): " old_ip
read -p "Enter the new, your current IP (IPv4 - run 'curl ifcfg.me' in terminal) address: " new_ip
read -p "Enter the project number (001,002,...): " project_number

# Construct resource names using static variables
resource_suffix_kv="${resource_suffix#-0}" # Remove -0 from the beginning
resource_suffix_kv="${resource_suffix_kv#-}" # Remove any remaining hyphen: -001 -> 01

rg="${prefix}esml-project${project_number}-${region}-${env}${rg_instance_suffix}-rg"
ai_hub="ai-hub-prj${project_number}-${region}-${env}-${salt}${resource_suffix}"
ai_project="ai-prj-${project_number}-01-${region}-${env}-${salt}${resource_suffix}"

ai_services="aiservicesprj${project_number}${region}${env}${salt}${resource_suffix}"
ai_services="${ai_services//-/}" # Remove all hyphens

ai_search="aisearchprj${project_number}${region}${env}${salt}${resource_suffix}"
ai_search="${ai_search//-/}" # Remove all hyphens

keyvault="kv-p${project_number}-${region}-${env}-${salt}${resource_suffix_kv}"

storage_account_1="saprj${project_number}${region}${salt}1${resource_suffix}${env}" 
storage_account_1="${storage_account_1//-/}" # Remove all hyphens

storage_account_2="saprj${project_number}${region}${salt}2${resource_suffix}${env}"
storage_account_2="${storage_account_2//-/}" # Remove all hyphens

#### Ensure Azure AI Search - checkbox is set: "Allow Azure Services on the trusted services list to access this search service" 
#az search service show --resource-group $rg --name $ai_search --query "networkRuleSet"
#az search service update --resource-group $rg --name $ai_search --set networkRuleSet.bypass="AzureServices"
#az search service update --resource-group $rg --name $ai_search --set properties.networkRuleSet.bypass="AzureServices"

########### ADD new IP #########

echo -e "${GREEN}Adding NEW ip${NC}"

# 1) AI Services (Cognitive services)
echo -e "${YELLOW} 1/7: AI Services: Adding new IP:"$new_ip"...${NC}"
az cognitiveservices account network-rule add -g $rg --name $ai_services --ip-address "$new_ip"

# 2) AI Search
echo -e "${YELLOW}2/7: AI Search: Adding new IP: "$new_ip"...${NC}"
#az search service update --resource-group $rg --name $ai_search --set properties.networkRuleSet.ipRules="[{'value':'$new_ip'}]"
az search service update --resource-group $rg --name $ai_search --ip-rules $new_ip

# 3) Azure AI Project: Update the Azure ML aiproject with the new IP rule
echo -e "${YELLOW}-3/7: AI Foundry Project: Adding new IP:"$new_ip"...${NC}"
#az ml workspace update --name $ai_project --resource-group $rg --network-acls "$new_ip"

# 4) Azure AI Hub: Update the Azure ML ai_hub with the new IP rule
echo -e "${YELLOW}-4/7: AI Foundry Hub: Adding new IP: "$new_ip"...${NC}"
#az ml workspace update --name $ai_hub --resource-group $rg --network-acls "$new_ip"

# 5) Keyvault
#az keyvault update --name $keyvault --resource-group $rg --set properties.networkAcls.ipRules="[{'value':'$new_ip'}]"
echo -e "${YELLOW}5/7: Azure Keyvault: Adding new IP: "$new_ip"...${NC}"
az keyvault network-rule add --resource-group $rg --name $keyvault --ip-address "$new_ip"

# 6,7) Storage account 1,2
echo -e "${YELLOW}6/7: Azure Storage Account 1: Adding new IP: "$new_ip"...${NC}"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_1 --ip-address "$new_ip"
echo -e "${YELLOW}7/7: Azure Storage Account 2: Adding new IP: "$new_ip"...${NC}"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_2 --ip-address "$new_ip"

########### REMOVE OLD IP's #########

if [ -n "$old_ip" ]; then

    echo -e "${GREEN}Trying (may fail if cleaned earlier) to remove OLD ip${NC}"

    # 3) AI Services (Cognitive services)
    echo -e "${YELLOW}1/7: Azure AI Services: REMOVING old IP:"$old_ip"...${NC}"
    az cognitiveservices account network-rule remove -g $rg --name $ai_services --ip-address "$old_ip"
    
    # 5) Keyvault
    echo -e "${YELLOW}2/7: Azure Keyvault: REMOVING old IP:"$old_ip"...${NC}"
    az keyvault network-rule remove --resource-group $rg --name $keyvault --ip-address $old_ip

    # Storage
    echo -e "${YELLOW}3/7: Azure Storage Account 1: REMOVING old IP:"$old_ip"...${NC}"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_1 --ip-address $old_ip
    echo -e "${YELLOW}4/7: Azure Storage Account 2: REMOVING old IP:"$old_ip"...${NC}"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_2 --ip-address $old_ip

    # Search
    echo -e "${YELLOW}-5/7: Azure AI Search: REMOVING old IP:"$old_ip"...${NC}"
    #az search service update --resource-group $rg --name $ai_search --remove ipRules $old_ip
    #Error: Couldn't find 'ipRules' in ''

    # 1) Azure AI Project: Update the Azure ML aiproject with the new IP rule
    #az ml workspace update --name $ai_project --resource-group $rg --network-acls "$old_ip"
    echo -e "${YELLOW}-6/7: Azure AI Foundry Project: REMOVING old IP:"$old_ip"...${NC}"
    #az ml workspace update --name $ai_project --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

    # 2) Azure AI Hub: Update the Azure ML ai_hub with the new IP rule
    #az ml workspace update --name $ai_hub --resource-group $rg --network-acls "$old_ip"
    echo -e "${YELLOW}-7/7: Azure AI Foundry Hub: REMOVING old IP:"$old_ip"...${NC}"
    #az ml workspace update --name $ai_hub --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

fi

echo -e "${GREEN}Finished! ${NC}"
echo -e "${GREEN}Be sure to update your Excel sheet, with your new IP adress for future updates (new_ip, old_ip)${NC}"
echo -e "${GREEN}new_ip:$new_ip${NC}"
echo -e "${GREEN}old_ip:$old_ip ${NC}"

# Azure ML --network-acls
# Comma-separated list of IP addresses or IP ranges in CIDR notation that are allowed to access the workspace. Example: 'XX.XX.XX.XX,XX.XX.XX.XX/32'. 
# To set Public network access to 'Enabled', pass networkAcls as 'none' (i.e. this will reset network-acls) along with the PNA flag set as 'Enabled'.
# To disable, set the PNA flag as 'Disabled'. 
# To set Public network access as 'Enabled from selected IP addresses', set the PNA flag as 'Enabled' and pass a comma-separated list of IPs in CIDR notation in 'network-acls.'.