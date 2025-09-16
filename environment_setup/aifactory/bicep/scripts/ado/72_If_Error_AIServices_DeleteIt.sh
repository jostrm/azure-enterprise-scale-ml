#!/bin/bash

echo "=== AI Services Error Cleanup ==="
echo "This task runs only when 63-cognitive-services task failed with AI Services related errors"

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

# AI Services name pattern (same as in 05b task)
aiServicesPrefix="aiservices${projectName}${locationSuffix}${envName}"

echo "Target Resource Group: $targetResourceGroup"
echo "AI Services Name Pattern: $aiServicesPrefix"

# Check if this is specifically a Cognitive Services (63-cognitive-services) related error
echo "Checking if error is related to Cognitive Services deployment (63-cognitive-services)..."

# Get the error details from recent deployments
DEPLOYMENT_NAME_PATTERN="03-AIServices"
AI_SERVICES_RESOURCE_PATTERN="$aiServicesPrefix"

echo "Looking for deployment errors containing: $DEPLOYMENT_NAME_PATTERN"
echo "Looking for resource errors mentioning: $AI_SERVICES_RESOURCE_PATTERN"

# Check recent deployment failures for Cognitive Services related patterns
echo "Checking recent deployments for Cognitive Services (63-cognitive-services) related failures..."
recent_deployments=$(az deployment sub list \
  --subscription "$(dev_test_prod_sub_id)" \
  --query "[?starts_with(name, 'esml-p$(project_number_000)-$(dev_test_prod)-$(admin_locationSuffix)') && contains(name, '63-cognitive-services')].{name:name, provisioningState:properties.provisioningState, error:properties.error}" \
  --output json 2>/dev/null || echo "[]")

echo "Recent Cognitive Services deployments: $recent_deployments"

# Check if we should proceed with cleanup based on error patterns
should_cleanup="false"

if echo "$recent_deployments" | grep -qi "03-AIServices\|$aiServicesPrefix"; then
  echo "Found Cognitive Services (63-cognitive-services) related deployment errors"
  should_cleanup="true"
fi

# Alternative check: look for AI Services resources that might exist but be in error state
ai_services_resources=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.CognitiveServices/accounts" \
  --query "[?starts_with(name, '$aiServicesPrefix')].name" \
  --output tsv 2>/dev/null || echo "")

if [ -n "$ai_services_resources" ]; then
  echo "Found existing AI Services resources that may need cleanup"
  should_cleanup="true"
fi

if [ "$should_cleanup" = "true" ]; then
  echo "=== Proceeding with AI Services resource cleanup ==="

# Function to delete AI Services resource and its related components with fuzzy endpoint matching
delete_ai_services_and_endpoints() {
  local resourceName="$1"
  local resourceType="$2"
  
  echo "=== Processing AI Services resource: $resourceName ==="
  
  # Check if the resource exists
  if az resource show --resource-group "$targetResourceGroup" --name "$resourceName" --resource-type "$resourceType" &> /dev/null; then
    echo "Found AI Services resource: $resourceName"
    
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
      echo "No private endpoints found for AI Services resource $resourceName"
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
      echo "No NICs found for AI Services resource $resourceName"
    fi
    
    # Delete the main AI Services resource
    echo "Deleting AI Services resource: $resourceName"
    az resource delete \
      --resource-group "$targetResourceGroup" \
      --name "$resourceName" \
      --resource-type "$resourceType" \
      --yes || echo "Failed to delete AI Services resource $resourceName"
      
    echo "Cleanup completed for AI Services resource: $resourceName"
  else
    echo "AI Services resource $resourceName not found, skipping"
  fi
}

# Look for AI Services resources that match the pattern
echo "=== Searching for AI Services resources ==="
aiServicesResources=$(az resource list \
  --resource-group "$targetResourceGroup" \
  --resource-type "Microsoft.CognitiveServices/accounts" \
  --query "[?starts_with(name, '$aiServicesPrefix')].name" \
  --output tsv)

if [ -n "$aiServicesResources" ]; then
  echo "Found AI Services resources to clean up:"
  echo "$aiServicesResources"
  while IFS= read -r serviceName; do
    if [ -n "$serviceName" ]; then
      delete_ai_services_and_endpoints "$serviceName" "Microsoft.CognitiveServices/accounts"
    fi
  done <<< "$aiServicesResources"
else
  echo "No AI Services resources found matching pattern: $aiServicesPrefix"
fi

else
  echo "No Cognitive Services (63-cognitive-services) related errors detected. Skipping cleanup."
  echo "This cleanup only runs for errors related to:"
  echo "- Resources starting with '$aiServicesPrefix'"
  echo "- Deployments containing '03-AIServices'"
  echo "- Task '63-cognitive-services' failures"
fi

# Set variable to indicate task 72 performed deletions
if [ "$should_cleanup" = "true" ]; then
  echo "##vso[task.setvariable variable=72_deleted]true"
  echo "Set variable 72_deleted=true for purge task"
else
  echo "##vso[task.setvariable variable=72_deleted]false"
  echo "Set variable 72_deleted=false (no deletions performed)"
fi

echo "=== AI Services Error Cleanup Completed ==="