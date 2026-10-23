#!/bin/bash
# Entra administrator script: create (or complete) the AI Factory MCP API app registration ("MCP SP")
# for one or more AI Factory projects and store its IDs in the seeding Key Vault.
#
# The MCP SP is the MCP's identity as a resource: callers (the Foundry project identity, the AI Gateway,
# classic APIM) request tokens for it, and it exposes the app role AiFactory.Mcp.Read. It has NO secret:
# the MCP only validates incoming tokens. Per project NNN it writes these seeding Key Vault secrets:
#   esml-projectNNN-mcp-app-id   client ID (appId); the pipelines read it via aifactory_mcp_AppID_seeding_kv_name
#   esml-projectNNN-mcp-sp-oid   object ID of its service principal (for Graph role assignments)
# Re-running is safe: an existing app is completed (role, api://<appId>, v2 tokens, service principal).
#
# Usage: edit the variables below (or export them), then run:  ./29b-create-mcp-api-sp-for-projects.sh [--yes]
# Requires: Azure CLI, an Entra role that may create app registrations, and Key Vault secret set rights.

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 1) EDIT once (or export before running) ###################
SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-<your-seeding-keyvault-subscription-id>}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-<your-seeding-keyvault-name>}"
TENANT_ID="${TENANT_ID:-<your-tenant-id>}"
MCP_SP_NAME_TEMPLATE="${MCP_SP_NAME_TEMPLATE:-esml-project[XXX]-mcp-api}" # [XXX] becomes the project number

# 2) EDIT per batch: one project, or a range such as 001..010 ###################
PROJECT_NUMBER_FROM="${PROJECT_NUMBER_FROM:-001}"
PROJECT_NUMBER_TO="${PROJECT_NUMBER_TO:-}" # empty = only PROJECT_NUMBER_FROM
SKIP_LOGIN="${SKIP_LOGIN:-false}"          # true when already signed in to the right tenant

AIF_KV_SECRET_EXPIRES="${AIF_KV_SECRET_EXPIRES:-$(date -u -d '+1 year' '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -v+1y '+%Y-%m-%dT%H:%M:%SZ')}" # Key Vault secrets expire one year from now (UTC)

##################### DO NOT CHANGE ANYTHING BELOW #####################
APP_ROLE_VALUE="AiFactory.Mcp.Read"
KV_APP_ID_TEMPLATE="esml-projectXXX-mcp-app-id"
KV_SP_OID_TEMPLATE="esml-projectXXX-mcp-sp-oid"
WORK_DIR="$(mktemp -d)" || { echo -e "${RED}mktemp failed; set TMPDIR${NC}"; exit 1; }
trap 'rm -rf "$WORK_DIR"' EXIT

# The first interpreter that actually runs (Windows can have a non-working python3 store alias).
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" > /dev/null && "$candidate" -c "" 2> /dev/null; then PYTHON="$candidate"; break; fi
done
[ -n "$PYTHON" ] || { echo -e "${RED}Python 3 is required${NC}"; exit 1; }

new_guid() {
    "$PYTHON" -c "import uuid; print(uuid.uuid4())"
}

