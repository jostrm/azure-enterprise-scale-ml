"""Offline persona policy and scope validation contracts."""

from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path
import sys
from uuid import uuid5

import pytest


BICEP = Path(__file__).resolve().parents[3] / "aifactory" / "bicep"
sys.path.insert(0, str(BICEP))
from personas import policy


TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
COMMON = f"/subscriptions/{SUB}/resourceGroups/common-rg"
PROJECT = f"/subscriptions/{SUB}/resourceGroups/project-rg"


def manifest():
    return {
        "schema": policy.SCHEMA, "tenant_id": TENANT, "factory": "factory", "scaleset": "001",
        "environment": "dev", "project": "project001",
        "seeding": {"subscription_id": SUB, "resource_group": "seed-rg", "vault_name": "factory-seed"},
        "common_scope": COMMON, "project_scope": PROJECT,
        "log_analytics_resource_id": COMMON + "/providers/Microsoft.OperationalInsights/workspaces/logs",
        "security_review": {name: True for name in policy.SECURITY_REVIEWS},
    }


def allows(role, operation, *, data=False):
    allowed, excluded = ("dataActions", "notDataActions") if data else ("actions", "notActions")
    return any(
        any(fnmatchcase(operation.lower(), item.lower()) for item in permission[allowed])
        and not any(fnmatchcase(operation.lower(), item.lower()) for item in permission[excluded])
        for definition in policy.role_definitions(role, PROJECT)
        for permission in definition["properties"]["permissions"]
    )


def test_nine_stable_personas_and_core_scope():
    assert policy.PERSONA_IDS == (
        "persona200", "persona201", "persona210", "persona211", "persona212", "persona213",
        "persona214", "persona215", "persona216",
    )
    assert all(policy.CATALOG["personas"][name]["scope"] == "core" for name in policy.CORE_PERSONAS)
    assert [key for key, value in policy.CATALOG["personas"].items() if value.get("lake")] == ["persona213"]


def test_manifest_normalization_does_not_modify_input():
    raw = manifest()
    original = deepcopy(raw)
    result = policy.validate_manifest(raw)
    assert raw == original
    assert result["project_scope"] == PROJECT.lower()
    assert result["connectivity_scopes"] == []
    assert result["adoption"]["execute_migration"] is False


@pytest.mark.parametrize("changes", [
    {"schema": "v1"}, {"tenant_id": "invalid"}, {"factory": "../evil"}, {"environment": "qa"},
    {"factory": "has--delimiter"}, {"scaleset": "trailing-"}, {"factory": "x" * 25},
    {"scaleset": ""}, {"project": "project1"}, {"groups": {"persona999": TENANT}},
    {"groups": {"persona210": TENANT, "persona211": TENANT}},
    {"common_scope": PROJECT}, {"project_scope": f"/subscriptions/{SUB}"},
    {"project_scope": PROJECT + "/providers/Microsoft.Web/sites/app"},
    {"project_scope": PROJECT + "/"}, {"project_scope": PROJECT + "/../other"},
    {"log_analytics_resource_id": PROJECT + "/providers/Microsoft.OperationalInsights/workspaces/logs"},
    {"log_analytics_resource_id": COMMON + "/providers/Microsoft.KeyVault/vaults/vault"},
    {"connectivity_scopes": [PROJECT]},
    {"adoption": {"execute_migration": "true"}},
    {"adoption": {"trusted_lake_admin_principal_ids": ["bad-id"]}},
    {"adoption": {"trusted_lake_admin_principal_ids": [TENANT, TENANT]}},
    {"adoption": {"approved_acl_principal_ids": [TENANT]}},
    {"security_review": {"workload_identities_and_secrets_reviewed": "yes"}},
])
def test_manifest_rejects_ambiguous_or_wrong_schema(changes):
    with pytest.raises(ValueError):
        policy.validate_manifest({**manifest(), **changes})


@pytest.mark.parametrize("value", [
    COMMON, COMMON + "/providers/Microsoft.Storage/storageAccounts/lake",
    COMMON + "/providers/Microsoft.Network/virtualNetworks/shared",
    f"/subscriptions/{TENANT}/resourceGroups/common-rg/providers/Microsoft.Network/virtualNetworks/vnet",
    COMMON + "/providers/Microsoft.Network/virtualNetworks",
])
def test_network_scopes_reject_wrong_provider_subscription_or_shape(value):
    with pytest.raises(ValueError):
        policy.validate_manifest({**manifest(), "project_network_scopes": [value]})


