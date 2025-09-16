#!/bin/bash

echo "=== AI Foundry Hub and Project Error Cleanup ==="
echo "This task runs only when 66-ai-platform task failed with AIFoundry Hub/Project related errors"

az account set --subscription "$(dev_test_prod_sub_id)"

# Input parameters - replicating the same logic from 05b_Check if resource exists
commonRGNamePrefix="$(admin_aifactoryPrefixRG)"
projectNumber="$(project_number_000)"
projectName="prj${projectNumber}"
locationSuffix="$(admin_locationSuffix)"
envName="$(dev_test_prod)"
aifactorySuffixRG="$(admin_aifactorySuffixRG)"
resourceSuffix="$(admin_prjResourceSuffix)"

# Construct resource group name
projectNameReplaced="${projectName/prj/project}"
targetResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"

# Resource names (same as in 05b task)
aiHubName="aif-hub-${projectNumber}-${locationSuffix}-${envName}"
aifProjectName="aif-p-${projectNumber}-1-${locationSuffix}-${envName}"

echo "Target Resource Group: $targetResourceGroup"
echo "AI Hub Name Pattern: $aiHubName"
echo "AI Project Name Pattern: $aifProjectName"

# Check if this is specifically an AI Platform (66-ai-platform) related error
echo "Checking if error is related to AI Platform deployment (66-ai-platform)..."

# Get the error details from recent deployments
DEPLOYMENT_NAME_PATTERN="06-aiHubModule"
AI_HUB_RESOURCE_PATTERN="$aiHubName"
AIF_PROJECT_RESOURCE_PATTERN="$aifProjectName"

echo "Looking for deployment errors containing: $DEPLOYMENT_NAME_PATTERN"
echo "Looking for resource errors mentioning: $AI_HUB_RESOURCE_PATTERN or $AIF_PROJECT_RESOURCE_PATTERN"

# Check recent deployment failures for AI Platform related patterns
echo "Checking recent deployments for AI Platform (66-ai-platform) related failures..."
recent_deployments=$(az deployment sub list \
  --subscription "$(dev_test_prod_sub_id)" \
  --query "[?starts_with(name, 'esml-p$(project_number_000)-$(dev_test_prod)-$(admin_locationSuffix)') && contains(name, '66-ai-platform')].{name:name, provisioningState:properties.provisioningState, error:properties.error}" \
  --output json 2>/dev/null || echo "[]")

echo "Recent AI Platform deployments: $recent_deployments"

# Check if we should proceed with cleanup based on error patterns
should_cleanup="false"

if echo "$recent_deployments" | grep -qi "06-aiHubModule\|$aiHubName\|$aifProjectName"; then
  echo "Found AI Platform (66-ai-platform) related deployment errors"
  should_cleanup="true"
fi

# Alternative check: look for AI Hub/Project resources that might exist but be in error state
ai_hub_resources=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.MachineLearningServices/workspaces" \
  --query "[?starts_with(name, '$aiHubName') || starts_with(name, '$aifProjectName')].name" \
  --output tsv 2>/dev/null || echo "")

if [ -n "$ai_hub_resources" ]; then
  echo "Found existing AI Hub/Project resources that may need cleanup"
  should_cleanup="true"
fi

if [ "$should_cleanup" = "true" ]; then
  echo "=== Proceeding with AI Foundry Hub and Project resource cleanup ==="

# Function to delete resource and its related components with fuzzy endpoint matching
delete_ai_resource_and_endpoints() {
  local resourceName="$1"
  local resourceType="$2"
  
  echo "=== Processing resource: $resourceName ==="
  
  # Check if the resource exists
  if az resource show --resource-group "$targetResourceGroup" --name "$resourceName" --resource-type "$resourceType" &> /dev/null; then
    echo "Found resource: $resourceName"
    
    # Delete private endpoints and NICs using fuzzy matching (since they have random salt)
    echo "Searching for private endpoints matching pattern: ${resourceName}*-pend"
    privateEndpoints=$(az network private-endpoint list --resource-group "$targetResourceGroup" --query "[?starts_with(name, '${resourceName}') && contains(name, '-pend')].name" --output tsv)
    
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
      echo "No private endpoints found for resource $resourceName"
    fi
    
    echo "Searching for NICs matching pattern: ${resourceName}*-pend-nic"
    nics=$(az network nic list --resource-group "$targetResourceGroup" --query "[?starts_with(name, '${resourceName}') && contains(name, '-pend-nic')].name" --output tsv)
    
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
      echo "No NICs found for resource $resourceName"
    fi
    
    # Delete the main resource
    echo "Deleting main resource: $resourceName"
    az resource delete \
      --resource-group "$targetResourceGroup" \
      --name "$resourceName" \
      --resource-type "$resourceType" \
      --yes || echo "Failed to delete resource $resourceName"
      
    echo "Cleanup completed for resource: $resourceName"
  else
    echo "Resource $resourceName not found, skipping"
  fi
}

# Look for AI Hub resources that match the pattern
echo "=== Searching for AI Hub resources ==="
aiHubResources=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.MachineLearningServices/workspaces" \
  --query "[?starts_with(name, '$aiHubName')].name" \
  --output tsv)

if [ -n "$aiHubResources" ]; then
  echo "Found AI Hub resources to clean up:"
  echo "$aiHubResources"
  while IFS= read -r hubName; do
    if [ -n "$hubName" ]; then
      delete_ai_resource_and_endpoints "$hubName" "Microsoft.MachineLearningServices/workspaces"
    fi
  done <<< "$aiHubResources"
else
  echo "No AI Hub resources found matching pattern: $aiHubName"
fi

# Look for AI Project resources that match the pattern
echo "=== Searching for AI Project resources ==="
aifProjectResources=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.MachineLearningServices/workspaces" \
  --query "[?starts_with(name, '$aifProjectName')].name" \
  --output tsv)

if [ -n "$aifProjectResources" ]; then
  echo "Found AI Project resources to clean up:"
  echo "$aifProjectResources"
  while IFS= read -r projectName; do
    if [ -n "$projectName" ]; then
      delete_ai_resource_and_endpoints "$projectName" "Microsoft.MachineLearningServices/workspaces"
    fi
  done <<< "$aifProjectResources"
else
  echo "No AI Project resources found matching pattern: $aifProjectName"
fi

else
  echo "No AI Platform (66-ai-platform) related errors detected. Skipping cleanup."
  echo "This cleanup only runs for errors related to:"
  echo "- Resources mentioning '$aiHubName' or '$aifProjectName'"
  echo "- Deployments containing '06-aiHubModule'"
  echo "- Task '66-ai-platform' failures"
fi

# Set variable to indicate task 71 performed deletions
if [ "$should_cleanup" = "true" ]; then
  echo "##vso[task.setvariable variable=71_deleted]true"
  echo "Set variable 71_deleted=true for purge task"
else
  echo "##vso[task.setvariable variable=71_deleted]false"
  echo "Set variable 71_deleted=false (no deletions performed)"
fi

echo "=== AI Foundry Hub and Project Error Cleanup Completed ==="