#!/bin/bash

# ============================================================================
# AI Factory Data Lake Upload
# 
# This script uploads the cross-charging CSV report to the AI Factory
# common data lake storage account for archival and analysis purposes.
# ============================================================================

set -e

echo "=== AI Factory Data Lake Upload ==="

# Set up file paths
FINAL_CSV_FILE="/tmp/aifactory_cross_charging_${TIMESTAMP}.csv"

# Verify input file exists
if [ ! -f "$FINAL_CSV_FILE" ]; then
    echo "ERROR: Final CSV file not found: $FINAL_CSV_FILE"
    echo "Make sure the cost data collection script ran successfully."
    exit 1
fi

echo "Preparing to upload cost report to data lake..."
echo "Source file: $FINAL_CSV_FILE"

# Calculate the unique identifier for AI Factory environment
# This mimics the logic from CmnAIfactoryNaming.bicep
echo "Calculating AI Factory naming components..."

# Build common resource group name to get unique identifier
COMMON_RG_NAME="${AIFACTORY_PREFIX_RG}esml-common-${LOCATION_SUFFIX}-${ENVIRONMENT}${AIFACTORY_SUFFIX_RG}"
echo "Common resource group name: $COMMON_RG_NAME"

# Get the unique identifier from the common resource group
echo "Retrieving unique identifier from common resource group..."
UNIQUE_IN_AIFENV=""

# Try to get the resource group and extract unique string
rg_exists=$(az group exists --name "$COMMON_RG_NAME" --output tsv 2>/dev/null || echo "false")

if [ "$rg_exists" = "true" ]; then
    echo "✓ Common resource group found: $COMMON_RG_NAME"
    
    # Get resource group ID and calculate unique string (similar to Bicep logic)
    rg_id=$(az group show --name "$COMMON_RG_NAME" --query "id" --output tsv)
    
    # Calculate a deterministic 5-character hash from the resource group ID
    # This mimics the uniqueString() function in Bicep
    UNIQUE_IN_AIFENV=$(echo -n "$rg_id" | sha256sum | cut -c1-5)
    echo "Calculated unique identifier: $UNIQUE_IN_AIFENV"
else
    echo "WARNING: Common resource group not found: $COMMON_RG_NAME"
    echo "Using fallback unique identifier..."
    UNIQUE_IN_AIFENV="00000"
fi

# Build data lake storage account name using naming convention
# Pattern: ${commonLakeNamePrefixMax8chars}${uniqueInAIFenv}esml${replace(commonResourceSuffix,'-','')}${env}
COMMON_RESOURCE_SUFFIX_NO_DASH=$(echo "$AIFACTORY_SUFFIX_RG" | tr -d '-')
DATALAKE_NAME="${COMMON_LAKE_PREFIX}${UNIQUE_IN_AIFENV}esml${COMMON_RESOURCE_SUFFIX_NO_DASH}${ENVIRONMENT}"

echo "Data lake storage account name: $DATALAKE_NAME"
echo "Container name: $LAKE_CONTAINER_NAME"

# Check if storage account exists
echo "Verifying data lake storage account exists..."
storage_exists=$(az storage account show --name "$DATALAKE_NAME" --resource-group "$COMMON_RG_NAME" --query "name" --output tsv 2>/dev/null || echo "")

if [ -z "$storage_exists" ]; then
    echo "ERROR: Data lake storage account not found: $DATALAKE_NAME"
    echo "Please verify the naming convention and ensure the common infrastructure is deployed."
    exit 1
fi

echo "✓ Data lake storage account found: $DATALAKE_NAME"

# Get storage account key
echo "Retrieving storage account access key..."
STORAGE_KEY=$(az storage account keys list \
    --resource-group "$COMMON_RG_NAME" \
    --account-name "$DATALAKE_NAME" \
    --query "[0].value" \
    --output tsv)

if [ -z "$STORAGE_KEY" ]; then
    echo "ERROR: Failed to retrieve storage account key"
    exit 1
fi

echo "✓ Storage account key retrieved"