def test_explicit_network_scopes_and_project_dashboards():
    network = COMMON + "/providers/Microsoft.Network/virtualNetworks/vnet/subnets/project001"
    dashboard = PROJECT + "/providers/Microsoft.Portal/dashboards/overview"
    result = policy.validate_manifest({
        **manifest(), "project_network_scopes": [network], "dashboard_resource_ids": [dashboard],
    })
    assert result["project_network_scopes"] == [network.lower()]
    with pytest.raises(ValueError, match="Dashboard"):
        policy.validate_manifest({**manifest(), "dashboard_resource_ids": [
            COMMON + "/providers/Microsoft.Portal/dashboards/shared"]})


def test_dedicated_project_vnet_and_explicit_common_nsg_remain_supported():
    project_vnet = PROJECT + "/providers/Microsoft.Network/virtualNetworks/dedicated"
    common_nsg = COMMON + "/providers/Microsoft.Network/networkSecurityGroups/project001"
    result = policy.validate_manifest({**manifest(), "project_network_scopes": [project_vnet, common_nsg]})
    assert result["project_network_scopes"] == [project_vnet.lower(), common_nsg.lower()]


def test_adoption_requires_exact_owned_assignment_ids():
    for identity in ("role-guid", f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments/{TENANT}",
                     PROJECT + "/providers/Microsoft.Authorization/roleAssignments/not-guid",
                     COMMON + "/providers/Microsoft.KeyVault/vaults/other"):
        with pytest.raises(ValueError):
            policy.validate_manifest({**manifest(), "adoption": {"approved_role_assignment_ids": [identity]}})


def test_acl_adoption_requires_explicit_legacy_principal_review():
    value = policy.validate_manifest({**manifest(), "adoption": {
        "legacy_principal_ids": [TENANT], "approved_acl_principal_ids": [TENANT],
    }})
    assert value["adoption"]["approved_acl_principal_ids"] == [TENANT]


def test_lake_binding_and_configuration():
    lake = {"tenant_id": TENANT, "subscription_id": SUB, "resource_group": "common-rg",
            "storage_account": "factorylake", "filesystem": "lake3",
            "project": "project001", "environment": "dev", "legacy_layout": False}
    assert policy.validate_manifest({**manifest(), "lake": lake})["lake"] == lake
    for field, value in (("subscription_id", TENANT), ("tenant_id", SUB), ("project", "project002"),
                         ("environment", "prod"), ("resource_group", "other-rg"), ("legacy_layout", "false")):
        with pytest.raises(ValueError):
            policy.validate_manifest({**manifest(), "lake": {**lake, field: value}})


@pytest.mark.parametrize("role", ["member", "admin", "frontend", "ai", "database"])
@pytest.mark.parametrize("operation", [
    "Microsoft.Authorization/roleAssignments/write",
    "Microsoft.Authorization/roleAssignments/delete",
    "Microsoft.Authorization/elevateAccess/action",
    "Microsoft.Authorization/roleDefinitions/write",
    "Microsoft.Storage/storageAccounts/write",
    "Microsoft.Storage/storageAccounts/delete",
    "Microsoft.Storage/storageAccounts/listKeys/action",
    "Microsoft.Storage/storageAccounts/listAccountSas/action",
    "Microsoft.Storage/storageAccounts/listServiceSas/action",
    "Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action",
    "Microsoft.Storage/storageAccounts/localUsers/write",
    "Microsoft.KeyVault/vaults/write",
    "Microsoft.KeyVault/vaults/accessPolicies/write",
    "Microsoft.KeyVault/vaults/delete",
    "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
    "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/write",
    "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments/write",
    "Microsoft.DBforPostgreSQL/flexibleServers/administrators/write",
    "Microsoft.Sql/servers/administrators/write",
    "Microsoft.Cache/redis/accessPolicyAssignments/write",
    "Microsoft.Resources/deploymentStacks/write",
    "Microsoft.Resources/subscriptions/resourceGroups/delete",
    "Microsoft.MachineLearningServices/workspaces/listStorageAccountKeys/action",
    "Microsoft.MachineLearningServices/workspaces/listKeys/action",
    "Microsoft.MachineLearningServices/workspaces/connections/listsecrets/action",
    "Microsoft.MachineLearningServices/workspaces/datastores/listsecrets/action",
    "Microsoft.MachineLearningServices/workspaces/metadata/listsecrets/action",
    "Microsoft.CognitiveServices/accounts/connections/listsecrets/action",
    "Microsoft.CognitiveServices/accounts/projects/connections/listsecrets/action",
])
def test_ordinary_roles_do_not_allow_access_elevation_or_storage_mutation(role, operation):
    assert not allows(role, operation)


