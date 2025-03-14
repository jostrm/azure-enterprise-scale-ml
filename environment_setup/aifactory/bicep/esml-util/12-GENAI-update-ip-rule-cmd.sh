#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --prefix)
      prefix="$2"
      shift 2
      ;;
    --region)
      region="$2"
      shift 2
      ;;
    --env)
      env="$2"
      shift 2
      ;;
    --rg-instance-suffix)
      rg_instance_suffix="$2"
      shift 2
      ;;
    --resource-suffix)
      resource_suffix="$2"
      shift 2
      ;;
    --salt)
      salt="$2"
      shift 2
      ;;
    --old-ip)
      old_ip="$2"
      shift 2
      ;;
    --new-ip)
      new_ip="$2"
      shift 2
      ;;
    --project-number)
      project_number="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [options]"
      echo "Options:"
      echo "  --prefix VALUE             Prefix for AI Factory common resource group (default: acme-1-)"
      echo "  --region VALUE             Short name for location, e.g. eus2, weu (default: sdc)"
      echo "  --env VALUE                Environment: dev, test, prod (default: dev)"
      echo "  --rg-instance-suffix VALUE Suffix on AIFactory resource group (default: -001)"
      echo "  --resource-suffix VALUE    Suffix on resources (default: -001)"
      echo "  --salt VALUE               5-character salt for resource names (default: abcde)"
      echo "  --old-ip VALUE             Old IP address to remove (can be blank)"
      echo "  --new-ip VALUE             New IP address to add"
      echo "  --project-number VALUE     Project number (e.g., 001, 002)"
      exit 0
      ;;
    *)
      echo "Unknown parameter: $1"
      exit 1
      ;;
  esac
done

# Set defaults if not provided through arguments
prefix="${prefix:-acme-1-}"
region="${region:-sdc}"
env="${env:-dev}"
rg_instance_suffix="${rg_instance_suffix:--001}"
resource_suffix="${resource_suffix:--001}"
salt="${salt:-abcde}"

# Validate required parameters
if [ -z "$new_ip" ]; then
  echo -e "${RED}Error: New IP address is required. Use --new-ip parameter.${NC}"
  exit 1
fi

if [ -z "$project_number" ]; then
  echo -e "${RED}Error: Project number is required. Use --project-number parameter.${NC}"
  exit 1
fi

echo -e "${GREEN}NB! This is for AI Project type: GenAI-1 with Azure AI Foundry (GenAIOps) ${NC}"
echo -e "${GREEN}Using parameters:${NC}"
echo -e "${GREEN}- prefix: $prefix${NC}"
echo -e "${GREEN}- region: $region${NC}"
echo -e "${GREEN}- environment: $env${NC}"
echo -e "${GREEN}- resource group suffix: $rg_instance_suffix${NC}"
echo -e "${GREEN}- resource suffix: $resource_suffix${NC}"
echo -e "${GREEN}- salt: $salt${NC}"
echo -e "${GREEN}- old IP: $old_ip${NC}"
echo -e "${GREEN}- new IP: $new_ip${NC}"
echo -e "${GREEN}- project number: $project_number${NC}"

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
echo -e "${YELLOW}3/7: AI Foundry Project: Adding new IP:"$new_ip"...${NC}"
az ml workspace update --name $ai_project --resource-group $rg --network-acls "$new_ip"

# 4) Azure AI Hub: Update the Azure ML ai_hub with the new IP rule
echo -e "${YELLOW}4/7: AI Foundry Hub: Adding new IP: "$new_ip"...${NC}"
#az ml workspace update --name $ai_hub --resource-group $rg --network-acls "$new_ip"

# 5) Keyvault
#az keyvault update --name $keyvault --resource-group $rg --set properties.networkAcls.ipRules="[{'value':'$new_ip'}]"
echo -e "${YELLOW}5/7: Azure Keyvault: Adding new IP: "$new_ip"...${NC}"
#az keyvault network-rule add --resource-group $rg --name $keyvault --ip-address "$new_ip"

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
    echo -e "${YELLOW}5/7: Azure AI Search: REMOVING old IP:"$old_ip"...${NC}"
    #az search service update --resource-group $rg --name $ai_search --remove ipRules $old_ip
    #Error: Couldn't find 'ipRules' in ''

    # 1) Azure AI Project: Update the Azure ML aiproject with the new IP rule
    #az ml workspace update --name $ai_project --resource-group $rg --network-acls "$old_ip"
    echo -e "${YELLOW}6/7: Azure AI Foundry Project: REMOVING old IP:"$old_ip"...${NC}"
    #az ml workspace update --name $ai_project --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

    # 2) Azure AI Hub: Update the Azure ML ai_hub with the new IP rule
    #az ml workspace update --name $ai_hub --resource-group $rg --network-acls "$old_ip"
    echo -e "${YELLOW}7/7: Azure AI Foundry Hub: REMOVING old IP:"$old_ip"...${NC}"
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