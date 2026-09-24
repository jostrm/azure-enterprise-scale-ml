"""Real registered filesystem fixtures; fake cloud transport, never cloud commands."""

import copy
import base64
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit, parse_qs
from types import SimpleNamespace
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
sys.path.insert(0, str(LIB))
SPEC = importlib.util.spec_from_file_location("registered_prerequisites", LIB / "registered_prerequisites.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
REAL_SUBPROCESS_RUN = subprocess.run
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
EXTERNAL = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FACTORY = "11111111-1111-1111-1111-111111111111"
SCALE = "22222222-2222-2222-2222-222222222222"
GROUP = "33333333-3333-3333-3333-333333333333"
MEMBER = "44444444-4444-4444-4444-444444444444"
OWNED = f"/subscriptions/{SUB}/resourcegroups/common"
ACCOUNT = OWNED + "/providers/microsoft.storage/storageaccounts/canonicalcommonlake"
VAULT = OWNED + "/providers/microsoft.keyvault/vaults/seed-reviewed"
COMMON_VNET = OWNED + "/providers/microsoft.network/virtualnetworks/common-vnet"
HUB_RG = f"/subscriptions/{EXTERNAL}/resourcegroups/shared-hub"
HUB = HUB_RG + "/providers/microsoft.network/virtualnetworks/hub-reviewed"


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LIVE COMMANDS/HTTP/SLEEP FORBIDDEN")
    monkeypatch.setattr(core.enrollment.subprocess, "run", fail)
    monkeypatch.setattr(core.enrollment, "build_opener", fail)
    monkeypatch.setattr(core.time, "sleep", fail)


class Runtime:
    def __init__(self, group_exists=True):
        self.read_only = True
        self.serialized_provisioning = False
        self.resources = {
            OWNED: {"id": OWNED, "location": "swedencentral", "tags": {
                "aifactory.factory_id": FACTORY, "aifactory.scaleset_id": SCALE}},
            ACCOUNT: {"id": ACCOUNT, "properties": {"isHnsEnabled": True, "publicNetworkAccess": "Disabled"}},
            ACCOUNT + "/blobservices/default/containers/factorymeta": {"properties": {"publicAccess": "None"}},
            COMMON_VNET: {"id": COMMON_VNET, "location": "swedencentral",
                          "properties": {"addressSpace": {"addressPrefixes": ["172.16.0.0/20"]}}},
        }
        self.groups = {GROUP: {"id": GROUP, "displayName": "factory team", "securityEnabled": True,
                               "mailEnabled": False}} if group_exists else {}
        self.members = {GROUP: [MEMBER]} if group_exists else {}
        self.writes = []
        self.blobs = {}
        self.leases = {}
        self.fail_write = None
        self.fail_read = None
        self.on_acquire = None

    def arm(self, method, identifier, api, data=None, headers=None, allowed=(200,)):
        identifier = identifier.lower()
        if method == "GET":
            if self.fail_read:
                raise core.PrerequisiteError(self.fail_read)
            if len(identifier.split("/")) == 5 and "/providers/" in identifier and identifier not in self.resources:
                return 200, {}, {"id": identifier, "registrationState": "Registered"}
            return (200, {}, copy.deepcopy(self.resources[identifier])) if identifier in self.resources else (404, {}, None)
        assert not self.read_only and self.serialized_provisioning
        self.writes.append(("arm", method, identifier, copy.deepcopy(data)))
        if self.fail_write and self.fail_write(identifier):
            raise core.PrerequisiteError("remote-request-uncertain")
        if method == "POST" and identifier.endswith("/register"):
            self.resources[identifier.removesuffix("/register")]["registrationState"] = "Registered"
            return 200, {}, copy.deepcopy(self.resources[identifier.removesuffix("/register")])
        body = copy.deepcopy(data)
        body["id"] = identifier
        body.setdefault("properties", {})["provisioningState"] = "Succeeded"
        if "/virtualnetworks/" in identifier and "/subnets/" in identifier:
            body["name"] = identifier.rsplit("/", 1)[1]
            parent_id = identifier.rsplit("/subnets/", 1)[0]
            parent = self.resources.get(parent_id)
            if parent:
                retained = [child for child in parent["properties"].get("subnets", [])
                            if child["id"].lower() != identifier]
                parent["properties"]["subnets"] = retained + [copy.deepcopy(body)]
        elif "/virtualnetworks/" in identifier and len(identifier.split("/")) == 9:
            body["properties"].setdefault("subnets", [])
            body["properties"].setdefault("virtualNetworkPeerings", [])
        self.resources[identifier] = body
        return 201, {}, copy.deepcopy(body)

    def collection(self, identifier, api):
        if identifier.endswith("/inboundEndpoints"):
            return [copy.deepcopy(value) for key, value in self.resources.items()
                    if key.startswith(identifier.lower() + "/")]
        if identifier.endswith(("/virtualNetworkPeerings", "/virtualNetworkLinks")):
            return [copy.deepcopy(value) for key, value in self.resources.items()
                    if key.startswith(identifier.lower() + "/")]
        kind = ("/dnsresolvers/" if identifier.endswith("/dnsResolvers") else
                "/bastionhosts/" if identifier.endswith("/bastionHosts") else "/virtualnetworkgateways/")
        return [copy.deepcopy(value) for key, value in self.resources.items()
                if key.startswith("/subscriptions/" + identifier.split("/")[2])
                and kind in key and "/inboundendpoints/" not in key]

    def graph(self, method, path, body=None, allowed=(200,)):
        if method == "GET":
            if path.startswith("users/"):
                return {"id": MEMBER}
            if path.startswith("groups?"):
                return {"value": list(copy.deepcopy(self.groups).values())}
            group_id = path.split("/")[1].split("?")[0]
            if "/members?" in path:
                return {"value": [{"id": member} for member in self.members[group_id]]}
            return copy.deepcopy(self.groups[group_id])
        assert not self.read_only
        self.writes.append(("graph", method, path, copy.deepcopy(body)))
        if path == "groups":
            self.groups[GROUP] = {"id": GROUP, **copy.deepcopy(body)}
            self.members[GROUP] = [MEMBER]
            return copy.deepcopy(self.groups[GROUP])
        group_id = path.split("/")[1]
        self.members[group_id].append(body["@odata.id"].rsplit("/", 1)[1])
        return None

    def blob(self, method, blob, data=None, headers=None, allowed=(200,), query=""):
        if method == "GET":
            return (200, {}, copy.deepcopy(self.blobs[blob])) if blob in self.blobs else (404, {}, None)
        assert not self.read_only
        headers = headers or {}
        action = headers.get("x-ms-lease-action")
        if action == "acquire":
            if blob in self.leases:
                raise core.PrerequisiteError("lease-already-present")
            self.leases[blob] = headers["x-ms-proposed-lease-id"]
            if self.on_acquire:
                callback, self.on_acquire = self.on_acquire, None
                callback()
        elif action == "renew":
            assert self.leases.get(blob) == headers["x-ms-lease-id"]
        elif action == "release":
            assert self.leases.pop(blob) == headers["x-ms-lease-id"]
        else:
            if headers.get("If-None-Match") == "*" and blob in self.blobs:
                if 412 in allowed:
                    return 412, {}, None
                raise core.PrerequisiteError("remote-request-failed-412")
            self.blobs[blob] = copy.deepcopy(data)
        return 201 if action in (None, "acquire") else 200, {}, None


@pytest.fixture
def workspace():
    folder = ROOT / (".prerequisites-offline-" + str(uuid4()))
    consumer, source, state = folder / "consumer", folder / "source", folder / "state"
    (consumer / "azurefactory").mkdir(parents=True)
    state.mkdir()
    for relative in core.SOURCE_FILES:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    document = {"schema_version": 2, "generation": "test", "configurations": {}, "bindings": {},
                "factories": [{"id": FACTORY, "kind": "ai", "aifactory_version": "main", "prefix": "aif-", "region": "swedencentral",
                               "scale_sets": [{"id": SCALE, "environment": "dev", "suffix": "001",
                                               "tenant_id": TENANT, "subscription_id": SUB, "orchestrator": "gha"}]}]}
    (consumer / "azurefactory" / "register.json").write_bytes(core.canonical(document))
    try:
        yield consumer, source, state
    finally:
        shutil.rmtree(folder)


def arguments(workspace, **config):
    consumer, source, _ = workspace
    return {"source_root": source, "consumer_root": consumer,
            "scope": {"factory_id": FACTORY, "scale_set_id": SCALE}, "expected_revision": "reviewed-revision",
            "bootstrap_config": {"team_group_name": "factory team", "team_member_email": "owner@example.org",
                                 "access_hub_mode": "integrated", "setup_hub_access": False, **config},
            "context": {"source_payload_sha256": core.source_fingerprint(source)["payload_sha256"],
                        "location_short": "sdc", "seeding_keyvault_id": VAULT,
                        "integrated_vnet_id": COMMON_VNET, "integrated_vnet_cidr": "172.16.0.0/20",
                        "owned_resource_group_ids": [OWNED], "coordination": {
                            "account_id": ACCOUNT, "account_url": "https://canonicalcommonlake.blob.core.windows.net",
                            "container": "factorymeta"}}}


def external_arguments(workspace, setup=True):
    return arguments(workspace, access_hub_mode="external", setup_hub_access=setup,
                     access_hub_subscription_id=EXTERNAL, access_hub_resource_group="shared-hub",
                     access_hub_vnet_name="hub-reviewed", access_hub_vnet_cidr="10.40.0.0/24",
                     vpn_client_cidr="172.30.0.0/24", dev_vnet_cidr="172.16.0.0/20")


def execute(plan, workspace, runtime):
    return core.execute(plan, expected_plan_hash=plan["plan_hash"], state_dir=workspace[2], runtime=runtime,
                        acknowledge_exclusive_writer_governance=True, sleep=lambda _: pytest.fail("unexpected wait"))


def test_prepare_readonly_and_no_hub_is_independent(workspace):
    runtime = Runtime()
    consumer = workspace[0]
    before = (consumer / "azurefactory" / "register.json").read_bytes()
    plan = core.prepare(**arguments(workspace), runtime=runtime)
    assert plan["can_execute"] and plan["bindings"]["network"]["mode"] == "none"
    assert not runtime.writes and not runtime.blobs
    assert [x["id"] for x in plan["effects"]] == [VAULT]
    assert (consumer / "azurefactory" / "register.json").read_bytes() == before
    assert not list(workspace[2].iterdir())


def test_backend_plan_schema_and_explicit_capabilities(workspace):
    runtime = Runtime()
    args = arguments(workspace)
    args["scope"]["environment"] = "dev"
    plan = core.prepare(**args, runtime=runtime)
    assert {"contract_version", "can_execute", "blockers", "effects", "commands", "auth_scopes",
            "source_hashes", "input_hash", "plan_hash", "stages", "preconditions"} <= set(plan)
    assert len(plan["commands"]) == len(plan["effects"])
    assert plan["commands"][0]["method"] == "PUT"
    assert core.capabilities()["implemented_stages"] == ["privileged-prerequisites"]
    assert core.capabilities()["cold_start_supported"] is False
    assert core.capabilities()["supports_restricted_wizard"] is False
    args["scope"]["environment"] = "prod"
    with pytest.raises(core.PrerequisiteError, match="initial-dev-environment-required"):
        core.prepare(**args, runtime=runtime)


def load_snapshot_in_isolated_python(source, expected_hash, cwd):
    code = (
        "import json,sys;from pathlib import Path;"
        "sys.path.insert(0,str(Path(sys.argv[1])/'bootstrap'/'lib'));"
        "import registered_prerequisites as p;"
        "source=p.verify_source_snapshot(source_root=sys.argv[1],expected_payload_sha256=sys.argv[2]);"
        "print(json.dumps({'source':source,'capabilities':p.capabilities()}))"
    )
    return REAL_SUBPROCESS_RUN([sys.executable, "-I", "-B", "-c", code, str(source), expected_hash],
                               cwd=cwd, capture_output=True, text=True, timeout=30)


def test_real_isolated_source_bundle_resolves_exact_pinned_unpublished_bytes(workspace):
    consumer, source, _ = workspace
    # A consumer-supplied module must not shadow the pinned helper dependencies.
    (consumer / "factory_enrollment.py").write_text("raise RuntimeError('consumer-module-must-not-load')\n")
    expected = core.source_fingerprint(source)
    result = load_snapshot_in_isolated_python(source, expected["payload_sha256"], consumer)
    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    assert resolved["source"] == expected
    assert resolved["source"]["kind"] == "reviewed-local-payload"
    assert resolved["source"]["published_ref_verified"] is False
    assert resolved["source"]["verification"] == "exact-local-file-bytes-only"
    assert "commit" not in resolved["source"]
    assert resolved["capabilities"]["cold_start_supported"] is False


def test_real_old_bundle_missing_helper_does_not_fall_back_to_worktree_or_main(workspace):
    consumer, source, _ = workspace
    expected_hash = core.source_fingerprint(source)["payload_sha256"]
    (source / core.SOURCE_FILES[0]).unlink()
    result = load_snapshot_in_isolated_python(source, expected_hash, consumer)
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
    assert not result.stdout.strip()
    with pytest.raises(core.PrerequisiteError, match="privileged-source-file-missing"):
        core.verify_source_snapshot(source_root=source, expected_payload_sha256=expected_hash)


def test_real_bundle_modified_after_pin_requires_a_new_review(workspace):
    consumer, source, _ = workspace
    expected_hash = core.source_fingerprint(source)["payload_sha256"]
    path = source / core.SOURCE_FILES[-1]
    path.write_bytes(path.read_bytes() + b"\n# Unreviewed local change.\n")
    result = load_snapshot_in_isolated_python(source, expected_hash, consumer)
    assert result.returncode != 0
    assert "reviewed-source-payload-required" in result.stderr
    assert not result.stdout.strip()


def test_different_loaded_dependency_cannot_impersonate_reviewed_bundle(workspace):
    source = workspace[1]
    path = source / core.SOURCE_FILES[-1]
    path.write_bytes(path.read_bytes() + b"\n# Different from this process's already-loaded module.\n")
    new_hash = core.source_fingerprint(source)["payload_sha256"]
    with pytest.raises(core.PrerequisiteError, match="loaded-prerequisite-code-differs"):
        core.verify_source_snapshot(source_root=source, expected_payload_sha256=new_hash)


def test_backend_default_cidrs_are_preserved_and_large_hub_is_bounded(workspace):
    runtime = Runtime()
    runtime.resources[COMMON_VNET]["properties"]["addressSpace"]["addressPrefixes"] = ["172.16.0.0/18"]
    args = external_arguments(workspace)
    del args["bootstrap_config"]["vpn_client_cidr"]
    del args["bootstrap_config"]["dev_vnet_cidr"]
    args["bootstrap_config"]["access_hub_vnet_cidr"] = "10.0.0.0/8"
    plan = core.prepare(**args, runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    gateway = next(e for e in plan["effects"] if "/virtualNetworkGateways/" in e.get("id", ""))
    properties = gateway["body"]["properties"]
    assert properties["customRoutes"]["addressPrefixes"] == ["172.16.0.0/18"]
    assert properties["vpnClientConfiguration"]["vpnClientAddressPool"]["addressPrefixes"] == ["172.31.240.0/24"]
    subnet = next(e for e in plan["effects"] if e.get("id", "").endswith("/subnets/GatewaySubnet"))
    assert subnet["body"]["properties"]["addressPrefix"] == "10.255.255.224/27"


@pytest.mark.parametrize("version,allowed", [("main", True), ("125", True), ("1.25", True), ("124", False)])
def test_only_modern_registered_versions_are_supported(workspace, version, allowed):
    runtime = Runtime()
    path = workspace[0] / "azurefactory" / "register.json"
    document = json.loads(path.read_text())
    document["factories"][0]["aifactory_version"] = version
    path.write_bytes(core.canonical(document))
    if allowed:
        assert core.prepare(**arguments(workspace), runtime=runtime)["can_execute"]
    else:
        with pytest.raises(core.PrerequisiteError, match="require-main-or-v125-plus"):
            core.prepare(**arguments(workspace), runtime=runtime)
    assert not runtime.writes


def test_group_and_vault_execute_with_durable_proof_and_one_use(workspace):
    runtime = Runtime(group_exists=False)
    args = arguments(workspace)
    plan = core.prepare(**args, runtime=runtime)
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    assert result["bindings"]["team_group_id"] == GROUP
    assert result["requires_downstream_review"] and result["enrollment_required"]
    assert not result["runtime_ready"] and not result["runtime_binding_published"]
    assert runtime.resources[VAULT]["properties"]["enabledForTemplateDeployment"] is True
    assert not runtime.leases
    durable = json.loads((workspace[2] / (plan["plan_id"] + ".json")).read_text())
    assert durable == result
    assert core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"]) == result
    assert durable["source"] == plan["source"]
    assert durable["scope"] == plan["scope"]
    assert {"status", "stage_results", "outputs", "changed", "reconciliation_required", "receipt_path"} <= set(result)
    assert result["outputs"] == result["bindings"]
    assert result["changed"] is True and result["stage_results"][0]["status"] == "succeeded"
    writes = copy.deepcopy(runtime.writes)
    with pytest.raises((core.PrerequisiteError, FileExistsError)):
        execute(plan, workspace, runtime)
    assert runtime.writes == writes


def test_external_network_plan_never_enrolls_or_tags_hub_as_owned(workspace):
    runtime = Runtime()
    plan = core.prepare(**external_arguments(workspace), runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    external = [e for e in plan["effects"] if e.get("id", "").lower().startswith(HUB_RG)]
    assert external and all(e["ownership"] == "external-retain-never-enroll-or-delete" for e in external)
    assert all("aifactory.factory_id" not in e.get("body", {}).get("tags", {}) for e in external)
    assert HUB_RG in plan["lock_scopes"]
    assert HUB_RG not in plan["context"]["owned_resource_group_ids"]
    assert plan["bindings"]["network"]["owned"] is False
    assert len([e for e in external if "/virtualNetworkGateways/" in e.get("id", "")]) == 1
    assert not runtime.writes


def test_new_external_network_executes_and_verifies_real_arm_shapes(workspace):
    runtime = Runtime()
    plan = core.prepare(**external_arguments(workspace), runtime=runtime)
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    network = result["bindings"]["network"]
    gateway = runtime.resources[network["gateway_id"].lower()]["properties"]
    assert gateway["vpnClientConfiguration"]["vpnAuthenticationTypes"] == ["AAD"]
    assert gateway["customRoutes"]["addressPrefixes"] == ["172.16.0.0/20"]
    assert runtime.resources[HUB]["properties"]["dhcpOptions"]["dnsServers"] == [network["resolver_inbound_ip"]]
    assert not runtime.leases


def existing_gateway(runtime, compatible=True):
    runtime.resources[HUB_RG] = {"id": HUB_RG, "location": "swedencentral"}
    runtime.resources[HUB] = {"id": HUB, "location": "swedencentral", "properties": {
        "addressSpace": {"addressPrefixes": ["10.40.0.0/24"]}, "dhcpOptions": {"dnsServers": ["10.40.0.10"]}}}
    identifier = HUB_RG + "/providers/microsoft.network/virtualnetworkgateways/corporate-gateway-not-generated"
    runtime.resources[identifier] = {"id": identifier, "properties": {
        "gatewayType": "Vpn", "vpnType": "RouteBased", "provisioningState": "Succeeded", "ipConfigurations": [{
            "properties": {"subnet": {"id": HUB + "/subnets/GatewaySubnet"}}}],
        "customRoutes": {"addressPrefixes": ["172.16.0.0/20", "10.42.0.0/24"]},
        "vpnClientConfiguration": {"vpnClientAddressPool": {"addressPrefixes": ["172.30.0.0/24"]},
            "vpnClientProtocols": ["OpenVPN"], "vpnAuthenticationTypes": ["AAD"],
            "aadTenant": "https://login.microsoftonline.com/" + TENANT,
            "aadAudience": "c632b3df-fb67-4d84-bdcf-b95ad541b5c8",
            "aadIssuer": "https://sts.windows.net/" + TENANT + "/"}}}
    if not compatible:
        runtime.resources[identifier]["properties"]["vpnClientConfiguration"]["vpnClientProtocols"] = ["IkeV2"]
    resolver = HUB_RG + "/providers/microsoft.network/dnsresolvers/corporate-dns"
    runtime.resources[resolver] = {"id": resolver, "properties": {"virtualNetwork": {"id": HUB},
                                                              "provisioningState": "Succeeded"}}
    endpoint = resolver + "/inboundendpoints/corporate"
    runtime.resources[endpoint] = {"id": endpoint, "properties": {
        "provisioningState": "Succeeded", "ipConfigurations": [{"privateIpAddress": "10.40.0.10"}]}}
    return identifier


def test_arbitrary_existing_gateway_binds_exact_id_without_overwrite(workspace):
    runtime = Runtime()
    identifier = existing_gateway(runtime)
    plan = core.prepare(**external_arguments(workspace), runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    assert plan["bindings"]["network"]["gateway_id"] == identifier
    assert plan["bindings"]["network"]["gateway_reused_unchanged"] is True
    assert not any("virtualnetworkgateways" in e.get("id", "").lower() or e["kind"] == "vnet-dns"
                   for e in plan["effects"])
    before = copy.deepcopy(runtime.resources[identifier])
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    assert runtime.resources[identifier] == before


def test_incompatible_gateway_blocks_before_any_write_with_exact_id(workspace):
    runtime = Runtime()
    identifier = existing_gateway(runtime, compatible=False)
    plan = core.prepare(**external_arguments(workspace), runtime=runtime)
    assert not plan["can_execute"]
    assert any("p2s-configuration-incompatible" in b and identifier in b for b in plan["blockers"])
    with pytest.raises(core.PrerequisiteError, match="plan-blocked"):
        execute(plan, workspace, runtime)
    assert not runtime.writes and not runtime.blobs


@pytest.mark.parametrize("mutation,code", [
    ("source", "source-changed"), ("register", "consumer-register-changed"),
    ("plan", "plan-hash-mismatch"), ("remote", "live-state-or-plan-changed"), ("expired", "review-expired"),
])
def test_drift_and_tampering_block_before_writes(workspace, mutation, code):
    runtime = Runtime()
    plan = core.prepare(**arguments(workspace), runtime=runtime)
    if mutation == "source":
        path = workspace[1] / core.SOURCE_FILES[0]
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "register":
        path = workspace[0] / "azurefactory" / "register.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "plan":
        plan["effects"][0]["body"]["properties"]["enablePurgeProtection"] = False
    elif mutation == "remote":
        runtime.members[GROUP] = []
    else:
        plan["expires_at"] = 0
        plan["plan_hash"] = core.digest({k: v for k, v in plan.items() if k != "plan_hash"})
    with pytest.raises(core.PrerequisiteError, match=code):
        execute(plan, workspace, runtime)
    assert not runtime.writes and not runtime.blobs


def test_failure_retains_durable_uncertain_lease_and_no_retry(workspace):
    runtime = Runtime()
    plan = core.prepare(**arguments(workspace), runtime=runtime)
    runtime.fail_write = lambda _: True
    result = execute(plan, workspace, runtime)
    assert result["status"] == "uncertain" and result["reconciliation_required"]
    assert result["pending_effect"] == 0 and result["leases"] and runtime.leases
    assert json.loads((workspace[2] / (plan["plan_id"] + ".json")).read_text()) == result
    assert core.read_result(state_dir=workspace[2], plan_id=plan["plan_id"]) == result
    before = copy.deepcopy(runtime.writes)
    with pytest.raises(FileExistsError):
        execute(plan, workspace, runtime)
    assert runtime.writes == before


def test_changes_during_lock_acquisition_stop_cloud_resource_writes(workspace):
    runtime = Runtime()
    plan = core.prepare(**arguments(workspace), runtime=runtime)
    runtime.on_acquire = lambda: runtime.members.update({GROUP: []})
    result = execute(plan, workspace, runtime)
    assert result["status"] == "uncertain"
    assert result["error"] == "prerequisites-changed-before-lock"
    assert not runtime.writes


def test_no_cold_start_fake_success_or_separate_lock_account(workspace):
    runtime = Runtime()
    del runtime.resources[ACCOUNT]
    plan = core.prepare(**arguments(workspace), runtime=runtime)
    assert not plan["can_execute"]
    assert "canonical-common-adls-must-exist-before-distributed-prerequisites" in plan["blockers"]
    assert not any("/storageaccounts/" in e.get("id", "").lower() for e in plan["effects"])


def test_integrated_network_requires_common_first_and_preserves_ownership(workspace):
    runtime = Runtime()
    del runtime.resources[COMMON_VNET]
    args = arguments(workspace, setup_hub_access=True)
    args["context"].update(integrated_vnet_id=OWNED + "/providers/Microsoft.Network/virtualNetworks/common-vnet",
                           integrated_vnet_cidr="172.16.0.0/20")
    plan = core.prepare(**args, runtime=runtime)
    assert not plan["can_execute"]
    assert any("integrated-access-requires-common-network-first" in x for x in plan["blockers"])
    assert plan["bindings"]["network"]["owned"]


def test_external_no_access_intent_avoids_vpn_but_preserves_shared_dns_prerequisites(workspace):
    runtime = Runtime()
    plan = core.prepare(**external_arguments(workspace, setup=False), runtime=runtime)
    assert plan["can_execute"]
    assert not any("/virtualnetworkgateways/" in x.get("id", "").lower()
                   or "/bastionhosts/" in x.get("id", "").lower() for x in plan["effects"])
    assert any("/privatednszones/" in x.get("id", "").lower() for x in plan["effects"])
    assert plan["bindings"]["network"]["mode"] == "external"


def test_bastion_is_owned_common_only_and_peering_is_explicit(workspace):
    runtime = Runtime()
    plan = core.prepare(**external_arguments(workspace), runtime=runtime)
    bastion = next(x for x in plan["effects"] if "/bastionHosts/" in x.get("id", ""))
    assert bastion["id"].startswith(OWNED)
    assert bastion["body"]["properties"]["virtualNetwork"]["id"] == COMMON_VNET
    assert bastion["body"]["sku"]["name"] == "Developer"
    peers = [x for x in plan["effects"] if "/virtualNetworkPeerings/" in x.get("id", "")]
    assert len(peers) == 2
    hub = next(x for x in peers if x["id"].startswith(HUB))
    common = next(x for x in peers if x["id"].startswith(COMMON_VNET))
    assert hub["body"]["properties"]["allowGatewayTransit"] is True
    assert hub["ownership"] == "external-retain-never-enroll-or-delete"
    assert common["body"]["properties"]["useRemoteGateways"] is True
    assert common["ownership"] == "factory-owned"


def test_resource_provider_registration_is_reviewed_and_verified(workspace):
    runtime = Runtime()
    identifier = f"/subscriptions/{SUB}/providers/microsoft.keyvault"
    runtime.resources[identifier] = {"id": identifier, "registrationState": "NotRegistered"}
    plan = core.prepare(**arguments(workspace), runtime=runtime)
    assert plan["effects"][0]["kind"] == "provider-register"
    assert identifier in plan["lock_scopes"]
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    assert runtime.resources[identifier]["registrationState"] == "Registered"


def test_existing_gateway_requires_verified_private_dns_resolver(workspace):
    runtime = Runtime()
    identifier = existing_gateway(runtime)
    runtime.resources[HUB]["properties"]["dhcpOptions"]["dnsServers"] = ["10.40.0.11"]
    plan = core.prepare(**external_arguments(workspace), runtime=runtime)
    assert not plan["can_execute"]
    assert any("private-dns-resolver-unverified:" + identifier == x.split("existing-gateway-", 1)[-1]
               for x in plan["blockers"])


@pytest.mark.parametrize("field,value", [("isAssignableToRole", True), ("groupTypes", ["DynamicMembership"])])
def test_role_assignable_or_dynamic_group_is_not_a_bootstrap_team(workspace, field, value):
    runtime = Runtime()
    runtime.groups[GROUP][field] = value
    with pytest.raises(core.PrerequisiteError, match="cannot-be-role-assignable-or-dynamic"):
        core.prepare(**arguments(workspace), runtime=runtime)
    assert not runtime.writes


@pytest.mark.parametrize("change,code", [
    (lambda args: args["context"]["coordination"].update(container="lake3"), "factory-common-factorymeta-required"),
    (lambda args: args["context"].update(source_payload_sha256="0" * 64), "reviewed-source-payload-required"),
    (lambda args: args["context"].update(owned_resource_group_ids=[OWNED, HUB_RG]), "owned-scope-subscription-mismatch"),
    (lambda args: args["bootstrap_config"].update(subscription_id=EXTERNAL), "registered-config-mismatch"),
    (lambda args: args["bootstrap_config"].update(legacy_launcher=True), "unknown-prerequisite-config-field"),
])
def test_scope_and_source_boundaries(workspace, change, code):
    runtime = Runtime()
    args = arguments(workspace)
    change(args)
    with pytest.raises(core.PrerequisiteError, match=code):
        core.prepare(**args, runtime=runtime)
    assert not runtime.writes and not runtime.blobs


def test_forbidden_scope_guards_remain_in_authoritative_enrollment_and_lifecycle():
    assert 'all(x.split("/")[2] == subscription for x in scopes)' in (LIB / "factory_enrollment.py").read_text()
    assert "writable-scope-subscription-mismatch" in (LIB / "factory_enrollment.py").read_text()
    assert "lock-subscription-mismatch" in (LIB / "factory_lifecycle.py").read_text()


foundation = core.hub_lock_foundation
BOOTSTRAP_IP = "8.8.4.4"


class FoundationRuntime(Runtime):
    def __init__(self):
        super().__init__()
        self.resources = {}
        self.operator = MEMBER
        self.available = True
        self.events = []
        self.etags = {}
        self.after_write = None

    def principal(self):
        return self.operator

    def az(self, *args):
        assert args[:3] == ("storage", "account", "check-name")
        return {"nameAvailable": self.available}

    def collection(self, identifier, api):
        if identifier.endswith("/providers/Microsoft.Authorization/roleAssignments"):
            return [copy.deepcopy(v) for k, v in self.resources.items()
                    if k.startswith(identifier.lower() + "/")]
        return super().collection(identifier, api)

    def arm(self, method, identifier, api, data=None, headers=None, allowed=(200,)):
        result = super().arm(method, identifier, api, data=data, headers=headers, allowed=allowed)
        if method != "GET":
            self.events.append(("arm", identifier))
            if "/roleassignments/" in identifier.lower():
                self.resources[identifier.lower()]["properties"]["scope"] = identifier.lower().split("/providers/microsoft.authorization/")[0]
            if self.after_write:
                self.after_write(identifier)
        return result

    def blob(self, method, blob=None, data=None, headers=None, allowed=(200,), query=""):
        if method == "HEAD":
            assert any(k.endswith("/containers/hub-locks") for k in self.resources)
            return 200, {}, None
        if method != "GET":
            self.events.append(("blob", blob, copy.deepcopy(headers)))
        if headers and headers.get("If-Match"):
            assert self.etags[blob] == headers["If-Match"]
        result = super().blob(method, blob, data=data, headers=headers, allowed=allowed, query=query)
        if method == "PUT" and not query and result[0] == 201:
            self.etags[blob] = '"' + str(len(self.events)) + '"'
            return result[0], {"etag": self.etags[blob]}, result[2]
        return result


def foundation_args(workspace, hub=HUB_RG):
    return {"source_root": workspace[1], "tenant_id": TENANT, "hub_resource_group_id": hub,
            "location": "swedencentral", "bootstrap_public_ipv4": BOOTSTRAP_IP,
            "expected_source_hash": foundation.source_fingerprint(workspace[1])["payload_sha256"]}


def foundation_execute(plan, workspace, runtime, **kwargs):
    return foundation.execute(plan, state_dir=workspace[2], expected_plan_hash=plan["plan_hash"],
                              acknowledge_initialization_governance=True, runtime=runtime,
                              sleep=lambda _: pytest.fail("unexpected wait"), **kwargs)


def provision_foundation(workspace, runtime, hub=HUB_RG):
    plan = foundation.prepare(**foundation_args(workspace, hub), runtime=runtime)
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    return result


def test_foundation_cold_start_real_plan_without_consumer_common_or_git(workspace):
    runtime = FoundationRuntime()
    shutil.rmtree(workspace[0])
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["can_execute"] and not runtime.writes and not runtime.blobs
    assert len(plan["effects"]) == 4  # RG, first account, private container, exact operator grant.
    assert plan["principal_id"] == MEMBER
    assert plan["source"]["published_ref_verified"] is False
    assert plan["private_transition_required"] and not plan["private_transition"]["automatic_network_changes"]
    assert not plan["capabilities"]["distributed_lock_before_initialization"]
    account = plan["effects"][1]["body"]
    assert account["kind"] == "StorageV2" and account["sku"] == {"name": "Standard_LRS"}
    assert account["properties"]["isHnsEnabled"] is False
    assert account["properties"]["networkAcls"] == {
        "defaultAction": "Deny", "bypass": "None", "ipRules": [{"value": BOOTSTRAP_IP, "action": "Allow"}]}
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    assert result["bootstrap_data_plane_verified"] and result["private_transition_required"]
    network_access = result["bootstrap_network_access"]
    assert network_access["account_id"] == result["coordination"]["account_id"]
    assert network_access["rule"] == {"value": BOOTSTRAP_IP, "action": "Allow"}
    assert network_access["added_by_this_execution"] is True
    assert network_access["rule_write_state"] == "verified-created"
    assert network_access["automatic_expiration"] is False and network_access["expires_at"] is None
    assert network_access["removal_authorized"] is False
    assert result["private_transition"]["status"] == "pending"
    assert not result["private_transition"]["writer_inventory_complete"]
    assert not result["private_transition"]["private_endpoint_verified"]
    assert not result["private_transition"]["private_dns_verified"]
    assert not result["private_transition"]["authenticated_private_path_verified"]
    assert all(result["coordination"]["account_id"] in instruction
               for instruction in result["private_transition"]["cleanup_instructions"]
               if "privateLinkServiceId" in instruction)
    assert not result["runtime_ready"] and not result["leases"] and not runtime.leases
    assert json.loads(Path(result["receipt_path"]).read_bytes()) == result
    assert not Path(result["initialization_guard_path"]).exists()
    role = next(v for k, v in runtime.resources.items() if "/roleassignments/" in k)
    assert role["properties"]["principalId"] == MEMBER
    assert role["properties"]["scope"].endswith("/containers/hub-locks")
    acquire = next(i for i, e in enumerate(runtime.events) if e[0] == "blob" and e[2].get("x-ms-lease-action") == "acquire")
    assert all(i < acquire for i, e in enumerate(runtime.events) if e[0] == "arm")
    assert foundation.lock_blob(HUB_RG) in runtime.blobs
    assert not any("factorymeta" in str(x) or "listKeys" in str(x) for x in runtime.events)


def test_foundation_stable_names_reuse_and_preserve_existing_lock(workspace):
    assert foundation.coordination(HUB_RG) == foundation.coordination(HUB_RG.upper())
    assert foundation.coordination(HUB_RG) != foundation.coordination(HUB_RG + "-different")
    runtime = FoundationRuntime()
    first = provision_foundation(workspace, runtime)
    blob = foundation.lock_blob(HUB_RG)
    runtime.blobs[blob] = b"existing-lock-metadata-retained"
    before = copy.deepcopy(runtime.resources)
    writes = len(runtime.writes)
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["effects"] == []
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded" and result["coordination"] == first["coordination"]
    assert runtime.resources == before and len(runtime.writes) == writes
    assert runtime.blobs[blob] == b"existing-lock-metadata-retained"
    assert result["bootstrap_network_access"]["added_by_this_execution"] is False
    assert result["bootstrap_network_access"]["rule_write_state"] == "reused-unchanged"
    assert result["bootstrap_network_access"]["rule_origin"] == "existing-rule-retained"
    assert result["bootstrap_network_access"]["rule"] == {"value": BOOTSTRAP_IP, "action": "Allow"}
    assert result["bootstrap_network_access"]["existing_rules_must_be_retained"]


@pytest.mark.parametrize("mutate", [
    lambda a: a["tags"].update({"aifactory.factory_id": FACTORY}),
    lambda a: a["tags"].update({"aifactory.hub_scope_sha256": "wrong"}),
    lambda a: a["properties"].update(isHnsEnabled=True),
    lambda a: a["properties"].update(allowSharedKeyAccess=True),
    lambda a: a["properties"].update(allowBlobPublicAccess=True),
    lambda a: a["properties"].update(supportsHttpsTrafficOnly=False),
    lambda a: a["properties"].update(minimumTlsVersion="TLS1_0"),
    lambda a: a["properties"]["networkAcls"].update(defaultAction="Allow"),
    lambda a: a["properties"]["networkAcls"].update(bypass="AzureServices"),
    lambda a: a["properties"]["networkAcls"].update(ipRules=[{"value": "1.1.1.1", "action": "Allow"}]),
])
def test_foundation_refuses_existing_security_ownership_and_network_conflicts(workspace, mutate):
    runtime = FoundationRuntime()
    result = provision_foundation(workspace, runtime)
    mutate(runtime.resources[result["coordination"]["account_id"]])
    before = copy.deepcopy(runtime.resources)
    writes = len(runtime.writes)
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert not plan["can_execute"] and plan["blockers"]
    with pytest.raises(foundation.FoundationError, match="plan-blocked"):
        foundation_execute(plan, workspace, runtime)
    assert len(runtime.writes) == writes and runtime.resources == before


@pytest.mark.parametrize("ip", ["0.0.0.0", "10.0.0.1", "127.0.0.1", "8.8.4.0/24", "::1", "224.0.0.1", None, 134744072])
def test_foundation_requires_exact_explicit_global_ipv4(workspace, ip):
    args = foundation_args(workspace)
    args["bootstrap_public_ipv4"] = ip
    runtime = FoundationRuntime()
    with pytest.raises(foundation.FoundationError, match="public-ipv4-required"):
        foundation.prepare(**args, runtime=runtime)
    assert not runtime.writes


@pytest.mark.parametrize("registration", ["Unregistering", "Unavailable", None])
def test_foundation_missing_provider_preserves_blocker_without_dependent_cli(workspace, registration):
    class Unregistered(FoundationRuntime):
        def arm(self, method, identifier, api, **kwargs):
            if method == "GET" and identifier.lower().endswith("/providers/microsoft.storage"):
                return 200, {}, {"registrationState": registration}
            return super().arm(method, identifier, api, **kwargs)

        def az(self, *args):
            pytest.fail("Name availability must not mask missing Storage registration.")

    runtime = Unregistered()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert not plan["can_execute"]
    assert any(item.startswith("storage-provider-state-unavailable:") for item in plan["blockers"])
    assert runtime.writes == []
    with pytest.raises(foundation.FoundationError, match="plan-blocked"):
        foundation_execute(plan, workspace, runtime)
    assert runtime.writes == []


@pytest.mark.parametrize("registration", ["Registered", "NotRegistered", "Registering"])
def test_foundation_registers_only_missing_hub_provider_before_storage(workspace, registration):
    provider = f"/subscriptions/{EXTERNAL}/providers/Microsoft.Storage"
    runtime = FoundationRuntime()
    runtime.resources[provider.lower()] = {"id": provider, "registrationState": registration}
    calls = []
    native_az = runtime.az

    def az(*args):
        assert runtime.resources[provider.lower()]["registrationState"] == "Registered"
        assert args[-2:] == ("--subscription", EXTERNAL)
        calls.append(args)
        return native_az(*args)

    runtime.az = az
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    assert not runtime.writes
    provider_effects = [effect for effect in plan["effects"] if effect["kind"].startswith("provider-")]
    if registration == "Registered":
        assert not provider_effects and calls
    else:
        assert not calls
        assert provider_effects == [plan["effects"][0]]
        assert plan["effects"][0]["kind"] == ("provider-register" if registration == "NotRegistered" else "provider-wait")
        assert plan["commands"][0]["resource_id"] == provider + ("/register" if registration == "NotRegistered" else "")
        assert plan["commands"][0]["wait_for"] == "Registered"
        authority = next(item for item in plan["auth_scopes"] if item["scope"] == "/subscriptions/" + EXTERNAL)
        assert ("Microsoft.Storage/register/action" in authority["permissions"]) is (registration == "NotRegistered")
    with pytest.raises(foundation.FoundationError, match="initialization-governance-required"):
        foundation.execute(plan, state_dir=workspace[2], expected_plan_hash=plan["plan_hash"], runtime=runtime)
    assert not runtime.writes

    def sleep(_):
        assert registration == "Registering"
        assert not runtime.writes and not calls
        runtime.resources[provider.lower()]["registrationState"] = "Registered"

    result = foundation.execute(plan, state_dir=workspace[2], expected_plan_hash=plan["plan_hash"],
                                acknowledge_initialization_governance=True, runtime=runtime, sleep=sleep)
    assert result["status"] == "succeeded", result
    registrations = [item for item in runtime.writes if item[1] == "POST"]
    assert len(registrations) == (1 if registration == "NotRegistered" else 0)
    if registrations:
        assert registrations[0][2] == (provider + "/register").lower()
        assert runtime.writes[0] == registrations[0]
    assert calls and runtime.resources[provider.lower()]["registrationState"] == "Registered"
    assert not any("/subscriptions/" + SUB + "/" in item[2] for item in runtime.writes)
    rerun = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert rerun["can_execute"] and not rerun["effects"]
    writes = len(runtime.writes)
    assert foundation_execute(rerun, workspace, runtime)["status"] == "succeeded"
    assert len(runtime.writes) == writes


@pytest.mark.parametrize("failure", ["denied", "lost-response", "timeout", "failed", "expired", "name-conflict"])
def test_foundation_registration_failure_never_proceeds_to_storage(workspace, monkeypatch, failure):
    provider = f"/subscriptions/{EXTERNAL}/providers/Microsoft.Storage"
    runtime = FoundationRuntime()
    runtime.resources[provider.lower()] = {"id": provider, "registrationState": "NotRegistered"}
    original_arm = runtime.arm

    def arm(method, identifier, api, **kwargs):
        if identifier.lower() == (provider + "/register").lower():
            if failure == "denied":
                raise core.enrollment.EnrollmentError("remote-request-failed-403")
            result = original_arm(method, identifier, api, **kwargs)
            if failure == "lost-response":
                raise core.enrollment.EnrollmentError("remote-request-uncertain")
            if failure in ("timeout", "expired", "failed"):
                runtime.resources[provider.lower()]["registrationState"] = "Failed" if failure == "failed" else "Registering"
            return result
        return original_arm(method, identifier, api, **kwargs)

    runtime.arm = arm
    runtime.available = failure != "name-conflict"
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["can_execute"] and not runtime.writes
    now = [foundation.time.time()]
    monkeypatch.setattr(foundation.time, "time", lambda: now[0])

    def sleep(_):
        if failure == "expired":
            now[0] = plan["expires_at"]

    result = foundation.execute(plan, state_dir=workspace[2], expected_plan_hash=plan["plan_hash"],
                                acknowledge_initialization_governance=True, runtime=runtime, sleep=sleep)
    assert result["status"] == "uncertain" and result["reconciliation_required"]
    assert result["error"] == {
        "denied": "remote-request-failed-403", "lost-response": "remote-request-uncertain",
        "timeout": "storage-provider-registration-uncertain", "failed": "storage-provider-registration-failed",
        "expired": "foundation-review-expired", "name-conflict": "deterministic-hub-account-name-unavailable",
    }[failure]
    assert all(item[1] == "POST" and item[2] == (provider + "/register").lower() for item in runtime.writes)
    assert not runtime.blobs
    assert Path(result["initialization_guard_path"]).exists()
    assert result["bootstrap_network_access"]["rule_write_state"] == "not-attempted"


def test_foundation_global_name_collision_does_not_pick_a_random_fallback(workspace):
    runtime = FoundationRuntime()
    runtime.available = False
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert not plan["can_execute"]
    assert any("deterministic-hub-account-name-unavailable" in b for b in plan["blockers"])
    assert not runtime.writes


def test_foundation_needs_explicit_initialization_governance(workspace):
    runtime = FoundationRuntime()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    with pytest.raises(foundation.FoundationError, match="initialization-governance-required"):
        foundation.execute(plan, state_dir=workspace[2], expected_plan_hash=plan["plan_hash"], runtime=runtime)
    assert not runtime.writes and not runtime.blobs


def test_foundation_lost_account_write_persists_uncertainty_blocks_new_plan(workspace):
    runtime = FoundationRuntime()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)

    def lose_response(identifier):
        if "/storageaccounts/" in identifier:
            raise core.enrollment.EnrollmentError("remote-request-uncertain")

    runtime.after_write = lose_response
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "uncertain" and result["pending_effect"] == 1
    assert result["bootstrap_network_access"]["rule"] == {"value": BOOTSTRAP_IP, "action": "Allow"}
    assert result["bootstrap_network_access"]["added_by_this_execution"] is None
    assert result["bootstrap_network_access"]["rule_write_state"] == "submitted-outcome-unknown"
    assert result["private_transition"]["status"] == "pending"
    assert result["private_transition"]["cleanup_instructions"]
    assert Path(result["initialization_guard_path"]).exists()
    assert json.loads(Path(result["receipt_path"]).read_bytes()) == result
    assert not runtime.leases  # Cannot claim distributed protection during account creation.
    runtime.after_write = None
    fresh = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    before = copy.deepcopy(runtime.writes)
    with pytest.raises(FileExistsError):
        foundation_execute(fresh, workspace, runtime)
    assert runtime.writes == before


def test_foundation_lock_conflict_retains_existing_lease_without_break(workspace):
    runtime = FoundationRuntime()
    provision_foundation(workspace, runtime)
    blob = foundation.lock_blob(HUB_RG)
    runtime.leases[blob] = "another-owner"
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "uncertain" and result["leases"]
    assert runtime.leases[blob] == "another-owner"
    assert Path(result["initialization_guard_path"]).exists()
    assert not any(e[0] == "blob" and e[2].get("x-ms-lease-action") == "break" for e in runtime.events)


def test_foundation_does_not_enable_public_path_on_existing_private_account(workspace):
    runtime = FoundationRuntime()
    initial = provision_foundation(workspace, runtime)
    props = runtime.resources[initial["coordination"]["account_id"]]["properties"]
    props["publicNetworkAccess"] = "Disabled"
    props["networkAcls"]["ipRules"] = []
    before = len(runtime.writes)
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["can_execute"] and not plan["private_transition_required"]
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded" and len(runtime.writes) == before
    assert result["private_transition"]["runner_reachability_verified"] is False


@pytest.mark.parametrize("change,code", [
    ("source", "source-changed"), ("principal", "live-state-or-plan-changed"),
    ("plan", "plan-hash-mismatch"), ("expired", "review-expired"),
])
def test_foundation_source_identity_and_plan_drift_stop_before_writes(workspace, change, code):
    runtime = FoundationRuntime()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    if change == "source":
        path = workspace[1] / foundation.SOURCE_FILES[0]
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "principal":
        runtime.operator = GROUP
    elif change == "plan":
        plan["effects"][0]["body"]["location"] = "eastus"
    else:
        plan["expires_at"] = 0
        plan["plan_hash"] = foundation.digest({k: v for k, v in plan.items() if k != "plan_hash"})
    with pytest.raises(foundation.FoundationError, match=code):
        foundation_execute(plan, workspace, runtime)
    assert not runtime.writes and not runtime.blobs


@pytest.mark.parametrize("hub_sub", [SUB, EXTERNAL])
def test_shared_standard_blob_coordinates_real_prerequisite_chain(workspace, hub_sub):
    hub = f"/subscriptions/{hub_sub}/resourcegroups/shared-hub"
    foundation_runtime = FoundationRuntime()
    result = provision_foundation(workspace, foundation_runtime, hub)
    runtime = Runtime()
    runtime.resources.update(copy.deepcopy(foundation_runtime.resources))
    del runtime.resources[ACCOUNT]  # Shared mode has NO factory-common storage dependency.
    args = external_arguments(workspace, setup=False)
    args["bootstrap_config"]["access_hub_subscription_id"] = hub_sub
    args["context"].update(coordination_mode="connectivity-hub", hub_resource_group_id=hub,
                           coordination=result["coordination"])
    plan = core.prepare(**args, runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    assert hub in plan["lock_scopes"] and hub not in plan["context"]["owned_resource_group_ids"]
    assert not any("factorymeta" in str(s) for s in plan["auth_scopes"])
    execution = execute(plan, workspace, runtime)
    assert execution["status"] == "succeeded", execution
    assert foundation.lock_blob(hub) in runtime.blobs
    assert execution["bindings"]["network"]["owned"] is False


def test_shared_coordination_cannot_be_factory_owned_or_wrong_hub(workspace):
    runtime = Runtime()
    args = external_arguments(workspace)
    args["context"].update(coordination_mode="connectivity-hub", hub_resource_group_id=OWNED,
                           coordination=foundation.coordination(OWNED))
    with pytest.raises(core.PrerequisiteError, match="must-not-be-factory-owned"):
        core.prepare(**args, runtime=runtime)
    args["context"].update(hub_resource_group_id=HUB_RG, coordination=foundation.coordination(HUB_RG + "-wrong"))
    with pytest.raises(core.PrerequisiteError, match="canonical-shared-hub-coordination-required"):
        core.prepare(**args, runtime=runtime)


def test_no_hub_cannot_silently_bypass_existing_core_leases(workspace):
    args = arguments(workspace)
    args["context"].pop("coordination")
    with pytest.raises(core.PrerequisiteError, match="exact-coordination-required"):
        core.prepare(**args, runtime=Runtime())


def test_foundation_real_cloud_transport_uses_exact_cached_oid_and_oauth_only():
    coords = foundation.coordination(HUB_RG)
    commands, requests = [], []

    def run(argv, **kwargs):
        commands.append(argv)
        assert kwargs["shell"] is False and kwargs["capture_output"] is True
        audience = argv[argv.index("--resource") + 1]
        claims = {"tid": TENANT, "oid": MEMBER, "aud": audience, "exp": core.time.time() + 3600}
        token = "header." + base64.urlsafe_b64encode(core.canonical(claims)).decode().rstrip("=") + ".opaque"
        return SimpleNamespace(returncode=0, stdout=core.canonical({"accessToken": token}))

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return b""

    class Opener:
        def open(self, request, **kwargs):
            requests.append(request)
            return Response()

    cloud = foundation.Cloud({"tenant_id": TENANT, "subscription_id": EXTERNAL}, coords,
                             command_runner=run, opener=Opener())
    assert cloud.principal() == MEMBER
    cloud.blob("HEAD")
    assert requests[0].full_url == coords["account_url"] + "/hub-locks?restype=container"
    assert requests[0].get_header("Authorization").startswith("Bearer ")
    assert all(argv[argv.index("--subscription") + 1] == EXTERNAL for argv in commands)
    assert not any("login" in argv or "listKeys" in argv for argv in commands)
    serialized = core.canonical({"coordinates": coords, "principal": cloud.principal()}).decode()
    assert "opaque" not in serialized and "accessToken" not in serialized


@pytest.mark.parametrize("registered", [False, True])
def test_foundation_full_real_cloud_prepare_execute_transport_chain(workspace, registered):
    transport = FoundationRuntime()
    provider = f"/subscriptions/{EXTERNAL}/providers/Microsoft.Storage"
    transport.resources[provider.lower()] = {"id": provider, "registrationState": "Registered" if registered else "NotRegistered"}
    requests = []
    coordinates = foundation.coordination(HUB_RG)

    def run(argv, **kwargs):
        assert argv[0] == "az" and kwargs["shell"] is False
        if argv[1:4] == ["storage", "account", "check-name"]:
            assert transport.resources[provider.lower()]["registrationState"] == "Registered"
            return SimpleNamespace(returncode=0, stdout=b'{"nameAvailable":true}')
        assert argv[1:3] == ["account", "get-access-token"]
        claims = {"tid": TENANT, "oid": MEMBER, "aud": argv[argv.index("--resource") + 1],
                  "exp": core.time.time() + 3600}
        token = "header." + base64.urlsafe_b64encode(core.canonical(claims)).decode().rstrip("=") + ".opaque"
        return SimpleNamespace(returncode=0, stdout=core.canonical({"accessToken": token}))

    class Response:
        def __init__(self, status, headers, value):
            self.status, self.headers = status, headers
            self.data = value if isinstance(value, bytes) else core.canonical(value) if value is not None else b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return self.data[:limit]

    class Opener:
        def open(self, request, **kwargs):
            parsed = urlsplit(request.full_url)
            method = request.get_method()
            requests.append((method, request.full_url))
            assert request.get_header("Authorization").startswith("Bearer ")
            assert parsed.scheme == "https" and not parsed.username and not parsed.password
            transport.read_only = method in ("GET", "HEAD")
            transport.serialized_provisioning = True
            data = core.enrollment.parse_json(request.data) if request.data else None
            if parsed.hostname == "management.azure.com":
                api = parse_qs(parsed.query)["api-version"][0]
                if parsed.path.lower().endswith("/roleassignments"):
                    return Response(200, {}, {"value": transport.collection(parsed.path, api)})
                return Response(*transport.arm(method, parsed.path, api, data=data, allowed=(200, 404)))
            assert parsed.hostname == urlsplit(coordinates["account_url"]).hostname
            assert parsed.path.startswith("/hub-locks")
            if method == "HEAD":
                return Response(*transport.blob("HEAD"))
            blob = unquote(parsed.path.removeprefix("/hub-locks/"))
            headers = {}
            for key, value in request.header_items():
                key = key.lower()
                if key.startswith("x-ms-") and key not in ("x-ms-version", "x-ms-date"):
                    headers[key] = value
                if key in ("if-match", "if-none-match"):
                    headers[{"if-match": "If-Match", "if-none-match": "If-None-Match"}[key]] = value
            return Response(*transport.blob(method, blob, data=data, headers=headers,
                                            query=("?" + parsed.query) if parsed.query else "",
                                            allowed=(200, 201, 412)))

    cloud = foundation.Cloud({"tenant_id": TENANT, "subscription_id": EXTERNAL}, coordinates,
                             command_runner=run, opener=Opener())
    plan = foundation.prepare(**foundation_args(workspace), runtime=cloud)
    assert plan["can_execute"] and not transport.writes
    result = foundation_execute(plan, workspace, cloud)
    assert result["status"] == "succeeded", result
    assert result["coordination"] == coordinates and result["bootstrap_data_plane_verified"]
    assert any(method == "HEAD" and url.endswith("hub-locks?restype=container") for method, url in requests)
    assert any(method == "PUT" and "?comp=lease" in url for method, url in requests)
    assert sum(method == "POST" and "/register?" in url for method, url in requests) == (0 if registered else 1)
    assert json.loads(Path(result["receipt_path"]).read_bytes()) == result


def test_foundation_resource_appearing_after_review_is_not_overwritten(workspace):
    runtime = FoundationRuntime()
    account = foundation.coordination(HUB_RG)["account_id"]
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    foreign = {"id": account, "tags": {"foreign": "retain"}, "properties": {"isHnsEnabled": True}}

    def appeared(identifier):
        if identifier == HUB_RG:
            runtime.resources[account] = copy.deepcopy(foreign)

    runtime.after_write = appeared
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "uncertain"
    assert result["error"].startswith("foundation-resource-appeared-after-review:")
    assert runtime.resources[account] == foreign
    assert len(runtime.writes) == 1


def test_foundation_second_operator_grant_is_container_scoped_only(workspace):
    runtime = FoundationRuntime()
    first = provision_foundation(workspace, runtime)
    runtime.operator = GROUP
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert len(plan["effects"]) == 1
    effect = plan["effects"][0]
    assert effect["body"]["properties"]["principalId"] == GROUP
    assert effect["id"].startswith(first["coordination"]["account_id"] + "/blobservices/default/containers/hub-locks/")
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded"


def test_foundation_lost_acquisition_retains_proposed_id_and_lease(workspace):
    runtime = FoundationRuntime()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)

    def lost():
        raise core.enrollment.EnrollmentError("remote-request-uncertain")

    runtime.on_acquire = lost
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "uncertain"
    assert result["lease_state"] == "proposed-acquisition-not-yet-confirmed"
    assert runtime.leases[foundation.lock_blob(HUB_RG)] == result["leases"][HUB_RG]
    assert json.loads(Path(result["receipt_path"]).read_bytes()) == result


def test_foundation_rbac_propagation_retries_only_authenticated_reads(workspace):
    class Propagating(FoundationRuntime):
        attempts = 0

        def blob(self, method, *args, **kwargs):
            if method == "HEAD":
                self.attempts += 1
                if self.attempts <= 2:
                    raise core.enrollment.EnrollmentError("remote-request-failed-403")
            return super().blob(method, *args, **kwargs)

    runtime, pauses = Propagating(), []
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    result = foundation.execute(plan, state_dir=workspace[2], expected_plan_hash=plan["plan_hash"],
                                acknowledge_initialization_governance=True, runtime=runtime, sleep=pauses.append)
    assert result["status"] == "succeeded"
    assert pauses == [5, 5] and len(runtime.writes) == 4


def test_foundation_reuses_immutable_shared_account_location_for_another_factory_region(workspace):
    runtime = FoundationRuntime()
    first = provision_foundation(workspace, runtime)
    before = copy.deepcopy(runtime.resources)
    args = foundation_args(workspace)
    args["location"] = "eastus"
    plan = foundation.prepare(**args, runtime=runtime)
    assert plan["can_execute"] and plan["effects"] == []
    assert any("location is retained unchanged: swedencentral" in w for w in plan["warnings"])
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded" and result["coordination"] == first["coordination"]
    assert runtime.resources == before


def test_foundation_never_queries_children_of_known_absent_parents(workspace):
    class MissingParentRuntime(FoundationRuntime):
        def arm(self, method, identifier, api, **kwargs):
            if method == "GET":
                lower = identifier.lower()
                if "/roleassignments/" in lower:
                    parent = lower.split("/providers/microsoft.authorization/")[0]
                    assert parent in self.resources, "Azure can reject an absent role scope as InvalidScope"
                elif "/blobservices/" in lower:
                    parent = lower.split("/blobservices/")[0]
                    assert parent in self.resources
                elif "/storageaccounts/" in lower:
                    parent = lower.split("/providers/microsoft.storage/")[0]
                    assert parent in self.resources
            return super().arm(method, identifier, api, **kwargs)

    runtime = MissingParentRuntime()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert len([o for o in plan["observations"] if o.get("absence_derived_from_parent")]) == 3
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result


def test_foundation_reuses_equivalent_existing_noncanonical_container_role(workspace):
    runtime = FoundationRuntime()
    provision_foundation(workspace, runtime)
    canonical_id = next(k for k in runtime.resources if "/roleassignments/" in k)
    role = runtime.resources.pop(canonical_id)
    alternate = canonical_id.rsplit("/", 1)[0] + "/" + str(uuid4())
    role["id"] = alternate
    role["properties"]["principalId"] = role["properties"]["principalId"].upper()
    role["properties"]["roleDefinitionId"] = role["properties"]["roleDefinitionId"].upper()
    role["properties"]["scope"] = role["properties"]["scope"].upper()
    runtime.resources[alternate] = role
    before = copy.deepcopy(runtime.resources)
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["can_execute"] and not plan["effects"]
    assert foundation_execute(plan, workspace, runtime)["status"] == "succeeded"
    assert runtime.resources == before and canonical_id not in runtime.resources


def test_foundation_does_not_bypass_conditioned_existing_container_role(workspace):
    runtime = FoundationRuntime()
    provision_foundation(workspace, runtime)
    canonical_id = next(k for k in runtime.resources if "/roleassignments/" in k)
    role = runtime.resources.pop(canonical_id)
    alternate = canonical_id.rsplit("/", 1)[0] + "/" + str(uuid4())
    role["id"] = alternate
    role["properties"].update(condition="@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'restricted'",
                              conditionVersion="2.0")
    runtime.resources[alternate] = role
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert not plan["can_execute"] and not plan["effects"]
    assert "hub-container-conditioned-role-requires-explicit-review:" + alternate in plan["blockers"]


@pytest.mark.parametrize("error,allowed", [("remote-request-failed-403", True),
                                          ("remote-request-failed-401", False),
                                          ("remote-request-uncertain", False)])
def test_foundation_new_grant_defers_only_known_authorization_propagation(workspace, error, allowed):
    runtime = FoundationRuntime()
    provision_foundation(workspace, runtime)
    runtime.operator = GROUP
    original = runtime.blob

    def inaccessible(method, *args, **kwargs):
        if method == "HEAD":
            raise core.enrollment.EnrollmentError(error)
        return original(method, *args, **kwargs)

    runtime.blob = inaccessible
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    assert plan["can_execute"] is allowed
    if not allowed:
        assert any("bootstrap-entra-data-plane-unreachable:" in b and error in b for b in plan["blockers"])


def test_foundation_verifies_new_account_security_before_rbac_and_lease(workspace):
    runtime = FoundationRuntime()
    account = foundation.coordination(HUB_RG)["account_id"]

    def inject_unapproved_rule(identifier):
        if identifier == account:
            runtime.resources[account]["properties"]["networkAcls"]["resourceAccessRules"] = [
                {"resourceId": "/unapproved", "tenantId": TENANT}]

    runtime.after_write = inject_unapproved_rule
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "uncertain" and result["error"] == "hub-coordination-network-conflict"
    assert len(runtime.writes) == 2 and not runtime.leases
    assert not any("/roleassignments/" in w[2] for w in runtime.writes)


def test_shared_prerequisites_contend_on_exact_foundation_hub_lease(workspace):
    foundation_runtime = FoundationRuntime()
    result = provision_foundation(workspace, foundation_runtime)
    runtime = Runtime()
    runtime.resources.update(copy.deepcopy(foundation_runtime.resources))
    args = external_arguments(workspace, setup=False)
    args["context"].update(coordination_mode="connectivity-hub", hub_resource_group_id=HUB_RG,
                           coordination=result["coordination"])
    plan = core.prepare(**args, runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    physical_blob = foundation.lock_blob(HUB_RG)
    runtime.blobs[physical_blob] = b"retain"
    runtime.leases[physical_blob] = "foundation-writer"
    receipt = execute(plan, workspace, runtime)
    assert receipt["status"] == "uncertain" and receipt["error"] == "lease-already-present"
    assert runtime.leases[physical_blob] == "foundation-writer"
    assert not runtime.writes and runtime.blobs[physical_blob] == b"retain"


def test_shared_hub_coordinates_are_identical_for_gha_and_ado_factory_ids(workspace):
    shared_runtime = FoundationRuntime()
    result = provision_foundation(workspace, shared_runtime)
    runtime = Runtime()
    runtime.resources.update(copy.deepcopy(shared_runtime.resources))
    args = external_arguments(workspace, setup=False)
    args["context"].update(coordination_mode="connectivity-hub", hub_resource_group_id=HUB_RG,
                           coordination=result["coordination"])
    gha = core.prepare(**args, runtime=runtime)
    path = workspace[0] / "azurefactory" / "register.json"
    register = json.loads(path.read_bytes())
    factory = register["factories"][0]
    factory["id"] = GROUP
    factory["scale_sets"][0].update(id=MEMBER, orchestrator="ado")
    path.write_bytes(core.canonical(register))
    args["scope"].update(factory_id=GROUP, scale_set_id=MEMBER)
    runtime.resources[OWNED]["tags"].update({"aifactory.factory_id": GROUP, "aifactory.scaleset_id": MEMBER})
    ado = core.prepare(**args, runtime=runtime)
    assert gha["can_execute"] and ado["can_execute"]
    assert gha["context"]["coordination"] == ado["context"]["coordination"] == result["coordination"]
    assert HUB_RG in gha["lock_scopes"] and HUB_RG in ado["lock_scopes"]
    assert foundation.lock_blob(HUB_RG) == core.enrollment.lock_blob(HUB_RG)


def test_foundation_two_file_source_bundle_is_sufficient_without_common_or_git(workspace):
    source = workspace[1]
    for relative in set(core.SOURCE_FILES) - set(foundation.SOURCE_FILES):
        (source / relative).unlink()
    expected = foundation.source_fingerprint(source)
    code = (
        "import json,sys;from pathlib import Path;"
        "sys.path.insert(0,str(Path(sys.argv[1])/'bootstrap'/'lib'));"
        "import hub_lock_foundation as h;"
        "print(json.dumps(h.verify_source_snapshot(source_root=sys.argv[1],expected_payload_sha256=sys.argv[2])))"
    )
    result = REAL_SUBPROCESS_RUN([sys.executable, "-I", "-B", "-c", code, str(source), expected["payload_sha256"]],
                                 cwd=workspace[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("invalid", ["tenant", "principal", "audience", "expired"])
def test_foundation_native_cloud_rejects_mismatched_identity_and_token_claims(invalid):
    coords = foundation.coordination(HUB_RG)

    def run(argv, **kwargs):
        audience = argv[argv.index("--resource") + 1]
        claims = {"tid": TENANT, "oid": MEMBER, "aud": audience, "exp": core.time.time() + 3600}
        if audience == core.enrollment.STORAGE:
            if invalid == "tenant":
                claims["tid"] = EXTERNAL
            elif invalid == "principal":
                claims["oid"] = GROUP
            elif invalid == "audience":
                claims["aud"] = core.enrollment.ARM + "/"
            else:
                claims["exp"] = 1
        token = "header." + base64.urlsafe_b64encode(core.canonical(claims)).decode().rstrip("=") + ".secret-must-not-leak"
        return SimpleNamespace(returncode=0, stdout=core.canonical({"accessToken": token}))

    class Opener:
        def open(self, *args, **kwargs):
            pytest.fail("No HTTP request permitted after token validation fails")

    cloud = foundation.Cloud({"tenant_id": TENANT, "subscription_id": EXTERNAL}, coords,
                             command_runner=run, opener=Opener())
    with pytest.raises((foundation.FoundationError, core.enrollment.EnrollmentError)) as captured:
        cloud.principal()
    assert "secret-must-not-leak" not in str(captured.value)


def test_foundation_rehashed_plan_cannot_hide_pending_private_transition(workspace):
    runtime = FoundationRuntime()
    plan = foundation.prepare(**foundation_args(workspace), runtime=runtime)
    plan["private_transition_required"] = False
    plan["plan_hash"] = foundation.digest({k: v for k, v in plan.items() if k != "plan_hash"})
    with pytest.raises(foundation.FoundationError, match="live-state-or-plan-changed:private_transition_required"):
        foundation_execute(plan, workspace, runtime)
    assert not runtime.writes and not runtime.blobs