def test_secret_baseline_has_exact_four_actions_not_officer():
    prefix = "Microsoft.KeyVault/vaults/secrets/"
    expected = {prefix + operation for operation in ("getSecret/action", "readMetadata/action", "setSecret/action", "delete")}
    assert set(policy.role_permissions("vault-secrets")[0]["dataActions"]) == expected
    for operation in ("purge/action", "backup/action", "restore/action", "recover/action"):
        assert not allows("vault-secrets", prefix + operation, data=True)
    assert "b86a8fe4-44ce-4948-aee5-eccb2c155cd7" not in policy.CATALOG["builtins"].values()


def test_custom_role_operations_obey_azure_single_wildcard_limit():
    for key in policy.CATALOG["roles"]:
        for permission in policy.role_permissions(key):
            for operations in permission.values():
                assert all(operation.count("*") <= 1 for operation in operations), key


@pytest.mark.parametrize("key", policy.CATALOG["roles"])
def test_role_components_preserve_exact_logical_blocks_and_primary_identity(key):
    definitions = policy.role_definitions(key, PROJECT)
    assert definitions == policy.role_definitions(key, PROJECT.upper())
    assert definitions != policy.role_definitions(key, COMMON)
    assert all(len(item["properties"]["permissions"]) == 1 for item in definitions)
    assert [item["properties"]["permissions"][0] for item in definitions] == policy.role_permissions(key)
    assert len({item["id"] for item in definitions}) == len(definitions)
    primary_name = str(uuid5(policy.NAMESPACE, f"role|{PROJECT.lower()}|{key}"))
    assert definitions[0]["name"] == primary_name
    assert definitions[0]["properties"]["roleName"] == f"AI Factory {key} {primary_name}"
    for item in definitions:
        assert item["properties"]["assignableScopes"] == [PROJECT.lower()]
        assert item["properties"]["description"] == f"{policy.SCHEMA} owned role {item['key']} {PROJECT.lower()}"
    definitions[0]["properties"]["permissions"][0]["actions"].append("mutated")
    assert "mutated" not in policy.role_permissions(key)[0]["actions"]


@pytest.mark.parametrize("key", ["member", "admin", "frontend", "ai", "database"])
def test_compiled_management_bundle_restores_metadata_without_new_secret_or_data_grants(key):
    for operation in ("Microsoft.Storage/storageAccounts/read", "Microsoft.KeyVault/vaults/read",
                      "Microsoft.Authorization/roleAssignments/read",
                      "Microsoft.ManagedIdentity/userAssignedIdentities/read"):
        assert allows(key, operation)
    metadata = policy.role_definitions(key, PROJECT)[1]["properties"]["permissions"][0]
    assert metadata == {
        "actions": ["*/read"], "notActions": ["Microsoft.OperationalInsights/workspaces/sharedKeys/read"],
        "dataActions": [], "notDataActions": [],
    }
    for operation in ("Microsoft.KeyVault/vaults/secrets/getSecret/action",
                      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                      "Microsoft.CognitiveServices/accounts/AIServices/connections/listSecrets/action"):
        assert not allows(key, operation, data=True)


@pytest.mark.parametrize("operation", [
    "Microsoft.DBforPostgreSQL/flexibleServers/administrators/write",
    "Microsoft.Sql/servers/administrators/write",
    "Microsoft.Sql/managedInstances/administrators/write",
    "Microsoft.Sql/servers/azureADOnlyAuthentications/write",
    "Microsoft.Sql/managedInstances/azureADOnlyAuthentications/write",
])
def test_concrete_administrator_exclusions_retain_protection(operation):
    for role in ("member", "admin", "frontend", "ai", "database"):
        assert not allows(role, operation)


@pytest.mark.parametrize("role", ["frontend", "ai", "database"])
def test_specialists_can_deploy_permitted_resources_without_full_deployment_admin(role):
    for operation in ("read", "write", "validate/action", "whatIf/action", "cancel/action", "operations/read"):
        assert allows(role, "Microsoft.Resources/deployments/" + operation)
    assert not allows(role, "Microsoft.Resources/deployments/delete")
    assert not allows(role, "Microsoft.Resources/deployments/exportTemplate/action")
    assert allows("admin", "Microsoft.Resources/deployments/delete")
    assert not allows(role, "Microsoft.Resources/deploymentStacks/write")


