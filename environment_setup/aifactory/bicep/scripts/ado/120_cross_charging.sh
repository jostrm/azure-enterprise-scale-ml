#!/bin/bash

# ============================================================================
# AI Factory Cross-Charging Report Generator
# Main orchestrator script that calls individual components
# 
# This script coordinates the following operations:
# 1. Discover AI Factory resource groups
# 2. Collect cost and forecasting data
# 3. Upload reports to data lake
# 4. Send email notifications to project owners
# ============================================================================

set -e  # Exit on any error

echo "=== AI Factory Cross-Charging Report Generator ==="
echo "Starting at: $(date)"
echo "Environment: ${ENVIRONMENT:-unknown}"
echo "Subscription: ${SUBSCRIPTION_ID:-unknown}"

# Validate required environment variables
REQUIRED_VARS=(
    "AIFACTORY_PREFIX_RG"
    "LOCATION_SUFFIX"
    "AIFACTORY_SUFFIX_RG"
    "PROJECT_PREFIX"
    "PROJECT_SUFFIX"
    "ENVIRONMENT"
    "SUBSCRIPTION_ID"
    "COMMON_LAKE_PREFIX"
    "LAKE_CONTAINER_NAME"
)

echo "Validating environment variables..."
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
    echo "✓ $var = ${!var}"
done

# Set script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Script directory: $SCRIPT_DIR"

# Generate timestamp for this run
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
export TIMESTAMP

echo ""
echo "=== Step 1: Discovering AI Factory Resource Groups ==="
bash "$SCRIPT_DIR/121_discover_resource_groups.sh"

echo ""
echo "=== Step 2: Collecting Cost Data ==="
bash "$SCRIPT_DIR/122_collect_cost_data.sh"

echo ""
echo "=== Step 3: Uploading to Data Lake ==="
bash "$SCRIPT_DIR/123_upload_to_datalake.sh"

echo ""
echo "=== Step 4: Sending Email Notifications ==="
bash "$SCRIPT_DIR/124_send_email_notifications.sh"

echo ""
echo "=== Cross-Charging Report Generation Completed ==="
echo "Completed at: $(date)"
