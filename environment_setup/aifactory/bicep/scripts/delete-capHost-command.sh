#!/bin/bash
set -e

# =============================================================================
# Delete Capability Hosts for AI Foundry Account & Project
# Order: 1) project caphost, 2) account caphost
# =============================================================================

# --- PARAMETERS (edit these) ---
SUBSCRIPTION_ID="TODO-subscription-id"
RESOURCE_GROUP="TODO-resource-group"
FOUNDRY_ACCOUNT_NAME="TODO-foundry-account-name"
FOUNDRY_PROJECT_NAME="TODO-foundry-project-name"
API_VERSION="2026-01-15-preview"

# --- CALCULATED ---
PROJECT_CAPHOST_NAME="${FOUNDRY_ACCOUNT_NAME}caphost"
ACCOUNT_CAPHOST_NAME="${FOUNDRY_ACCOUNT_NAME}%40aml_aiagentservice"
BASE_URL="https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT_NAME}"

echo "=== Configuration ==="
echo "Subscription:    $SUBSCRIPTION_ID"
echo "Resource Group:  $RESOURCE_GROUP"
echo "Account:         $FOUNDRY_ACCOUNT_NAME"
echo "Project:         $FOUNDRY_PROJECT_NAME"
echo "Project Caphost: $PROJECT_CAPHOST_NAME"
echo "Account Caphost: ${FOUNDRY_ACCOUNT_NAME}@aml_aiagentservice"
echo "====================="

# --- Step 1: Delete project-level capability host ---
echo ""
echo "[1/3] Deleting project caphost: $PROJECT_CAPHOST_NAME ..."
az rest --method DELETE \
  --url "${BASE_URL}/projects/${FOUNDRY_PROJECT_NAME}/capabilityHosts/${PROJECT_CAPHOST_NAME}?api-version=${API_VERSION}" \
  --headers "Content-Type=application/json" -o json || true

echo "Project caphost delete initiated. Waiting 60s before deleting account caphost (required ordering)..."
sleep 60

# --- Step 2: Delete account-level capability host ---
echo ""
echo "[2/3] Deleting account caphost: ${FOUNDRY_ACCOUNT_NAME}@aml_aiagentservice ..."
az rest --method DELETE \
  --url "${BASE_URL}/capabilityHosts/${ACCOUNT_CAPHOST_NAME}?api-version=${API_VERSION}" \
  --headers "Content-Type=application/json" -o json || true

# --- Step 3: Verify deletion ---
echo ""
echo "[3/3] Checking account caphost provisioning state..."
STATE=$(az rest --method GET \
  --url "${BASE_URL}/capabilityHosts/${ACCOUNT_CAPHOST_NAME}?api-version=${API_VERSION}" \
  --query "properties.provisioningState" -o tsv 2>/dev/null || echo "NotFound")

echo "Account caphost state: $STATE"

if [ "$STATE" = "NotFound" ]; then
  echo "Both caphosts fully deleted."
else
  echo "Account caphost still in state: $STATE. Typically takes 2-5 min (up to 15 min)."
  echo "Re-run the GET check or wait before deleting the Foundry account to avoid 409 conflict."
fi