def test_shared_service_data_catalog_restores_baseline_without_credential_builtins():
    assert policy.CATALOG["builtins"]["search-index-data-contributor"] == "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
    assert {key for key, value in policy.CATALOG["personas"].items() if value.get("service_data")} == {
        "persona200", "persona201", "persona210", "persona211", "persona213",
    }
    assert {value["service_data"] for value in policy.CATALOG["personas"].values() if value.get("service_data")} == {"project-ai"}
    assert {role["role"] for role in policy.CATALOG["service_data_bundles"]["project-ai"]} == {
        "search-index-data-contributor", "cognitive-inference", "foundry-agent-author",
    }
    assert not {
        "a97b65f3-24c7-4388-baec-2e87135dc908",  # Cognitive Services User includes keys and all Cognitive data.
        "64702f94-c441-49e6-a78b-ef80e0188fee",  # Azure AI Developer includes broad workspace actions.
        "f6c7c914-8db3-469d-8ca1-694a8f32e121",  # AzureML Data Scientist includes datastore secret actions.
        "53ca6127-db72-4b80-b1b0-d745d6d5456d",  # Foundry User / Azure AI User includes all Cognitive data.
        "eadc314b-1a2d-4efa-be10-5d325db5065e",  # Foundry Project Manager includes RBAC management.
    } & set(policy.CATALOG["builtins"].values())
    assert all("*" not in action for action in policy.role_permissions("cognitive-inference")[0]["dataActions"])


@pytest.mark.parametrize("operation", [
    "Microsoft.CognitiveServices/accounts/AIServices/agents/read",
    "Microsoft.CognitiveServices/accounts/AIServices/agents/write",
    "Microsoft.CognitiveServices/accounts/AIServices/agents/delete",
    "Microsoft.CognitiveServices/accounts/AIServices/connections/read",
    "Microsoft.CognitiveServices/accounts/AIServices/responses/write",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/write",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/threads/write",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/threads/messages/write",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/threads/runs/write",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/threads/runs/steps/read",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/vector_stores/files/write",
    "Microsoft.CognitiveServices/accounts/OpenAI/files/write",
])
def test_foundry_authors_can_manage_normal_agent_lifecycle_and_artifacts(operation):
    assert allows("foundry-agent-author", operation, data=True)


@pytest.mark.parametrize("operation", [
    "Microsoft.CognitiveServices/accounts/AIServices/connections/listSecrets/action",
    "Microsoft.CognitiveServices/accounts/AIServices/managedAgentIdentityBlueprints/write",
    "Microsoft.CognitiveServices/accounts/AIServices/managedAgentIdentityBlueprints/delete",
    "Microsoft.CognitiveServices/accounts/AIServices/managed-deployments/action",
    "Microsoft.CognitiveServices/accounts/AIServices/fine_tuning/write",
    "Microsoft.CognitiveServices/accounts/AIServices/evaluations/write",
    "Microsoft.CognitiveServices/accounts/projects/connections/listsecrets/action",
    "Microsoft.Authorization/roleAssignments/write",
    "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
    "Microsoft.Storage/storageAccounts/listKeys/action",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
    "Microsoft.Storage/storageAccounts/fileServices/fileshares/files/write",
    "Microsoft.Storage/storageAccounts/queueServices/queues/messages/write",
])
def test_foundry_author_data_role_excludes_credentials_access_management_and_source_storage(operation):
    assert not allows("foundry-agent-author", operation)
    assert not allows("foundry-agent-author", operation, data=True)


@pytest.mark.parametrize("operation", [
    "Microsoft.CognitiveServices/accounts/OpenAI/deployments/chat/completions/action",
    "Microsoft.CognitiveServices/accounts/OpenAI/responses/write",
    "Microsoft.CognitiveServices/accounts/MaaS/chat/completions/action",
    "Microsoft.CognitiveServices/accounts/ContentSafety/text:analyze/action",
    "Microsoft.CognitiveServices/accounts/FormRecognizer/analysis/analyze/document/action",
    "Microsoft.CognitiveServices/accounts/TextAnalytics/analyze/action",
    "Microsoft.CognitiveServices/accounts/ComputerVision/analyze/action",
    "Microsoft.CognitiveServices/accounts/SpeechServices/unified-speech/frontend/action",
])
def test_cognitive_inference_grants_specific_service_data_operations(operation):
    assert allows("cognitive-inference", operation, data=True)