# Check if container exists
echo "Verifying container exists: $LAKE_CONTAINER_NAME"
container_exists=$(az storage container exists \
    --name "$LAKE_CONTAINER_NAME" \
    --account-name "$DATALAKE_NAME" \
    --account-key "$STORAGE_KEY" \
    --query "exists" \
    --output tsv 2>/dev/null || echo "false")

if [ "$container_exists" != "true" ]; then
    echo "ERROR: Container not found: $LAKE_CONTAINER_NAME"
    echo "Available containers:"
    az storage container list \
        --account-name "$DATALAKE_NAME" \
        --account-key "$STORAGE_KEY" \
        --query "[].name" \
        --output table
    exit 1
fi

echo "✓ Container verified: $LAKE_CONTAINER_NAME"

# Create target directory structure in data lake
REPORT_DATE=$(date +"%Y/%m/%d")
TARGET_DIRECTORY="aifactory-governance/cross-charging/${ENVIRONMENT}/${REPORT_DATE}"
TARGET_FILENAME="aifactory_cross_charging_${ENVIRONMENT}_${TIMESTAMP}.csv"
TARGET_BLOB_PATH="${TARGET_DIRECTORY}/${TARGET_FILENAME}"

echo "Target path in data lake: $TARGET_BLOB_PATH"

# Upload the CSV file to data lake
echo "Uploading cross-charging report to data lake..."
az storage blob upload \
    --file "$FINAL_CSV_FILE" \
    --name "$TARGET_BLOB_PATH" \
    --container-name "$LAKE_CONTAINER_NAME" \
    --account-name "$DATALAKE_NAME" \
    --account-key "$STORAGE_KEY" \
    --overwrite

if [ $? -eq 0 ]; then
    echo "✓ Successfully uploaded cross-charging report to data lake"
    echo "  Storage Account: $DATALAKE_NAME"
    echo "  Container: $LAKE_CONTAINER_NAME"
    echo "  Blob Path: $TARGET_BLOB_PATH"
    echo "  File Size: $(wc -c < "$FINAL_CSV_FILE") bytes"
    echo "  Records: $(($(wc -l < "$FINAL_CSV_FILE") - 1))"
else
    echo "ERROR: Failed to upload file to data lake"
    exit 1
fi

# Also create a "latest" copy for easy access
LATEST_BLOB_PATH="aifactory-governance/cross-charging/${ENVIRONMENT}/latest/aifactory_cross_charging_${ENVIRONMENT}_latest.csv"

echo "Creating latest copy for easy access..."
az storage blob upload \
    --file "$FINAL_CSV_FILE" \
    --name "$LATEST_BLOB_PATH" \
    --container-name "$LAKE_CONTAINER_NAME" \
    --account-name "$DATALAKE_NAME" \
    --account-key "$STORAGE_KEY" \
    --overwrite

if [ $? -eq 0 ]; then
    echo "✓ Latest copy created: $LATEST_BLOB_PATH"
else
    echo "WARNING: Failed to create latest copy (non-critical)"
fi

# Set metadata on the blob
echo "Setting blob metadata..."
az storage blob metadata update \
    --name "$TARGET_BLOB_PATH" \
    --container-name "$LAKE_CONTAINER_NAME" \
    --account-name "$DATALAKE_NAME" \
    --account-key "$STORAGE_KEY" \
    --metadata \
        "environment=$ENVIRONMENT" \
        "timestamp=$TIMESTAMP" \
        "generated_by=aifactory_cross_charging_pipeline" \
        "report_date=$(date +"%Y-%m-%d")" \
        "subscription_id=$SUBSCRIPTION_ID" \
    2>/dev/null || echo "WARNING: Failed to set metadata (non-critical)"

echo ""
echo "=== Data Lake Upload Summary ==="
echo "✓ Cross-charging report successfully uploaded to AI Factory data lake"
echo "📁 Archive location: $TARGET_BLOB_PATH"
echo "📁 Latest location: $LATEST_BLOB_PATH"
echo "🔗 Access via: https://${DATALAKE_NAME}.dfs.core.windows.net/${LAKE_CONTAINER_NAME}/${TARGET_BLOB_PATH}"

# Export variables for email script
export DATALAKE_NAME
export TARGET_BLOB_PATH
export LATEST_BLOB_PATH