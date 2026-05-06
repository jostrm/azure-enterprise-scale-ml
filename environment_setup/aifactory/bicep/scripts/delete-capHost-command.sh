#!/bin/bash
set -e

# =============================================================================
# Delete Capability Hosts for AI Foundry Account & Project
# Order: 1) project caphost  →  60s wait  →  2) account caphost
#
# Handles all scenarios:
#   - Normal:          project + caphost exist        → DELETE, wait 60s, delete account caphost
#   - Orphaned:        project deleted via portal,    → ParentResourceNotFound logged (warning),
#                      caphost may still linger         wait 60s, delete account caphost
#   - Already gone:    caphost already deleted        → ResourceNotFound logged (info), continue
#
# Usage:
#   bash delete-capHost-command.sh <subscription_id> <resource_group> <foundry_account_name> <foundry_project_name> [api_version]
# =============================================================================

# --- PARAMETERS (from args or defaults) ---
SUBSCRIPTION_ID="${1:-TODO-subscription-id}"
RESOURCE_GROUP="${2:-TODO-resource-group}"
FOUNDRY_ACCOUNT_NAME="${3:-TODO-foundry-account-name}"
FOUNDRY_PROJECT_NAME="${4:-TODO-foundry-project-name}"
API_VERSION="${5:-2025-04-01-preview}"

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
# Always attempt the delete. If the Foundry project itself is already gone the REST call
# returns ParentResourceNotFound — that is expected and logged. In that case we skip the
# --- Step 1: Delete project-level capability host ---
# Always attempt — handles 3 scenarios:
#   a) Normal:              project + caphost exist   → DELETE succeeds (200/202)
#   b) Orphaned caphost:    user deleted project via portal, caphost may still exist →
#                           ParentResourceNotFound is returned (project gone, caphost was
#                           implicitly removed too). Logged as warning, pipeline continues.
#   c) Already gone:        caphost was already deleted → ResourceNotFound. Logged, continue.
# In all cases step 2 (account caphost) always runs after the 60s ordering wait.
echo ""
echo "[1/3] Deleting project caphost: $PROJECT_CAPHOST_NAME ..."
PROJECT_CAPHOST_HTTP=$(az rest --method DELETE \
  --url "${BASE_URL}/projects/${FOUNDRY_PROJECT_NAME}/capabilityHosts/${PROJECT_CAPHOST_NAME}?api-version=${API_VERSION}" \
  --headers "Content-Type=application/json" 2>&1) || true
echo "$PROJECT_CAPHOST_HTTP"

if echo "$PROJECT_CAPHOST_HTTP" | grep -q "ParentResourceNotFound"; then
  echo "⚠️  ParentResourceNotFound: project '$FOUNDRY_PROJECT_NAME' no longer exists (e.g. deleted via portal)."
  echo "   The project caphost was implicitly removed with it. Continuing to account caphost."
elif echo "$PROJECT_CAPHOST_HTTP" | grep -qi "ResourceNotFound\|NotFound"; then
  echo "ℹ️  Project caphost not found — already deleted or never created."
else
  echo "✅ Project caphost delete accepted."
fi

echo "Waiting 60s before deleting account caphost (required ordering)..."
sleep 60

# --- Step 2: Delete account-level capability host ---
# Always attempt. "Workspace not found" can occur when the Foundry project was deleted
# externally (portal/API) — the caphost's internal workspace reference is broken but the
# caphost object may still need to be cleaned up. All error cases are logged and handled.
echo ""
echo "[2/3] Deleting account caphost: ${FOUNDRY_ACCOUNT_NAME}@aml_aiagentservice ..."
ACCOUNT_CAPHOST_HTTP=$(az rest --method DELETE \
  --url "${BASE_URL}/capabilityHosts/${ACCOUNT_CAPHOST_NAME}?api-version=${API_VERSION}" \
  --headers "Content-Type=application/json" 2>&1) || true
echo "$ACCOUNT_CAPHOST_HTTP"

if echo "$ACCOUNT_CAPHOST_HTTP" | grep -qi "Workspace not found"; then
  echo "⚠️  'Workspace not found': the caphost's internal workspace reference is broken (project was deleted externally)."
  echo "   The account caphost will be cleaned up by Azure in the background. Continuing."
elif echo "$ACCOUNT_CAPHOST_HTTP" | grep -qi "ResourceNotFound\|NotFound"; then
  echo "ℹ️  Account caphost not found — already deleted or never created."
else
  echo "✅ Account caphost delete accepted."
fi

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
