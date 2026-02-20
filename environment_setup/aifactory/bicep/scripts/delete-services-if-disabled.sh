#!/bin/bash
set -e

az account set --subscription "$dev_test_prod_sub_id"

echo "=== Delete Services If Not Enabled (Complete Mode) ==="

# Build resource group name
commonRGNamePrefix="$admin_aifactoryPrefixRG"
projectNumber="$project_number_000"
projectName="prj${projectNumber}"
locationSuffix="$admin_locationSuffix"
envName="$dev_test_prod"
aifactorySuffixRG="$admin_aifactorySuffixRG"
projectPrefix="$projectPrefix"
projectSuffix="$projectSuffix"

projectNameReplaced="${projectName/prj/project}"
projectResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"

echo "Target resource group: $projectResourceGroup"

# Override mode: deleteAllServicesForProject bypasses all enable_ flags (except KeyVault, Storage, AppInsights)
deleteAllServicesForProject="$deleteAllServicesForProject"
echo ""
echo "=== Delete Mode ==="
echo "deleteAllServicesForProject: $deleteAllServicesForProject"
if [ "$deleteAllServicesForProject" = "true" ]; then
  echo "⚠️  deleteAllServicesForProject=true: ALL services will be deleted (except KeyVault, Storage, AppInsights)"
fi

# =============================================================================
# SERVICES THAT ARE ** NEVER ** DELETED BY THIS SCRIPT (any flag value):
#   - Key Vault          (foundational secret store)
#   - Storage Accounts   (foundational data plane)
#   - Application Insights / Dashboard Insights (foundational observability)
#   - AI Foundry Hub v1 (MachineLearningServices/workspaces kind=Hub)
#   - AI Foundry V2 / Azure OpenAI / AI Services (CognitiveServices) -
#       these are handled by 04_Purge_SoftDeleted after soft-delete settles
#   - Managed Identities (miPrjExists / miACAExists)
# =============================================================================

# Check networking mode to determine if private endpoints are expected
allowPublic="$allowPublicAccessWhenBehindVnet"
enablePublicGenAI="$enablePublicGenAIAccess"
enablePublicPerimeter="$enablePublicAccessWithPerimeter"

echo "Networking configuration:"
echo "  allowPublicAccessWhenBehindVnet: $allowPublic"
echo "  enablePublicGenAIAccess: $enablePublicGenAI"
echo "  enablePublicAccessWithPerimeter: $enablePublicPerimeter"

# Determine if private endpoints are expected
# No private endpoints: true, true, true
# Has private endpoints: false, false, false OR false, false, true
if [ "$allowPublic" = "true" ] && [ "$enablePublicGenAI" = "true" ] && [ "$enablePublicPerimeter" = "true" ]; then
  expect_private_endpoints=false
  echo "Networking mode: Public access (no private endpoints expected)"
else
  expect_private_endpoints=true
  echo "Networking mode: Private networking (private endpoints expected)"
fi

