#!/bin/bash

echo "=== AI Factory Hosts File Generator with Private IPs ==="
echo "Generating hosts file entries for all deployed resources with actual private IP addresses"

# Map positional arguments passed from the pipeline (if provided)
# Expected order (as passed by the AzureCLI task):
# 1 dev_test_prod_sub_id
# 2 admin_aifactoryPrefixRG
# 3 project_number_000
# 4 admin_locationSuffix
# 5 dev_test_prod
# 6 admin_aifactorySuffixRG
# 7 admin_prjResourceSuffix
# 8 aifactory_salt
# 9 aifactory_salt_random
# 10 deployment_random_value
# 11 projectPrefix
# 12 projectSuffix
if [ $# -ge 1 ]; then dev_test_prod_sub_id="$1"; fi
if [ $# -ge 2 ]; then admin_aifactoryPrefixRG="$2"; fi
if [ $# -ge 3 ]; then project_number_000="$3"; fi
if [ $# -ge 4 ]; then admin_locationSuffix="$4"; fi
if [ $# -ge 5 ]; then dev_test_prod="$5"; fi
if [ $# -ge 6 ]; then admin_aifactorySuffixRG="$6"; fi
if [ $# -ge 7 ]; then admin_prjResourceSuffix="$7"; fi
if [ $# -ge 8 ]; then aifactory_salt="$8"; fi
if [ $# -ge 9 ]; then aifactory_salt_random="$9"; fi
if [ $# -ge 10 ]; then deployment_random_value="${10}"; fi
if [ $# -ge 11 ]; then projectPrefix="${11}"; fi
if [ $# -ge 12 ]; then projectSuffix="${12}"; fi

# Use the subscription provided
az account set --subscription "$dev_test_prod_sub_id"

# Get variables from pipeline (now from positional args / shell variables)
commonRGNamePrefix="$admin_aifactoryPrefixRG"
projectNumber="$project_number_000"
projectName="prj${projectNumber}"
locationSuffix="$admin_locationSuffix"
envName="$dev_test_prod"
aifactorySuffixRG="$admin_aifactorySuffixRG"
resourceSuffix="$admin_prjResourceSuffix"
aifactorySalt="$aifactory_salt"
aifactorySaltRandom="$aifactory_salt_random"
randomValue="$deployment_random_value"
prjResourceSuffixNoDash=$(echo "${resourceSuffix}" | sed 's/-//g')
twoNumbers=$(echo "${resourceSuffix}" | cut -c3-4)

# Construct resource group name using same logic as pipeline
projectNameReplaced="${projectName/prj/project}"
targetResourceGroup="${commonRGNamePrefix}$(projectPrefix)${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}$(projectSuffix)"

echo "Target Resource Group: $targetResourceGroup"
echo "Project: $projectName ($projectNumber)"
echo "Environment: $envName"
echo "Location: $locationSuffix"
echo "AI Factory Salt: $aifactorySalt"
echo "Random Value: $aifactorySaltRandom"
echo ""

# Check if resource group exists
if ! az group show --name "$targetResourceGroup" &>/dev/null; then
  echo "Resource group $targetResourceGroup not found. Skipping hosts file generation."
  exit 0
fi

# Get unique identifier from common resource group (same logic as bicep)
commonResourceGroup="${commonRGNamePrefix}cmn-${locationSuffix}-${envName}${aifactorySuffixRG}"
uniqueInAIFenv=""
if az group show --name "$commonResourceGroup" &>/dev/null; then
  commonRGId=$(az group show --name "$commonResourceGroup" --query id -o tsv)
  uniqueInAIFenv=$(echo -n "$commonRGId" | sha256sum | cut -c1-5)
fi

echo "Common RG: $commonResourceGroup"
echo "Unique ID: $uniqueInAIFenv"
echo ""

# Helper function to get private IP from private endpoint
get_private_ip_from_endpoint() {
  local resource_name="$1"
  local endpoint_suffix="$2"
  local private_endpoint_name="${resource_name}${endpoint_suffix}-pend"
  local nic_name="${private_endpoint_name}-nic"
  
  echo "  Checking private endpoint: $private_endpoint_name" >&2
  
  # Option A: Get IP from private endpoint DNS configuration
  local ip_from_dns=$(az network private-endpoint show \
    --name "$private_endpoint_name" \
    --resource-group "$targetResourceGroup" \
    --query "customDnsConfigs[0].ipAddresses[0]" \
    -o tsv 2>/dev/null)
  
  if [ -n "$ip_from_dns" ] && [ "$ip_from_dns" != "null" ]; then
    echo "$ip_from_dns"
    return 0
  fi
  
  # Option B: Get IP from network interface
  echo "  Fallback: Checking network interface: $nic_name" >&2
  local ip_from_nic=$(az network nic show \
    --name "$nic_name" \
    --resource-group "$targetResourceGroup" \
    --query "ipConfigurations[0].privateIpAddress" \
    -o tsv 2>/dev/null)
  
  if [ -n "$ip_from_nic" ] && [ "$ip_from_nic" != "null" ]; then
    echo "$ip_from_nic"
    return 0
  fi
  
  echo "  No IP found for $private_endpoint_name" >&2
  return 1
}

# Helper function to get FQDN from private DNS zone mapping
get_fqdn_for_service() {
  local service_type="$1"
  local resource_name="$2"
  
  case "$service_type" in
    "amlworkspace")
      echo "${resource_name}.workspace.${locationSuffix}.api.azureml.ms"
      ;;
    "notebooks")
      echo "${resource_name}.${locationSuffix}.notebooks.azure.net"
      ;;
    "blob")
      echo "${resource_name}.blob.core.windows.net"
      ;;
    "file")
      echo "${resource_name}.file.core.windows.net"
      ;;
    "table")
      echo "${resource_name}.table.core.windows.net"
      ;;
    "queue")
      echo "${resource_name}.queue.core.windows.net"
      ;;
    "dfs")
      echo "${resource_name}.dfs.core.windows.net"
      ;;
    "vault")
      echo "${resource_name}.vault.azure.net"
      ;;
    "registry")
      echo "${resource_name}.azurecr.io"
      ;;
    "registryregion")
      echo "${locationSuffix}.data.${resource_name}.azurecr.io"
      ;;
    "openai"|"cognitiveservices")
      echo "${resource_name}.openai.azure.com"
      ;;
    "searchService")
      echo "${resource_name}.search.windows.net"
      ;;
    "azurewebapps")
      echo "${resource_name}.azurewebsites.net"
      ;;
    "cosmosdbnosql")
      echo "${resource_name}.documents.azure.com"
      ;;
    "servicesai")
      echo "${resource_name}.services.ai.azure.com"
      ;;
    *)
      echo "${resource_name}.${service_type}.azure.com"
      ;;
  esac
}

