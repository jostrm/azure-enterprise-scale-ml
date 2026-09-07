#!/bin/bash

AIF_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for AIF_UI_LIBRARY in "$AIF_UI_DIR/ui/terminal.sh" "$AIF_UI_DIR/azure-enterprise-scale-ml/bootstrap/ui/terminal.sh"; do
    [[ ! -f "$AIF_UI_LIBRARY" ]] || break
done
if [[ ! -f "$AIF_UI_LIBRARY" ]]; then
    printf 'ERROR: AI Factory terminal library is missing. Copy bootstrap/ui alongside this script.\n' >&2
    exit 1
fi
source "$AIF_UI_LIBRARY"
aif_banner "GENAI / NETWORK ACCESS" "Update your project IP allowlist."


# Static - EDIT THIS ONCE
prefix="mrvel-1-" # Prefix for AI Factory common resource group, example: "acme-1-"
region="eus2" #short name for location, e.g. eus2, weu, sdc
env="dev" # dev, test, prod
rg_instance_suffix="-005" # -001 (The suffix on your AIFactory Common resource group and suffix on project resource group)
resource_suffix="-001" # -001 (The suffix on your resources inside of project resource group, such as Azure AI Foundry, in your project resource group)

rg_instance_suffix="-004" # -001 (The suffix on your AIFactory Common resource group and suffix on project resource group)
salt="abtkd" # 5 chars. replace with your own salt, see keyvault name or aiservices name as example. Should be 5 characters 'asdfg' in the resource name
rg_instance_suffix="-005" # -001 (The suffix on your AIFactory Common resource group and suffix on project resource group)
salt="avhwo"
# Static - EDIT THIS ONCE, END 

aif_info "NB! This is for AI Project type: GenAI-1  with Azure AI Foundry (GenAIOps) "

# Dynamic
read -p "$(aif_prompt "Enter the old IP address (leave blank if you dont know): ")" old_ip
read -p "$(aif_prompt "Enter the new, your current IP (IPv4 - run 'curl ifcfg.me' in terminal) address: ")" new_ip
read -p "$(aif_prompt "Enter the project number (001,002,...): ")" project_number

# Trim leading and trailing whitespace from new_ip
new_ip="${new_ip#"${new_ip%%[![:space:]]*}"}"   # Remove leading whitespace
new_ip="${new_ip%"${new_ip##*[![:space:]]}"}"   # Remove trailing whitespace

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

########### REMOVE OLD IP's #########

if [ -n "$old_ip" ]; then

    aif_section "Trying (may fail if cleaned earlier) to remove OLD ip"

    # 3) AI Services (Cognitive services)
    aif_step "01/07" "Azure AI Services / remove $old_ip"
    az cognitiveservices account network-rule remove -g $rg --name $ai_services --ip-address "$old_ip"
    
    # 5) Keyvault
    aif_step "02/07" "Key Vault / remove $old_ip"
    az keyvault network-rule remove --resource-group $rg --name $keyvault --ip-address $old_ip

    # Storage
    aif_step "03/07" "Storage account 1 / remove $old_ip"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_1 --ip-address $old_ip
    aif_step "04/07" "Storage account 2 / remove $old_ip"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_2 --ip-address $old_ip

    # Search
    aif_detail "05/07 / AI Search removal is not automated by this script."
    #az search service update --resource-group $rg --name $ai_search --remove ipRules $old_ip
    #Error: Couldn't find 'ipRules' in ''

    # 1) Azure AI Project: Update the Azure ML aiproject with the new IP rule
    #az ml workspace update --name $ai_project --resource-group $rg --network-acls "$old_ip"
    aif_detail "06/07 / Foundry Project removal is not automated by this script."
    #az ml workspace update --name $ai_project --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

    # 2) Azure AI Hub: Update the Azure ML ai_hub with the new IP rule
    #az ml workspace update --name $ai_hub --resource-group $rg --network-acls "$old_ip"
    aif_detail "07/07 / Foundry Hub removal is not automated by this script."
    #az ml workspace update --name $ai_hub --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

fi

########### ADD new IP #########

aif_section "Adding NEW ip"

# 1) AI Services (Cognitive services)
aif_step "01/07" "Azure AI Services / add $new_ip"
az cognitiveservices account network-rule add -g $rg --name $ai_services --ip-address "$new_ip"

# 2) AI Search
aif_step "02/07" "AI Search / add $new_ip"
#az search service update --resource-group $rg --name $ai_search --set properties.networkRuleSet.ipRules="[{'value':'$new_ip'}]"
az search service update --resource-group $rg --name $ai_search --ip-rules $new_ip

# 3) Keyvault
#az keyvault update --name $keyvault --resource-group $rg --set properties.networkAcls.ipRules="[{'value':'$new_ip'}]"
aif_step "03/07" "Key Vault / add $new_ip"
az keyvault network-rule add --resource-group $rg --name $keyvault --ip-address "$new_ip"

# 4,5) Storage account 1,2
aif_step "04/07" "Storage account 1 / add $new_ip"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_1 --ip-address "$new_ip"
aif_step "05/07" "Storage account 2 / add $new_ip"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_2 --ip-address "$new_ip"

# 6) Azure AI Project: Update the Azure ML aiproject with the new IP rule
aif_detail "06/07 / Foundry Project allowlist is not automated by this script."
#az ml workspace update --name $ai_project --resource-group $rg --network-acls "$new_ip"

# 7) Azure AI Hub: Update the Azure ML ai_hub with the new IP rule
aif_detail "07/07 / Foundry Hub allowlist is not automated by this script."
#az ml workspace update --name $ai_hub --resource-group $rg --network-acls "$new_ip"

# AML enabler
#echo -e "${YELLOW}+ Enable Azure ML Private Link...${NC}"
#az ml workspace update --resource-group $rg --name $ai_project --file ./aifactory/esml-util/001-aml.yml

aif_section "Network update summary"
aif_warn "Review any command errors above and record the new IP for your next update."
aif_value "New IP" "$new_ip"
aif_value "Previous IP" "${old_ip:-Not supplied}"

# Azure ML --network-acls
# Comma-separated list of IP addresses or IP ranges in CIDR notation that are allowed to access the workspace. Example: 'XX.XX.XX.XX,XX.XX.XX.XX/32'. 
# To set Public network access to 'Enabled', pass networkAcls as 'none' (i.e. this will reset network-acls) along with the PNA flag set as 'Enabled'.
# To disable, set the PNA flag as 'Disabled'. 
# To set Public network access as 'Enabled from selected IP addresses', set the PNA flag as 'Enabled' and pass a comma-separated list of IPs in CIDR notation in 'network-acls.'.
