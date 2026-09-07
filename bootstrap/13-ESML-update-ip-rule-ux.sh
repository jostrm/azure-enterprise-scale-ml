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
aif_banner "AZURE ML / NETWORK ACCESS" "Update your project IP allowlist."

# Static - EDIT THIS ONCE
prefix="acme-1-" # Prefix for AI Factory common resource group, example: "acme-1-"
region="sdc" #short name for location, e.g. eus2, weu
env="dev" # dev, test, prod
rg_instance_suffix="-001" # -001 (The suffix on your AIFactory Common resource group and suffix on project resource group)
resource_suffix="-001" # -001 (The suffix on your resources inside of project resource group, such as Azure AI Foundry, in your project resource group)
salt="abcde" # 5 chars. replace with your own salt, see keyvault name or aiservices name as example. Should be 5 characters 'asdfg' in the resource name
# Static - EDIT THIS ONCE, END 

aif_info "NB! This is for AI Project type: ESML - with Azure Machine Learning (DataOps, MLOps) "

# Dynamic
read -p "$(aif_prompt "Enter the old IP address (leave blank if you dont know): ")" old_ip
read -p "$(aif_prompt "Enter the new, your current IP (IPv4 - run 'curl ifcfg.me' in terminal) address: ")" new_ip
read -p "$(aif_prompt "Enter the project number (001,002,...): ")" project_number

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

aif_section "Adding NEW ip"


# Keyvault 2
aif_step "01/06" "Key Vault / AML v2 / add $new_ip"
az keyvault network-rule add --resource-group $rg --name $keyvault_2 --ip-address "$new_ip"

# Storage account 2
aif_step "02/06" "Storage / AML v2 / add $new_ip"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_2 --ip-address "$new_ip"

# Azure ML v2: Update the Azure ML v1 with the new IP rule
aif_detail "03/06 / AML v2 workspace allowlist is not automated by this script."
#az ml workspace update --name $aml2 --resource-group $rg --network-acls "$new_ip"
# Other commands (if needed)
#az ml workspace update --resource-group $rg --name $aiproject --file 001-aml.yml

# Keyvault 1
aif_step "04/06" "Key Vault / AML v1 / add $new_ip"
az keyvault network-rule add --resource-group $rg --name $keyvault_1 --ip-address "$new_ip"

# Storage account 1
aif_step "05/06" "Storage / AML v1 / add $new_ip"
az storage account network-rule add --resource-group $rg  --account-name $storage_account_1 --ip-address "$new_ip"

# 4) Azure ML v1: Update the Azure ML v2 with the new IP rule
aif_detail "06/06 / AML v1 workspace allowlist is not automated by this script."
#az ml workspace update --name $aml --resource-group $rg --network-acls "$new_ip"

# EventHubs
#echo -e "${YELLOW}2/7: EventHubs Namespace: Adding new IP: "$new_ip"...${NC}"
#az search service update --resource-group $rg --name $ai_search --ip-rules $new_ip

########### REMOVE OLD IP's #########

if [ -n "$old_ip" ]; then

    aif_section "Trying (may fail if cleaned earlier) to remove OLD ip"

    # Keyvault v1
    aif_step "01/06" "Key Vault / AML v2 / remove $old_ip"
    az keyvault network-rule remove --resource-group $rg --name $keyvault_2 --ip-address $old_ip

    # Storage v2
    aif_step "02/06" "Storage / AML v2 / remove $old_ip"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_2 --ip-address $old_ip

    # Keyvault v1
    aif_step "03/06" "Key Vault / AML v1 / remove $old_ip"
    az keyvault network-rule remove --resource-group $rg --name $keyvault_1 --ip-address $old_ip

    # Storage v1
    aif_step "04/06" "Storage / AML v1 / remove $old_ip"
    az storage account network-rule remove --resource-group $rg  --account-name $storage_account_1 --ip-address $old_ip

    # 1) Azure AI Project: Update the Azure ML aiproject with the new IP rule
    #az ml workspace update --name $aml2 --resource-group $rg --network-acls "$old_ip"
    aif_detail "05/06 / AML v1 workspace removal is not automated by this script."
    #az ml workspace update --name $aml2 --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

    # 2) Azure AI Hub: Update the Azure ML aml with the new IP rule
    #az ml workspace update --name $aml --resource-group $rg --network-acls "$old_ip"
    aif_detail "06/06 / AML v2 workspace removal is not automated by this script."
    #az ml workspace update --name $aml --resource-group $rg --remove networkAcls.ipRules "[{'value':'$old_ip'}]"
    #Error: Couldn't find 'networkAcls' in 'networkAcls'. Available options: []

fi

aif_section "Network update summary"
aif_warn "Review any command errors above and record the new IP for your next update."
aif_value "New IP" "$new_ip"
aif_value "Previous IP" "${old_ip:-Not supplied}"

# Azure ML --network-acls
# Comma-separated list of IP addresses or IP ranges in CIDR notation that are allowed to access the workspace. Example: 'XX.XX.XX.XX,XX.XX.XX.XX/32'. 
# To set Public network access to 'Enabled', pass networkAcls as 'none' (i.e. this will reset network-acls) along with the PNA flag set as 'Enabled'.
# To disable, set the PNA flag as 'Disabled'. 
# To set Public network access as 'Enabled from selected IP addresses', set the PNA flag as 'Enabled' and pass a comma-separated list of IPs in CIDR notation in 'network-acls.'.
