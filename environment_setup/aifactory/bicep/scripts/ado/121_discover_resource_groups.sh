#!/bin/bash

# ============================================================================
# AI Factory Resource Group Discovery
# 
# This script discovers all AI Factory resource groups in the current subscription
# that match the naming convention and extracts relevant information.
# ============================================================================

set -e

echo "=== AI Factory Resource Group Discovery ==="

# Set up temporary files
TEMP_FILE="/tmp/resource_groups_${TIMESTAMP}.txt"
RG_INFO_FILE="/tmp/rg_info_${TIMESTAMP}.csv"

echo "Discovering resource groups in subscription: $SUBSCRIPTION_ID"

# Set the subscription context
az account set --subscription "$SUBSCRIPTION_ID"

# Build the resource group name pattern based on naming convention
# Pattern: {admin_aifactoryPrefixRG}{projectPrefix}project{XXX}-{locationSuffix}-{environment}{aifactorySuffixRG}{projectSuffix}
# Example: mrvel-1-esml-project001-eus2-dev-001-rg

echo "Searching for resource groups with naming pattern..."
echo "Prefix: ${AIFACTORY_PREFIX_RG}"
echo "Project Prefix: ${PROJECT_PREFIX}"
echo "Location Suffix: ${LOCATION_SUFFIX}"
echo "Environment: ${ENVIRONMENT}"
echo "AI Factory Suffix: ${AIFACTORY_SUFFIX_RG}"
echo "Project Suffix: ${PROJECT_SUFFIX}"

# Get all resource groups and filter by naming convention
az group list --query "[].{name:name, location:location, tags:tags}" --output json > "$TEMP_FILE"

# Initialize CSV header
echo "resource_group,location,cost_center,project_owner,environment,project_number" > "$RG_INFO_FILE"

# Process each resource group
echo "Processing discovered resource groups..."
processed_count=0

# Read the JSON and process each resource group
jq -r '.[] | @base64' "$TEMP_FILE" | while read -r encoded_rg; do
    # Decode the base64 encoded JSON
    rg_data=$(echo "$encoded_rg" | base64 --decode)
    
    # Extract resource group name
    rg_name=$(echo "$rg_data" | jq -r '.name')
    
    # Check if resource group matches our naming convention
    # Pattern check: starts with aifactory prefix and contains project pattern
    if [[ "$rg_name" =~ ^${AIFACTORY_PREFIX_RG}.*project[0-9]+.*-${LOCATION_SUFFIX}-${ENVIRONMENT}.* ]]; then
        echo "✓ Found matching resource group: $rg_name"
        
        # Extract location
        location=$(echo "$rg_data" | jq -r '.location')
        
        # Extract tags
        tags=$(echo "$rg_data" | jq -r '.tags // {}')
        
        # Extract specific tag values
        cost_center=$(echo "$tags" | jq -r '.CostCenter // "Unknown"')
        project_owner=$(echo "$tags" | jq -r '."AIF-Project Owners" // "Unknown"')
        
        # Extract project number from resource group name
        # Pattern: project001 -> 001
        if [[ "$rg_name" =~ project([0-9]+) ]]; then
            project_number="${BASH_REMATCH[1]}"
        else
            project_number="Unknown"
        fi
        
        # Determine environment from resource group name (should match current environment)
        extracted_env="$ENVIRONMENT"
        
        echo "  - Location: $location"
        echo "  - Cost Center: $cost_center"
        echo "  - Project Owner: $project_owner"
        echo "  - Project Number: $project_number"
        echo "  - Environment: $extracted_env"
        
        # Add to CSV
        echo "\"$rg_name\",\"$location\",\"$cost_center\",\"$project_owner\",\"$extracted_env\",\"$project_number\"" >> "$RG_INFO_FILE"
        
        ((processed_count++))
    else
        echo "  Skipping non-matching resource group: $rg_name"
    fi
done

echo ""
echo "Resource group discovery completed!"
echo "Total matching resource groups found: $processed_count"
echo "Resource group information saved to: $RG_INFO_FILE"

# Display summary
if [ -f "$RG_INFO_FILE" ] && [ $processed_count -gt 0 ]; then
    echo ""
    echo "=== Summary of Discovered Resource Groups ==="
    echo "Resource Group Name | Project Number | Cost Center | Project Owner"
    echo "-------------------|----------------|-------------|---------------"
    
    # Skip header and display data
    tail -n +2 "$RG_INFO_FILE" | while IFS=',' read -r rg_name location cost_center project_owner environment project_number; do
        # Remove quotes
        rg_name=$(echo "$rg_name" | tr -d '"')
        project_number=$(echo "$project_number" | tr -d '"')
        cost_center=$(echo "$cost_center" | tr -d '"')
        project_owner=$(echo "$project_owner" | tr -d '"')
        
        printf "%-50s | %-14s | %-11s | %s\n" "$rg_name" "$project_number" "$cost_center" "$project_owner"
    done
    
    echo ""
    echo "Resource group information file: $RG_INFO_FILE"
else
    echo "WARNING: No matching resource groups found!"
    echo "Please verify the naming convention and environment variables."
fi

# Export file path for next script
export RG_INFO_FILE