project_numbers() {
    local from=$((10#$PROJECT_NUMBER_FROM)) to=$((10#${PROJECT_NUMBER_TO:-$PROJECT_NUMBER_FROM}))
    if (( from < 1 || to < from || to > 999 )); then
        echo -e "${RED}Invalid project range ${PROJECT_NUMBER_FROM}..${PROJECT_NUMBER_TO}${NC}" >&2
        return 1
    fi
    for ((n = from; n <= to; n++)); do printf '%03d\n' "$n"; done
}

# Completes an app registration: keeps existing app roles and adds AiFactory.Mcp.Read when missing,
# sets the audience api://<appId> and v2 access tokens. One Graph PATCH, body passed as a file.
complete_app() {
    local app_id="$1" object_id roles
    object_id=$(az ad app show --id "$app_id" --query id -o tsv) || return 1
    roles=$(az ad app show --id "$app_id" --query appRoles -o json) || return 1
    ROLES_JSON="$roles" APP_ID="$app_id" ROLE_VALUE="$APP_ROLE_VALUE" ROLE_ID="$(new_guid)"         "$PYTHON" - > "$WORK_DIR/patch.json" <<'EOF' || return 1
import json, os
roles = json.loads(os.environ["ROLES_JSON"] or "[]")
if not any(role.get("value") == os.environ["ROLE_VALUE"] for role in roles):
    roles.append({"id": os.environ["ROLE_ID"], "value": os.environ["ROLE_VALUE"], "isEnabled": True,
                  "allowedMemberTypes": ["Application"], "displayName": os.environ["ROLE_VALUE"],
                  "description": "Call the read-only Enterprise Scale AI Factory MCP tools."})
print(json.dumps({"appRoles": roles, "identifierUris": ["api://" + os.environ["APP_ID"]],
                  "api": {"requestedAccessTokenVersion": 2}}))
EOF
    az rest --method PATCH --uri "https://graph.microsoft.com/v1.0/applications/$object_id"         --headers "Content-Type=application/json" --body "@$WORK_DIR/patch.json" > /dev/null
}

provision_project() {
    local nnn="$1" name app_id sp_oid
    name="${MCP_SP_NAME_TEMPLATE//\[XXX\]/$nnn}"
    echo -e "${YELLOW}Project ${nnn}: MCP SP ${GREEN}${name}${NC}"
    app_id=$(az ad app list --display-name "$name" --query "[].appId" -o tsv)
    if [ "$(printf '%s\n' "$app_id" | grep -c .)" -gt 1 ]; then
        echo -e "${RED}More than one app registration is named ${name}; resolve that first.${NC}"
        return 1
    fi
    if [ -z "$app_id" ]; then
        app_id=$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg --query appId -o tsv) || return 1
        echo -e "${GREEN}Created app registration ${app_id}${NC}"
    else
        echo -e "${YELLOW}App registration exists (${app_id}); completing it${NC}"
    fi
    complete_app "$app_id" || { echo -e "${RED}Failed to set the app role, api://${app_id} and v2 tokens${NC}"; return 1; }
    sp_oid=$(az ad sp list --filter "appId eq '$app_id'" --query "[].id" -o tsv)
    if [ -z "$sp_oid" ]; then
        sp_oid=$(az ad sp create --id "$app_id" --query id -o tsv) || return 1
    fi
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "${KV_APP_ID_TEMPLATE/XXX/$nnn}" --value "$app_id" --expires "$AIF_KV_SECRET_EXPIRES" > /dev/null || return 1
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "${KV_SP_OID_TEMPLATE/XXX/$nnn}" --value "$sp_oid" --expires "$AIF_KV_SECRET_EXPIRES" > /dev/null || return 1
    echo -e "${GREEN}Stored ${KV_APP_ID_TEMPLATE/XXX/$nnn}=${app_id} and ${KV_SP_OID_TEMPLATE/XXX/$nnn} in ${KEY_VAULT_NAME}${NC}"
}

PROJECTS=$(project_numbers) || exit 1
echo -e "${YELLOW}MCP SPs for projects:${NC} $(echo $PROJECTS)"
echo -e "${YELLOW}Seeding Key Vault:${NC} ${KEY_VAULT_NAME} (subscription ${SUBSCRIPTION_ID})"
if [ "$1" != "--yes" ]; then
    read -p "Continue (Y/n)? " choice
    if [[ "$choice" == "n" || "$choice" == "N" ]]; then
        echo "Exiting script."
        exit 1
    fi
fi

if [ "$SKIP_LOGIN" != "true" ]; then
    az login --tenant "$TENANT_ID" > /dev/null || { echo -e "${RED}Failed to login to Azure${NC}"; exit 1; }
fi
az account set --subscription "$SUBSCRIPTION_ID" || exit 1

for nnn in $PROJECTS; do
    provision_project "$nnn" || { echo -e "${RED}Project ${nnn} failed; the earlier projects are done.${NC}"; exit 1; }
done
echo -e "${GREEN}Done. Next: the MCP step prints the az deployment command that assigns ${APP_ROLE_VALUE} to each caller.${NC}"
