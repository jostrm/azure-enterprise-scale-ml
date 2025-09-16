#!/bin/bash

echo "=== AI Foundry Project Error Cleanup ==="
echo "This task runs only when 69-aifoundry-2025 task failed with AIFoundry V2 related errors"

az account set --subscription "$(dev_test_prod_sub_id)"

# Input parameters - replicating the same logic from 05b_Check if resource exists
commonRGNamePrefix="$(admin_aifactoryPrefixRG)"
projectNumber="$(project_number_000)"
projectName="prj${projectNumber}"
locationSuffix="$(admin_locationSuffix)"
envName="$(dev_test_prod)"
aifactorySuffixRG="$(admin_aifactorySuffixRG)"

# Construct resource group name
projectNameReplaced="${projectName/prj/project}"
targetResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"

# AI Foundry V2 name pattern (same as in 05b task)
aiFoundryV2Name="aif2"

echo "Target Resource Group: $targetResourceGroup"
echo "AI Foundry V2 Name Pattern: $aiFoundryV2Name"

# Check if this is specifically an AIFoundry V2 related error
echo "Checking if error is related to AIFoundry V2 resources..."

# Get the error details from the pipeline (this will help identify if it's aif2 related)
DEPLOYMENT_NAME_PATTERN="09-AifV2-NoAvm_"
AIF2_RESOURCE_PATTERN="aif2"

echo "Looking for deployment errors containing: $DEPLOYMENT_NAME_PATTERN"
echo "Looking for resource errors starting with: $AIF2_RESOURCE_PATTERN"

# Check recent deployment failures for AIFoundry V2 patterns
echo "Checking recent deployments for AIFoundry V2 related failures..."
recent_deployments=$(az deployment sub list \
  --subscription "$(dev_test_prod_sub_id)" \
  --query "[?starts_with(name, 'esml-p$(project_number_000)-$(dev_test_prod)-$(admin_locationSuffix)') && contains(name, '69-aifoundry-2025')].{name:name, provisioningState:properties.provisioningState, error:properties.error}" \
  --output json 2>/dev/null || echo "[]")

echo "Recent deployments: $recent_deployments"

# Check if we should proceed with cleanup based on error patterns
should_cleanup="false"

if echo "$recent_deployments" | grep -qi "09-AifV2-NoAvm_\|aif2"; then
  echo "Found AIFoundry V2 related deployment errors"
  should_cleanup="true"
fi

# Alternative check: look for AIFoundry V2 resources that might exist but be in error state
aif2_resources=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.CognitiveServices/accounts" \
  --query "[?starts_with(name, '$aiFoundryV2Name')].name" \
  --output tsv 2>/dev/null || echo "")

if [ -n "$aif2_resources" ]; then
  echo "Found existing AIFoundry V2 resources that may need cleanup"
  should_cleanup="true"
fi

if [ "$should_cleanup" = "true" ]; then
  echo "=== Proceeding with AIFoundry V2 resource cleanup ==="
  
  # Function to delete AIFoundry V2 resource and its related components with fuzzy endpoint matching
  delete_aifoundry_v2_and_endpoints() {
    local resourceName="$1"
    local resourceType="$2"
    
    echo "=== Processing AIFoundry V2 resource: $resourceName ==="
    
    # Check if the resource exists
    if az resource show --resource-group "$targetResourceGroup" --name "$resourceName" --resource-type "$resourceType" &> /dev/null; then
      echo "Found AIFoundry V2 resource: $resourceName"
      
      # Delete private endpoints and NICs using fuzzy matching (since they have random salt)
      echo "Searching for private endpoints matching pattern: ${resourceName}-pend"
      privateEndpoints=$(az network private-endpoint list --resource-group "$targetResourceGroup" --query "[?starts_with(name, '${resourceName}-pend')].name" --output tsv)
      
      if [ -n "$privateEndpoints" ]; then
        while IFS= read -r pendName; do
          if [ -n "$pendName" ]; then
            echo "Deleting private endpoint: $pendName"
            az network private-endpoint delete \
              --resource-group "$targetResourceGroup" \
              --name "$pendName" \
              --yes || echo "Failed to delete private endpoint $pendName"
          fi
        done <<< "$privateEndpoints"
      else
        echo "No private endpoints found for AIFoundry V2 resource $resourceName"
      fi
      
      echo "Searching for NICs matching pattern: ${resourceName}-pend-nic"
      nics=$(az network nic list --resource-group "$targetResourceGroup" --query "[?starts_with(name, '${resourceName}-pend-nic')].name" --output tsv)
      
      if [ -n "$nics" ]; then
        while IFS= read -r nicName; do
          if [ -n "$nicName" ]; then
            echo "Deleting NIC: $nicName"
            az network nic delete \
              --resource-group "$targetResourceGroup" \
              --name "$nicName" \
              --yes || echo "Failed to delete NIC $nicName"
          fi
        done <<< "$nics"
      else
        echo "No NICs found for AIFoundry V2 resource $resourceName"
      fi
      
      # Delete the main AIFoundry V2 resource
      echo "Deleting AIFoundry V2 resource: $resourceName"
      az resource delete \
        --resource-group "$targetResourceGroup" \
        --name "$resourceName" \
        --resource-type "$resourceType" \
        --yes || echo "Failed to delete AIFoundry V2 resource $resourceName"
        
      echo "Cleanup completed for AIFoundry V2 resource: $resourceName"
    else
      echo "AIFoundry V2 resource $resourceName not found, skipping"
    fi
  }
  
  # Look for AIFoundry V2 resources that match the pattern
  echo "=== Searching for AIFoundry V2 resources ==="
  aifoundryV2Resources=$(az resource list \
    --resource-group "$targetResourceGroup" \
    --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[?starts_with(name, '$aiFoundryV2Name')].name" \
    --output tsv)
  
  if [ -n "$aifoundryV2Resources" ]; then
    echo "Found AIFoundry V2 resources to clean up:"
    echo "$aifoundryV2Resources"
    while IFS= read -r serviceName; do
      if [ -n "$serviceName" ]; then
        delete_aifoundry_v2_and_endpoints "$serviceName" "Microsoft.CognitiveServices/accounts"
      fi
    done <<< "$aifoundryV2Resources"
  else
    echo "No AIFoundry V2 resources found matching pattern: $aiFoundryV2Name"
  fi
  
else
  echo "No AIFoundry V2 related errors detected. Skipping cleanup."
  echo "This cleanup only runs for errors related to:"
  echo "- Resources starting with 'aif2'"
  echo "- Deployments containing '09-AifV2-NoAvm_'"
fi

echo "=== AI Foundry Project Error Cleanup Completed ==="