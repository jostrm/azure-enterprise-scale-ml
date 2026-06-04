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
vnetResourceGroupBase="$vnetResourceGroupBase"

projectNameReplaced="${projectName/prj/project}"
projectResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"

echo "Target resource group: $projectResourceGroup"

# Complete mode: deleteAllServicesForProject deletes EVERYTHING including KeyVault (if deleteKeyvaultAlso=true), Storage, AppInsights, and networking resources in common RG (subnets, NSGs)
# Ultra mode: deleteAllForProject does everything from deleteAllServicesForProject PLUS deletes the project resource group itself
# Safety flag: deleteKeyvaultAlso (default false) preserves the project Key Vault when deleteAllServicesForProject=true.
#              Set to true to also delete the Key Vault (e.g. for a full teardown).
# Normalize to lowercase because ADO serializes unquoted YAML booleans as "True"/"False" (capital T/F)
# and all bash comparisons in this script use lowercase "true"/"false"
deleteAllServicesForProject=$(echo "${deleteAllServicesForProject:-false}" | tr '[:upper:]' '[:lower:]')
deleteAllForProject=$(echo "${deleteAllForProject:-false}" | tr '[:upper:]' '[:lower:]')
deleteKeyvaultAlso=$(echo "${deleteKeyvaultAlso:-false}" | tr '[:upper:]' '[:lower:]')
echo ""
echo "=== Delete Mode ==="
echo "deleteAllServicesForProject: $deleteAllServicesForProject"
echo "deleteAllForProject: $deleteAllForProject"
echo "deleteKeyvaultAlso: $deleteKeyvaultAlso"
if [ "$deleteAllServicesForProject" = "true" ]; then
  if [ "$deleteKeyvaultAlso" = "true" ]; then
    echo "🔥 deleteAllServicesForProject=true + deleteKeyvaultAlso=true: EVERYTHING will be deleted including KeyVault, Storage, AppInsights, and networking resources in common RG"
  else
    echo "🔥 deleteAllServicesForProject=true (deleteKeyvaultAlso=false): EVERYTHING will be deleted EXCEPT KeyVault (Storage, AppInsights, and networking resources in common RG are deleted)"
  fi
fi
if [ "$deleteAllForProject" = "true" ]; then
  echo "💀 deleteAllForProject=true: EVERYTHING will be deleted including KeyVault, Storage, AppInsights, networking resources, AND the entire project resource group"
fi

