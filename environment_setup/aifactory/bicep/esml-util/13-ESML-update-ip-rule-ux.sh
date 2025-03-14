#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Static - EDIT THIS ONCE
prefix="acme-1-" # Prefix for AI Factory common resource group, example: "acme-1-", "acme-"
region="sdc" #short name for location, e.g. eus2, weu
env="dev" # dev, test, prod
rg_instance_suffix="-001" # -001 (The suffix on your AIFactory Common resource group and suffix on project resource group)
resource_suffix="-001" # -001 (The suffix on your resources inside of project resource group, such as Azure AI Foundry, in your project resource group)
salt="abcde" # 5 chars. replace with your own salt, see keyvault name or aiservices name as example. Should be 5 characters 'asdfg' in the resource name
# Static - EDIT THIS ONCE, END 

echo -e "${GREEN}NB! This is for AI Project type: ESML - with Azure Machine Learning (DataOps, MLOps) ${NC}"

# Dynamic
read -p "Enter the old IP address (leave blank if you dont know): " old_ip
read -p "Enter the new, your current IP (IPv4 - run 'curl ifcfg.me' in terminal) address: " new_ip
read -p "Enter the project number (001,002,...): " project_number

# Construct resource names using static variables
resource_suffix_kv="${resource_suffix#-0}" # Remove -0 from the beginning
resource_suffix_kv="${resource_suffix_kv#-}" # Remove any remaining hyphen: -001 -> 01

rg="${prefix}esml-project${project_number}-${region}-${env}${rg_instance_suffix}-rg"
aml="aml-prj${project_number}-${region}-${env}-${resource_suffix}" # aml-prj002-sdc-dev-001
aml2="aml2-prj-${project_number}-${region}-${env}-${resource_suffix}" # aml2-prj002-sdc-dev-001

keyvault_1="kv-p${project_number}-${region}-${env}-${salt}${resource_suffix_kv}"
keyvault_2="kv-2${project_number}-${region}-${env}-${salt}${resource_suffix_kv}"

storage_account_1="saprj${project_number}${region}${salt}${resource_suffix}${env}"  
storage_account_1="${storage_account_1//-/}" # Remove all hyphens

storage_account_2="saprj${project_number}${region}${salt}${resource_suffix}${env}"
storage_account_2="${storage_account_2//-/}" # Remove all hyphens

########### ADD new IP #########

echo -e "${GREEN}Adding NEW ip${NC}"


# Keyvault 2
echo -e "${YELLOW}1/6: Azure Keyvault (for AML v2): Adding new IP: "$new_ip"...${NC}"
az keyvault network-rule add --resource-group $rg --name $keyvault_2 --ip-address "$new_ip"

# Storage account 2
echo -e "${YELLOW}2/6: Azure Storage Account (for AML v2): Adding new IP: "$new_ip"...${NC}"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_2 --ip-address "$new_ip"

# Azure ML v2: Update the Azure ML v1 with the new IP rule
echo -e "${YELLOW}-3/6: Azure ML v2: Adding new IP:"$new_ip"...${NC}"
#az ml workspace update --name $aml2 --resource-group $rg --network-acls "$new_ip"
# Other commands (if needed)
#az ml workspace update --resource-group $rg --name $aiproject --file 001-aml.yml

# Keyvault 1
echo -e "${YELLOW}4/6: Azure Keyvault (for AML v1): Adding new IP: "$new_ip"...${NC}"
az keyvault network-rule add --resource-group $rg --name $keyvault_1 --ip-address "$new_ip"

# Storage account 1
echo -e "${YELLOW}5/6: Azure Storage Account 2: Adding new IP: "$new_ip"...${NC}"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_1 --ip-address "$new_ip"

# 4) Azure ML v1: Update the Azure ML v2 with the new IP rule
echo -e "${YELLOW}-6/6: Azure ML v1: Adding new IP: "$new_ip"...${NC}"
#az ml workspace update --name $aml --resource-group $rg --network-acls "$new_ip"

# EventHubs
#echo -e "${YELLOW}2/7: EventHubs Namespace: Adding new IP: "$new_ip"...${NC}"
#az search service update --resource-group $rg --name $ai_search --ip-rules $new_ip

########### REMOVE OLD IP's #########

if [ -n "$old_ip" ]; then

    echo -e "${GREEN}Trying (may fail if cleaned earlier) to remove OLD ip${NC}"

    # Keyvault v1
    echo -e "${YELLOW}1/6: Azure Keyvault (Aml v2): REMOVING old IP:"$old_ip"...${NC}"
    az keyvault network-rule remove --resource-group $rg --name $keyvault_2 --ip-address $old_ip

    # Storage v2
    echo -e "${YELLOW}2/6: Azure Storage Account (Aml v2): REMOVING old IP:"$old_ip"...${NC}"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_2 --ip-address $old_ip

    # Keyvault v1
    echo -e "${YELLOW}3/6: Azure Keyvault (Aml v2): REMOVING old IP:"$old_ip"...${NC}"
    az keyvault network-rule remove --resource-group $rg --name $keyvault_1 --ip-address $old_ip

    # Storage v1
    echo -e "${YELLOW}4/6: Azure Storage Account (Aml v1): REMOVING old IP:"$old_ip"...${NC}"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_1 --ip-address $old_ip

    # 1) Azure AI Project: Update the Azure ML aiproject with the new IP rule
    #az ml workspace update --name $aml2 --resource-group $rg --network-acls "$old_ip"
    echo -e "${YELLOW}-5/6: Azure ML v1: REMOVING old IP:"$old_ip"...${NC}"
    #az ml workspace update --name $aml2 --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

    # 2) Azure AI Hub: Update the Azure ML aml with the new IP rule
    #az ml workspace update --name $aml --resource-group $rg --network-acls "$old_ip"
    echo -e "${YELLOW}-6/6: Azure ML v2: REMOVING old IP:"$old_ip"...${NC}"
    #az ml workspace update --name $aml --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
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