# Function to delete private endpoints for a resource
delete_private_endpoints() {
  local resource_name="$1"
  local resource_type="$2"
  
  echo "Searching for private endpoints for $resource_type: $resource_name"
  
  # Find private endpoints matching pattern: resourcename-pend or resourcename-pend-*
  pend_list=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${resource_name}-pend')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$pend_list" ]; then
    while IFS= read -r pend_name; do
      if [ -n "$pend_name" ]; then
        echo "  Deleting private endpoint: $pend_name"
        az network private-endpoint delete \
          --resource-group "$projectResourceGroup" \
          --name "$pend_name" \
          --yes 2>&1 || echo "  Warning: Failed to delete private endpoint $pend_name"
      fi
    done <<< "$pend_list"
  else
    echo "  No private endpoints found for $resource_name"
  fi
  
  # Also check for NICs with pattern: resourcename-pend-nic or resourcename-pend-*-nic
  nic_list=$(az network nic list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${resource_name}-pend')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$nic_list" ]; then
    while IFS= read -r nic_name; do
      if [ -n "$nic_name" ]; then
        echo "  Deleting NIC: $nic_name"
        az network nic delete \
          --resource-group "$projectResourceGroup" \
          --name "$nic_name" 2>&1 || echo "  Warning: Failed to delete NIC $nic_name"
      fi
    done <<< "$nic_list"
  fi
}

# Function to delete storage account private endpoints
delete_storage_private_endpoints() {
  local storage_name="$1"
  
  echo "Searching for storage private endpoints for: $storage_name"
  
  # Storage has special naming: storagename-file-pend, storagename-blob-pend, etc.
  storage_pend_patterns=(
    "${storage_name}-file-pend"
    "${storage_name}-blob-pend"
    "${storage_name}-queue-pend"
    "${storage_name}-table-pend"
  )
  
  for pattern in "${storage_pend_patterns[@]}"; do
    # Find exact match or with suffix
    pend_list=$(az network private-endpoint list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${pattern}')].name" \
      -o tsv 2>/dev/null || echo "")
    
    if [ -n "$pend_list" ]; then
      while IFS= read -r pend_name; do
        if [ -n "$pend_name" ]; then
          echo "  Deleting storage private endpoint: $pend_name"
          az network private-endpoint delete \
            --resource-group "$projectResourceGroup" \
            --name "$pend_name" \
            --yes 2>&1 || echo "  Warning: Failed to delete $pend_name"
        fi
      done <<< "$pend_list"
    fi
    
    # Also clean up NICs
    nic_list=$(az network nic list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${pattern}')].name" \
      -o tsv 2>/dev/null || echo "")
    
    if [ -n "$nic_list" ]; then
      while IFS= read -r nic_name; do
        if [ -n "$nic_name" ]; then
          echo "  Deleting storage NIC: $nic_name"
          az network nic delete \
            --resource-group "$projectResourceGroup" \
            --name "$nic_name" 2>&1 || echo "  Warning: Failed to delete $nic_name"
        fi
      done <<< "$nic_list"
    fi
  done
}

# =============================================================================
# AI SEARCH - Delete if disabled and exists
# =============================================================================
enableAISearch="$enableAISearch"
aiSearchExists="$aiSearchExists"
addAISearch="$addAISearch"
enableAFoundryCaphost="$enableAFoundryCaphost"
enableAIFoundry="$enableAIFoundry"

echo ""
echo "--- AI Search ---"
echo "enableAISearch: $enableAISearch"
echo "aiSearchExists: $aiSearchExists"
echo "addAISearch: $addAISearch"
echo "enableAFoundryCaphost: $enableAFoundryCaphost"
echo "enableAIFoundry: $enableAIFoundry"

# When deleteAllServicesForProject=true, override enable_ flag regardless of Foundry dependencies
if [ "$deleteAllServicesForProject" = "true" ]; then enableAISearch="false"; addAISearch="false"; fi
# Check if AI Search is a dependency for Foundry with capability host (bypassed when deleteAllServicesForProject=true)
if [ "$enableAFoundryCaphost" = "true" ] && [ "$enableAIFoundry" = "true" ] && [ "$deleteAllServicesForProject" != "true" ]; then
  echo "🔒 AI Search is required as dependency for AI Foundry with capability host - skipping deletion"
  skip_aisearch_deletion=true
else
  skip_aisearch_deletion=false
fi

if [ "$skip_aisearch_deletion" = "false" ] && [ "$enableAISearch" = "false" ] && [ "$addAISearch" = "false" ] && [ "$aiSearchExists" = "true" ]; then
  echo "✓ AI Search is disabled but exists - proceeding with deletion"
  
  # Find AI Search resource
  safeNameAISearch="aisearch${projectName}${locationSuffix}${envName}"
  
  # Find with fuzzy matching
  aisearch_name=$(az search service list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${safeNameAISearch}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$aisearch_name" ]; then
    echo "Found AI Search service: $aisearch_name"
    
    # STEP 1: Delete AI Search shared private endpoints (special for AI Search)
    echo "Deleting AI Search shared private endpoints..."
    
    # Pattern 1: {aisearch_name}-shared-pe-0, {aisearch_name}-shared-pe-1
    shared_pe_list=$(az search shared-private-link-resource list \
      --resource-group "$projectResourceGroup" \
      --service-name "$aisearch_name" \
      --query "[].name" \
      -o tsv 2>/dev/null || echo "")
    
    if [ -n "$shared_pe_list" ]; then
      echo "  Found shared private endpoints for AI Search:"
      while IFS= read -r shared_pe_name; do
        if [ -n "$shared_pe_name" ]; then
          echo "    - $shared_pe_name"
          echo "    Deleting shared private endpoint: $shared_pe_name"
          az search shared-private-link-resource delete \
            --resource-group "$projectResourceGroup" \
            --service-name "$aisearch_name" \
            --name "$shared_pe_name" \
            --yes 2>&1 || echo "    Warning: Failed to delete $shared_pe_name"
          
          # Wait a bit for deletion to propagate
          sleep 5
        fi
      done <<< "$shared_pe_list"
      
      # Wait for shared private endpoints to be fully deleted
      echo "  Waiting for shared private endpoints deletion to complete..."
      sleep 10
    else
      echo "  No shared private endpoints found via Azure CLI"
    fi
    
    # Also try to find and delete using naming patterns (fallback method)
    echo "  Checking for shared private endpoints using naming patterns..."
    
    # Delete pattern: {aisearch_name}-shared-pe-*
    for i in 0 1 2 3; do
      shared_pe_pattern="${aisearch_name}-shared-pe-${i}"
      echo "    Checking for: $shared_pe_pattern"
      
      az search shared-private-link-resource delete \
        --resource-group "$projectResourceGroup" \
        --service-name "$aisearch_name" \
        --name "$shared_pe_pattern" \
        --yes 2>/dev/null && echo "    ✓ Deleted $shared_pe_pattern" || true
    done
    
    # Delete common foundry-related shared endpoints
    foundry_shared_endpoints=(
      "shared-pe-foundry-openai"
      "shared-pe-foundry-cogsvc"
    )
    
    for shared_pe_name in "${foundry_shared_endpoints[@]}"; do
      echo "    Checking for: $shared_pe_name"
      az search shared-private-link-resource delete \
        --resource-group "$projectResourceGroup" \
        --service-name "$aisearch_name" \
        --name "$shared_pe_name" \
        --yes 2>/dev/null && echo "    ✓ Deleted $shared_pe_name" || true
    done
    
    echo "  Shared private endpoints deletion completed"
    
    # STEP 2: Delete regular private endpoints (always attempt, fail silently if not found)
    delete_private_endpoints "$aisearch_name" "AI Search"
    
    # STEP 3: Delete the AI Search service
    echo "Deleting AI Search service: $aisearch_name"
    az search service delete \
      --resource-group "$projectResourceGroup" \
      --name "$aisearch_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted AI Search service"
      echo "##vso[task.setvariable variable=aiSearchExists]false"
    else
      echo "❌ Failed to delete AI Search service"
    fi
  else
    echo "⚠️  AI Search service not found with prefix: $safeNameAISearch"
  fi
elif [ "$skip_aisearch_deletion" = "true" ]; then
  echo "ℹ️  AI Search deletion skipped - required for AI Foundry with capability host"
elif [ "$enableAISearch" = "true" ]; then
  echo "ℹ️  AI Search is enabled - skipping deletion"
elif [ "$aiSearchExists" = "false" ]; then
  echo "ℹ️  AI Search doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for AI Search deletion"
fi

# =============================================================================
# COSMOS DB - Delete if disabled and exists (Capability host dependency)
# =============================================================================
enableCosmosDB="$enableCosmosDB"
cosmosDBExists="$cosmosDBExists"

echo ""
echo "--- Cosmos DB ---"
echo "enableCosmosDB: $enableCosmosDB"
echo "cosmosDBExists: $cosmosDBExists"

# When deleteAllServicesForProject=true, override enable_ flag regardless of Foundry dependencies
if [ "$deleteAllServicesForProject" = "true" ]; then enableCosmosDB="false"; fi
# Check if Cosmos DB is a dependency for Foundry with capability host (bypassed when deleteAllServicesForProject=true)
if [ "$enableAFoundryCaphost" = "true" ] && [ "$enableAIFoundry" = "true" ] && [ "$deleteAllServicesForProject" != "true" ]; then
  echo "🔒 Cosmos DB is required as dependency for AI Foundry with capability host - skipping deletion"
  skip_cosmosdb_deletion=true
else
  skip_cosmosdb_deletion=false
fi

if [ "$skip_cosmosdb_deletion" = "false" ] && [ "$enableCosmosDB" = "false" ] && [ "$cosmosDBExists" = "true" ]; then
  echo "✓ Cosmos DB is disabled but exists - proceeding with deletion"
  
  cosmosDBName="cosmos-${projectName}-${locationSuffix}-${envName}"
  
  cosmosdb_name=$(az cosmosdb list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${cosmosDBName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$cosmosdb_name" ]; then
    echo "Found Cosmos DB: $cosmosdb_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$cosmosdb_name" "Cosmos DB"
    
    echo "Deleting Cosmos DB: $cosmosdb_name"
    az cosmosdb delete \
      --resource-group "$projectResourceGroup" \
      --name "$cosmosdb_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Cosmos DB"
      echo "##vso[task.setvariable variable=cosmosDBExists]false"
    else
      echo "❌ Failed to delete Cosmos DB"
    fi
  else
    echo "⚠️  Cosmos DB not found with prefix: $cosmosDBName"
  fi
elif [ "$skip_cosmosdb_deletion" = "true" ]; then
  echo "ℹ️  Cosmos DB deletion skipped - required for AI Foundry with capability host"
elif [ "$enableCosmosDB" = "true" ]; then
  echo "ℹ️  Cosmos DB is enabled - skipping deletion"
elif [ "$cosmosDBExists" = "false" ]; then
  echo "ℹ️  Cosmos DB doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Cosmos DB deletion"
fi

# =============================================================================
# WEB APP - Delete if disabled and exists
# Includes: private endpoints, NICs, App Service Plan (only if byoASEv3=false)
# =============================================================================
enableWebApp="$enableWebApp"
webAppExists="$webAppExists"
byoASEv3Val="$byoASEv3"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableWebApp="false"; fi

echo ""
echo "--- Web App ---"
echo "enableWebApp: $enableWebApp"
echo "webAppExists: $webAppExists"
echo "byoASEv3: $byoASEv3Val"

if [ "$enableWebApp" = "false" ] && [ "$webAppExists" = "true" ]; then
  echo "✓ Web App is disabled but exists - proceeding with full deletion (pends, NICs, plan, app)"
  
  webAppName="webapp-${projectName}-${locationSuffix}-${envName}"
  
  webapp_name=$(az webapp list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${webAppName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$webapp_name" ]; then
    echo "Found Web App: $webapp_name"
    
    # STEP 1: Delete all private endpoints (any connection state) for this WebApp
    echo "Deleting all private endpoints for Web App: $webapp_name"
    pend_list=$(az network private-endpoint list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${webapp_name}')].name" \
      -o tsv 2>/dev/null || echo "")
    if [ -n "$pend_list" ]; then
      while IFS= read -r pend_name; do
        if [ -n "$pend_name" ]; then
          echo "  Deleting private endpoint: $pend_name"
          az network private-endpoint delete \
            --resource-group "$projectResourceGroup" \
            --name "$pend_name" \
            --yes 2>&1 || echo "  Warning: could not delete $pend_name"
        fi
      done <<< "$pend_list"
    else
      echo "  No private endpoints found for $webapp_name"
    fi
    
    # STEP 2: Delete orphaned NICs matching webapp naming pattern
    echo "Deleting NICs for Web App: $webapp_name"
    nic_list=$(az network nic list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${webapp_name}')].name" \
      -o tsv 2>/dev/null || echo "")
    if [ -n "$nic_list" ]; then
      while IFS= read -r nic_name; do
        if [ -n "$nic_name" ]; then
          echo "  Deleting NIC: $nic_name"
          az network nic delete \
            --resource-group "$projectResourceGroup" \
            --name "$nic_name" 2>&1 || echo "  Warning: could not delete NIC $nic_name"
        fi
      done <<< "$nic_list"
    else
      echo "  No NICs found for $webapp_name"
    fi
    
    # STEP 3: Delete the Web App itself
    echo "Deleting Web App: $webapp_name"
    az webapp delete \
      --resource-group "$projectResourceGroup" \
      --name "$webapp_name" 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Web App"
      echo "##vso[task.setvariable variable=webAppExists]false"
    else
      echo "❌ Failed to delete Web App"
    fi
    
    # STEP 4: Delete App Service Plan (only if NOT using BYO ASE v3)
    if [ "$byoASEv3Val" != "true" ]; then
      echo "byoASEv3 is false - looking for App Service Plan to delete"
      # Naming convention: starts with "webapp-" ends with "-plan"
      asp_name=$(az appservice plan list \
        --resource-group "$projectResourceGroup" \
        --query "[?starts_with(name, 'webapp-') && ends_with(name, '-plan')].name" \
        -o tsv 2>/dev/null | head -n1)
      if [ -n "$asp_name" ]; then
        echo "  Deleting App Service Plan: $asp_name"
        az appservice plan delete \
          --resource-group "$projectResourceGroup" \
          --name "$asp_name" \
          --yes 2>&1 && echo "  ✅ Deleted App Service Plan: $asp_name" || echo "  Warning: could not delete App Service Plan $asp_name"
      else
        echo "  No webapp App Service Plan found (starts with 'webapp-', ends with '-plan')"
      fi
    else
      echo "byoASEv3 is true - skipping App Service Plan deletion (managed by ASE)"
    fi
  else
    echo "⚠️  Web App not found with prefix: $webAppName"
  fi
elif [ "$enableWebApp" = "true" ]; then
  echo "ℹ️  Web App is enabled - skipping deletion"
elif [ "$webAppExists" = "false" ]; then
  echo "ℹ️  Web App doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Web App deletion"
fi

# =============================================================================
# FUNCTION APP - Delete if disabled and exists
# Includes: private endpoints, NICs, App Service Plan (only if byoASEv3=false)
# =============================================================================
enableFunction="$enableFunction"
functionAppExists="$functionAppExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableFunction="false"; fi

echo ""
echo "--- Function App ---"
echo "enableFunction: $enableFunction"
echo "functionAppExists: $functionAppExists"
echo "byoASEv3: $byoASEv3Val"

if [ "$enableFunction" = "false" ] && [ "$functionAppExists" = "true" ]; then
  echo "✓ Function App is disabled but exists - proceeding with full deletion (pends, NICs, plan, app)"
  
  functionAppName="func-${projectName}-${locationSuffix}-${envName}"
  
  func_name=$(az functionapp list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${functionAppName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$func_name" ]; then
    echo "Found Function App: $func_name"
    
    # STEP 1: Delete all private endpoints (any connection state) for this Function App
    echo "Deleting all private endpoints for Function App: $func_name"
    pend_list=$(az network private-endpoint list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${func_name}')].name" \
      -o tsv 2>/dev/null || echo "")
    if [ -n "$pend_list" ]; then
      while IFS= read -r pend_name; do
        if [ -n "$pend_name" ]; then
          echo "  Deleting private endpoint: $pend_name"
          az network private-endpoint delete \
            --resource-group "$projectResourceGroup" \
            --name "$pend_name" \
            --yes 2>&1 || echo "  Warning: could not delete $pend_name"
        fi
      done <<< "$pend_list"
    else
      echo "  No private endpoints found for $func_name"
    fi
    
    # STEP 2: Delete orphaned NICs matching function app naming pattern
    echo "Deleting NICs for Function App: $func_name"
    nic_list=$(az network nic list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${func_name}')].name" \
      -o tsv 2>/dev/null || echo "")
    if [ -n "$nic_list" ]; then
      while IFS= read -r nic_name; do
        if [ -n "$nic_name" ]; then
          echo "  Deleting NIC: $nic_name"
          az network nic delete \
            --resource-group "$projectResourceGroup" \
            --name "$nic_name" 2>&1 || echo "  Warning: could not delete NIC $nic_name"
        fi
      done <<< "$nic_list"
    else
      echo "  No NICs found for $func_name"
    fi
    
    # STEP 3: Delete the Function App itself
    echo "Deleting Function App: $func_name"
    az functionapp delete \
      --resource-group "$projectResourceGroup" \
      --name "$func_name" 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Function App"
      echo "##vso[task.setvariable variable=functionAppExists]false"
    else
      echo "❌ Failed to delete Function App"
    fi
    
    # STEP 4: Delete App Service Plan (only if NOT using BYO ASE v3)
    if [ "$byoASEv3Val" != "true" ]; then
      echo "byoASEv3 is false - looking for Function App Service Plan to delete"
      # Naming convention: starts with "func-" ends with "-plan"
      asp_name=$(az appservice plan list \
        --resource-group "$projectResourceGroup" \
        --query "[?starts_with(name, 'func-') && ends_with(name, '-plan')].name" \
        -o tsv 2>/dev/null | head -n1)
      if [ -n "$asp_name" ]; then
        echo "  Deleting App Service Plan: $asp_name"
        az appservice plan delete \
          --resource-group "$projectResourceGroup" \
          --name "$asp_name" \
          --yes 2>&1 && echo "  ✅ Deleted App Service Plan: $asp_name" || echo "  Warning: could not delete App Service Plan $asp_name"
      else
        echo "  No function App Service Plan found (starts with 'func-', ends with '-plan')"
      fi
    else
      echo "byoASEv3 is true - skipping App Service Plan deletion (managed by ASE)"
    fi
  else
    echo "⚠️  Function App not found with prefix: $functionAppName"
  fi
elif [ "$enableFunction" = "true" ]; then
  echo "ℹ️  Function App is enabled - skipping deletion"
elif [ "$functionAppExists" = "false" ]; then
  echo "ℹ️  Function App doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Function App deletion"
fi

# =============================================================================
# CONTAINER APPS - Delete if disabled and exists
# =============================================================================
enableContainerApps="$enableContainerApps"
containerAppAExists="$containerAppAExists"
containerAppWExists="$containerAppWExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableContainerApps="false"; fi

echo ""
echo "--- Container Apps ---"
echo "enableContainerApps: $enableContainerApps"
echo "containerAppAExists: $containerAppAExists"
echo "containerAppWExists: $containerAppWExists"

if [ "$enableContainerApps" = "false" ]; then
  # Delete Container App A
  if [ "$containerAppAExists" = "true" ]; then
    echo "✓ Container App A is disabled but exists - proceeding with deletion"
    
    containerAppAName="aca-a-${projectName}${locationSuffix}${envName}"
    
    aca_a_name=$(az containerapp list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${containerAppAName}')].name" \
      -o tsv | head -n1)
    
    if [ -n "$aca_a_name" ]; then
      echo "Found Container App A: $aca_a_name"
      
      echo "Deleting Container App A: $aca_a_name"
      az containerapp delete \
        --resource-group "$projectResourceGroup" \
        --name "$aca_a_name" \
        --yes 2>&1
      
      if [ $? -eq 0 ]; then
        echo "✅ Successfully deleted Container App A"
        echo "##vso[task.setvariable variable=containerAppAExists]false"
      else
        echo "❌ Failed to delete Container App A"
      fi
    fi
  fi
  
  # Delete Container App W
  if [ "$containerAppWExists" = "true" ]; then
    echo "✓ Container App W is disabled but exists - proceeding with deletion"
    
    containerAppWName="aca-w-${projectName}${locationSuffix}${envName}"
    
    aca_w_name=$(az containerapp list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, '${containerAppWName}')].name" \
      -o tsv | head -n1)
    
    if [ -n "$aca_w_name" ]; then
      echo "Found Container App W: $aca_w_name"
      
      echo "Deleting Container App W: $aca_w_name"
      az containerapp delete \
        --resource-group "$projectResourceGroup" \
        --name "$aca_w_name" \
        --yes 2>&1
      
      if [ $? -eq 0 ]; then
        echo "✅ Successfully deleted Container App W"
        echo "##vso[task.setvariable variable=containerAppWExists]false"
      else
        echo "❌ Failed to delete Container App W"
      fi
    fi
  fi
elif [ "$enableContainerApps" = "true" ]; then
  echo "ℹ️  Container Apps are enabled - skipping deletion"
else
  echo "ℹ️  Container Apps don't exist - skipping deletion"
fi

# =============================================================================
# CONTAINER APPS ENVIRONMENT - Delete after all Container Apps are gone
# =============================================================================
containerAppsEnvExists="$containerAppsEnvExists"
# When deleteAllServicesForProject=true, override enable_ flag (reuse enableContainerApps)
if [ "$deleteAllServicesForProject" = "true" ]; then enableContainerApps="false"; fi

echo ""
echo "--- Container Apps Environment ---"
echo "enableContainerApps: $enableContainerApps"
echo "containerAppsEnvExists: $containerAppsEnvExists"

if [ "$enableContainerApps" = "false" ] && [ "$containerAppsEnvExists" = "true" ]; then
  echo "✓ Container Apps Env is no longer needed - proceeding with deletion"

  acaEnvName="aca-env-${projectName}-${locationSuffix}-${envName}"

  acaenv_name=$(az containerapp env list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${acaEnvName}')].name" \
    -o tsv | head -n1)

  if [ -n "$acaenv_name" ]; then
    echo "Found Container Apps Environment: $acaenv_name"

    # Delete private endpoints before the environment
    delete_private_endpoints "$acaenv_name" "Container Apps Environment"

    echo "Deleting Container Apps Environment: $acaenv_name"
    az containerapp env delete \
      --resource-group "$projectResourceGroup" \
      --name "$acaenv_name" \
      --yes 2>&1

    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Container Apps Environment"
      echo "##vso[task.setvariable variable=containerAppsEnvExists]false"
    else
      echo "❌ Failed to delete Container Apps Environment"
    fi
  else
    echo "⚠️  Container Apps Environment not found with prefix: $acaEnvName"
  fi
elif [ "$enableContainerApps" = "true" ]; then
  echo "ℹ️  Container Apps are enabled - skipping environment deletion"
elif [ "$containerAppsEnvExists" = "false" ]; then
  echo "ℹ️  Container Apps Environment doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Container Apps Environment deletion"
fi

# =============================================================================
# LOGIC APPS - Delete if disabled and exists
# =============================================================================
enableLogicApps="$enableLogicApps"
logicAppsExists="$logicAppsExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableLogicApps="false"; fi

echo ""
echo "--- Logic Apps ---"
echo "enableLogicApps: $enableLogicApps"
echo "logicAppsExists: $logicAppsExists"

if [ "$enableLogicApps" = "false" ] && [ "$logicAppsExists" = "true" ]; then
  echo "✓ Logic Apps is disabled but exists - proceeding with deletion"
  
  logicAppName="logic-${projectName}-${locationSuffix}-${envName}"
  
  logic_name=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "Microsoft.Logic/workflows" \
    --query "[?starts_with(name, '${logicAppName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$logic_name" ]; then
    echo "Found Logic App: $logic_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$logic_name" "Logic App"
    
    echo "Deleting Logic App: $logic_name"
    az logic workflow delete \
      --resource-group "$projectResourceGroup" \
      --name "$logic_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Logic App"
      echo "##vso[task.setvariable variable=logicAppsExists]false"
    else
      echo "❌ Failed to delete Logic App"
    fi
  else
    echo "⚠️  Logic App not found with prefix: $logicAppName"
  fi
elif [ "$enableLogicApps" = "true" ]; then
  echo "ℹ️  Logic Apps is enabled - skipping deletion"
elif [ "$logicAppsExists" = "false" ]; then
  echo "ℹ️  Logic Apps doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Logic Apps deletion"
fi

# =============================================================================
# EVENT HUBS - Delete if disabled and exists
# =============================================================================
enableEventHubs="$enableEventHubs"
eventHubsExists="$eventHubsExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableEventHubs="false"; fi

echo ""
echo "--- Event Hubs ---"
echo "enableEventHubs: $enableEventHubs"
echo "eventHubsExists: $eventHubsExists"

if [ "$enableEventHubs" = "false" ] && [ "$eventHubsExists" = "true" ]; then
  echo "✓ Event Hubs is disabled but exists - proceeding with deletion"
  
  eventHubName="eh-${projectNumber}-${locationSuffix}-${envName}"
  
  eh_name=$(az eventhubs namespace list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${eventHubName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$eh_name" ]; then
    echo "Found Event Hub: $eh_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$eh_name" "Event Hub"
    
    echo "Deleting Event Hub: $eh_name"
    az eventhubs namespace delete \
      --resource-group "$projectResourceGroup" \
      --name "$eh_name" 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Event Hub"
      echo "##vso[task.setvariable variable=eventHubsExists]false"
    else
      echo "❌ Failed to delete Event Hub"
    fi
  else
    echo "⚠️  Event Hub not found with prefix: $eventHubName"
  fi
elif [ "$enableEventHubs" = "true" ]; then
  echo "ℹ️  Event Hubs is enabled - skipping deletion"
elif [ "$eventHubsExists" = "false" ]; then
  echo "ℹ️  Event Hubs doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Event Hubs deletion"
fi

# =============================================================================
# POSTGRESQL - Delete if disabled and exists
# =============================================================================
enablePostgreSQL="$enablePostgreSQL"
postgreSQLExists="$postgreSQLExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enablePostgreSQL="false"; fi

echo ""
echo "--- PostgreSQL ---"
echo "enablePostgreSQL: $enablePostgreSQL"
echo "postgreSQLExists: $postgreSQLExists"

if [ "$enablePostgreSQL" = "false" ] && [ "$postgreSQLExists" = "true" ]; then
  echo "✓ PostgreSQL is disabled but exists - proceeding with deletion"
  
  postgresName="pg-flex-${projectName}-${locationSuffix}-${envName}"
  
  pg_name=$(az postgres flexible-server list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${postgresName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$pg_name" ]; then
    echo "Found PostgreSQL: $pg_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$pg_name" "PostgreSQL"
    
    echo "Deleting PostgreSQL: $pg_name"
    az postgres flexible-server delete \
      --resource-group "$projectResourceGroup" \
      --name "$pg_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted PostgreSQL"
      echo "##vso[task.setvariable variable=postgreSQLExists]false"
    else
      echo "❌ Failed to delete PostgreSQL"
    fi
  else
    echo "⚠️  PostgreSQL not found with prefix: $postgresName"
  fi
elif [ "$enablePostgreSQL" = "true" ]; then
  echo "ℹ️  PostgreSQL is enabled - skipping deletion"
elif [ "$postgreSQLExists" = "false" ]; then
  echo "ℹ️  PostgreSQL doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for PostgreSQL deletion"
fi

# =============================================================================
# REDIS CACHE - Delete if disabled and exists
# =============================================================================
enableRedisCache="$enableRedisCache"
redisExists="$redisExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableRedisCache="false"; fi

echo ""
echo "--- Redis Cache ---"
echo "enableRedisCache: $enableRedisCache"
echo "redisExists: $redisExists"

if [ "$enableRedisCache" = "false" ] && [ "$redisExists" = "true" ]; then
  echo "✓ Redis Cache is disabled but exists - proceeding with deletion"
  
  redisName="redis-${projectName}-${locationSuffix}-${envName}"
  
  redis_name=$(az redis list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${redisName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$redis_name" ]; then
    echo "Found Redis Cache: $redis_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$redis_name" "Redis Cache"
    
    echo "Deleting Redis Cache: $redis_name"
    az redis delete \
      --resource-group "$projectResourceGroup" \
      --name "$redis_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Redis Cache"
      echo "##vso[task.setvariable variable=redisExists]false"
    else
      echo "❌ Failed to delete Redis Cache"
    fi
  else
    echo "⚠️  Redis Cache not found with prefix: $redisName"
  fi
elif [ "$enableRedisCache" = "true" ]; then
  echo "ℹ️  Redis Cache is enabled - skipping deletion"
elif [ "$redisExists" = "false" ]; then
  echo "ℹ️  Redis Cache doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Redis Cache deletion"
fi

# =============================================================================
# SQL DATABASE - Delete if disabled and exists
# =============================================================================
enableSQLDatabase="$enableSQLDatabase"
sqlServerExists="$sqlServerExists"
sqlDBExists="$sqlDBExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableSQLDatabase="false"; fi

echo ""
echo "--- SQL Database ---"
echo "enableSQLDatabase: $enableSQLDatabase"
echo "sqlServerExists: $sqlServerExists"
echo "sqlDBExists: $sqlDBExists"

if [ "$enableSQLDatabase" = "false" ] && [ "$sqlServerExists" = "true" ]; then
  echo "✓ SQL Database is disabled but exists - proceeding with deletion"
  
  sqlServerName="sql-${projectName}-${locationSuffix}-${envName}"
  
  sql_server=$(az sql server list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${sqlServerName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$sql_server" ]; then
    echo "Found SQL Server: $sql_server"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$sql_server" "SQL Server"
    
    echo "Deleting SQL Server (and databases): $sql_server"
    az sql server delete \
      --resource-group "$projectResourceGroup" \
      --name "$sql_server" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted SQL Server"
      echo "##vso[task.setvariable variable=sqlServerExists]false"
      echo "##vso[task.setvariable variable=sqlDBExists]false"
    else
      echo "❌ Failed to delete SQL Server"
    fi
  else
    echo "⚠️  SQL Server not found with prefix: $sqlServerName"
  fi
elif [ "$enableSQLDatabase" = "true" ]; then
  echo "ℹ️  SQL Database is enabled - skipping deletion"
elif [ "$sqlServerExists" = "false" ]; then
  echo "ℹ️  SQL Server doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for SQL Database deletion"
fi

# =============================================================================
# DATABRICKS - Delete if disabled and exists
# =============================================================================
enableDatabricks="$enableDatabricks"
databricksExists="$databricksExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableDatabricks="false"; fi

echo ""
echo "--- Databricks ---"
echo "enableDatabricks: $enableDatabricks"
echo "databricksExists: $databricksExists"

if [ "$enableDatabricks" = "false" ] && [ "$databricksExists" = "true" ]; then
  echo "✓ Databricks is disabled but exists - proceeding with deletion"
  
  databricksName="dbx-${projectNumber}-${locationSuffix}-${envName}"
  
  dbx_name=$(az databricks workspace list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${databricksName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$dbx_name" ]; then
    echo "Found Databricks: $dbx_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$dbx_name" "Databricks"
    
    echo "Deleting Databricks: $dbx_name"
    az databricks workspace delete \
      --resource-group "$projectResourceGroup" \
      --name "$dbx_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Databricks"
      echo "##vso[task.setvariable variable=databricksExists]false"
    else
      echo "❌ Failed to delete Databricks"
    fi
  else
    echo "⚠️  Databricks not found with prefix: $databricksName"
  fi
elif [ "$enableDatabricks" = "true" ]; then
  echo "ℹ️  Databricks is enabled - skipping deletion"
elif [ "$databricksExists" = "false" ]; then
  echo "ℹ️  Databricks doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Databricks deletion"
fi

# =============================================================================
# AKS FOR AZURE ML - Delete BEFORE AML (AKS must be detached before workspace delete)
# =============================================================================
enableAzureMachineLearning="$enableAzureMachineLearning"
amlExists="$amlExists"
enableAksForAzureML="$enableAksForAzureML"
aksExists="$aksExists"
# When deleteAllServicesForProject=true, override enable_ flags (covers AML and AKS)
if [ "$deleteAllServicesForProject" = "true" ]; then enableAzureMachineLearning="false"; enableAksForAzureML="false"; fi

echo ""
echo "--- AKS for Azure ML (deleted before AML) ---"
echo "enableAksForAzureML: $enableAksForAzureML"
echo "aksExists: $aksExists"

if [ "$enableAksForAzureML" = "false" ] && [ "$aksExists" = "true" ]; then
  echo "✓ AKS for Azure ML is disabled but exists - proceeding with deletion"

  aksName="aks${projectNumber}-${locationSuffix}-${envName}"

  aks_name=$(az aks list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${aksName}')].name" \
    -o tsv | head -n1)

  if [ -n "$aks_name" ]; then
    echo "Found AKS cluster: $aks_name"

    echo "Deleting AKS cluster: $aks_name"
    az aks delete \
      --resource-group "$projectResourceGroup" \
      --name "$aks_name" \
      --yes 2>&1

    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted AKS cluster"
      echo "##vso[task.setvariable variable=aksExists]false"
    else
      echo "❌ Failed to delete AKS cluster"
    fi
  else
    echo "⚠️  AKS cluster not found with prefix: $aksName"
  fi
else
  echo "ℹ️  AKS skipped (enableAksForAzureML=$enableAksForAzureML, aksExists=$aksExists)"
fi

# =============================================================================
# AZURE MACHINE LEARNING - Delete if disabled and exists (AFTER AKS)
# =============================================================================
echo ""
echo "--- Azure Machine Learning ---"
echo "enableAzureMachineLearning: $enableAzureMachineLearning"
echo "amlExists: $amlExists"

if [ "$enableAzureMachineLearning" = "false" ] && [ "$amlExists" = "true" ]; then
  echo "✓ Azure ML is disabled but exists - proceeding with deletion"

  amlName="aml-${projectNumber}-${locationSuffix}-${envName}"

  aml_name=$(az ml workspace list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${amlName}')].name" \
    -o tsv | head -n1)

  if [ -n "$aml_name" ]; then
    echo "Found Azure ML workspace: $aml_name"

    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$aml_name" "Azure ML"

    echo "Deleting Azure ML workspace: $aml_name"
    az ml workspace delete \
      --resource-group "$projectResourceGroup" \
      --name "$aml_name" \
      --yes 2>&1

    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Azure ML workspace"
      echo "##vso[task.setvariable variable=amlExists]false"
    else
      echo "❌ Failed to delete Azure ML workspace"
    fi
  else
    echo "⚠️  Azure ML workspace not found with prefix: $amlName"
  fi
elif [ "$enableAzureMachineLearning" = "true" ]; then
  echo "ℹ️  Azure Machine Learning is enabled - skipping deletion"
elif [ "$amlExists" = "false" ]; then
  echo "ℹ️  Azure ML doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Azure ML deletion"
fi

# =============================================================================
# DATA FACTORY - Delete if disabled and exists
# =============================================================================
enableDatafactory="$enableDatafactory"
dataFactoryExists="$dataFactoryExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableDatafactory="false"; fi

echo ""
echo "--- Data Factory ---"
echo "enableDatafactory: $enableDatafactory"
echo "dataFactoryExists: $dataFactoryExists"

if [ "$enableDatafactory" = "false" ] && [ "$dataFactoryExists" = "true" ]; then
  echo "✓ Data Factory is disabled but exists - proceeding with deletion"
  
  adfName="adf-${projectNumber}-${locationSuffix}-${envName}"
  
  adf_name=$(az datafactory list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${adfName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$adf_name" ]; then
    echo "Found Data Factory: $adf_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$adf_name" "Data Factory"
    
    echo "Deleting Data Factory: $adf_name"
    az datafactory delete \
      --resource-group "$projectResourceGroup" \
      --name "$adf_name" \
      --yes 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Data Factory"
      echo "##vso[task.setvariable variable=dataFactoryExists]false"
    else
      echo "❌ Failed to delete Data Factory"
    fi
  else
    echo "⚠️  Data Factory not found with prefix: $adfName"
  fi
elif [ "$enableDatafactory" = "true" ]; then
  echo "ℹ️  Data Factory is enabled - skipping deletion"
elif [ "$dataFactoryExists" = "false" ]; then
  echo "ℹ️  Data Factory doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Data Factory deletion"
fi

# =============================================================================
# BOT SERVICE - Delete if disabled and exists
# =============================================================================
enableBotService="$enableBotService"
botServiceExists="$botServiceExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableBotService="false"; fi

echo ""
echo "--- Bot Service ---"
echo "enableBotService: $enableBotService"
echo "botServiceExists: $botServiceExists"

if [ "$enableBotService" = "false" ] && [ "$botServiceExists" = "true" ]; then
  echo "✓ Bot Service is disabled but exists - proceeding with deletion"

  botServiceName="bot-${projectNumber}-${locationSuffix}-${envName}"

  bot_name=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "Microsoft.BotService/botServices" \
    --query "[?starts_with(name, '${botServiceName}')].name" \
    -o tsv | head -n1)

  if [ -n "$bot_name" ]; then
    echo "Found Bot Service: $bot_name"

    delete_private_endpoints "$bot_name" "Bot Service"

    echo "Deleting Bot Service: $bot_name"
    az resource delete \
      --resource-group "$projectResourceGroup" \
      --name "$bot_name" \
      --resource-type "Microsoft.BotService/botServices" 2>&1

    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Bot Service"
      echo "##vso[task.setvariable variable=botServiceExists]false"
    else
      echo "❌ Failed to delete Bot Service"
    fi
  else
    echo "⚠️  Bot Service not found with prefix: $botServiceName"
  fi
elif [ "$enableBotService" = "true" ]; then
  echo "ℹ️  Bot Service is enabled - skipping deletion"
elif [ "$botServiceExists" = "false" ]; then
  echo "ℹ️  Bot Service doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Bot Service deletion"
fi

# =============================================================================
# VM / DSVM - Delete if disabled and exists (deleteAllServicesForProject only)
# =============================================================================
vmExists="$vmExists"

echo ""
echo "--- VM / DSVM ---"
echo "vmExists: $vmExists"
echo "deleteAllServicesForProject: $deleteAllServicesForProject"

if [ "$deleteAllServicesForProject" = "true" ] && [ "$vmExists" = "true" ]; then
  echo "✓ deleteAllServicesForProject=true and VM exists - proceeding with deletion"

  vmName="dsvm-${projectName}-${locationSuffix}-${envName}"

  vm_name=$(az vm list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${vmName}')].name" \
    -o tsv | head -n1)

  if [ -n "$vm_name" ]; then
    echo "Found VM: $vm_name"

    echo "Deleting VM (with managed disks and NIC): $vm_name"
    az vm delete \
      --resource-group "$projectResourceGroup" \
      --name "$vm_name" \
      --yes 2>&1

    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted VM"
      echo "##vso[task.setvariable variable=vmExists]false"
    else
      echo "❌ Failed to delete VM"
    fi
  else
    echo "⚠️  VM not found with prefix: $vmName"
  fi
else
  echo "ℹ️  VM deletion skipped (deleteAllServicesForProject=$deleteAllServicesForProject, vmExists=$vmExists)"
fi

# =============================================================================
# ACR PROJECT - Delete if disabled and exists (deleteAllServicesForProject only)
# =============================================================================
acrProjectExists="$acrProjectExists"

echo ""
echo "--- ACR Project ---"
echo "acrProjectExists: $acrProjectExists"
echo "deleteAllServicesForProject: $deleteAllServicesForProject"

if [ "$deleteAllServicesForProject" = "true" ] && [ "$acrProjectExists" = "true" ]; then
  echo "✓ deleteAllServicesForProject=true and ACR project exists - proceeding with deletion"

  acrName="acr${projectName}genai${locationSuffix}"

  acr_name=$(az acr list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${acrName}')].name" \
    -o tsv | head -n1)

  if [ -n "$acr_name" ]; then
    echo "Found ACR: $acr_name"

    delete_private_endpoints "$acr_name" "ACR Project"

    echo "Deleting ACR: $acr_name"
    az acr delete \
      --resource-group "$projectResourceGroup" \
      --name "$acr_name" \
      --yes 2>&1

    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted ACR project"
      echo "##vso[task.setvariable variable=acrProjectExists]false"
    else
      echo "❌ Failed to delete ACR project"
    fi
  else
    echo "⚠️  ACR not found with prefix: $acrName"
  fi
else
  echo "ℹ️  ACR deletion skipped (deleteAllServicesForProject=$deleteAllServicesForProject, acrProjectExists=$acrProjectExists)"
fi

# =============================================================================
# BING SEARCH - Delete if disabled and exists
# =============================================================================
enableBing="$enableBing"
bingExists="$bingExists"
# When deleteAllServicesForProject=true, override enable_ flag
if [ "$deleteAllServicesForProject" = "true" ]; then enableBing="false"; fi

echo ""
echo "--- Bing Search ---"
echo "enableBing: $enableBing"
echo "bingExists: $bingExists"

if [ "$enableBing" = "false" ] && [ "$bingExists" = "true" ]; then
  echo "✓ Bing Search is disabled but exists - proceeding with deletion"
  
  bingName="bing-${projectName}-${locationSuffix}-${envName}"
  
  bing_name=$(az cognitiveservices account list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${bingName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$bing_name" ]; then
    echo "Found Bing Search: $bing_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$bing_name" "Bing Search"
    
    echo "Deleting Bing Search: $bing_name"
    az cognitiveservices account delete \
      --resource-group "$projectResourceGroup" \
      --name "$bing_name" 2>&1
    
    if [ $? -eq 0 ]; then
      echo "✅ Successfully deleted Bing Search"
      echo "##vso[task.setvariable variable=bingExists]false"
    else
      echo "❌ Failed to delete Bing Search"
    fi
  else
    echo "⚠️  Bing Search not found with prefix: $bingName"
  fi
elif [ "$enableBing" = "true" ]; then
  echo "ℹ️  Bing Search is enabled - skipping deletion"
elif [ "$bingExists" = "false" ]; then
  echo "ℹ️  Bing Search doesn't exist - skipping deletion"
else
  echo "ℹ️  Conditions not met for Bing Search deletion"
fi

echo ""

# ======================================
# Azure AI Vision
# ======================================
echo "Checking Azure AI Vision deletion conditions..."
if ([ "$enableDeleteForDisabledResources" = "true" ] || [ "$deleteAllServicesForProject" = "true" ]) && [ "$enableAzureAIVision" = "false" ]; then
  echo "✓ Delete mode enabled and Azure AI Vision not enabled"
  
  # Find Azure AI Vision resource (vision-{projectName}-...)
  visionName="vision-${projectName}"
  echo "Looking for Azure AI Vision with prefix: $visionName"
  
  visionResource=$(az cognitiveservices account list \
    --resource-group "$projectResourceGroup" \
    --subscription "$dev_test_prod_sub_id" \
    --query "[?starts_with(name, '$visionName')] | [0].name" -o tsv 2>/dev/null || echo "")
  
  if [ -n "$visionResource" ]; then
    echo "Found Azure AI Vision: $visionResource"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$visionResource" "Azure AI Vision"
    
    # Delete the Azure AI Vision account
    echo "Deleting Azure AI Vision account: $visionResource"
    az cognitiveservices account delete \
      --name "$visionResource" \
      --resource-group "$projectResourceGroup" \
      --subscription "$dev_test_prod_sub_id"
    
    if [ $? -eq 0 ]; then
      echo "✓ Azure AI Vision deleted successfully"
    else
      echo "⚠️  Failed to delete Azure AI Vision"
    fi
  else
    echo "⚠️  Azure AI Vision not found with prefix: $visionName"
  fi
elif [ "$enableAzureAIVision" = "true" ]; then
  echo "ℹ️  Azure AI Vision is enabled - skipping deletion"
else
  echo "ℹ️  Conditions not met for Azure AI Vision deletion"
fi

echo ""

# ======================================
# Azure Speech Services
# ======================================
echo "Checking Azure Speech Services deletion conditions..."
if ([ "$enableDeleteForDisabledResources" = "true" ] || [ "$deleteAllServicesForProject" = "true" ]) && [ "$enableAzureSpeech" = "false" ]; then
  echo "✓ Delete mode enabled and Azure Speech not enabled"
  
  # Find Azure Speech resource (speech-{projectName}-...)
  speechName="speech-${projectName}"
  echo "Looking for Azure Speech with prefix: $speechName"
  
  speechResource=$(az cognitiveservices account list \
    --resource-group "$projectResourceGroup" \
    --subscription "$dev_test_prod_sub_id" \
    --query "[?starts_with(name, '$speechName')] | [0].name" -o tsv 2>/dev/null || echo "")
  
  if [ -n "$speechResource" ]; then
    echo "Found Azure Speech: $speechResource"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$speechResource" "Azure Speech"
    
    # Delete the Azure Speech account
    echo "Deleting Azure Speech account: $speechResource"
    az cognitiveservices account delete \
      --name "$speechResource" \
      --resource-group "$projectResourceGroup" \
      --subscription "$dev_test_prod_sub_id"
    
    if [ $? -eq 0 ]; then
      echo "✓ Azure Speech deleted successfully"
    else
      echo "⚠️  Failed to delete Azure Speech"
    fi
  else
    echo "⚠️  Azure Speech not found with prefix: $speechName"
  fi
elif [ "$enableAzureSpeech" = "true" ]; then
  echo "ℹ️  Azure Speech is enabled - skipping deletion"
else
  echo "ℹ️  Conditions not met for Azure Speech deletion"
fi

echo ""

# ======================================
# AI Document Intelligence
# ======================================
echo "Checking AI Document Intelligence deletion conditions..."
if ([ "$enableDeleteForDisabledResources" = "true" ] || [ "$deleteAllServicesForProject" = "true" ]) && [ "$enableAIDocIntelligence" = "false" ]; then
  echo "✓ Delete mode enabled and AI Document Intelligence not enabled"
  
  # Find Document Intelligence resource (docs-{projectName}-...)
  docsName="docs-${projectName}"
  echo "Looking for AI Document Intelligence with prefix: $docsName"
  
  docsResource=$(az cognitiveservices account list \
    --resource-group "$projectResourceGroup" \
    --subscription "$dev_test_prod_sub_id" \
    --query "[?starts_with(name, '$docsName')] | [0].name" -o tsv 2>/dev/null || echo "")
  
  if [ -n "$docsResource" ]; then
    echo "Found AI Document Intelligence: $docsResource"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$docsResource" "AI Document Intelligence"
    
    # Delete the AI Document Intelligence account
    echo "Deleting AI Document Intelligence account: $docsResource"
    az cognitiveservices account delete \
      --name "$docsResource" \
      --resource-group "$projectResourceGroup" \
      --subscription "$dev_test_prod_sub_id"
    
    if [ $? -eq 0 ]; then
      echo "✓ AI Document Intelligence deleted successfully"
    else
      echo "⚠️  Failed to delete AI Document Intelligence"
    fi
  else
    echo "⚠️  AI Document Intelligence not found with prefix: $docsName"
  fi
elif [ "$enableAIDocIntelligence" = "true" ]; then
  echo "ℹ️  AI Document Intelligence is enabled - skipping deletion"
else
  echo "ℹ️  Conditions not met for AI Document Intelligence deletion"
fi

echo ""

# ======================================
# Bing Custom Search
# ======================================
echo "Checking Bing Custom Search deletion conditions..."
if ([ "$enableDeleteForDisabledResources" = "true" ] || [ "$deleteAllServicesForProject" = "true" ]) && [ "$enableBingCustomSearch" = "false" ]; then
  echo "✓ Delete mode enabled and Bing Custom Search not enabled"
  
  # Find Bing Custom Search resource (bing-custom-{projectName}-...)
  bingCustomName="bing-custom-${projectName}"
  echo "Looking for Bing Custom Search with prefix: $bingCustomName"
  
  # Bing resources are of type Microsoft.Bing/accounts
  bingCustomResource=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --subscription "$dev_test_prod_sub_id" \
    --resource-type "Microsoft.Bing/accounts" \
    --query "[?starts_with(name, '$bingCustomName')] | [0].name" -o tsv 2>/dev/null || echo "")
  
  if [ -n "$bingCustomResource" ]; then
    echo "Found Bing Custom Search: $bingCustomResource"
    
    # Bing Custom Search is deployed to 'global' location and typically doesn't support private endpoints
    # Delete the Bing Custom Search account
    echo "Deleting Bing Custom Search account: $bingCustomResource"
    az resource delete \
      --name "$bingCustomResource" \
      --resource-group "$projectResourceGroup" \
      --subscription "$dev_test_prod_sub_id" \
      --resource-type "Microsoft.Bing/accounts"
    
    if [ $? -eq 0 ]; then
      echo "✓ Bing Custom Search deleted successfully"
    else
      echo "⚠️  Failed to delete Bing Custom Search"
    fi
  else
    echo "⚠️  Bing Custom Search not found with prefix: $bingCustomName"
  fi
elif [ "$enableBingCustomSearch" = "true" ]; then
  echo "ℹ️  Bing Custom Search is enabled - skipping deletion"
else
  echo "ℹ️  Conditions not met for Bing Custom Search deletion"
fi

echo ""
echo "=== Deletion task completed ==="