@pytest.mark.parametrize("operation", [
    "Microsoft.Storage/storageAccounts/listKeys/action",
    "Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action",
    "Microsoft.CognitiveServices/accounts/listkeys/action",
    "Microsoft.CognitiveServices/accounts/AIServices/connections/listSecrets/action",
    "Microsoft.CognitiveServices/accounts/projects/connections/listsecrets/action",
    "Microsoft.CognitiveServices/accounts/OpenAI/assistants/write",
    "Microsoft.CognitiveServices/accounts/AIServices/agents/write",
    "Microsoft.Authorization/roleAssignments/write",
])
def test_cognitive_data_role_never_adds_credentials_storage_or_agent_administration(operation):
    assert not allows("cognitive-inference", operation)
    assert not allows("cognitive-inference", operation, data=True)


def test_aml_jobs_and_endpoint_scoring_do_not_require_broad_data_scientist_role():
    assert allows("ai", "Microsoft.MachineLearningServices/workspaces/jobs/write")
    assert allows("ai", "Microsoft.MachineLearningServices/workspaces/onlineEndpoints/score/action")
    assert not allows("ai", "Microsoft.MachineLearningServices/workspaces/datastores/listsecrets/action")
    assert not allows("ai", "Microsoft.MachineLearningServices/workspaces/listStorageAccountKeys/action")


def test_member_preserves_deployment_monitoring_and_admin_adds_only_resource_locks():
    assert allows("member", "Microsoft.Compute/virtualMachines/write")
    assert allows("member", "Microsoft.Web/sites/write")
    for operation in ("Microsoft.Resources/deployments/write", "Microsoft.Insights/metricAlerts/write"):
        assert allows("admin", operation)
        assert allows("member", operation)
    for operation in ("Microsoft.Authorization/locks/write", "Microsoft.Authorization/locks/delete"):
        assert allows("admin", operation)
        assert not allows("member", operation)
    assert policy.CATALOG["roles"]["admin"]["additional_actions"] == [
        "Microsoft.Authorization/locks/read", "Microsoft.Authorization/locks/write",
        "Microsoft.Authorization/locks/delete",
    ]


def test_developer_provider_boundaries():
    for role, allowed, denied in (
        ("frontend", "Microsoft.Web/sites/write", "Microsoft.Compute/virtualMachines/write"),
        ("ai", "Microsoft.CognitiveServices/accounts/write", "Microsoft.Web/sites/write"),
        ("database", "Microsoft.Sql/servers/write", "Microsoft.Search/searchServices/write"),
    ):
        assert allows(role, allowed)
        assert not allows(role, denied)
    assert policy.CATALOG["roles"]["database"]["providers"] == [
        "Microsoft.DocumentDB", "Microsoft.Sql", "Microsoft.DBforPostgreSQL", "Microsoft.Cache", "Microsoft.Elastic",
    ]


def test_workspace_observer_has_no_shared_keys_secret_values_or_write():
    assert allows("workspace-observer", "Microsoft.OperationalInsights/workspaces/query/MyTable/read")
    for operation in ("Microsoft.OperationalInsights/workspaces/sharedKeys/action",
                      "Microsoft.OperationalInsights/workspaces/sharedKeys/read",
                      "Microsoft.OperationalInsights/workspaces/write",
                      "Microsoft.KeyVault/vaults/secrets/getSecret/action"):
        assert not allows("workspace-observer", operation)
        assert not allows("workspace-observer", operation, data=True)


def test_identifiers_are_stable_and_scoped():
    role = policy.role_definitions("member", PROJECT)[0]
    assert policy.role_definitions("member", PROJECT.upper())[0] == role
    assert role != policy.role_definitions("member", COMMON)[0]
    first = policy.assignment("persona210", TENANT, role["id"], PROJECT)
    assert first == policy.assignment("persona210", TENANT.upper(), role["id"].upper(), PROJECT.upper())
    assert first["id"] != policy.assignment("persona210", SUB, role["id"], PROJECT)["id"]
    assert "owned assignment" in first["description"]


def test_extension_resource_type_uses_the_last_provider_namespace():
    identity = PROJECT + "/providers/Microsoft.Web/sites/app/providers/Microsoft.Insights/diagnosticSettings/logs"
    assert policy.resource_type(identity) == "microsoft.insights/diagnosticsettings"
    assert policy.rg_scope(identity) == PROJECT.lower()


@pytest.mark.parametrize("scope", ["all", "", "subscription", None])
def test_unknown_persona_scope_rejected(scope):
    with pytest.raises(ValueError, match="scope"):
        policy.validate_scope(scope)
