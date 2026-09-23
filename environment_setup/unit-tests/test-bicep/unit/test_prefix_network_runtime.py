"""Runtime preserve-v1 proof against real emitted ARM and offline native GETs."""

import copy
from types import SimpleNamespace

import pytest

from unit.test_factory_lifecycle import fl
from unit.test_common_network_preservation import (
    ROOT, RG, VNET, apply_native_arm, compiled, desired, initial, net, plan,
)


def prepared(compiled):
    intent = desired()
    first = plan(initial(), intent)
    state, _ = apply_native_arm(initial(), first, compiled)
    intent["owned_resource_ids"] = first["owned_resource_ids"]
    replay = plan(state, intent)
    document = {"target": {"factory_id": intent["factory_id"]}}
    step = {"template": fl.COMMON_TEMPLATES["12-networkCommon"],
            "template_hash": fl.digest(compiled), "resource_group": RG,
            "parameters": replay["deployment_parameters"], "network_preservation": {
                "contract": "preserve-v1-runtime-proof", "desired": intent,
                "source_payload_sha256": net.digest(net._source_files(ROOT)), "reserved_ranges": [],
                "expected_resource_ids": [identifier for identifier in net.required_resource_ids(intent)
                                          if state.get(identifier) is not None]}}
    reads = []
    def arm(method, identifier, version, **kwargs):
        assert method == "GET"
        reads.append(identifier)
        return (200, {}, copy.deepcopy(state[identifier])) if identifier in state else (404, {}, None)
    cloud = SimpleNamespace(arm=arm, compile_template=lambda *args: compiled)
    return document, step, state, cloud, reads


def test_runtime_replay_freezes_current_post_runner_inventory(compiled):
    document, step, state, cloud, reads = prepared(compiled)
    state[VNET]["etag"] = "post-runner-and-private-endpoint"
    fl.verify_preserved_network(cloud, document, step, ROOT, freeze=True)
    fl.verify_preserved_network(cloud, document, step, ROOT)
    assert len(reads) == 18
    state[VNET]["etag"] = "changed-after-approval"
    with pytest.raises(fl.Blocked, match="network-inventory-changed-since-prepare"):
        fl.verify_preserved_network(cloud, document, step, ROOT)
    fl.verify_preserved_network(cloud, document, step, ROOT, freeze=True)
    fl.verify_preserved_network(cloud, document, step, ROOT)


@pytest.mark.parametrize("change", ["missing", "mutation", "source", "compiler", "subnet", "address"])
def test_runtime_replay_cannot_bypass_preservation_proof(compiled, change):
    document, step, state, cloud, reads = prepared(compiled)
    fl.verify_preserved_network(cloud, document, step, ROOT, freeze=True)
    if change == "missing":
        step.pop("network_preservation")
    elif change == "mutation":
        step["parameters"]["preservationPlan"]["createVnet"] = True
    elif change == "source":
        step["network_preservation"]["source_payload_sha256"] = "0" * 64
    elif change == "compiler":
        step["template_hash"] = "0" * 64
    elif change == "subnet":
        del state[VNET + "/subnets/snet-one"]
    else:
        state[VNET]["properties"]["addressSpace"]["addressPrefixes"] = ["10.2.0.0/20"]
    with pytest.raises(fl.Blocked):
        fl.verify_preserved_network(cloud, document, step, ROOT)


def test_legacy_runtime_does_not_require_new_proof_or_inventory():
    cloud = SimpleNamespace(arm=lambda *args, **kwargs: pytest.fail("No legacy inventory change."))
    fl.verify_preserved_network(cloud, {}, {"parameters": {}}, ROOT)


def test_created_group_receipt_bootstraps_exact_untagged_descendants_not_shared_groups(monkeypatch):
    owner = {"factory_id": "factory-one", "scaleset_id": "scale-one"}
    child = VNET + "/subnets/common"
    bodies = {
        RG: {"id": RG, "tags": {fl.TAG_KEYS[key]: value for key, value in owner.items()}},
        child: {"id": child, "properties": {"addressPrefix": "10.1.0.0/26"}},
    }
    closure = {"resources": {child: {"body_hash": "f" * 64}}}
    reads = []
    monkeypatch.setattr(fl, "collect_resource_closure",
                        lambda cloud, scopes: reads.append(scopes) or (closure, bodies))
    document = {"target": owner, "locks": {"scopes": [RG]}, "deployment": {
        "bootstrap_foundation": {"contract": "created-group-ownership-v1", "groups": {RG: {
            "plan_id": "11111111-1111-4111-8111-111111111111", "plan_hash": "a" * 64}}}}}
    assert fl.bootstrap_ownership_snapshot(None, document) == {
        child: {"owner": owner, "body_hash": "f" * 64}}
    assert reads == [[RG]]
    bodies[child]["tags"] = {fl.TAG_KEYS["factory_id"]: "another-factory"}
    with pytest.raises(fl.Blocked, match="ownership-conflict"):
        fl.bootstrap_ownership_snapshot(None, document)
    document["locks"]["scopes"] = [RG + "-different"]
    reads.clear()
    assert fl.bootstrap_ownership_snapshot(None, document) == {}
    assert reads == []
