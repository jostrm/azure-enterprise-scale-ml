"""Control-plane activation tests; no permissions or Azure resources are changed."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.activate_monitoring import ACTIONS, execute, plan


RUNTIME = {
    "subscription_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "resource_group": "rg", "workspace_name": "ml", "compute": "cpu",
    "aifactory": "factory", "project": "001", "environment_name": "dev",
}


def planned():
    responses = [
        {"tenantId": RUNTIME["tenant_id"]},
        {"identity": {"principal_id": "workspace"}},
        {"identity": {"principal_id": "compute"}, "provisioning_state": "Succeeded"},
        {"publicNetworkAccess": "Disabled"},
    ]
    with patch("scripts.activate_monitoring.azure_cli", side_effect=responses):
        return plan(RUNTIME, "storageexample", "ml-model-factory", "ml_model_factory")


def test_preview_is_explicit_dev_only_and_uses_least_privilege():
    result = planned()
    assert result["network_changes"] is False
    assert result["schedules_enabled"] is False
    assert result["role_definition"]["Actions"] == ACTIONS
    assert not any("*" in action or "delete" in action or "roleAssignments" in action for action in ACTIONS)
    assert len(result["assignments"]) == 3
    with patch("scripts.activate_monitoring.azure_cli") as cli, pytest.raises(ValueError, match="Dev pilot"):
        plan({**RUNTIME, "environment_name": "prod"}, "storageexample", "ml-model-factory", "data")
    cli.assert_not_called()


def test_creation_never_opens_storage_or_changes_default_datastores(tmp_path):
    commands = []
    datastore_definitions = []
    def cli(*args):
        commands.append(args)
        if args[:3] == ("role", "definition", "create"):
            return {"id": f"/subscriptions/{RUNTIME['subscription_id']}/providers/Microsoft.Authorization/roleDefinitions/server-assigned-id"}
        if args[:3] == ("ml", "datastore", "create"):
            datastore_definitions.append(json.loads(Path(args[args.index("--file") + 1]).read_text()))
        return [] if args[:3] in (("storage", "container-rm", "list"), ("role", "definition", "list"),
                                  ("role", "assignment", "list"), ("ml", "datastore", "list")) else {}
    with patch("scripts.activate_monitoring.azure_cli", side_effect=cli):
        result = execute(RUNTIME, planned(), tmp_path / "runtime.json")
    assert result["schedules_enabled"] is False
    create = next(args for args in commands if args[:3] == ("storage", "container-rm", "create"))
    assert create[create.index("--public-access") + 1] == "off"
    assert not any(args[:3] == ("storage", "account", "update") for args in commands)
    assert all("--assignee-object-id" in args for args in commands if args[:3] == ("role", "assignment", "create"))
    role_calls = [args for args in commands if args[:3] == ("role", "assignment", "create")]
    assert any("server-assigned-id" in args[args.index("--role") + 1] for args in role_calls)
    assert datastore_definitions[0]["name"] == "ml_model_factory"
    assert "credentials" not in datastore_definitions[0]


def test_existing_conflicting_role_or_datastore_is_not_overwritten(tmp_path):
    item = planned()
    def cli(*args):
        if args[:3] == ("storage", "container-rm", "list"):
            return [{"name": item["container"], "publicAccess": None}]
        if args[:3] == ("role", "definition", "list"):
            return [{"permissions": [{"actions": ["*"]}], "assignableScopes": ["/subscriptions/other"]}]
        raise AssertionError("Must stop before assigning permissions")
    with patch("scripts.activate_monitoring.azure_cli", side_effect=cli), patch("ml_model_factory.azureml._client"), pytest.raises(ValueError, match="differs"):
        execute(RUNTIME, item, tmp_path / "runtime.json")


def test_resume_reuses_actual_role_and_credentialless_datastore(tmp_path):
    item = planned()
    role = f"/subscriptions/{RUNTIME['subscription_id']}/providers/Microsoft.Authorization/roleDefinitions/existing-role"
    def cli(*args):
        if args[:3] == ("storage", "container-rm", "list"):
            return [{"name": item["container"], "publicAccess": "None"}]
        if args[:3] == ("role", "definition", "list"):
            return [{"id": role, "permissions": [{"actions": ACTIONS, "notActions": [], "dataActions": [], "notDataActions": []}],
                     "assignableScopes": item["role_definition"]["AssignableScopes"]}]
        if args[:3] == ("role", "assignment", "list"):
            scope = args[args.index("--scope") + 1]
            return [{"principalId": row["principal"], "roleDefinitionId": role if row["role"].startswith("custom:") else row["role"],
                     "scope": row["scope"]} for row in item["assignments"] if row["scope"] == scope]
        if args[:3] == ("ml", "datastore", "list"):
            return [{"name": item["datastore"], "account_name": item["storage_account"], "container_name": item["container"],
                     "credentials": {"type": "none"}}]
        raise AssertionError("Existing prerequisites must not be recreated")
    with patch("scripts.activate_monitoring.azure_cli", side_effect=cli):
        result = execute(RUNTIME, item, tmp_path / "runtime.json")
    assert result["role_definition_id"] == role