echo "=== Generating Hosts File Entries with Private IPs ==="
echo "# ${projectName} START - Generated on $(date)"
echo ""

# Get all resources in the resource group
echo "Scanning resources in $targetResourceGroup..."

# Get all private endpoints to understand the naming pattern
private_endpoints=$(az network private-endpoint list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")

if [ -n "$private_endpoints" ]; then
  echo "Found private endpoints:"
  echo "$private_endpoints" | while read -r pend_name; do
    echo "  - $pend_name"
  done
  echo ""
fi

# Process different resource types

# 1. AML Workspaces (AI Foundry Hubs/Projects)
echo "# AML Workspaces (AI Foundry Hubs/Projects)"
aml_workspaces=$(az ml workspace list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$aml_workspaces" ]; then
  echo "$aml_workspaces" | while read -r workspace_name; do
    if [ -n "$workspace_name" ]; then
      # AML workspace endpoint
      ip_aml=$(get_private_ip_from_endpoint "$workspace_name" "")
      if [ $? -eq 0 ]; then
        fqdn_aml=$(get_fqdn_for_service "amlworkspace" "$workspace_name")
        echo "$ip_aml $fqdn_aml"
        
        # Notebooks endpoint (same IP, different FQDN)
        fqdn_notebooks=$(get_fqdn_for_service "notebooks" "$workspace_name")
        echo "$ip_aml $fqdn_notebooks"
      else
        echo "# $workspace_name - IP not found"
      fi
    fi
  done
fi
echo ""

# 2. Storage Accounts
echo "# Storage Accounts"
storage_accounts=$(az storage account list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$storage_accounts" ]; then
  echo "$storage_accounts" | while read -r storage_name; do
    if [ -n "$storage_name" ]; then
      # Blob endpoint
      ip_blob=$(get_private_ip_from_endpoint "$storage_name" "-blob")
      if [ $? -eq 0 ]; then
        fqdn_blob=$(get_fqdn_for_service "blob" "$storage_name")
        echo "$ip_blob $fqdn_blob"
      fi
      
      # File endpoint
      ip_file=$(get_private_ip_from_endpoint "$storage_name" "-file")
      if [ $? -eq 0 ]; then
        fqdn_file=$(get_fqdn_for_service "file" "$storage_name")
        echo "$ip_file $fqdn_file"
      fi
      
      # Table endpoint
      ip_table=$(get_private_ip_from_endpoint "$storage_name" "-table")
      if [ $? -eq 0 ]; then
        fqdn_table=$(get_fqdn_for_service "table" "$storage_name")
        echo "$ip_table $fqdn_table"
      fi
      
      # Queue endpoint
      ip_queue=$(get_private_ip_from_endpoint "$storage_name" "-queu")  # Note: truncated to 'queu'
      if [ $? -eq 0 ]; then
        fqdn_queue=$(get_fqdn_for_service "queue" "$storage_name")
        echo "$ip_queue $fqdn_queue"
      fi
      
      # DFS endpoint (for Data Lake)
      ip_dfs=$(get_private_ip_from_endpoint "$storage_name" "-dfs")
      if [ $? -eq 0 ]; then
        fqdn_dfs=$(get_fqdn_for_service "dfs" "$storage_name")
        echo "$ip_dfs $fqdn_dfs"
      fi
    fi
  done
fi
echo ""

# 3. Key Vaults
echo "# Key Vaults"
key_vaults=$(az keyvault list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$key_vaults" ]; then
  echo "$key_vaults" | while read -r kv_name; do
    if [ -n "$kv_name" ]; then
      ip_kv=$(get_private_ip_from_endpoint "$kv_name" "")
      if [ $? -eq 0 ]; then
        fqdn_kv=$(get_fqdn_for_service "vault" "$kv_name")
        echo "$ip_kv $fqdn_kv"
      else
        echo "# $kv_name - IP not found"
      fi
    fi
  done
fi
echo ""

# 4. AI Services (Cognitive Services)
echo "# AI Services (Cognitive Services)"
cognitive_services=$(az cognitiveservices account list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$cognitive_services" ]; then
  echo "$cognitive_services" | while read -r cs_name; do
    if [ -n "$cs_name" ]; then
      ip_cs=$(get_private_ip_from_endpoint "$cs_name" "")
      if [ $? -eq 0 ]; then
        # Check if it's OpenAI or general cognitive services
        cs_kind=$(az cognitiveservices account show --name "$cs_name" --resource-group "$targetResourceGroup" --query "kind" -o tsv 2>/dev/null)
        if [[ "$cs_kind" == *"OpenAI"* ]]; then
          fqdn_cs=$(get_fqdn_for_service "openai" "$cs_name")
        else
          fqdn_cs=$(get_fqdn_for_service "cognitiveservices" "$cs_name")
        fi
        echo "$ip_cs $fqdn_cs"
      else
        echo "# $cs_name - IP not found"
      fi
    fi
  done
fi
echo ""

# 5. AI Search Services
echo "# AI Search Services"
search_services=$(az search service list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$search_services" ]; then
  echo "$search_services" | while read -r search_name; do
    if [ -n "$search_name" ]; then
      ip_search=$(get_private_ip_from_endpoint "$search_name" "")
      if [ $? -eq 0 ]; then
        fqdn_search=$(get_fqdn_for_service "searchService" "$search_name")
        echo "$ip_search $fqdn_search"
      else
        echo "# $search_name - IP not found"
      fi
    fi
  done
fi
echo ""

# 6. Container Registry
echo "# Container Registry"
container_registries=$(az acr list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$container_registries" ]; then
  echo "$container_registries" | while read -r acr_name; do
    if [ -n "$acr_name" ]; then
      ip_acr=$(get_private_ip_from_endpoint "$acr_name" "")
      if [ $? -eq 0 ]; then
        fqdn_acr=$(get_fqdn_for_service "registry" "$acr_name")
        echo "$ip_acr $fqdn_acr"
        
        # Registry region endpoint
        fqdn_acr_region=$(get_fqdn_for_service "registryregion" "$acr_name")
        echo "$ip_acr $fqdn_acr_region"
      else
        echo "# $acr_name - IP not found"
      fi
    fi
  done
fi
echo ""

# 7. Web Apps
echo "# Web Apps"
web_apps=$(az webapp list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$web_apps" ]; then
  echo "$web_apps" | while read -r webapp_name; do
    if [ -n "$webapp_name" ]; then
      ip_webapp=$(get_private_ip_from_endpoint "$webapp_name" "")
      if [ $? -eq 0 ]; then
        fqdn_webapp=$(get_fqdn_for_service "azurewebapps" "$webapp_name")
        echo "$ip_webapp $fqdn_webapp"
      else
        echo "# $webapp_name - IP not found"
      fi
    fi
  done
fi
echo ""

# 8. Cosmos DB
echo "# Cosmos DB"
cosmos_accounts=$(az cosmosdb list --resource-group "$targetResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$cosmos_accounts" ]; then
  echo "$cosmos_accounts" | while read -r cosmos_name; do
    if [ -n "$cosmos_name" ]; then
      ip_cosmos=$(get_private_ip_from_endpoint "$cosmos_name" "")
      if [ $? -eq 0 ]; then
        fqdn_cosmos=$(get_fqdn_for_service "cosmosdbnosql" "$cosmos_name")
        echo "$ip_cosmos $fqdn_cosmos"
      else
        echo "# $cosmos_name - IP not found"
      fi
    fi
  done
fi
echo ""

echo "# ${projectName} END - Generated on $(date)"
echo ""

echo "=== Hosts File Generation Complete ==="
echo ""
echo "Instructions:"
echo "1. Copy the generated host entries above (lines starting with IP addresses)"
echo "2. Add them to your local hosts file:"
echo "   - Windows: C:\\Windows\\System32\\drivers\\etc\\hosts"
echo "   - Linux/Mac: /etc/hosts"
echo "3. Format: <PRIVATE_IP> <FQDN>"
echo "4. Restart your applications or flush DNS cache after adding entries"
echo ""
echo "DNS Cache Flush Commands:"
echo "- Windows: ipconfig /flushdns"
echo "- Linux: sudo systemctl restart systemd-resolved"
echo "- Mac: sudo dscacheutil -flushcache"
echo ""