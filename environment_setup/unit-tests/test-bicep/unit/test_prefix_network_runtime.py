"""Runtime preserve-v1 proof against real emitted ARM and offline native GETs."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from unit.test_factory_lifecycle import ClosureCloud, GROUP, RULE, fl
from unit.test_factory_lifecycle_bootstrap_handoff import exact_document
from unit.test_common_network_preservation import (
    ROOT, RG, VNET, apply_native_arm, compiled, desired, initial, net, plan,
)


def prepared(compiled):
    intent = desired()
    first = plan(initial(), intent)
    state, _ = apply_native_arm(initial(), first, compiled)
    intent["owned_resource_ids"] = first["owned_resource_ids"]
    replay = plan(state, intent)
    document = {"target": {"factory_id": intent["factory_id"]}, "locks": {"scopes": [RG]},
                "identity": {"object_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"}}
    step = {"template": fl.COMMON_TEMPLATES["12-networkCommon"],
            "template_hash": fl.digest(compiled), "scope": "subscription",
            "resource_group": RG, "resource_groups": [RG],
            "parameters": replay["deployment_parameters"], "network_preservation": {
                "contract": "preserve-v1-runtime-proof", "desired": intent,
                "source_payload_sha256": net.digest(net._source_files(ROOT)), "reserved_ranges": [],
                "expected_resource_ids": [identifier for identifier in net.required_resource_ids(intent)
                                          if state.get(identifier) is not None]}}
    reads = []
    def request(method, url, audience, *, allowed, headers):
        parsed = urlsplit(url)
        assert method == "GET" and url.startswith(fl.ARM + "/") and audience == fl.ARM
        assert parse_qs(parsed.query) == {"api-version": [net.API_VERSION]}
        assert allowed == (200, 404)
        identifier = parsed.path.lower()
        reads.append(identifier)
        return (200, {}, copy.deepcopy(state[identifier])) if identifier in state else (404, {}, None)
    cloud = fl.Cloud(document, command_runner=Mock(side_effect=AssertionError("No runtime commands")),
                     opener=Mock(side_effect=AssertionError("No real HTTP")))
    cloud.request = request
    cloud.compile_template = lambda *args: compiled
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


@pytest.mark.parametrize("change,code", [
    ("missing", "runtime-network-preservation-proof-required"),
    ("mutation", "runtime-network-replay-must-be-exactly-zero-write"),
    ("source", "runtime-network-preservation-source-changed"),
    ("compiler", "compiled-template-hash-mismatch"),
    ("subnet", "runtime-network-preservation-unverified"),
    ("address", "runtime-network-preservation-address-space-changed"),
])
def test_runtime_replay_cannot_bypass_preservation_proof(compiled, change, code):
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
    with pytest.raises(fl.Blocked, match=code):
        fl.verify_preserved_network(cloud, document, step, ROOT)


def test_legacy_runtime_does_not_require_new_proof_or_inventory():
    cloud = SimpleNamespace(arm=lambda *args, **kwargs: pytest.fail("No legacy inventory change."))
    fl.verify_preserved_network(cloud, {}, {"parameters": {}}, ROOT)


def test_created_group_receipt_requires_exact_v2_child_proof_not_shared_groups(monkeypatch):
    cloud = ClosureCloud()
    document = exact_document(cloud)
    proof = document["deployment"]["bootstrap_foundation"]
    child = RULE.lower()
    document["deployment"]["bootstrap_foundation"] = {
        "contract": "created-group-ownership-v1", "groups": proof["groups"]}
    reads = Mock(wraps=cloud.list_resources)
    monkeypatch.setattr(cloud, "list_resources", reads)
    with pytest.raises(fl.Blocked, match="exact-bootstrap-resource-proof-required"):
        fl.bootstrap_ownership_snapshot(cloud, document)
    reads.assert_called_once_with(GROUP.lower())
    cloud.bodies[child]["tags"] = {fl.TAG_KEYS["factory_id"]: "another-factory"}
    with pytest.raises(fl.Blocked, match="ownership-conflict"):
        fl.bootstrap_ownership_snapshot(cloud, document)
    del cloud.bodies[child]["tags"]
    document["locks"]["scopes"] = [GROUP + "-different"]
    reads.reset_mock()
    assert fl.bootstrap_ownership_snapshot(cloud, document) == {}
    reads.assert_not_called()
    document["locks"]["scopes"] = [GROUP]
    document["deployment"]["bootstrap_foundation"] = proof
    assert fl.bootstrap_ownership_snapshot(cloud, document)[child] == {
        "owner": proof["resources"][child]["owner"], "body_hash": proof["resources"][child]["body_hash"]}
    proof["resources"][child]["receipt"]["resource_id"] = GROUP.lower()
    with pytest.raises(fl.Blocked, match="exact-bootstrap-resource-owner-required"):
        fl.bootstrap_ownership_snapshot(cloud, document)
