"""Real persona orchestration with only Azure CLI and DFS transports faked."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from .test_persona_access import Azure, GROUPS, TENANT, SUB, COMMON, PROJECT, manifest
from .test_persona_lake import ADMIN, BASE, FakeLake
from personas import access, groups, lake, policy


class PersonaCloud(Azure):
    def __init__(self, config, group_ids=None):
        super().__init__()
        self.config = config
        self.group_ids = group_ids or GROUPS
        self.records = {
            spec["seed_key"]: {
                "attributes": {"enabled": True},
                "value": json.dumps({
                    "schema": groups.RECORD_SCHEMA, **spec["binding"], "persona": persona,
                    "object_id": self.group_ids[persona], "display_name": spec["name"],
                }),
            }
            for persona, spec in groups.group_specs(config).items()
        }
        self.shared_key = False

    def __call__(self, *args):
        def arg(name):
            return args[args.index(name) + 1]
        if args[:3] == ("keyvault", "secret", "show"):
            self.calls.append(args)
            return deepcopy(self.records[arg("--name")])
        if args[:3] == ("storage", "account", "show"):
            self.calls.append(args)
            return {
                "id": COMMON + "/providers/Microsoft.Storage/storageAccounts/isolatedlake",
                "isHnsEnabled": True, "allowSharedKeyAccess": self.shared_key,
                "allowBlobPublicAccess": False,
            }
        if args[:3] == ("role", "definition", "list"):
            self.calls.append(args)
            name = arg("--name")
            if name in (policy.CATALOG["builtins"]["owner"], policy.CATALOG["builtins"]["contributor"]):
                return [{"permissions": [{"actions": ["*"], "dataActions": []}]}]
            return [item for item in self.definitions if item["name"] == name]
        return super().__call__(*args)


def environment(monkeypatch):
    config = manifest()
    config["lake"] = {
        "tenant_id": TENANT, "subscription_id": SUB, "resource_group": "common-rg",
        "storage_account": "isolatedlake", "filesystem": "lake3",
        "project": "project001", "environment": "dev",
    }
    config["adoption"] = {"trusted_lake_admin_principal_ids": [ADMIN]}
    cloud, filesystem = PersonaCloud(config), FakeLake()
    monkeypatch.setattr(lake, "Lake", lambda config, cli_runner: filesystem)
    return config, cloud, filesystem


def test_real_seed_to_rbac_to_acl_rerun(monkeypatch):
    config, cloud, filesystem = environment(monkeypatch)
    preview = access.provision(config, execute=False, cli=cloud)
    assert preview["state"] == "preview"
    assert set(preview["groups"]) == set(policy.PERSONA_IDS)
    assert not cloud.mutations and not filesystem.writes

    applied = access.provision(config, execute=True, cli=cloud)
    assert applied["state"] == "applied" and applied["lake"]["state"] == "complete"
    leaf = applied["lake"]["authorized_path"]
    assert f"group:{GROUPS['persona213']}:r-x" in filesystem.values[leaf]
    assert filesystem.values["mlops/v1/projects/project002"] == BASE
    assert not any(call[0] == "ad" for call in cloud.calls)
    for persona in policy.CORE_PERSONAS:
        assert any(item["persona"] == persona and item["role_key"] == "admin"
                   and item["scope"] == PROJECT.lower() for item in applied["assignments"])
    assert not any(item["persona"] == "persona216" and "vault" in item["role_key"]
                   for item in applied["assignments"])
    cloud.calls.clear()
    filesystem.writes.clear()
    assert access.provision(config, execute=True, cli=cloud)["state"] == "applied"
    assert not cloud.mutations and not filesystem.writes


@pytest.mark.parametrize("failure", ["misbound-seed", "duplicate-seed", "shared-key", "missing-review"])
def test_real_preflight_stops_before_any_write(monkeypatch, failure):
    config, cloud, filesystem = environment(monkeypatch)
    specs = groups.group_specs(config)
    key = specs["persona213"]["seed_key"]
    if failure in ("misbound-seed", "duplicate-seed"):
        record = json.loads(cloud.records[key]["value"])
        record.update({"project": "project002"} if failure == "misbound-seed"
                      else {"object_id": GROUPS["persona210"]})
        cloud.records[key]["value"] = json.dumps(record)
    elif failure == "shared-key":
        cloud.shared_key = True
    else:
        config["security_review"]["transitive_membership_reviewed"] = False
    with pytest.raises((ValueError, access.ProvisioningBlocked)):
        access.provision(config, execute=True, cli=cloud)
    assert not cloud.mutations and not filesystem.writes


def test_missing_project_lake_fails_before_even_seed_discovery():
    cloud = Mock(side_effect=AssertionError("No Azure call should occur"))
    config = manifest()
    config.pop("lake", None)
    with pytest.raises(ValueError, match="explicit HNS lake"):
        access.provision(config, execute=True, cli=cloud)
    cloud.assert_not_called()


def test_subsequent_project_reuses_core_but_does_not_share_ai_acl(monkeypatch):
    config, first_cloud, filesystem = environment(monkeypatch)
    first = access.provision(config, execute=True, cli=first_cloud)
    first_leaf = first["lake"]["authorized_path"]
    first_acl = filesystem.values[first_leaf]

    second_config = deepcopy(config)
    second_config["project"] = "project002"
    second_config["project_scope"] = PROJECT + "-two"
    second_config["lake"]["project"] = "project002"
    second_groups = {
        persona: oid if persona in policy.CORE_PERSONAS else f"10000000-0000-0000-0000-{index:012d}"
        for index, (persona, oid) in enumerate(GROUPS.items(), 1)
    }
    second_cloud = PersonaCloud(second_config, second_groups)
    second_cloud.assignments = first_cloud.assignments
    second_cloud.definitions = first_cloud.definitions
    second_cloud.resources = [
        {**resource, "id": resource["id"].replace(PROJECT.lower(), second_config["project_scope"].lower())}
        for resource in first_cloud.resources
    ]
    second = access.provision(second_config, execute=True, cli=second_cloud)
    second_leaf = second["lake"]["authorized_path"]
    assert second["state"] == "applied"
    assert filesystem.values[first_leaf] == first_acl
    assert GROUPS["persona213"] not in filesystem.values[second_leaf]
    assert second_groups["persona213"] not in filesystem.values[first_leaf]
    assert f"group:{second_groups['persona213']}:r-x" in filesystem.values[second_leaf]
    for persona in policy.CORE_PERSONAS:
        assert second["groups"][persona] == first["groups"][persona]
        assert any(row["role_key"] == "admin" and row["persona"] == persona
                   and row["scope"] == second_config["project_scope"].lower()
                   for row in second["assignments"])
