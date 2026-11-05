"""Offline: platform-maintained children leave with their parent; the deletion never sends them a DELETE of their own.

aif-138 (2026-11-02): the resumed factory deletion's common stage sent its first DELETE to the registry's built-in
scope map _repositories_admin, because Microsoft.ContainerRegistry lists registries/scopeMaps/delete. ARM refused it
with 400 (system-defined scope maps cannot be deleted) and the run stopped before deleting anything. A private
endpoint's privateLinkServiceProxies and a VNet's taggedTrafficConsumers are maintained by the platform the same way.
"""

import json

import pytest

from .test_factory_lifecycle import fl, GROUP, OWNER, seal, workspace, no_real_services  # noqa: F401
from .test_selective_project_deletion import tagged
from .test_factory_deletion_pipeline import factory_prepared

REGISTRY = GROUP + "/providers/Microsoft.ContainerRegistry/registries/acrproject"
BUILT_IN = REGISTRY + "/scopeMaps/_repositories_admin"
CUSTOM = REGISTRY + "/scopeMaps/ci-push"


def with_registry():
    document, cloud, projects = factory_prepared()
    for identifier, kind in ((REGISTRY, "Microsoft.ContainerRegistry/registries"),
                             (BUILT_IN, "Microsoft.ContainerRegistry/registries/scopeMaps"),
                             (CUSTOM, "Microsoft.ContainerRegistry/registries/scopeMaps")):
        cloud.bodies[identifier.lower()] = tagged(identifier, kind, OWNER)
    old_schema, old_operations = cloud.provider_schema, cloud.provider_operations

    def schema(namespace):
        if namespace.lower() == "microsoft.containerregistry":
            return {"resourceTypes": [{"resourceType": name, "apiVersions": ["2025-04-01"]}
                                      for name in ("registries", "registries/scopeMaps")]}
        return old_schema(namespace)

    def operations(namespace):
        if namespace.lower() == "microsoft.containerregistry":
            return ["microsoft.containerregistry/registries/" + action for action in ("read", "write", "delete")] + [
                "microsoft.containerregistry/registries/scopemaps/" + action for action in ("read", "write", "delete")]
        return old_operations(namespace)

    old_collection = cloud.collection

    def collection(path, api_version, extension=False):
        if path.lower().endswith("/scopemaps"):
            return [dict(body) for key, body in sorted(cloud.bodies.items()) if key.startswith(path.lower() + "/")], None
        return old_collection(path, api_version, extension)

    cloud.provider_schema, cloud.provider_operations, cloud.collection = schema, operations, collection
    unsealed = dict(document)
    unsealed["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    return seal(unsealed), cloud


def rows(document):
    return {row["id"].lower(): row for row in document["deletion"]["resources"]}


@pytest.mark.parametrize("kind, name, expected", [
    ("microsoft.containerregistry/registries/scopemaps", "_repositories_admin", True),
    ("microsoft.containerregistry/registries/scopemaps", "_REPOSITORIES_PULL", True),
    ("microsoft.containerregistry/registries/scopemaps", "ci-push", False),
    ("microsoft.network/privateendpoints/privatelinkserviceproxies", "pe.proxy.534e4b28", True),
    ("microsoft.network/virtualnetworks/taggedtrafficconsumers", "Microsoft.KeyVault.swedencentral", True),
    # run15 (2026-11-02): ARM refuses a Bastion NSG rule DELETE (NetworkSecurityGroupNotCompliantForAzureBastionSubnet);
    # rules leave with their NSG, after the subnets that reference it.
    ("microsoft.network/networksecuritygroups/securityrules", "Bastion_AzureCloudOutbound", True),
    ("microsoft.network/networksecuritygroups/securityrules", "allow-https", True),
    ("microsoft.network/virtualnetworks/subnets", "snet-esml-cmn-001", False),
    # aif-144 (2026-11-05, delete_factory run17): governance deallocates the runner VM nightly, and ARM answers 409 to an
    # extension or run command DELETE on a deallocated VM. Both leave with their VM.
    ("microsoft.compute/virtualmachines/extensions", "AzurePolicyforLinux", True),
    ("microsoft.compute/virtualmachines/extensions", "MDE.Linux", True),
    ("microsoft.compute/virtualmachines/runcommands", "register-aifactory-gha-20261103140304-31278", True),
])
def test_only_platform_maintained_children_are_classified_as_such(kind, name, expected):
    module = fl.factory_deletion_module()
    assert bool(module.platform_child({"id": GROUP + "/providers/x/y/z/" + name, "type": kind})) is expected


def test_a_built_in_scope_map_is_deleted_with_its_registry_and_a_custom_one_on_its_own():
    document, _ = with_registry()
    fl.validate_manifest(document)
    frozen = rows(document)
    assert frozen[BUILT_IN.lower()]["independent_delete"] is False
    assert frozen[BUILT_IN.lower()]["delete_via_parent"] == REGISTRY.lower()
    assert frozen[CUSTOM.lower()]["independent_delete"] is True


def test_validation_refuses_a_platform_child_marked_for_its_own_delete():
    document, _ = with_registry()
    row = rows(document)[BUILT_IN.lower()]
    row["independent_delete"] = True
    row.pop("delete_via_parent")
    document["deletion"]["inventory_hash"] = fl.digest(document["deletion"]["resources"])
    with pytest.raises(fl.Blocked, match="factory-delete-platform-child-delete-forbidden"):
        fl.validate_manifest(seal(document))


def test_the_project_stage_never_sends_the_built_in_scope_map_a_delete(workspace, monkeypatch):
    document, cloud = with_registry()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)

    def dispatch(actual_cloud, locks, actual, source_root, receipt, persist):
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(actual, locks)), source_root,
            actual["run_id"], actual["manifest_hash"], cloud=actual_cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        assert BUILT_IN not in cloud.deleted and BUILT_IN in result["deleted_resources"]
        assert CUSTOM in cloud.deleted and cloud.deleted.index(CUSTOM) < cloud.deleted.index(REGISTRY)
        receipt.update(remote_run={"kind": "ado", "pipeline_id": 8, "run_id": 44}, remote_terminal=True)

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", result