# =============================================================================
# SERVICES THAT ARE ** NEVER ** DELETED BY THIS SCRIPT (any flag value):
#   - Key Vault          (deleted only when deleteAllServicesForProject=true AND deleteKeyvaultAlso=true,
#                         OR when deleteAllForProject=true which removes the whole RG)
#   - Storage Accounts   (deleted only in deleteAllServicesForProject or deleteAllForProject mode)
#   - Application Insights / Dashboard Insights (deleted only in deleteAllServicesForProject or deleteAllForProject mode)
#   - AI Foundry Hub v1 (MachineLearningServices/workspaces kind=Hub)
#   - AI Foundry V2 / Azure OpenAI / AI Services (CognitiveServices) -
#       these are handled by 04_Purge_SoftDeleted after soft-delete settles
#   - Managed Identities (deleted only in deleteAllServicesForProject or deleteAllForProject mode)
# =============================================================================
# IMPORTANT: Common RG and VNet RG are NEVER deleted - only project resources and networking resources (subnets, NSGs) in common RG

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
  
  # Find private endpoints matching patterns:
  # 1. Exact match: resourcename
  # 2. With -pend suffix: resourcename-pend or resourcename-pend-*
  # 3. With p- prefix: p-resourcename or pend-resourcename
  pend_list=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[?(name == '${resource_name}' || starts_with(name, '${resource_name}-pend') || starts_with(name, 'p-${resource_name}') || starts_with(name, 'pend-${resource_name}'))].name" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")
  
  if [ -n "$pend_list" ]; then
    subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
    declare -a successfully_deleted=()
    
    while IFS= read -r pend_name; do
      if [ -n "$pend_name" ]; then
        echo "  Deleting private endpoint: $pend_name"
        
        # Try normal delete first
        if az network private-endpoint delete \
          --resource-group "$projectResourceGroup" \
          --name "$pend_name" \
          2>&1; then
          successfully_deleted+=("$pend_name")
          echo "    ✓ Successfully deleted $pend_name"
        else
          # Normal delete failed, try REST API force delete
          echo "    Normal delete failed, attempting force delete via REST API"
          rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01"
          
          if az rest --method DELETE --url "$rest_url" 2>&1; then
            successfully_deleted+=("$pend_name")
            echo "    ✓ Force delete succeeded for $pend_name"
          else
            echo "    ⚠️  Both normal and force delete failed for $pend_name"
          fi
        fi
      fi
    done <<< "$pend_list"
    
    # Wait for deletions to complete
    if [ ${#successfully_deleted[@]} -gt 0 ]; then
      echo "  Waiting 10 seconds for private endpoint deletions to complete..."
      sleep 10
    fi
  else
    echo "  No private endpoints found for $resource_name"
  fi
  
  # Also check for NICs with similar patterns (only after private endpoints are handled)
  nic_list=$(az network nic list \
    --resource-group "$projectResourceGroup" \
    --query "[?(starts_with(name, '${resource_name}-pend') || starts_with(name, '${resource_name}.nic'))].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$nic_list" ]; then
    echo "  Cleaning up NICs for $resource_name..."
    while IFS= read -r nic_name; do
      if [ -n "$nic_name" ]; then
        echo "    Deleting NIC: $nic_name"
        az network nic delete \
          --resource-group "$projectResourceGroup" \
          --name "$nic_name" \
          2>&1 || echo "      ⚠️  Failed to delete NIC $nic_name"
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
    "${storage_name}-file"
    "${storage_name}-blob"
    "${storage_name}-queue"
    "${storage_name}-table"
  )
  
  subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
  declare -a all_pends_to_delete=()
  
  # First, collect all private endpoints to delete
  for pattern in "${storage_pend_patterns[@]}"; do
    # Find exact match or with suffix (e.g., pattern-genai, pattern-genaiml)
    pend_list=$(az network private-endpoint list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, 'p-${pattern}') || starts_with(name, '${pattern}-pend')].name" \
      -o tsv 2>/dev/null | tr -d '\r' || echo "")
    
    if [ -n "$pend_list" ]; then
      while IFS= read -r pend_name; do
        if [ -n "$pend_name" ]; then
          all_pends_to_delete+=("$pend_name")
        fi
      done <<< "$pend_list"
    fi
  done
  
  # Delete all collected private endpoints
  if [ ${#all_pends_to_delete[@]} -gt 0 ]; then
    echo "  Found ${#all_pends_to_delete[@]} storage private endpoints to delete"
    
    for pend_name in "${all_pends_to_delete[@]}"; do
      echo "  Deleting storage private endpoint: $pend_name"
      
      # Try normal delete first
      if az network private-endpoint delete \
        --resource-group "$projectResourceGroup" \
        --name "$pend_name" \
        2>&1; then
        echo "    ✓ Successfully deleted $pend_name"
      else
        # Normal delete failed, try REST API force delete
        echo "    Normal delete failed, attempting force delete via REST API"
        rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01"
        
        if az rest --method DELETE --url "$rest_url" 2>&1; then
          echo "    ✓ Force delete succeeded for $pend_name"
        else
          echo "    ⚠️  Both normal and force delete failed for $pend_name"
        fi
      fi
    done
    
    # Wait for deletions to complete
    echo "  Waiting 15 seconds for private endpoint deletions to complete..."
    sleep 15
    
    # Verify deletions
    local retry_needed=false
    for pattern in "${storage_pend_patterns[@]}"; do
      remaining=$(az network private-endpoint list \
        --resource-group "$projectResourceGroup" \
        --query "[?starts_with(name, 'p-${pattern}') || starts_with(name, '${pattern}-pend')].name" \
        -o tsv 2>/dev/null | tr -d '\r' || echo "")

      if [ -n "$remaining" ]; then
        echo "  ⚠️  Some private endpoints still exist, will retry"
        retry_needed=true

        while IFS= read -r pend_name; do
          if [ -n "$pend_name" ]; then
            echo "    Retrying force delete for: $pend_name"
            rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01"
            az rest --method DELETE --url "$rest_url" 2>&1 || echo "      Warning: Retry failed for $pend_name"
          fi
        done <<< "$remaining"
      fi
    done
    
    if [ "$retry_needed" = true ]; then
      echo "  Waiting additional 15 seconds after retries..."
      sleep 15
    fi
  else
    echo "  No storage private endpoints found for $storage_name"
  fi
  
  # Now clean up NICs (only after private endpoints are handled)
  echo "  Cleaning up storage NICs..."
  local any_nics_found=false
  
  for pattern in "${storage_pend_patterns[@]}"; do
    nic_list=$(az network nic list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, 'p-${pattern}') || starts_with(name, '${pattern}-pend')].name" \
      -o tsv 2>/dev/null || echo "")
    
    if [ -n "$nic_list" ]; then
      any_nics_found=true
      while IFS= read -r nic_name; do
        if [ -n "$nic_name" ]; then
          echo "    Deleting storage NIC: $nic_name"
          az network nic delete \
            --resource-group "$projectResourceGroup" \
            --name "$nic_name" 2>&1 || echo "      ⚠️  Failed to delete $nic_name (may still be in use)"
        fi
      done <<< "$nic_list"
    fi
  done
  
  if [ "$any_nics_found" = false ]; then
    echo "    No storage NICs found"
  fi
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
# NOTE: Only enableAFoundryCaphost matters here — AI Search is needed as a caphost dependency even when enableAIFoundry=false
if [ "$enableAFoundryCaphost" = "true" ] && [ "$deleteAllServicesForProject" != "true" ]; then
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
    # Get all shared private link resources
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
          echo "    Deleting shared private endpoint: $shared_pe_name (async, no-wait)"
          # Use --no-wait to avoid blocking on locked resources
          az search shared-private-link-resource delete \
            --resource-group "$projectResourceGroup" \
            --service-name "$aisearch_name" \
            --name "$shared_pe_name" \
            --yes \
            --no-wait 2>&1 || echo "    Warning: Failed to initiate deletion of $shared_pe_name"
        fi
      done <<< "$shared_pe_list"
      
      # Wait for shared private endpoints to be fully deleted
      echo "  Waiting 30 seconds for shared private endpoints deletion to complete..."
      sleep 30
      
      # Verify deletion
      echo "  Verifying shared private endpoints deletion..."
      remaining_spl=$(az search shared-private-link-resource list \
        --resource-group "$projectResourceGroup" \
        --service-name "$aisearch_name" \
        --query "[].name" \
        -o tsv 2>/dev/null || echo "")
      
      if [ -z "$remaining_spl" ]; then
        echo "  ✓ All shared private endpoints deleted successfully"
      else
        echo "  ⚠️  Some shared private endpoints still exist, waiting additional 30 seconds..."
        sleep 30
        
        # Final check and force delete any remaining via REST API
        remaining_spl=$(az search shared-private-link-resource list \
          --resource-group "$projectResourceGroup" \
          --service-name "$aisearch_name" \
          --query "[].name" \
          -o tsv 2>/dev/null | tr -d '\r' || echo "")
        
        if [ -n "$remaining_spl" ]; then
          echo "  Force deleting remaining shared private endpoints via REST API..."
          subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
          while IFS= read -r remaining_pe; do
            if [ -n "$remaining_pe" ]; then
              echo "    Force deleting: $remaining_pe"
              rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Search/searchServices/${aisearch_name}/sharedPrivateLinkResources/${remaining_pe}?api-version=2025-02-01-preview"
              az rest --method DELETE --url "$rest_url" --headers "Content-Type=application/json" 2>&1 || echo "    Warning: Force delete failed for $remaining_pe"
            fi
          done <<< "$remaining_spl"
          
          echo "  Waiting additional 20 seconds after force deletion..."
          sleep 20
        fi
      fi
    else
      echo "  No shared private endpoints found"
    fi
    subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
    
    for shared_pe_name in "${foundry_shared_endpoints[@]}"; do
      echo "    Checking for: $shared_pe_name"
      rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Search/searchServices/${aisearch_name}/sharedPrivateLinkResources/${shared_pe_name}?api-version=2025-02-01-preview"
      az rest --method DELETE --url "$rest_url" --headers "Content-Type=application/json" -o none 2>/dev/null && echo "    ✓ Deleted $shared_pe_name" || true
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
            2>&1 || echo "  Warning: could not delete $pend_name"
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
            2>&1 || echo "  Warning: could not delete $pend_name"
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
    # NOTE: az functionapp delete is known to spuriously print
    #   "ERROR: Operation returned an invalid status 'Not Found'"
    # even on a successful delete (the LRO polling URL 404s once the resource
    # is gone). We therefore ignore the CLI exit code and instead VERIFY the
    # resource is actually absent by re-querying ARM.
    echo "Deleting Function App: $func_name"
    delete_output=$(az functionapp delete \
      --resource-group "$projectResourceGroup" \
      --name "$func_name" 2>&1) || true
    if [ -n "$delete_output" ]; then
      echo "$delete_output"
    fi

    # Verify deletion (give ARM up to ~30s to propagate)
    func_still_there=""
    for attempt in 1 2 3 4 5 6; do
      func_still_there=$(az functionapp show \
        --resource-group "$projectResourceGroup" \
        --name "$func_name" \
        --query "id" -o tsv 2>/dev/null || echo "")
      if [ -z "$func_still_there" ]; then
        break
      fi
      sleep 5
    done

    if [ -z "$func_still_there" ]; then
      echo "✅ Successfully deleted Function App: $func_name"
      echo "##vso[task.setvariable variable=functionAppExists]false"
    else
      echo "##[warning]❌ Function App still present after delete attempt: $func_still_there"
      echo "##[warning]   CLI output was: ${delete_output:-<empty>}"
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
      
      delete_private_endpoints "$aca_a_name" "Container App A"
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
      
      delete_private_endpoints "$aca_w_name" "Container App W"
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

    # Before deleting the env, delete ALL container apps inside it.
    # Azure refuses to delete a managed environment that still has container apps.
    echo "Checking for any remaining container apps in the environment..."
    remaining_apps=$(az containerapp list \
      --resource-group "$projectResourceGroup" \
      --query "[].name" \
      -o tsv 2>/dev/null || echo "")
    if [ -n "$remaining_apps" ]; then
      while IFS= read -r app_name; do
        if [ -n "$app_name" ]; then
          echo "  Deleting remaining container app: $app_name"
          az containerapp delete \
            --resource-group "$projectResourceGroup" \
            --name "$app_name" \
            --yes 2>&1 && echo "  ✅ Deleted: $app_name" || echo "  ⚠️  Could not delete: $app_name (continuing)"
        fi
      done <<< "$remaining_apps"
    else
      echo "  No remaining container apps found."
    fi

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
# AI FOUNDRY V1 PROJECT - Delete BEFORE AI Hub (child workspace of Hub)
# Deletion puts it in soft-delete state → 04_Purge_SoftDeleted task handles purge
# =============================================================================
enableAIFoundryHub="$enableAIFoundryHub"
aifProjectExists="$aifProjectExists"
# Normalize to lowercase (ADO may pass unquoted booleans as "True")
enableAIFoundryHub=$(echo "${enableAIFoundryHub:-false}" | tr '[:upper:]' '[:lower:]')
aifProjectExists=$(echo "${aifProjectExists:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$deleteAllServicesForProject" = "true" ]; then enableAIFoundryHub="false"; fi

echo ""
echo "--- AI Foundry V1 Project (deleted before AI Hub) ---"
echo "enableAIFoundryHub: $enableAIFoundryHub"
echo "aifProjectExists: $aifProjectExists"

if [ "$enableAIFoundryHub" = "false" ] && [ "$aifProjectExists" = "true" ]; then
  echo "✓ AI Foundry V1 project exists - proceeding with deletion (will go to soft-delete)"

  # Support both old naming (aif-p-) and new naming (ai-prj)
  aifProjectName1="aif-p-${projectNumber}-1-${locationSuffix}-${envName}"
  aifProjectName2="ai-prj${projectNumber}"

  aif_proj_name=$(az ml workspace list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${aifProjectName1}') || starts_with(name, '${aifProjectName2}')].name" \
    -o tsv 2>/dev/null | head -n1)

  if [ -n "$aif_proj_name" ]; then
    echo "Found AI Foundry V1 Project: $aif_proj_name"
    echo "##vso[task.setvariable variable=aifProjectActualName]$aif_proj_name"
    # Delete any ML endpoints before deleting the workspace
    echo "Checking for ML endpoints in workspace: $aif_proj_name"
    endpoint_list=$(az ml online-endpoint list --workspace-name "$aif_proj_name" --resource-group "$projectResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
    if [ -n "$endpoint_list" ]; then
      while IFS= read -r ep_name; do
        if [ -n "$ep_name" ]; then
          echo "  Deleting ML endpoint: $ep_name"
          az ml online-endpoint delete --workspace-name "$aif_proj_name" --resource-group "$projectResourceGroup" --name "$ep_name" --yes 2>&1 || echo "  Warning: Failed to delete endpoint $ep_name"
        fi
      done <<< "$endpoint_list"
    fi
    
    delete_private_endpoints "$aif_proj_name" "AI Foundry V1 Project"
    echo "Deleting AI Foundry V1 Project: $aif_proj_name"
    az ml workspace delete \
      --resource-group "$projectResourceGroup" \
      --name "$aif_proj_name" \
      --yes 2>&1 && echo "✅ Deleted AI Foundry V1 Project (soft-deleted)" || echo "⚠️  Could not delete AI Foundry V1 Project"
  else
    echo "⚠️  AI Foundry V1 Project not found with prefixes: $aifProjectName1 or $aifProjectName2"
  fi
else
  echo "ℹ️  AI Foundry V1 Project skipped (enableAIFoundryHub=$enableAIFoundryHub, aifProjectExists=$aifProjectExists)"
fi

# =============================================================================
# AI HUB (AI Foundry V1) - Delete if disabled and exists
# Deletion puts it in soft-delete state → 04_Purge_SoftDeleted task handles purge
# =============================================================================
aiHubExists="$aiHubExists"
aiHubExists=$(echo "${aiHubExists:-false}" | tr '[:upper:]' '[:lower:]')
# enableAIFoundryHub already set and overridden above

echo ""
echo "--- AI Hub (AI Foundry V1) ---"
echo "enableAIFoundryHub: $enableAIFoundryHub"
echo "aiHubExists: $aiHubExists"

if [ "$enableAIFoundryHub" = "false" ] && [ "$aiHubExists" = "true" ]; then
  echo "✓ AI Hub exists - proceeding with deletion (will go to soft-delete)"

  # Support both old naming (aif-hub-) and new naming (ai-hub-prj)
  aiHubName1="aif-hub-${projectNumber}-${locationSuffix}-${envName}"
  aiHubName2="ai-hub-prj${projectNumber}"

  ai_hub_name=$(az ml workspace list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, '${aiHubName1}') || starts_with(name, '${aiHubName2}')].name" \
    -o tsv 2>/dev/null | head -n1)

  if [ -n "$ai_hub_name" ]; then
    echo "Found AI Hub: $ai_hub_name"
    echo "##vso[task.setvariable variable=aiHubActualName]$ai_hub_name"
    # Delete any ML endpoints before deleting the hub
    echo "Checking for ML endpoints in hub: $ai_hub_name"
    endpoint_list=$(az ml online-endpoint list --workspace-name "$ai_hub_name" --resource-group "$projectResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
    if [ -n "$endpoint_list" ]; then
      while IFS= read -r ep_name; do
        if [ -n "$ep_name" ]; then
          echo "  Deleting ML endpoint: $ep_name"
          az ml online-endpoint delete --workspace-name "$ai_hub_name" --resource-group "$projectResourceGroup" --name "$ep_name" --yes 2>&1 || echo "  Warning: Failed to delete endpoint $ep_name"
        fi
      done <<< "$endpoint_list"
    fi
    
    delete_private_endpoints "$ai_hub_name" "AI Hub"
    echo "Deleting AI Hub: $ai_hub_name (soft-delete, purge by 04_Purge_SoftDeleted)"
    az ml workspace delete \
      --resource-group "$projectResourceGroup" \
      --name "$ai_hub_name" \
      --yes 2>&1 && echo "✅ Deleted AI Hub (soft-deleted)" || echo "⚠️  Could not delete AI Hub"
  else
    echo "⚠️  AI Hub not found with prefixes: $aiHubName1 or $aiHubName2"
  fi
else
  echo "ℹ️  AI Hub skipped (enableAIFoundryHub=$enableAIFoundryHub, aiHubExists=$aiHubExists)"
fi

# =============================================================================
# AI FOUNDRY V2 ACCOUNT (CognitiveServices) - Delete if disabled and exists
# Deletion puts it in soft-delete state → 04_Purge_SoftDeleted task handles purge
# =============================================================================
enableAIFoundry="$enableAIFoundry"
aiFoundryV2Exists="$aiFoundryV2Exists"
enableAIFoundry=$(echo "${enableAIFoundry:-true}" | tr '[:upper:]' '[:lower:]')
aiFoundryV2Exists=$(echo "${aiFoundryV2Exists:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$deleteAllServicesForProject" = "true" ]; then enableAIFoundry="false"; fi

echo ""
echo "--- AI Foundry V2 Account ---"
echo "enableAIFoundry: $enableAIFoundry"
echo "aiFoundryV2Exists: $aiFoundryV2Exists"

if [ "$enableAIFoundry" = "false" ] && [ "$aiFoundryV2Exists" = "true" ]; then
  echo "✓ AI Foundry V2 account exists - proceeding with deletion (will go to soft-delete)"

  aiFoundryV2Prefix="aif2"

  aif2_name=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[?starts_with(name, '${aiFoundryV2Prefix}')].name" \
    -o tsv 2>/dev/null | head -n1)

  if [ -n "$aif2_name" ]; then
    echo "Found AI Foundry V2 account: $aif2_name"

    # --- PREREQUISITE: Delete capability hosts BEFORE account/projects ---
    # Per Microsoft guidance: "Before deleting an Account, delete the associated Account Capability Host.
    # Failure to do so may result in residual dependencies (subnets, ACA apps) causing 'Subnet already in use' errors."
    # Reference: microsoft-foundry/foundry-samples/15-private-network-standard-agent-setup
    aif2_sub=$(az account show --query id -o tsv 2>/dev/null)

    # Step 1: Delete project-level capability hosts
    aif2_projects_for_caphost=$(az rest \
      --method GET \
      --url "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/projects?api-version=2026-01-15-preview" \
      --query "value[].name" -o tsv 2>/dev/null || echo "")

    if [ -n "$aif2_projects_for_caphost" ]; then
      while IFS= read -r proj_name; do
        [ -z "$proj_name" ] && continue
        # REST API returns name as 'accountName/projectName' — strip parent prefix
        proj_name="${proj_name##*/}"
        echo "  Checking project-level capability hosts for project: $proj_name"
        proj_caphosts=$(az rest \
          --method GET \
          --url "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/projects/${proj_name}/capabilityHosts?api-version=2026-01-15-preview" \
          --query "value[].name" -o tsv 2>/dev/null || echo "")
        if [ -n "$proj_caphosts" ]; then
          while IFS= read -r ch_name; do
            [ -z "$ch_name" ] && continue
            ch_name="${ch_name##*/}"
            echo "    Deleting project caphost: $ch_name"
            delete_response=$(az rest \
              --method DELETE \
              --url "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/projects/${proj_name}/capabilityHosts/${ch_name}?api-version=2026-01-15-preview" \
              --headers "Content-Type=application/json" \
              -o json 2>&1) && echo "    ✅ Delete initiated for project caphost: $ch_name" || echo "    ⚠️  Could not delete project caphost: $ch_name"
          done <<< "$proj_caphosts"
        fi
      done <<< "$aif2_projects_for_caphost"
    fi

    # Step 2: Delete account-level capability hosts (long-running async operation — poll for completion)
    echo "  Checking account-level capability hosts for: $aif2_name"
    acct_caphosts=$(az rest \
      --method GET \
      --url "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/capabilityHosts?api-version=2026-01-15-preview" \
      --query "value[].name" -o tsv 2>/dev/null || echo "")

    if [ -n "$acct_caphosts" ]; then
      while IFS= read -r ch_name; do
        [ -z "$ch_name" ] && continue
        ch_name="${ch_name##*/}"
        echo "    Deleting account caphost: $ch_name (this may take several minutes...)"
        # Capture response headers for async polling
        http_response=$(curl -s -w "\n%{http_code}" -X DELETE \
          -H "Authorization: Bearer $(az account get-access-token --query accessToken -o tsv)" \
          -H "Content-Type: application/json" \
          "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/capabilityHosts/${ch_name}?api-version=2026-01-15-preview" \
          -D /tmp/caphost_delete_headers.txt 2>/dev/null)
        http_code=$(echo "$http_response" | tail -n1)

        if [ "$http_code" = "202" ] || [ "$http_code" = "200" ]; then
          # Poll async operation if Azure-AsyncOperation header present
          async_url=$(grep -i "Azure-AsyncOperation" /tmp/caphost_delete_headers.txt 2>/dev/null | sed 's/.*: //' | tr -d '\r')
          if [ -n "$async_url" ]; then
            echo "    Polling deletion status..."
            poll_count=0
            max_polls=120  # 10 min max (120 * 5s)
            while [ $poll_count -lt $max_polls ]; do
              sleep 5
              poll_count=$((poll_count + 1))
              status=$(az rest --method GET --url "$async_url" --query "status" -o tsv 2>/dev/null)
              if [ "$status" = "Succeeded" ]; then
                echo "    ✅ Account caphost deleted: $ch_name"
                break
              elif [ "$status" = "Failed" ] || [ "$status" = "Canceled" ]; then
                echo "    ⚠️  Account caphost deletion $status: $ch_name"
                break
              fi
              # Print progress every 30 seconds
              if [ $((poll_count % 6)) -eq 0 ]; then
                echo "    ⏳ Still deleting... (${poll_count}x5s elapsed, status: $status)"
              fi
            done
            if [ $poll_count -ge $max_polls ]; then
              echo "    ⚠️  Timed out waiting for account caphost deletion: $ch_name"
            fi
          else
            echo "    ✅ Account caphost deleted: $ch_name"
          fi
        else
          echo "    ⚠️  Could not delete account caphost: $ch_name (HTTP $http_code)"
        fi
        rm -f /tmp/caphost_delete_headers.txt
      done <<< "$acct_caphosts"
    else
      echo "  No account-level capability hosts found."
    fi
    # --- End capability host cleanup ---

    # --- Delete nested projects (CannotDeleteResource if skipped) ---
    # AI Foundry V2 accounts have child resources: Microsoft.CognitiveServices/accounts/projects
    # Azure RM requires all nested resources to be removed before the parent account can be deleted.
    aif2_projects=$(az rest \
      --method GET \
      --url "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/projects?api-version=2026-01-15-preview" \
      --query "value[].name" -o tsv 2>/dev/null)

    if [ -n "$aif2_projects" ]; then
      echo "Found nested AI Foundry V2 projects — deleting before account removal:"
      while IFS= read -r proj_name; do
        [ -z "$proj_name" ] && continue
        # REST API returns name as 'accountName/projectName' — strip parent prefix
        proj_name="${proj_name##*/}"
        echo "  Deleting project: $proj_name"
        az rest \
          --method DELETE \
          --url "https://management.azure.com/subscriptions/${aif2_sub}/resourceGroups/${projectResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${aif2_name}/projects/${proj_name}?api-version=2026-01-15-preview" \
          2>&1 && echo "  ✅ Deleted project: $proj_name" || echo "  ⚠️  Could not delete project: $proj_name"
      done <<< "$aif2_projects"
      echo "All nested projects processed."
    else
      echo "No nested projects found under $aif2_name"
    fi
    # --- End nested project deletion ---

    delete_private_endpoints "$aif2_name" "AI Foundry V2"
    echo "Deleting AI Foundry V2 account: $aif2_name (soft-delete, purge by 04_Purge_SoftDeleted)"
    az cognitiveservices account delete \
      --resource-group "$projectResourceGroup" \
      --name "$aif2_name" 2>&1 && echo "✅ Deleted AI Foundry V2 (soft-deleted)" || echo "⚠️  Could not delete AI Foundry V2"
  else
    echo "⚠️  AI Foundry V2 account not found with prefix: $aiFoundryV2Prefix"
  fi
else
  echo "ℹ️  AI Foundry V2 skipped (enableAIFoundry=$enableAIFoundry, aiFoundryV2Exists=$aiFoundryV2Exists)"
fi

# =============================================================================
# AI SERVICES ACCOUNT (CognitiveServices) - Delete if disabled and exists
# Deletion puts it in soft-delete state → 04_Purge_SoftDeleted task handles purge
# =============================================================================
enableAIServices="$enableAIServices"
aiServicesExists="$aiServicesExists"
enableAIServices=$(echo "${enableAIServices:-false}" | tr '[:upper:]' '[:lower:]')
aiServicesExists=$(echo "${aiServicesExists:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$deleteAllServicesForProject" = "true" ]; then enableAIServices="false"; fi

echo ""
echo "--- AI Services Account ---"
echo "enableAIServices: $enableAIServices"
echo "aiServicesExists: $aiServicesExists"

if [ "$enableAIServices" = "false" ] && [ "$aiServicesExists" = "true" ]; then
  echo "✓ AI Services account exists - proceeding with deletion (will go to soft-delete)"

  aiServicesPrefix="aiservices${projectName}${locationSuffix}${envName}"

  aisvc_name=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[?starts_with(name, '${aiServicesPrefix}')].name" \
    -o tsv 2>/dev/null | head -n1)

  if [ -n "$aisvc_name" ]; then
    echo "Found AI Services account: $aisvc_name"
    delete_private_endpoints "$aisvc_name" "AI Services"
    echo "Deleting AI Services account: $aisvc_name (soft-delete, purge by 04_Purge_SoftDeleted)"
    az cognitiveservices account delete \
      --resource-group "$projectResourceGroup" \
      --name "$aisvc_name" 2>&1 && echo "✅ Deleted AI Services (soft-deleted)" || echo "⚠️  Could not delete AI Services"
  else
    echo "⚠️  AI Services account not found with prefix: $aiServicesPrefix"
  fi
else
  echo "ℹ️  AI Services skipped (enableAIServices=$enableAIServices, aiServicesExists=$aiServicesExists)"
fi

# =============================================================================
# AZURE OPENAI (CognitiveServices) - Delete if disabled and exists
# Deletion puts it in soft-delete state → 04_Purge_SoftDeleted task handles purge
# =============================================================================
enableAzureOpenAI="$enableAzureOpenAI"
openaiExists="$openaiExists"
enableAzureOpenAI=$(echo "${enableAzureOpenAI:-false}" | tr '[:upper:]' '[:lower:]')
openaiExists=$(echo "${openaiExists:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$deleteAllServicesForProject" = "true" ]; then enableAzureOpenAI="false"; fi

echo ""
echo "--- Azure OpenAI ---"
echo "enableAzureOpenAI: $enableAzureOpenAI"
echo "openaiExists: $openaiExists"

if [ "$enableAzureOpenAI" = "false" ] && [ "$openaiExists" = "true" ]; then
  echo "✓ Azure OpenAI account exists - proceeding with deletion (will go to soft-delete)"

  openaiName="aoai-${projectName}-${locationSuffix}-${envName}"

  aoai_name=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[?starts_with(name, '${openaiName}')].name" \
    -o tsv 2>/dev/null | head -n1)

  if [ -n "$aoai_name" ]; then
    echo "Found Azure OpenAI account: $aoai_name"
    delete_private_endpoints "$aoai_name" "Azure OpenAI"
    echo "Deleting Azure OpenAI account: $aoai_name (soft-delete, purge by 04_Purge_SoftDeleted)"
    az cognitiveservices account delete \
      --resource-group "$projectResourceGroup" \
      --name "$aoai_name" 2>&1 && echo "✅ Deleted Azure OpenAI (soft-deleted)" || echo "⚠️  Could not delete Azure OpenAI"
  else
    echo "⚠️  Azure OpenAI account not found with prefix: $openaiName"
  fi
else
  echo "ℹ️  Azure OpenAI skipped (enableAzureOpenAI=$enableAzureOpenAI, openaiExists=$openaiExists)"
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

    delete_private_endpoints "$aks_name" "AKS"
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
    echo "##vso[task.setvariable variable=amlActualName]$aml_name"

    # Delete any ML endpoints before deleting the workspace
    echo "Checking for ML endpoints in workspace: $aml_name"
    endpoint_list=$(az ml online-endpoint list --workspace-name "$aml_name" --resource-group "$projectResourceGroup" --query "[].name" -o tsv 2>/dev/null || echo "")
    if [ -n "$endpoint_list" ]; then
      while IFS= read -r ep_name; do
        if [ -n "$ep_name" ]; then
          echo "  Deleting ML endpoint: $ep_name"
          az ml online-endpoint delete --workspace-name "$aml_name" --resource-group "$projectResourceGroup" --name "$ep_name" --yes 2>&1 || echo "  Warning: Failed to delete endpoint $ep_name"
        fi
      done <<< "$endpoint_list"
    fi

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

    # Delete the Bot Service managed identity (naming: {botName}-identity)
    botMIName="${bot_name}-identity"
    botMIExists=$(az resource list \
      --resource-group "$projectResourceGroup" \
      --resource-type "Microsoft.ManagedIdentity/userAssignedIdentities" \
      --query "[?name=='${botMIName}'].name" \
      -o tsv 2>/dev/null | head -n1)

    if [ -n "$botMIExists" ]; then
      # Safety guard: NEVER delete the project core managed identities (mi-aca-prj... / mi-prj...)
      # These are essential to the project and are never deleted by this script.
      if [[ "$botMIName" == mi-aca-* ]] || [[ "$botMIName" == mi-* && "$botMIName" != *-identity ]]; then
        echo "🛑 Safety guard: refusing to delete protected managed identity: $botMIName — skipping"
      else
        echo "Deleting Bot Service managed identity: $botMIName"
        az identity delete \
          --resource-group "$projectResourceGroup" \
          --name "$botMIName" 2>&1
        if [ $? -eq 0 ]; then
          echo "✅ Successfully deleted Bot Service managed identity: $botMIName"
        else
          echo "❌ Failed to delete Bot Service managed identity: $botMIName"
        fi
      fi
    else
      echo "ℹ️  Bot Service managed identity not found: $botMIName — skipping"
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
  
  # Use az resource list for Microsoft.Bing/accounts (not cognitiveservices)
  bing_name=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "Microsoft.Bing/accounts" \
    --query "[?starts_with(name, '${bingName}')].name" \
    -o tsv | head -n1)
  
  if [ -n "$bing_name" ]; then
    echo "Found Bing Search: $bing_name"
    
    # Always attempt to delete private endpoints (fail silently if not found)
    delete_private_endpoints "$bing_name" "Bing Search"
    
    echo "Deleting Bing Search: $bing_name"
    az resource delete \
      --resource-group "$projectResourceGroup" \
      --name "$bing_name" \
      --resource-type "Microsoft.Bing/accounts" 2>&1
    
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
# Content Safety
# ======================================
echo "Checking Content Safety deletion conditions..."
if ([ "$enableDeleteForDisabledResources" = "true" ] || [ "$deleteAllServicesForProject" = "true" ]) && [ "$enableContentSafety" = "false" ]; then
  echo "✓ Delete mode enabled and Content Safety not enabled"

  # Name prefix from bicep: cs-{projectName}-{locationSuffix}-{env}-{uniqueInAIFenv}{commonResourceSuffix}
  contentSafetyPrefix="cs-${projectName}"
  echo "Looking for Content Safety with prefix: $contentSafetyPrefix"

  contentSafetyResource=$(az cognitiveservices account list \
    --resource-group "$projectResourceGroup" \
    --subscription "$dev_test_prod_sub_id" \
    --query "[?starts_with(name, '$contentSafetyPrefix')] | [0].name" -o tsv 2>/dev/null || echo "")

  if [ -n "$contentSafetyResource" ]; then
    echo "Found Content Safety: $contentSafetyResource"

    delete_private_endpoints "$contentSafetyResource" "Content Safety"

    echo "Deleting Content Safety account: $contentSafetyResource"
    az cognitiveservices account delete \
      --name "$contentSafetyResource" \
      --resource-group "$projectResourceGroup" \
      --subscription "$dev_test_prod_sub_id"

    if [ $? -eq 0 ]; then
      echo "✓ Content Safety deleted successfully"
      echo "##vso[task.setvariable variable=contentSafetyExists]false"
    else
      echo "⚠️  Failed to delete Content Safety"
    fi
  else
    echo "⚠️  Content Safety not found with prefix: $contentSafetyPrefix"
  fi
elif [ "$enableContentSafety" = "true" ]; then
  echo "ℹ️  Content Safety is enabled - skipping deletion"
else
  echo "ℹ️  Conditions not met for Content Safety deletion"
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
echo "=== Standard deletion completed ==="

# =============================================================================
# COMPLETE DELETE MODE: deleteAllServicesForProject=true OR deleteAllForProject=true
# Delete everything remaining in project RG + networking resources in common RG
# =============================================================================

if [ "$deleteAllServicesForProject" = "true" ] || [ "$deleteAllForProject" = "true" ]; then
  echo ""
  echo "🔥🔥🔥 ======================================== 🔥🔥🔥"
  if [ "$deleteAllForProject" = "true" ]; then
    echo "💀 ULTRA DELETE MODE: deleteAllForProject=true"
    echo "💀 Will delete everything + project resource group"
  else
    echo "🔥 COMPLETE DELETE MODE: deleteAllServicesForProject=true"
    echo "🔥 Will delete everything except project resource group"
  fi
  echo "🔥🔥🔥 ======================================== 🔥🔥🔥"
  echo ""
  
  # Step 1: Delete Storage Accounts
  echo "=== Step 1: Deleting Storage Accounts ==="
  storage_accounts=$(az storage account list \
    --resource-group "$projectResourceGroup" \
    --query "[].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$storage_accounts" ]; then
    while IFS= read -r sa_name; do
      if [ -n "$sa_name" ]; then
        echo "Deleting storage account: $sa_name"
        # Delete private endpoints first
        delete_storage_private_endpoints "$sa_name"
        # Delete the storage account
        az storage account delete \
          --name "$sa_name" \
          --resource-group "$projectResourceGroup" \
          --yes 2>&1 || echo "  Warning: Failed to delete storage account $sa_name"
      fi
    done <<< "$storage_accounts"
    echo "✓ Storage accounts deleted"
  else
    echo "No storage accounts found"
  fi
  
  # Step 1a: Delete Storage Private Endpoints and NICs (pattern: p-sa-prj*)
  echo ""
  echo "=== Step 1a: Deleting Storage Private Endpoints (p-sa-prj*) ==="
  storage_pends=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'p-sa-prj')].name" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")
  
  subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
  
  if [ -n "$storage_pends" ]; then
    # Track which endpoints were successfully deleted
    declare -a successfully_deleted_pends=()
    
    while IFS= read -r pend_name; do
      if [ -n "$pend_name" ]; then
        echo "Deleting storage private endpoint: $pend_name"
        
        # Try normal delete first
        if az network private-endpoint delete \
          --resource-group "$projectResourceGroup" \
          --name "$pend_name" \
          2>&1; then
          successfully_deleted_pends+=("$pend_name")
        else
          # Normal delete failed, try REST API force delete
          echo "  Normal delete failed, attempting force delete via REST API"
          rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01"
          
          if az rest --method DELETE --url "$rest_url" 2>&1; then
            successfully_deleted_pends+=("$pend_name")
            echo "  ✓ Force delete succeeded for $pend_name"
          else
            echo "  ⚠️  Force delete also failed for $pend_name - will retry after pause"
          fi
        fi
      fi
    done <<< "$storage_pends"
    
    # Wait for private endpoints to be fully deleted before attempting NIC deletion
    echo ""
    echo "Waiting 15 seconds for private endpoint deletions to complete..."
    sleep 15
    
    # Verify and retry failed deletions
    echo "Verifying private endpoint deletions..."
    remaining_pends=$(az network private-endpoint list \
      --resource-group "$projectResourceGroup" \
      --query "[?starts_with(name, 'p-sa-prj')].name" \
      -o tsv 2>/dev/null | tr -d '\r' || echo "")
    
    if [ -n "$remaining_pends" ]; then
      echo "⚠️  Some private endpoints still exist, retrying with force delete..."
      while IFS= read -r pend_name; do
        if [ -n "$pend_name" ]; then
          echo "  Retrying force delete for: $pend_name"
          rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01"
          az rest --method DELETE --url "$rest_url" 2>&1 || echo "    Warning: Retry failed for $pend_name"
        fi
      done <<< "$remaining_pends"
      
      echo "Waiting additional 15 seconds..."
      sleep 15
    fi
    
    echo "✓ Storage private endpoints deletion initiated"
  else
    echo "No storage private endpoints found with prefix p-sa-prj"
  fi
  
  # Delete storage NICs (pattern: p-sa-prj*) - only after private endpoints are gone
  echo ""
  echo "Deleting storage NICs (p-sa-prj*)"
  
  # Re-check for remaining private endpoints before deleting NICs
  remaining_pends=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'p-sa-prj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$remaining_pends" ]; then
    echo "⚠️  WARNING: Some private endpoints still exist. NICs may fail to delete:"
    echo "$remaining_pends"
    echo "Proceeding with NIC deletion (may encounter errors)..."
  fi
  
  storage_nics=$(az network nic list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'p-sa-prj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$storage_nics" ]; then
    while IFS= read -r nic_name; do
      if [ -n "$nic_name" ]; then
        echo "Deleting storage NIC: $nic_name"
        az network nic delete \
          --resource-group "$projectResourceGroup" \
          --name "$nic_name" \
          2>&1 || echo "  ⚠️  Failed to delete $nic_name (may still be in use by private endpoint)"
      fi
    done <<< "$storage_nics"
    echo "✓ Storage NICs deletion attempted"
  else
    echo "No storage NICs found with prefix p-sa-prj"
  fi
  
  # Step 2: Delete Application Insights
  echo ""
  echo "=== Step 2: Deleting Application Insights (all in resource group) ==="
  # Use 'az resource list' as the primary query — it doesn't require the application-insights CLI
  # extension and reliably surfaces both classic and workspace-based AI components.
  app_insights=$(az resource list \
    --resource-group "$projectResourceGroup" \
    --resource-type "microsoft.insights/components" \
    --query "[].name" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")

  # Fallback to the extension-based list in case the resource provider query was filtered out
  if [ -z "$app_insights" ]; then
    app_insights=$(az monitor app-insights component list \
      --resource-group "$projectResourceGroup" \
      --query "[].name" \
      -o tsv 2>/dev/null | tr -d '\r' || echo "")
  fi

  if [ -n "$app_insights" ]; then
    ai_count=$(echo "$app_insights" | wc -l)
    echo "Found $ai_count Application Insights instance(s)"
    
    while IFS= read -r ai_name; do
      if [ -n "$ai_name" ]; then
        echo "  Deleting Application Insights: $ai_name"
        # NOTE: 'az monitor app-insights component delete' requires the application-insights
        # extension AND does NOT support --yes (it has no prompt, but rejects the flag).
        # Use 'az resource delete' which is built-in, non-interactive, and works for both
        # classic and workspace-based components.
        if az resource delete \
          --resource-group "$projectResourceGroup" \
          --resource-type "microsoft.insights/components" \
          --name "$ai_name" 2>&1; then
          echo "    ✓ Successfully deleted: $ai_name"
        else
          echo "    ✗ Failed to delete: $ai_name"
          # Try with REST API as fallback
          subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
          echo "    Attempting REST API force delete for $ai_name..."
          if az rest --method DELETE \
            --url "https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/microsoft.insights/components/${ai_name}?api-version=2020-02-02" 2>&1; then
            echo "    ✓ REST API delete succeeded: $ai_name"
          else
            echo "    ✗ REST API delete also failed: $ai_name"
          fi
        fi
      fi
    done <<< "$app_insights"
    echo "✓ Application Insights deletion completed"
  else
    echo "No Application Insights found in resource group"
  fi
  
  # Step 3: Delete Dashboards
  echo ""
  echo "=== Step 3: Deleting Dashboards ==="
  dashboards=$(az portal dashboard list \
    --resource-group "$projectResourceGroup" \
    --query "[].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$dashboards" ]; then
    while IFS= read -r dash_name; do
      if [ -n "$dash_name" ]; then
        echo "Deleting dashboard: $dash_name"
        az portal dashboard delete \
          --resource-group "$projectResourceGroup" \
          --name "$dash_name" \
          --yes 2>&1 || echo "  Warning: Failed to delete $dash_name"
      fi
    done <<< "$dashboards"
    echo "✓ Dashboards deleted"
  else
    echo "No dashboards found"
  fi
  
  # Step 4: Delete Key Vaults (gated by deleteKeyvaultAlso flag)
  echo ""
  echo "=== Step 4: Deleting Key Vaults ==="
  if [ "$deleteKeyvaultAlso" != "true" ]; then
    echo "⏭  Skipping Key Vault deletion: deleteKeyvaultAlso=false (Key Vault is preserved as a safety net)."
    echo "   Set deleteKeyvaultAlso=true to also delete the project Key Vault."
  else
    keyvaults=$(az keyvault list \
      --resource-group "$projectResourceGroup" \
      --query "[].name" \
      -o tsv 2>/dev/null || echo "")

    if [ -n "$keyvaults" ]; then
      while IFS= read -r kv_name; do
        if [ -n "$kv_name" ]; then
          echo "Deleting Key Vault: $kv_name"
          # Delete private endpoints first
          delete_private_endpoints "$kv_name" "Microsoft.KeyVault/vaults"
          # Delete the Key Vault (soft delete)
          az keyvault delete \
            --name "$kv_name" \
            --resource-group "$projectResourceGroup" \
            2>&1 || echo "  Warning: Failed to delete Key Vault $kv_name"
        fi
      done <<< "$keyvaults"
      echo "✓ Key Vaults deleted (soft-deleted, use purge later if needed)"
    else
      echo "No Key Vaults found"
    fi
  fi
  
  # Step 4a: Delete AI Search Private Endpoints (aisearchprj*)
  echo ""
  echo "=== Step 4a: Deleting AI Search Private Endpoints (aisearchprj*) ==="
  aisearch_pends=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'aisearchprj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$aisearch_pends" ]; then
    while IFS= read -r pend_name; do
      if [ -n "$pend_name" ]; then
        echo "Deleting AI Search private endpoint: $pend_name"
        az network private-endpoint delete \
          --resource-group "$projectResourceGroup" \
          --name "$pend_name" \
          2>&1 || echo "  Warning: Failed to delete $pend_name"
      fi
    done <<< "$aisearch_pends"
    echo "✓ AI Search private endpoints deleted"
  else
    echo "No AI Search private endpoints found with prefix aisearchprj"
  fi
  
  # Delete AI Search NICs
  aisearch_nics=$(az network nic list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'aisearchprj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$aisearch_nics" ]; then
    while IFS= read -r nic_name; do
      if [ -n "$nic_name" ]; then
        echo "Deleting AI Search NIC: $nic_name"
        az network nic delete \
          --resource-group "$projectResourceGroup" \
          --name "$nic_name" \
          2>&1 || echo "  Warning: Failed to delete $nic_name"
      fi
    done <<< "$aisearch_nics"
    echo "✓ AI Search NICs deleted"
  fi
  
  # Step 4b: Delete AI Hub Private Endpoints (p-aihub-prj*)
  echo ""
  echo "=== Step 4b: Deleting AI Hub Private Endpoints (p-aihub-prj*) ==="
  aihub_pends=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'p-aihub-prj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$aihub_pends" ]; then
    while IFS= read -r pend_name; do
      if [ -n "$pend_name" ]; then
        echo "Deleting AI Hub private endpoint: $pend_name"
        az network private-endpoint delete \
          --resource-group "$projectResourceGroup" \
          --name "$pend_name" \
          2>&1 || echo "  Warning: Failed to delete $pend_name"
      fi
    done <<< "$aihub_pends"
    echo "✓ AI Hub private endpoints deleted"
  else
    echo "No AI Hub private endpoints found with prefix p-aihub-prj"
  fi
  
  # Delete AI Hub NICs
  aihub_nics=$(az network nic list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'p-aihub-prj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$aihub_nics" ]; then
    while IFS= read -r nic_name; do
      if [ -n "$nic_name" ]; then
        echo "Deleting AI Hub NIC: $nic_name"
        az network nic delete \
          --resource-group "$projectResourceGroup" \
          --name "$nic_name" \
          2>&1 || echo "  Warning: Failed to delete $nic_name"
      fi
    done <<< "$aihub_nics"
    echo "✓ AI Hub NICs deleted"
  fi
  
  # Step 4c: Delete User Assigned Managed Identities (mi-prj* and mi-aca-prj*)
  echo ""
  echo "=== Step 4c: Deleting User Assigned Managed Identities (mi-prj*, mi-aca-prj*) ==="
  uamis=$(az identity list \
    --resource-group "$projectResourceGroup" \
    --query "[?starts_with(name, 'mi-prj') || starts_with(name, 'mi-aca-prj')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$uamis" ]; then
    subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
    while IFS= read -r uami_name; do
      if [ -n "$uami_name" ]; then
        echo "Deleting User Assigned Managed Identity: $uami_name"

        # Pre-step: remove any Federated Identity Credentials on the UAMI.
        # A UAMI with attached FICs returns 'Bad Request' from az identity delete.
        fic_names=$(az identity federated-credential list \
          --identity-name "$uami_name" \
          --resource-group "$projectResourceGroup" \
          --query "[].name" -o tsv 2>/dev/null | tr -d '\r' || echo "")
        if [ -n "$fic_names" ]; then
          while IFS= read -r fic_name; do
            if [ -n "$fic_name" ]; then
              echo "  Removing federated credential: $fic_name"
              az identity federated-credential delete \
                --identity-name "$uami_name" \
                --resource-group "$projectResourceGroup" \
                --name "$fic_name" \
                --yes 2>&1 || echo "    Warning: failed to delete FIC $fic_name"
            fi
          done <<< "$fic_names"
        fi

        # Primary delete
        if az identity delete \
          --resource-group "$projectResourceGroup" \
          --name "$uami_name" 2>&1; then
          echo "  ✓ Deleted: $uami_name"
        else
          # REST API fallback (uses 2023-01-31 GA API)
          echo "  Primary delete failed for $uami_name — attempting REST fallback"
          rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${uami_name}?api-version=2023-01-31"
          if az rest --method DELETE --url "$rest_url" 2>&1; then
            echo "  ✓ REST delete succeeded: $uami_name"
          else
            echo "  ⚠️  Warning: Failed to delete $uami_name (likely still referenced by an Azure resource — check role assignments, ACA env, or AKS workload identity)"
          fi
        fi
      fi
    done <<< "$uamis"
    echo "✓ User Assigned Managed Identities deletion completed"
  else
    echo "No User Assigned Managed Identities found with prefix mi-prj or mi-aca-prj"
  fi
  
  # Step 5: Delete All Remaining Private Endpoints
  echo ""
  echo "=== Step 5: Deleting All Remaining Private Endpoints (with force delete) ==="
  pend_deletion_failures=0
  all_pends=$(az network private-endpoint list \
    --resource-group "$projectResourceGroup" \
    --query "[].name" \
    -o tsv 2>/dev/null | tr -d '\r' || echo "")

  # When deleteKeyvaultAlso=false, build a list of Key Vault private endpoints to PRESERVE
  # (and capture their NIC names so the Step 5a NIC sweep also skips them).
  kv_pends_to_preserve=""
  kv_nics_to_preserve=""
  if [ "$deleteKeyvaultAlso" != "true" ]; then
    kv_names_preserve=$(az keyvault list \
      --resource-group "$projectResourceGroup" \
      --query "[].name" \
      -o tsv 2>/dev/null || echo "")
    if [ -n "$kv_names_preserve" ]; then
      while IFS= read -r _kv_name; do
        if [ -n "$_kv_name" ]; then
          # Match the same naming patterns as delete_private_endpoints()
          _kv_pends=$(az network private-endpoint list \
            --resource-group "$projectResourceGroup" \
            --query "[?(name == '${_kv_name}' || starts_with(name, '${_kv_name}-pend') || starts_with(name, 'p-${_kv_name}') || starts_with(name, 'pend-${_kv_name}') || contains(name, '-${_kv_name}-') || contains(name, '-${_kv_name}'))].name" \
            -o tsv 2>/dev/null | tr -d '\r' || echo "")
          if [ -n "$_kv_pends" ]; then
            kv_pends_to_preserve="${kv_pends_to_preserve}${_kv_pends}"$'\n'
            # Capture NIC names attached to those PEs (PE NIC name pattern: <pend>.nic.<guid>)
            while IFS= read -r _kv_pend; do
              if [ -n "$_kv_pend" ]; then
                _kv_pe_nics=$(az network private-endpoint show \
                  --resource-group "$projectResourceGroup" \
                  --name "$_kv_pend" \
                  --query "networkInterfaces[].id" \
                  -o tsv 2>/dev/null | awk -F'/' '{print $NF}' | tr -d '\r' || echo "")
                if [ -n "$_kv_pe_nics" ]; then
                  kv_nics_to_preserve="${kv_nics_to_preserve}${_kv_pe_nics}"$'\n'
                fi
              fi
            done <<< "$_kv_pends"
          fi
        fi
      done <<< "$kv_names_preserve"
    fi
    if [ -n "$kv_pends_to_preserve" ]; then
      echo "⏭  Preserving Key Vault private endpoints (deleteKeyvaultAlso=false):"
      echo "$kv_pends_to_preserve" | sed '/^$/d' | sed 's/^/    - /'
    fi
    if [ -n "$kv_nics_to_preserve" ]; then
      echo "⏭  Preserving Key Vault NICs (deleteKeyvaultAlso=false):"
      echo "$kv_nics_to_preserve" | sed '/^$/d' | sed 's/^/    - /'
    fi
  fi

  if [ -n "$all_pends" ]; then
    subscriptionId=$(az account show --query id -o tsv | tr -d '\r')
    while IFS= read -r pend_name; do
      if [ -n "$pend_name" ]; then
        # Skip KV-related private endpoints when preserving the Key Vault
        if [ -n "$kv_pends_to_preserve" ] && echo "$kv_pends_to_preserve" | grep -Fxq "$pend_name"; then
          echo "⏭  Skipping Key Vault private endpoint: $pend_name (deleteKeyvaultAlso=false)"
          continue
        fi
        echo "Deleting private endpoint: $pend_name"
        # Try normal delete first (without --no-wait to detect failures)
        delete_output=$(az network private-endpoint delete \
          --resource-group "$projectResourceGroup" \
          --name "$pend_name" \
          2>&1)
        delete_exit_code=$?
        
        # If normal delete fails, try REST API force delete
        if [ $delete_exit_code -ne 0 ]; then
          echo "  Normal delete failed, attempting force delete via REST API"
          rest_url="https://management.azure.com/subscriptions/${subscriptionId}/resourceGroups/${projectResourceGroup}/providers/Microsoft.Network/privateEndpoints/${pend_name}?api-version=2023-11-01"
          az rest --method DELETE --url "$rest_url" 2>&1
          if [ $? -ne 0 ]; then
            echo "  ❌ Force delete also failed for $pend_name"
            pend_deletion_failures=$((pend_deletion_failures + 1))
          else
            echo "  ✓ Force delete succeeded for $pend_name"
          fi
        else
          echo "  ✓ Deleted successfully"
        fi
      fi
    done <<< "$all_pends"
    
    if [ $pend_deletion_failures -gt 0 ]; then
      echo "⚠️  Private endpoint deletion completed with $pend_deletion_failures failures"
    else
      echo "✓ All private endpoints deleted successfully"
    fi
  else
    echo "No private endpoints found"
  fi
  
  # Step 5a: Delete All Remaining NICs
  echo ""
  echo "=== Step 5a: Deleting All Remaining Network Interfaces ==="
  nic_deletion_failures=0
  all_nics=$(az network nic list \
    --resource-group "$projectResourceGroup" \
    --query "[].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$all_nics" ]; then
    while IFS= read -r nic_name; do
      if [ -n "$nic_name" ]; then
        # Skip NICs attached to Key Vault private endpoints when preserving the Key Vault
        if [ -n "$kv_nics_to_preserve" ] && echo "$kv_nics_to_preserve" | grep -Fxq "$nic_name"; then
          echo "⏭  Skipping Key Vault NIC: $nic_name (deleteKeyvaultAlso=false)"
          continue
        fi
        echo "Deleting NIC: $nic_name"
        az network nic delete \
          --resource-group "$projectResourceGroup" \
          --name "$nic_name" \
          2>&1
        if [ $? -ne 0 ]; then
          echo "  ❌ Failed to delete $nic_name"
          nic_deletion_failures=$((nic_deletion_failures + 1))
        fi
      fi
    done <<< "$all_nics"
    
    if [ $nic_deletion_failures -gt 0 ]; then
      echo "⚠️  NIC deletion completed with $nic_deletion_failures failures"
    else
      echo "✓ All NICs deleted successfully"
    fi
  else
    echo "No NICs found"
  fi
  
  # Check if we should proceed with subnet/NSG deletion
  total_network_failures=$((pend_deletion_failures + nic_deletion_failures))
  if [ $total_network_failures -gt 0 ]; then
    echo ""
    echo "⚠️⚠️⚠️ WARNING: $total_network_failures private endpoint/NIC deletion failures detected"
    echo "⚠️  Skipping subnet and NSG deletion to avoid errors"
    echo "⚠️  Private endpoints and NICs must be fully deleted before subnets/NSGs can be removed"
    echo "⚠️  Please resolve the failures and run the deletion again"
    skip_subnet_nsg_deletion=true
  else
    skip_subnet_nsg_deletion=false
  fi
  
  # Step 6: Wait for resources to fully release
  echo ""
  echo "=== Step 6: Waiting 5 minutes for resources to release ==="
  echo "Waiting for Azure to process deletions and release subnet dependencies..."
  sleep 300
  echo "✓ Wait completed"
  
  # Step 7: Build common resource group name (with vnetResourceGroupBase)
  # Precedence:
  #   1) BYO override: commonResourceGroup_param (full RG name) — used as-is when non-empty
  #   2) Built name: ${commonRGNamePrefix}${vnetResourceGroupBase}-${locationSuffix}-${envName}${aifactorySuffixRG}
  # Defensive fallback: if vnetResourceGroupBase is empty (e.g. missing from env block), default to "esml-common"
  # to avoid building a malformed name like "ingka-aif--swe-dev-002".
  if [ -z "${vnetResourceGroupBase:-}" ]; then
    echo "⚠️  vnetResourceGroupBase is empty — defaulting to 'esml-common' (check that the 06b env block exports it)"
    vnetResourceGroupBase="esml-common"
  fi
  if [ -n "${commonResourceGroup_param:-}" ]; then
    commonResourceGroup="$commonResourceGroup_param"
    echo "Using BYO commonResourceGroup_param: $commonResourceGroup"
  else
    commonResourceGroup="${commonRGNamePrefix}${vnetResourceGroupBase}-${locationSuffix}-${envName}${aifactorySuffixRG}"
  fi
  echo ""
  echo "=== Step 7: Deleting Subnets in Common Resource Group ==="
  
  if [ "$skip_subnet_nsg_deletion" = "true" ]; then
    echo "⚠️  SKIPPED: Private endpoint/NIC deletion failures detected"
    echo "⚠️  Subnets cannot be deleted until all private endpoints and NICs are removed"
  else
    echo "Common resource group: $commonResourceGroup"
    echo "Looking for subnets containing: $projectName"
    echo "Debug - commonRGNamePrefix: $commonRGNamePrefix"
    echo "Debug - vnetResourceGroupBase: $vnetResourceGroupBase"
    echo "Debug - locationSuffix: $locationSuffix"
    echo "Debug - envName: $envName"
    echo "Debug - aifactorySuffixRG: $aifactorySuffixRG"
  
    # Find all VNets in common resource group
    vnets=$(az network vnet list \
      --resource-group "$commonResourceGroup" \
      --query "[].name" \
      -o tsv 2>/dev/null || echo "")
    
    if [ -n "$vnets" ]; then
      # ---------------------------------------------------------------
      # PASS 1: Detach NSG / RouteTable / Delegations / ServiceEndpoints from
      # every project subnet across all VNets. This MUST happen before we try
      # to delete the NSGs (Step 8), otherwise NSG delete returns
      # InUseNetworkSecurityGroupCannotBeDeleted. We do this even if the
      # subnet itself ultimately can't be removed (e.g. Service Association
      # Links from ACA / Foundry managed env — those only clear when the
      # parent caphost / account fully deletes).
      # ---------------------------------------------------------------
      echo ""
      echo "--- Pass 1/2: Detaching NSG / RouteTable / Delegations from project subnets ---"
      # Helper: wait until the VNet is back at provisioningState=Succeeded
      # before issuing the next PATCH/DELETE. Azure serializes operations on
      # a single VNet — concurrent calls return "Bad Request". We poll up to
      # ~2 min per op, which is plenty for subnet PATCH/DELETE in practice.
      _wait_vnet_idle() {
        local _rg="$1" _vn="$2" _label="$3"
        local _max=24 _i=0 _state=""
        while [ "$_i" -lt "$_max" ]; do
          _state=$(az network vnet show -g "$_rg" -n "$_vn" --query "provisioningState" -o tsv 2>/dev/null || echo "")
          if [ "$_state" = "Succeeded" ] || [ -z "$_state" ]; then
            return 0
          fi
          # Updating / Deleting / Failed — back off
          sleep 5
          _i=$((_i + 1))
        done
        echo "    (waited $((_max * 5))s for vnet idle after $_label; last state=$_state — proceeding anyway)"
        return 0
      }

      while IFS= read -r vnet_name; do
        [ -z "$vnet_name" ] && continue
        subnets=$(az network vnet subnet list \
          --resource-group "$commonResourceGroup" \
          --vnet-name "$vnet_name" \
          --query "[?contains(name, '$projectName')].name" \
          -o tsv 2>/dev/null || echo "")
        [ -z "$subnets" ] && continue
        # Make sure VNet is idle before we start the per-subnet PATCH cascade
        _wait_vnet_idle "$commonResourceGroup" "$vnet_name" "pre-detach"
        while IFS= read -r subnet_name; do
          [ -z "$subnet_name" ] && continue
          echo "  Detaching from subnet: $vnet_name/$subnet_name"
          # IMPORTANT: do EACH detach as a separate PATCH. A bundled multi-remove
          # rolls the WHOLE patch back if any one attribute is locked (e.g. by a
          # surviving private endpoint or service-association-link), leaving the
          # NSG still bound and breaking Step 8. Per-attribute PATCH = best-effort
          # independent operations. After EACH PATCH we wait for the VNet to
          # leave the Updating state, otherwise the next call returns 400.
          for _attr in networkSecurityGroup routeTable delegations serviceEndpoints; do
            az network vnet subnet update \
              --resource-group "$commonResourceGroup" \
              --vnet-name "$vnet_name" \
              --name "$subnet_name" \
              --remove "$_attr" \
              >/dev/null 2>&1 || echo "    (could not remove $_attr — may already be absent or locked by SAL/PE)"
            _wait_vnet_idle "$commonResourceGroup" "$vnet_name" "remove-$_attr"
          done

          # Verify NSG is actually gone (this is the one that blocks Step 8)
          remaining_nsg=$(az network vnet subnet show \
            --resource-group "$commonResourceGroup" \
            --vnet-name "$vnet_name" \
            --name "$subnet_name" \
            --query "networkSecurityGroup.id" -o tsv 2>/dev/null || echo "")
          if [ -n "$remaining_nsg" ] && [ "$remaining_nsg" != "None" ]; then
            echo "    ⚠️  NSG still attached to $subnet_name: $remaining_nsg"
            echo "    Diagnosis — remaining holders on $subnet_name:"
            az network vnet subnet show \
              --resource-group "$commonResourceGroup" \
              --vnet-name "$vnet_name" \
              --name "$subnet_name" \
              --query "{pe:privateEndpoints, ipconfigs:ipConfigurations[].name, sal:serviceAssociationLinks[].name, deleg:delegations[].serviceName}" \
              -o json 2>/dev/null || true
          else
            echo "    ✓ NSG cleared on $subnet_name"
          fi
        done <<< "$subnets"
      done <<< "$vnets"

      # ---------------------------------------------------------------
      # PASS 2: Try to delete subnets. Subnets with surviving Service
      # Association Links (SALs) from ACA / Foundry managed environments
      # cannot be force-removed — those only release when 06a/06c finish
      # tearing down the parent service. We log and continue.
      # IMPORTANT: subnets are deleted strictly SEQUENTIALLY per VNet, with
      # an idle-wait between each, because a VNet can only process one
      # write operation at a time (concurrent calls return Bad Request).
      # ---------------------------------------------------------------
      echo ""
      echo "--- Pass 2/2: Deleting project subnets (sequential per VNet) ---"
      while IFS= read -r vnet_name; do
        if [ -n "$vnet_name" ]; then
          echo "Checking VNet: $vnet_name"
          subnets=$(az network vnet subnet list \
            --resource-group "$commonResourceGroup" \
            --vnet-name "$vnet_name" \
            --query "[?contains(name, '$projectName')].name" \
            -o tsv 2>/dev/null || echo "")
          
          if [ -n "$subnets" ]; then
            # Wait for VNet idle before starting the sequential delete loop
            _wait_vnet_idle "$commonResourceGroup" "$vnet_name" "pre-subnet-delete"
            while IFS= read -r subnet_name; do
              if [ -n "$subnet_name" ]; then
                echo "  Deleting subnet: $subnet_name from VNet: $vnet_name"
                if ! az network vnet subnet delete \
                  --resource-group "$commonResourceGroup" \
                  --vnet-name "$vnet_name" \
                  --name "$subnet_name" 2>&1; then
                  echo "    ⚠️  Warning: Failed to delete subnet $subnet_name"
                  # Diagnose what's still holding it
                  echo "    Diagnosis — remaining references on $subnet_name:"
                  az network vnet subnet show \
                    --resource-group "$commonResourceGroup" \
                    --vnet-name "$vnet_name" \
                    --name "$subnet_name" \
                    --query "{pe:privateEndpoints, ipconfigs:ipConfigurations, sal:serviceAssociationLinks, deleg:delegations, nsg:networkSecurityGroup.id, rt:routeTable.id}" \
                    -o json 2>/dev/null || true
                else
                  echo "    ✓ Subnet $subnet_name deleted"
                fi
                # CRITICAL: wait for the VNet to settle before deleting the next
                # subnet. Without this, the next call hits the still-Updating
                # VNet and returns "Bad Request".
                _wait_vnet_idle "$commonResourceGroup" "$vnet_name" "delete-$subnet_name"
              fi
            done <<< "$subnets"
          fi
        fi
      done <<< "$vnets"
      echo "✓ Subnets deletion pass complete"
    else
      echo "No VNets found in common resource group"
    fi
  fi
  
  # Step 8: Delete Network Security Groups
  echo ""
  echo "=== Step 8: Deleting Network Security Groups in Common Resource Group ==="
  
  if [ "$skip_subnet_nsg_deletion" = "true" ]; then
    echo "⚠️  SKIPPED: Private endpoint/NIC deletion failures detected"
    echo "⚠️  NSGs cannot be deleted until all private endpoints and NICs are removed"
  else
    echo "Looking for NSGs containing: $projectName"
    # NOTE: Pass 1 of Step 7 already detached every project subnet from its NSG.
    # If a subnet delete failed (e.g. surviving SAL), the NSG is still free
    # because we explicitly --removed networkSecurityGroup from the subnet.
  
  nsgs=$(az network nsg list \
    --resource-group "$commonResourceGroup" \
    --query "[?contains(name, '$projectName')].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$nsgs" ]; then
    while IFS= read -r nsg_name; do
      if [ -n "$nsg_name" ]; then
        echo "Deleting NSG: $nsg_name"

        # -------------------------------------------------------------
        # SELF-HEAL: re-detach any subnet still referencing this NSG.
        # Pass 1 (Step 7) does this preemptively, but a silently-failed
        # PATCH there leaves the NSG bound and the delete here returns
        # InUseNetworkSecurityGroupCannotBeDeleted. So we look at
        # nsg.subnets right now and explicitly clear each reference
        # before the delete attempt.
        # -------------------------------------------------------------
        still_attached=$(az network nsg show \
          --resource-group "$commonResourceGroup" \
          --name "$nsg_name" \
          --query "subnets[].id" -o tsv 2>/dev/null | tr -d '\r' || echo "")
        if [ -n "$still_attached" ]; then
          echo "  Self-heal: $nsg_name is still attached to subnets — detaching now"
          while IFS= read -r subnet_id; do
            [ -z "$subnet_id" ] && continue
            # subnet_id form: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}
            s_rg=$(echo "$subnet_id"   | awk -F/ '{print $5}')
            s_vnet=$(echo "$subnet_id" | awk -F/ '{print $9}')
            s_sub=$(echo "$subnet_id"  | awk -F/ '{print $11}')
            echo "    Detaching NSG from $s_rg / $s_vnet / $s_sub"
            # Wait for VNet idle before PATCH
            for _i in 1 2 3 4 5 6 7 8 9 10 11 12; do
              _st=$(az network vnet show -g "$s_rg" -n "$s_vnet" --query provisioningState -o tsv 2>/dev/null || echo "")
              [ "$_st" = "Succeeded" ] || [ -z "$_st" ] && break
              sleep 5
            done
            if az network vnet subnet update \
                 --resource-group "$s_rg" \
                 --vnet-name "$s_vnet" \
                 --name "$s_sub" \
                 --remove networkSecurityGroup 2>&1; then
              echo "    ✓ Detach PATCH accepted"
            else
              echo "    ⚠️  Detach PATCH failed — subnet may be locked by SAL/PE"
            fi
            # Wait for VNet idle after PATCH so the NSG delete that follows
            # doesn't race on a still-Updating VNet
            for _i in 1 2 3 4 5 6 7 8 9 10 11 12; do
              _st=$(az network vnet show -g "$s_rg" -n "$s_vnet" --query provisioningState -o tsv 2>/dev/null || echo "")
              [ "$_st" = "Succeeded" ] || [ -z "$_st" ] && break
              sleep 5
            done
          done <<< "$still_attached"
        fi

        # -------------------------------------------------------------
        # Delete NSG with retry. "Bad Request" here is almost always a
        # transient race (parent VNet still in Updating state after the
        # detach PATCH above). Retry with backoff before giving up.
        # -------------------------------------------------------------
        nsg_deleted=false
        for attempt in 1 2 3 4; do
          if az network nsg delete \
            --resource-group "$commonResourceGroup" \
            --name "$nsg_name" 2>&1; then
            echo "  ✓ NSG $nsg_name deleted (attempt $attempt)"
            nsg_deleted=true
            break
          fi
          # Check whether it's already gone (NotFound on the show)
          if ! az network nsg show -g "$commonResourceGroup" -n "$nsg_name" >/dev/null 2>&1; then
            echo "  ✓ NSG $nsg_name no longer present (attempt $attempt)"
            nsg_deleted=true
            break
          fi
          echo "  Attempt $attempt failed for $nsg_name — backing off 20s and retrying"
          sleep 20
        done

        if [ "$nsg_deleted" != "true" ]; then
          echo "  ⚠️  Warning: Failed to delete NSG $nsg_name after retries"
          # Diagnose remaining references (subnet/NIC associations)
          echo "  Diagnosis — subnets/NICs still referencing $nsg_name:"
          az network nsg show \
            --resource-group "$commonResourceGroup" \
            --name "$nsg_name" \
            --query "{subnets:subnets[].id, nics:networkInterfaces[].id}" \
            -o json 2>/dev/null || true
        fi
      fi
    done <<< "$nsgs"
    echo "✓ Network Security Groups deletion pass complete"
  else
    echo "No NSGs found containing $projectName"
  fi
  fi
  
  echo ""
  echo "🔥 ======================================== 🔥"
  if [ "$deleteAllForProject" = "true" ]; then
    echo "💀 COMPLETE DELETE MODE FINISHED (resources deleted)"
    echo "💀 Proceeding to ULTRA mode: deleting project resource group"
  else
    echo "🔥 COMPLETE DELETE MODE COMPLETED"
  fi
  echo "🔥 ======================================== 🔥"
else
  echo "ℹ️  deleteAllServicesForProject not enabled - skipping complete cleanup"
fi

# =============================================================================
# ULTRA DELETE MODE: deleteAllForProject=true
# Delete the entire project resource group (after all resources cleaned up)
# =============================================================================

if [ "$deleteAllForProject" = "true" ]; then
  echo ""
  echo "💀💀💀 ======================================== 💀💀💀"
  echo "💀 ULTRA MODE: Deleting Project Resource Group"
  echo "💀💀💀 ======================================== 💀💀💀"
  echo ""
  echo "Target resource group: $projectResourceGroup"
  echo ""
  echo "⚠️  WARNING: This will delete the ENTIRE resource group!"
  echo "⚠️  All resources within will be permanently removed."
  echo ""
  
  # Check if resource group exists
  rg_exists=$(az group exists --name "$projectResourceGroup" 2>/dev/null || echo "false")
  
  if [ "$rg_exists" = "true" ]; then
    echo "Deleting resource group: $projectResourceGroup"
    
    if az group delete \
      --name "$projectResourceGroup" \
      --subscription "$dev_test_prod_sub_id" \
      --yes \
      --no-wait 2>&1; then
      echo "✓ Resource group deletion initiated (running in background)"
      echo "ℹ️  Resource group deletion may take several minutes to complete"
      echo "ℹ️  Check Azure Portal or run 'az group show --name $projectResourceGroup' to verify"
    else
      echo "❌ Failed to initiate resource group deletion"
      echo "⚠️  You may need to manually delete the resource group from Azure Portal"
    fi
  else
    echo "ℹ️  Resource group does not exist or already deleted: $projectResourceGroup"
  fi
  
  echo ""
  echo "💀 ======================================== 💀"
  echo "💀 ULTRA DELETE MODE COMPLETED"
  echo "💀 Resource group deletion initiated"
  echo "💀 ======================================== 💀"
fi

echo ""
echo "=== Deletion task completed ==="
