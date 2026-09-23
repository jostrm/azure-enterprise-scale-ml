"""Actual transition planner/source/provider validation; no Azure/auth invocations."""

import base64
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
import hub_private_transition as core

spec = importlib.util.spec_from_file_location("hub_private_probe", ROOT / core.PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PRINCIPAL = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FOUNDATION = "dddddddd-dddd-dddd-dddd-dddddddddddd"
HUB = f"/subscriptions/{SUB}/resourcegroups/hub"
VNET = HUB + "/providers/microsoft.network/virtualnetworks/hub-vnet"
SUBNET = VNET + "/subnets/endpoints"
ZONE = HUB + "/providers/microsoft.network/privatednszones/privatelink.blob.core.windows.net"
VM = HUB + "/providers/microsoft.compute/virtualmachines/runner-vm"
COORDS = core.foundation.coordination(HUB)
ACCOUNT = COORDS["account_id"]
PE = HUB + "/providers/microsoft.network/privateendpoints/" + ACCOUNT.rsplit("/", 1)[1] + "-blob"
NIC = HUB + "/providers/microsoft.network/networkinterfaces/endpoint-nic"
RECORD = ZONE + "/a/" + ACCOUNT.rsplit("/", 1)[1]
IP = "10.20.1.4"
CONTEXT = {"private_endpoint_subnet_id": SUBNET, "dns_zone_id": ZONE, "dns_vnet_ids": [VNET],
           "closure_writer_id": "factory-one", "foundation_receipt": {"plan_id": FOUNDATION}}


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LIVE CLOUD/AUTH/SLEEP FORBIDDEN")
    monkeypatch.setattr(core.enrollment.subprocess, "run", fail)
    monkeypatch.setattr(core.enrollment, "build_opener", fail)
    monkeypatch.setattr(probe, "build_opener", fail)
    monkeypatch.setattr(core.time, "sleep", fail)


class Runtime(core.Cloud):
    def __init__(self):
        self.read_only = True
        self.serialized_provisioning = False
        self.resources = {}
        self.blobs = {}
        self.writes = []
        self.requests = []
        self.leases = {}
        self.fail = None
        self.mutate_result = None
        self.mutate_provider = None
        self.operations = {}
        self.add(ACCOUNT, core.foundation.account_body(HUB, "swedencentral", "8.8.8.8"))
        self.add(SUBNET, {"properties": {"delegations": []}})
        self.add(VNET, {"location": "swedencentral"})
        self.add(VM, {"location": "swedencentral", "identity": {"principalId": PRINCIPAL},
                     "properties": {"storageProfile": {"osDisk": {"osType": "Linux"}}}})
        writer = {"provider": "gha", "repository": "https://github.com/company/factory", "repository_id": 10,
                  "runner_id": 20, "runner_name": "private-runner", "vm_id": VM,
                  "runner_config_path": "/opt/runner/.runner", "principal_id": PRINCIPAL, "tenant_id": TENANT,
                  "source_commit": "a" * 40, "probe_path": "bootstrap/templates/hub_private_probe.py"}
        self.blobs[core.REGISTRY] = {"schema": 1, "hub_resource_group_id": HUB, "inventory_complete": True,
                                    "writers": {"factory-one": writer}}
        self.blobs[core.COORDINATION] = {"schema": 1, "protocol": "aifactory-physical-lock-v1",
                    "enforcement": "all-writers-exclusive", "revision": 1, "writers": {
                        "factory-one": {"kind": "gha", "repository": writer["repository"],
                        "deployment_object_id": PRINCIPAL, "runner": {"kind": "self-hosted", "os": "linux"}}},
                    "scopes": {HUB: {"writers": ["factory-one"]}}}
        self.blobs["bootstrap/foundation/" + FOUNDATION + ".json"] = {
            "status": "succeeded", "hub_resource_group_id": HUB, "coordination": COORDS,
            "bootstrap_network_access": {"account_id": ACCOUNT, "added_by_this_execution": True,
                "rule_write_state": "verified-created", "rule_origin": "planned-with-new-account",
                "rule": {"value": "8.8.8.8", "action": "Allow"}}}

    def add(self, identifier, body):
        value = copy.deepcopy(body)
        value.update(id=identifier, etag='"' + core.digest(value)[:12] + '"')
        value.setdefault("properties", {}).setdefault("provisioningState", "Succeeded")
        if "/virtualnetworklinks/" in identifier:
            value["properties"].setdefault("virtualNetworkLinkState", "Completed")
        self.resources[identifier] = value
        return value

    def principal(self):
        return PRINCIPAL

    def collection(self, identifier, api):
        return [copy.deepcopy(v) for k, v in self.resources.items() if k.startswith(identifier.lower() + "/")]

    def provider_read(self, writer, path):
        if path.endswith("/actions/runners/20"):
            value = {"id": 20, "name": "private-runner", "os": "linux", "status": "online"}
        elif "/actions/runners?" in path:
            value = {"runners": [{"id": 20, "name": "private-runner", "os": "linux", "status": "online"}]}
        elif "/commits/" in path:
            value = {"sha": "a" * 40}
        elif "/contents/" in path:
            value = {"type": "file", "encoding": "base64",
                     "content": base64.b64encode((ROOT / core.PROBE).read_bytes()).decode()}
        else:
            value = {"id": 10, "full_name": "company/factory", "default_branch": "main"}
        if self.mutate_provider:
            self.mutate_provider(path, value)
        return value

    def foundation_proofs(self):
        return [core._blob(self, name) for name in self.blobs if name.startswith("bootstrap/foundation/")]

    def arm(self, method, identifier, api, data=None, headers=None, allowed=(200,)):
        identifier = identifier.lower()
        if method == "GET":
            value = self.resources.get(identifier)
            return (200, {"etag": value["etag"]} if value.get("etag") else {}, copy.deepcopy(value)) if value else (404, {}, None)
        assert not self.read_only and self.serialized_provisioning
        self.writes.append((method, identifier, copy.deepcopy(data)))
        if self.fail == identifier:
            raise core.TransitionError("simulated-arm-failure")
        value = self.add(identifier, data)
        if identifier == PE:
            props = value["properties"]
            props["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"] = {"status": "Approved"}
            props["networkInterfaces"] = [{"id": NIC}]
            self.add(NIC, {"properties": {"privateEndpoint": {"id": PE},
                     "ipConfigurations": [{"properties": {"privateIPAddress": IP}}]}})
        if identifier.endswith("/privatednszonegroups/default"):
            config = value["properties"]["privateDnsZoneConfigs"][0]["properties"]
            name = ACCOUNT.rsplit("/", 1)[1]
            config["recordSets"] = [{"recordType": "A", "recordSetName": name,
                "fqdn": name + ".privatelink.blob.core.windows.net", "ttl": 10, "ipAddresses": [IP]}]
            self.add(RECORD, {"properties": {"aRecords": [{"ipv4Address": IP}], "ttl": 10}})
        return 201, {"etag": value["etag"]}, copy.deepcopy(value)

    def blob(self, method, blob, *, data=None, headers=None, allowed=(200,), query=""):
        headers = headers or {}
        if method == "GET":
            if blob in self.blobs:
                value = copy.deepcopy(self.blobs[blob])
                return 200, {"etag": core.digest(value)}, value
            return 404, {}, None
        assert not self.read_only
        action = headers.get("x-ms-lease-action")
        if action == "acquire":
            assert blob not in self.leases
            self.leases[blob] = headers["x-ms-proposed-lease-id"]
        elif action in ("release", "renew"):
            assert self.leases[blob] == headers["x-ms-lease-id"]
            if action == "release":
                del self.leases[blob]
        else:
            self.blobs[blob] = copy.deepcopy(data)
        return 201 if action != "renew" else 200, {"etag": "blob-etag"}, None

    def run_probe(self, writer, request, script, *, resume=False):
        assert not self.read_only and script == core._probe_bytes(ROOT)
        self.requests.append(copy.deepcopy(request))
        if resume:
            return self.operations[request["operation_id"]]
        if self.fail == request["writer_id"] or self.fail == request["phase"]:
            raise core.TransitionError("simulated-private-probe-failure")
        result = {k: request[k] for k in ("nonce", "plan_hash", "writer_id", "tenant_id", "principal_id",
                  "source_commit", "source_sha256", "operation_id", "phase", "runner_id", "repository")}
        result.update(success=True, at=time.time(), addresses=[IP])
        if self.mutate_result:
            self.mutate_result(result)
        if request["phase"] == "close":
            self.resources[ACCOUNT]["properties"].update(copy.deepcopy(request["desired_network"]))
            self.leases.pop(core.foundation.lock_blob(HUB))
            for name in request.get("registry_leases", {}):
                self.leases.pop(name)
        self.operations[request["operation_id"]] = result
        return result


def plan(runtime, context=None):
    return core.prepare(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB,
                        context=context or CONTEXT, runtime=runtime)


def execute(runtime, prepared, state_dir):
    return core.execute(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                        state_dir=state_dir, runtime=runtime)


def test_plan_creates_native_pe_dns_and_no_local_probe():
    runtime = Runtime()
    prepared = plan(runtime)
    assert prepared["can_execute"] and prepared["private_ip"] is None
    assert {e["id"] for e in prepared["effects"]} >= {PE, ZONE, PE + "/privatednszonegroups/default"}
    assert prepared["desired_network"]["publicNetworkAccess"] == "Disabled"
    assert runtime.writes == [] and runtime.requests == []
    assert prepared["source"]["files"][core.PROBE]


def test_execute_native_stages_and_repeat_private_reuse(tmp_path):
    runtime = Runtime()
    prepared = plan(runtime)
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "succeeded", result
    assert result["runtime_ready"] and result["lease_state"] == "released"
    assert [r["phase"] for r in runtime.requests] == ["probe", "close"]
    assert all(r["private_ip"] == IP for r in runtime.requests)
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Disabled"
    assert not runtime.leases
    repeated = plan(runtime)
    assert repeated["effects"] == []
    assert repeated["foundation_proof"] is None
    assert execute(runtime, repeated, tmp_path)["status"] == "succeeded"


@pytest.mark.parametrize("field,value", [
    ("principal_id", "00000000-0000-0000-0000-000000000000"), ("repository", "https://github.com/wrong/repo"),
    ("tenant_id", "00000000-0000-0000-0000-000000000000"), ("runner_id", 999),
    ("source_commit", "b" * 40), ("nonce", "replay"), ("at", 1), ("addresses", ["8.8.8.8"]),
])
def test_forged_replayed_wrong_identity_probe_never_closes(tmp_path, field, value):
    runtime = Runtime()
    prepared = plan(runtime)
    runtime.mutate_result = lambda result: result.update({field: value})
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain" and not result["runtime_ready"]
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Enabled"
    assert runtime.leases


@pytest.mark.parametrize("path_match,field,value", [
    ("repos/company/factory", "id", 999), ("/actions/runners/", "name", "wrong"),
    ("/actions/runners/", "status", "offline"), ("/commits/", "sha", "b" * 40),
    ("/contents/", "content", base64.b64encode(b"unreviewed").decode()),
])
def test_provider_independent_attestation_rejects_mismatch(path_match, field, value):
    runtime = Runtime()
    def mutate(path, body):
        if (path == path_match if path_match.startswith("repos/") else path_match in path):
            body[field] = value
    runtime.mutate_provider = mutate
    with pytest.raises(core.TransitionError):
        plan(runtime)


def test_vm_principal_mismatch():
    runtime = Runtime()
    runtime.resources[VM]["identity"]["principalId"] = "0" * 36
    with pytest.raises(core.TransitionError, match="managed-identity"):
        plan(runtime)


def test_unknown_writer_and_explicit_deenrollment():
    runtime = Runtime()
    runtime.blobs[core.COORDINATION]["writers"]["unknown"] = {}
    with pytest.raises(core.TransitionError, match="unknown-hub-writer"):
        plan(runtime)
    del runtime.blobs[core.COORDINATION]["writers"]["unknown"]
    runtime.blobs[core.REGISTRY]["writers"]["unknown"] = {
        "status": "inactive", "de_enrollment_revision": 1, "reason": "retired factory"}
    assert plan(runtime)["can_execute"]
    runtime.blobs[core.COORDINATION]["scopes"][HUB]["writers"].append("unknown")
    with pytest.raises(core.TransitionError, match="unknown-scope-writer"):
        plan(runtime)


def test_many_factories_each_probe_before_close(tmp_path):
    runtime = Runtime()
    runtime.blobs[core.REGISTRY]["writers"]["factory-two"] = copy.deepcopy(runtime.blobs[core.REGISTRY]["writers"]["factory-one"])
    runtime.blobs[core.COORDINATION]["writers"]["factory-two"] = copy.deepcopy(runtime.blobs[core.COORDINATION]["writers"]["factory-one"])
    runtime.blobs[core.COORDINATION]["scopes"][HUB]["writers"].append("factory-two")
    prepared = plan(runtime)
    runtime.fail = "factory-two"
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain"
    assert all(r["phase"] != "close" for r in runtime.requests)
    runtime.fail = None
    recovered = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                             state_dir=tmp_path, runtime=runtime)
    assert recovered["status"] == "succeeded", recovered
    assert len(runtime.requests[-1]["writer_proofs"]) == 2


def test_existing_firewall_paths_not_replaced(tmp_path):
    runtime = Runtime()
    acl = runtime.resources[ACCOUNT]["properties"]["networkAcls"]
    acl["ipRules"].append({"value": "9.9.9.9", "action": "Allow"})
    acl["virtualNetworkRules"] = [{"id": SUBNET, "action": "Allow"}]
    acl["resourceAccessRules"] = [{"resourceId": VM, "tenantId": TENANT}]
    expected = copy.deepcopy(acl)
    expected["ipRules"] = expected["ipRules"][1:]
    prepared = plan(runtime)
    assert prepared["desired_network"]["networkAcls"] == expected
    assert prepared["desired_network"]["publicNetworkAccess"] == "Enabled"
    assert execute(runtime, prepared, tmp_path)["status"] == "succeeded"
    assert runtime.resources[ACCOUNT]["properties"]["networkAcls"] == expected


def test_reused_rule_unknown_provenance_blocks():
    runtime = Runtime()
    runtime.blobs["bootstrap/foundation/" + FOUNDATION + ".json"]["bootstrap_network_access"]["added_by_this_execution"] = False
    with pytest.raises(core.TransitionError, match="provenance"):
        plan(runtime)


def test_wrong_dns_and_absent_subnet_block():
    runtime = Runtime()
    runtime.add(RECORD, {"properties": {"aRecords": [{"ipv4Address": "10.99.99.99"}]}})
    with pytest.raises(core.TransitionError, match="dns-record"):
        plan(runtime)
    runtime.resources.pop(RECORD)
    runtime.resources.pop(SUBNET)
    with pytest.raises(core.TransitionError, match="subnet-missing"):
        plan(runtime)


@pytest.mark.parametrize("mutation", ["target", "subnet", "approval", "nic"])
def test_wrong_existing_private_endpoint(tmp_path, mutation):
    runtime = Runtime()
    assert execute(runtime, plan(runtime), tmp_path)["status"] == "succeeded"
    props = runtime.resources[PE]["properties"]
    if mutation == "target":
        props["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceId"] = VM
    elif mutation == "subnet":
        props["subnet"]["id"] = SUBNET + "-other"
    elif mutation == "approval":
        props["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]["status"] = "Pending"
    else:
        runtime.resources[NIC]["properties"]["privateEndpoint"]["id"] = PE + "-other"
    with pytest.raises(core.TransitionError):
        plan(runtime)


def test_partial_arm_failure_recovery_does_not_delete(tmp_path):
    runtime = Runtime()
    prepared = plan(runtime)
    runtime.fail = ZONE
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain" and PE in runtime.resources and runtime.leases
    runtime.fail = None
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "succeeded", result
    assert all(method == "PUT" for method, _, _ in runtime.writes)


def test_expired_or_changed_plan_and_missing_source(tmp_path):
    runtime = Runtime()
    prepared = plan(runtime)
    prepared["expires_at"] = 1
    prepared["plan_hash"] = core.digest({k: v for k, v in prepared.items() if k != "plan_hash"})
    with pytest.raises(core.TransitionError, match="expired"):
        execute(runtime, prepared, tmp_path)
    with pytest.raises(core.TransitionError, match="source-missing"):
        core.source_fingerprint(tmp_path)


def test_probe_dns_public_or_arbitrary_ip_rejected(monkeypatch):
    runner = object.__new__(probe.Runner)
    runner.request = {"account_url": COORDS["account_url"], "private_ip": IP}
    monkeypatch.setattr(probe.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))])
    with pytest.raises(ValueError, match="canonical-storage-dns"):
        runner.probe()


@pytest.mark.parametrize("drift", [False, True])
def test_probe_native_close_freezes_storage_snapshot_without_unsupported_etag(drift):
    class PrivateRunner(probe.Runner):
        def __init__(self):
            self.account = {"properties": {"networkAcls": {"ipRules": [{"value": "8.8.8.8"}]},
                                          "publicNetworkAccess": "Enabled", "provisioningState": "Succeeded"}}
            self.request = {"lock_blob": "lock", "lease_id": "lease", "registry_hashes": {}, "writer_proofs": [],
                "account_id": ACCOUNT, "expected_account_snapshot": copy.deepcopy(self.account), "expected_network": {
                    k: copy.deepcopy(self.account["properties"][k]) for k in ("networkAcls", "publicNetworkAccess")},
                "desired_network": {"networkAcls": {"ipRules": []}, "publicNetworkAccess": "Disabled"},
                "remote_receipt": "receipt", "plan_hash": "plan", "nonce": "nonce",
                "issued_at": time.time(), "expires_at": time.time() + 300}
            self.events = []
            self.account_reads = 0

        def blob(self, method, name, data=None, headers=None, **kwargs):
            self.events.append(("blob", name, data, headers))
            return {}, {}

        def arm(self, method, identifier, data=None, headers=None, **kwargs):
            if method == "GET":
                self.account_reads += 1
                if drift and self.account_reads == 2:
                    self.account["tags"] = {"unreviewed": "drift"}
            if method == "PATCH":
                assert headers is None
                self.account["properties"].update(copy.deepcopy(data["properties"]))
            self.events.append(("arm", method))
            return {}, self.account

        def probe(self):
            assert self.request["nonce"] == "nonce-final"
            assert self.account["properties"]["publicNetworkAccess"] == "Disabled"
            self.events.append(("final-probe",))
            return [IP]

    runner = PrivateRunner()
    if drift:
        with pytest.raises(ValueError, match="account-snapshot-changed"):
            runner.close()
        assert ("arm", "PATCH") not in runner.events and ("final-probe",) not in runner.events
        return
    assert runner.close() == [IP]
    assert runner.events[-1][3]["x-ms-lease-action"] == "release"
    assert runner.events.index(("final-probe",)) < len(runner.events) - 1


def test_missing_registry_published_from_verified_stage_targets(tmp_path):
    runtime = Runtime()
    context = copy.deepcopy(CONTEXT)
    context["writer_targets"] = runtime.blobs.pop(core.REGISTRY)["writers"]
    prepared = plan(runtime, context)
    assert prepared["registries"][core.REGISTRY]["value"] is None
    assert execute(runtime, prepared, tmp_path)["status"] == "succeeded"
    assert runtime.blobs[core.REGISTRY]["writers"] == context["writer_targets"]


def test_no_registry_and_no_verified_targets_blocks():
    runtime = Runtime()
    runtime.blobs.pop(core.REGISTRY)
    with pytest.raises(core.TransitionError, match="unknown-hub-writer"):
        plan(runtime)


def test_reuses_shared_zone_existing_link_name(tmp_path):
    runtime = Runtime()
    runtime.add(ZONE, {"location": "global", "tags": {"owner": "central-network"}})
    link = ZONE + "/virtualnetworklinks/central-shared-link"
    runtime.add(link, {"location": "global", "properties": {"virtualNetwork": {"id": VNET}, "registrationEnabled": False}})
    prepared = plan(runtime)
    assert not any("/virtualnetworklinks/" in e["id"] for e in prepared["effects"])
    assert execute(runtime, prepared, tmp_path)["status"] == "succeeded"
    assert runtime.resources[ZONE]["tags"] == {"owner": "central-network"}


def test_native_runcommand_pinned_source_and_authenticated_operation(monkeypatch):
    runtime = Runtime()
    prepared = plan(runtime)
    writer = prepared["writers"]["factory-one"]
    request = core._request(prepared, "factory-one", writer, prepared["writer_attestations"]["factory-one"], IP, runtime)
    runtime.read_only = False
    runtime.serialized_provisioning = True
    operation = {}
    original_arm = runtime.arm

    def arm(method, identifier, api, data=None, **kwargs):
        if "/runcommands/" not in identifier:
            return original_arm(method, identifier, api, data, **kwargs)
        if method == "PUT":
            operation.update(copy.deepcopy(data))
            operation["id"] = request["operation_id"]
            fields = ("nonce", "plan_hash", "writer_id", "tenant_id", "principal_id",
                      "source_commit", "source_sha256", "operation_id", "phase", "runner_id", "repository")
            result = {k: request[k] for k in fields}
            result.update(success=True, addresses=[IP], at=time.time())
            operation["properties"]["instanceView"] = {"executionState": "Succeeded", "exitCode": 0,
                "output": "AFHUB_ATTESTATION:" + json.dumps(result)}
            return 201, {}, operation
        return (200, {"etag": "op-etag"}, operation) if operation else (404, {}, None)

    monkeypatch.setattr(runtime, "arm", arm)
    result = core.Cloud.run_probe(runtime, writer, request, core._probe_bytes(ROOT))
    core._verify_result(result, request)
    assert "python3 -c" in operation["properties"]["source"]["script"]
    operation["properties"]["source"]["script"] = "echo forged"
    with pytest.raises(core.TransitionError, match="run-command-source-mismatch"):
        core.Cloud.run_probe(runtime, writer, request, core._probe_bytes(ROOT), resume=True)


def test_native_ado_existing_windows_runner_and_source():
    runtime = Runtime()
    writer = copy.deepcopy(runtime.blobs[core.REGISTRY]["writers"]["factory-one"])
    writer.update(provider="ado", repository="https://dev.azure.com/company/project/_git/factory",
                  repository_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", pool_id=5,
                  runner_config_path=r"C:\agent\.agent")
    runtime.resources[VM]["properties"]["storageProfile"]["osDisk"]["osType"] = "Windows"

    def read(target, path):
        if "/agents/" in path:
            return {"id": 20, "name": "private-runner", "enabled": True, "status": "online",
                    "systemCapabilities": {"Agent.OS": "Windows_NT"}}
        if "/items?" in path:
            return {"commitId": "a" * 40, "content": (ROOT / core.PROBE).read_bytes().decode("utf-8")}
        return {"id": writer["repository_id"], "webUrl": writer["repository"]}

    runtime.provider_read = read
    attestation = runtime.attest_writer(writer, core.source_fingerprint(ROOT)["probe_sha256"])
    assert attestation["os"] == "Windows" and attestation["repository_id"] == writer["repository_id"]


def test_network_drift_after_lease_denied(tmp_path):
    runtime = Runtime()
    prepared = plan(runtime)
    original = runtime.blob

    def blob(method, name, **kwargs):
        result = original(method, name, **kwargs)
        if kwargs.get("headers", {}).get("x-ms-lease-action") == "acquire" and name == core.foundation.lock_blob(HUB):
            runtime.resources[ACCOUNT]["properties"]["networkAcls"]["defaultAction"] = "Allow"
        return result

    runtime.blob = blob
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain" and result["error"] == "reviewed-private-resource-changed"
    assert not runtime.requests and not runtime.writes


def test_lost_close_response_recovered_with_fresh_private_probe(tmp_path):
    runtime = Runtime()
    prepared = plan(runtime)
    original = runtime.run_probe
    interrupted = False

    def run(writer, request, script, **kwargs):
        nonlocal interrupted
        result = original(writer, request, script, **kwargs)
        if request["phase"] == "close" and not interrupted:
            interrupted = True
            raise core.TransitionError("response-lost-after-successful-close")
        return result

    runtime.run_probe = run
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain" and not result["runtime_ready"]
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Disabled"
    recovered = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                             state_dir=tmp_path, runtime=runtime)
    assert recovered["status"] == "succeeded", recovered
    assert runtime.requests[-1]["phase"] == "verify-closed"


def test_failed_final_probe_never_reports_success_or_releases_hub():
    class Runner(probe.Runner):
        def __init__(self):
            self.request = {"lock_blob": "hub", "lease_id": "lease", "registry_hashes": {}, "writer_proofs": [],
                "account_id": ACCOUNT, "expected_network": {
                    "networkAcls": {"ipRules": [{"value": "8.8.8.8"}]}, "publicNetworkAccess": "Enabled"},
                "desired_network": {"networkAcls": {"ipRules": []}, "publicNetworkAccess": "Disabled"},
                "remote_receipt": "receipt", "plan_hash": "plan", "nonce": "nonce",
                "issued_at": time.time(), "expires_at": time.time() + 300}
            self.properties = copy.deepcopy(self.request["expected_network"])
            self.request["expected_account_snapshot"] = {"properties": {**copy.deepcopy(self.properties), "provisioningState": "Succeeded"}}
            self.actions = []

        def blob(self, *args, **kwargs):
            self.actions.append(kwargs.get("headers", {}).get("x-ms-lease-action"))
            return {}, {}

        def arm(self, method, identifier, data=None, headers=None, **kwargs):
            if method == "PATCH":
                self.properties = data["properties"]
            return {"etag": "expected"}, {"properties": {**self.properties, "provisioningState": "Succeeded"}}

        def probe(self):
            raise ValueError("private final failure")

    runner = Runner()
    with pytest.raises(ValueError, match="private final failure"):
        runner.close()
    assert "release" not in runner.actions


def test_native_windows_runcommand_script_does_not_invoke_local_probe(monkeypatch):
    runtime = Runtime()
    prepared = plan(runtime)
    writer = prepared["writers"]["factory-one"]
    request = core._request(prepared, "factory-one", writer, prepared["writer_attestations"]["factory-one"], IP, runtime)
    request["runner_os"] = "Windows"
    runtime.read_only = False
    runtime.serialized_provisioning = True
    bodies = []
    original_arm = runtime.arm

    def arm(method, identifier, api, data=None, **kwargs):
        if identifier == VM:
            return original_arm(method, identifier, api, data=data, **kwargs)
        if method == "PUT":
            bodies.append(data)
            raise core.TransitionError("stop-after-reviewed-submission")
        return 404, {}, None

    monkeypatch.setattr(runtime, "arm", arm)
    with pytest.raises(core.TransitionError, match="stop-after-reviewed-submission"):
        core.Cloud.run_probe(runtime, writer, request, core._probe_bytes(ROOT))
    assert bodies[0]["properties"]["source"]["script"].startswith("$ErrorActionPreference='Stop'")
    assert "python.exe -c" in bodies[0]["properties"]["source"]["script"]
    assert "$LASTEXITCODE" in bodies[0]["properties"]["source"]["script"]


def test_terminal_failed_close_recovery_refreshes_all_proofs(tmp_path):
    runtime = Runtime()
    prepared = plan(runtime)
    runtime.fail = "close"
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain" and runtime.leases
    failed_id = result["close_request"]["operation_id"]
    original = runtime.run_probe
    runtime.fail = None

    def run(writer, request, script, *, resume=False):
        if resume and request["operation_id"] == failed_id:
            raise core.TransitionError("runner-probe-failed")
        return original(writer, request, script, resume=resume)

    runtime.run_probe = run
    recovered = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                             state_dir=tmp_path, runtime=runtime)
    assert recovered["status"] == "succeeded", recovered
    assert recovered["previous_close_operations"] == [failed_id]
    assert runtime.requests[-2]["phase"] == "close" and runtime.requests[-1]["phase"] == "verify-closed"


def test_lease_recovery_never_breaks_another_writer():
    runner = object.__new__(probe.Runner)
    calls = []

    def blob(*args, **kwargs):
        calls.append(kwargs)
        return {}, b"<Error><Code>LeaseIdMismatchWithLeaseOperation</Code></Error>"

    runner.blob = blob
    with pytest.raises(ValueError, match="another-writer-holds-lease"):
        runner.ensure_lease("exact-hub-lock", "own-lease")
    assert len(calls) == 1 and calls[0]["headers"]["x-ms-lease-action"] == "renew"


def test_preprobe_handoff_retains_public_then_final_transition_closes(tmp_path):
    runtime = Runtime()
    prepared = core.prepare_probe(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB,
                                  context=CONTEXT, runtime=runtime)
    assert prepared["stage"] == "hub-private-probe"
    assert prepared["desired_network"] == prepared["expected_network"]
    assert all(command.get("method") != "PATCH" for command in prepared["commands"])
    result = core.execute_probe(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                                state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "succeeded" and result["private_path_verified"]
    assert result["public_bootstrap_retained"] and result["private_transition_required"]
    assert result["outputs"] == result["bindings"]
    assert not result["outputs"]["hub_private_access"]["private_transition_complete"]
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Enabled"
    assert not runtime.leases and all(r["phase"] == "probe" for r in runtime.requests)
    final = execute(runtime, plan(runtime), tmp_path)
    assert final["status"] == "succeeded"
    assert final["outputs"]["hub_private_access"]["private_transition_complete"]
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Disabled"


def test_preprobe_never_requires_authority_to_remove_reused_rule(tmp_path):
    runtime = Runtime()
    runtime.blobs["bootstrap/foundation/" + FOUNDATION + ".json"]["bootstrap_network_access"]["added_by_this_execution"] = False
    prepared = core.prepare_probe(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB,
                                  context=CONTEXT, runtime=runtime)
    result = core.execute_probe(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                                state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "succeeded" and runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Enabled"
    with pytest.raises(core.TransitionError, match="provenance"):
        plan(runtime)


def test_cannot_run_wrong_phase_executor(tmp_path):
    runtime = Runtime()
    prepared = core.prepare_probe(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB,
                                  context=CONTEXT, runtime=runtime)
    with pytest.raises(core.TransitionError, match="final-private-transition-plan-required"):
        execute(runtime, prepared, tmp_path)


def test_private_endpoint_uses_vnet_region_not_retained_storage_region():
    runtime = Runtime()
    runtime.resources[ACCOUNT]["location"] = "westeurope"
    prepared = plan(runtime)
    endpoint = next(effect for effect in prepared["effects"] if effect["id"] == PE)
    assert endpoint["body"]["location"] == "swedencentral"


def test_manual_shared_dns_record_reused_without_zone_group_takeover(tmp_path):
    runtime = Runtime()
    assert execute(runtime, plan(runtime), tmp_path)["status"] == "succeeded"
    runtime.resources.pop(PE + "/privatednszonegroups/default")
    runtime.resources[RECORD]["properties"]["ttl"] = 120
    runtime.resources[RECORD]["properties"]["metadata"] = {"owner": "central-dns"}
    prepared = plan(runtime)
    assert prepared["effects"] == []
    assert execute(runtime, prepared, tmp_path)["status"] == "succeeded"
    assert runtime.resources[RECORD]["properties"]["ttl"] == 120
    assert runtime.resources[RECORD]["properties"]["metadata"] == {"owner": "central-dns"}


def test_concrete_workflow_adapters_derive_ids_and_bind_recovery(tmp_path):
    runtime = Runtime()
    factory_id = "11111111-1111-1111-1111-111111111111"
    runtime.blobs[core.COORDINATION]["scopes"][HUB]["target"] = {"factory_id": factory_id}
    bindings = {"runner_vm_id": VM, "runner_subnet_id": SUBNET, "deployment_principal_id": PRINCIPAL,
                "integrated_vnet_id": VNET, "runner_name": "private-runner",
                "runner_config_path": "/opt/runner/.runner", "hub_private_endpoint_subnet_id": SUBNET,
                "network": {"mode": "external", "owned": False, "vnet_id": VNET, "resource_group_id": HUB}}
    inputs = {"root": ROOT, "scope": {"factory_id": factory_id}, "bootstrap_config": {"tenant_id": TENANT},
              "expected_revision": "reviewed-revision", "workflow_id": "workflow-one",
              "coordination": COORDS, "bindings": bindings,
              "provider_serialization": {"repository": "https://github.com/company/factory",
                                        "ref": "refs/heads/aifactory-initializer-lock", "sha": "b" * 40, "owner": "one"}}
    adapter = core.PrivateProbeAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    prepared = adapter.prepare(**inputs)
    assert prepared["can_execute"], prepared
    writer = prepared["frozen_plan"]["writers"]["factory-one"]
    assert writer["runner_id"] == 20 and writer["source_commit"] == "a" * 40
    assert writer["probe_path"] == ".azurefactory/hub_private_probe.py"
    result = adapter.execute(prepared, root=ROOT, workflow_id="workflow-one")
    assert result["status"] == "succeeded", result
    assert result["outputs"]["hub_private_access"]["private_transition_complete"] is False
    with pytest.raises(core.TransitionError, match="workflow-binding-changed"):
        adapter.execute(prepared, root=ROOT, workflow_id="different-workflow")
    final_adapter = core.PrivateTransitionAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    reviewed = final_adapter.prepare(**inputs)
    assert reviewed["can_execute"], reviewed
    final = final_adapter.execute(reviewed, root=ROOT, workflow_id="workflow-one")
    assert final["status"] == "succeeded"
    assert final["outputs"]["hub_private_access"]["private_transition_complete"] is True


def test_adapter_unknown_factory_returns_actionable_blocker(tmp_path):
    runtime = Runtime()
    adapter = core.PrivateProbeAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    result = adapter.prepare(root=ROOT, scope={"factory_id": "unknown"}, bootstrap_config={"tenant_id": TENANT},
                             expected_revision="one", workflow_id="one", coordination=COORDS,
                             bindings={"deployment_principal_id": PRINCIPAL})
    assert result["can_execute"] is False
    assert result["blockers"] == ["selected-factory-enrollment-required"] and result["frozen_plan"] is None


def test_automatic_provenance_resolution_rejects_ambiguous_rules():
    runtime = Runtime()
    context = copy.deepcopy(CONTEXT)
    context.pop("foundation_receipt")
    assert plan(runtime, context)["foundation_proof"]["value"]["status"] == "succeeded"
    runtime.blobs["bootstrap/foundation/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee.json"] = copy.deepcopy(
        runtime.blobs["bootstrap/foundation/" + FOUNDATION + ".json"])
    with pytest.raises(core.TransitionError, match="unique-created-bootstrap-rule"):
        plan(runtime, context)


def test_foundation_atomic_replace_retries_only_transient_local_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    path.write_bytes(core.canonical({"status": "before"}))
    real_replace = core.foundation.os.replace
    calls, sleeps = [], []

    def replace(source, target):
        calls.append((source, target))
        if len(calls) < 3:
            raise PermissionError("transient local Windows sharing violation")
        return real_replace(source, target)

    monkeypatch.setattr(core.foundation.os, "replace", replace)
    core.foundation._persist(path, {"status": "after"}, retry_sleep=sleeps.append)
    assert len(calls) == 3 and sleeps == [0.05, 0.05]
    assert len({source for source, _ in calls}) == 1
    assert json.loads(path.read_bytes()) == {"status": "after"}
    assert not list(tmp_path.glob("*.writing"))


def test_foundation_permanent_atomic_replace_failure_propagates_and_preserves_evidence(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    before = core.canonical({"status": "before"})
    path.write_bytes(before)
    failure = PermissionError("persistent local permission failure")
    calls, sleeps = [], []

    def replace(source, target):
        calls.append((source, target))
        raise failure

    monkeypatch.setattr(core.foundation.os, "replace", replace)
    with pytest.raises(PermissionError) as caught:
        core.foundation._persist(path, {"status": "new-durable-evidence"}, retry_sleep=sleeps.append)
    assert caught.value is failure
    assert len(calls) == 20 and sleeps == [0.05] * 19
    assert path.read_bytes() == before
    staged = list(tmp_path.glob("*.writing"))
    assert len(staged) == 1 and json.loads(staged[0].read_bytes()) == {"status": "new-durable-evidence"}


def test_foundation_other_persistence_errors_are_not_retried(tmp_path, monkeypatch):
    calls, sleeps = [], []

    def replace(source, target):
        calls.append((source, target))
        raise OSError("non-permission storage failure")

    monkeypatch.setattr(core.foundation.os, "replace", replace)
    with pytest.raises(OSError, match="non-permission"):
        core.foundation._persist(tmp_path / "receipt.json", {"status": "before"}, retry_sleep=sleeps.append)
    assert len(calls) == 1 and not sleeps


class PrivateFoundationRuntime(Runtime):
    def __init__(self):
        super().__init__()
        self.head_failure = None
        self.head_reads = 0
        self.add(HUB, {"location": "swedencentral", "tags": core.foundation.ownership_tags(HUB)})
        self.add(f"/subscriptions/{SUB}/providers/microsoft.storage", {"registrationState": "Registered"})
        self.resources[ACCOUNT]["properties"]["publicNetworkAccess"] = "Disabled"
        self.resources[ACCOUNT]["properties"]["networkAcls"]["ipRules"] = []
        container = ACCOUNT + "/blobservices/default/containers/hub-locks"
        self.add(container, {"properties": {"publicAccess": "None"}})
        role = f"/subscriptions/{SUB}/providers/microsoft.authorization/roledefinitions/{core.enrollment.DATA_ROLE}"
        role_id = container + "/providers/microsoft.authorization/roleassignments/" + str(
            core.foundation.uuid5(core.foundation.NAMESPACE_URL, container + ":" + PRINCIPAL + ":" + role))
        self.add(role_id, {"properties": {"principalId": PRINCIPAL, "roleDefinitionId": role, "scope": container}})

    def blob(self, method, blob=None, **kwargs):
        if method == "HEAD":
            self.head_reads += 1
            if self.head_failure:
                raise core.enrollment.EnrollmentError(self.head_failure)
            return 200, {"x-ms-request-id": "authenticated-native-response"}, None
        return super().blob(method, blob, **kwargs)


def private_foundation_plan(runtime, ip=None):
    return core.foundation.prepare(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB,
                                   location="swedencentral", bootstrap_public_ipv4=ip, runtime=runtime)


@pytest.mark.parametrize("blank", [None, "", " \t"])
def test_foundation_blank_ipv4_reuses_only_authenticated_existing_private_account(tmp_path, blank):
    runtime = PrivateFoundationRuntime()
    before = copy.deepcopy(runtime.resources)
    prepared = private_foundation_plan(runtime, blank)
    assert prepared["can_execute"] and not prepared["effects"], prepared
    assert prepared["inputs"]["bootstrap_public_ipv4"] is None
    assert prepared["private_reuse_access"]["verified"] and runtime.head_reads == 1
    assert prepared["private_reuse_access"]["principal_id"] == PRINCIPAL
    assert prepared["private_reuse_access"]["authentication"] == "Entra-OAuth-only"
    assert prepared["bootstrap_network_access"]["rule"] is None
    result = core.foundation.execute(prepared, state_dir=tmp_path, expected_plan_hash=prepared["plan_hash"],
                                    acknowledge_initialization_governance=True, runtime=runtime)
    assert result["status"] == "succeeded", result
    assert result["private_reuse_access"]["verified"] and runtime.head_reads >= 3
    assert runtime.resources == before and not runtime.writes
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Disabled"


@pytest.mark.parametrize("state", ["absent-account", "public-account", "anonymous-container", "hns", "public-rules"])
def test_foundation_blank_ipv4_cannot_create_or_relax_incompatible_storage(state):
    runtime = PrivateFoundationRuntime()
    if state == "absent-account":
        runtime.resources.pop(ACCOUNT)
    elif state == "public-account":
        runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] = "Enabled"
        runtime.resources[ACCOUNT]["properties"]["networkAcls"]["ipRules"] = [{"value": "8.8.8.8", "action": "Allow"}]
    elif state == "anonymous-container":
        runtime.resources[ACCOUNT + "/blobservices/default/containers/hub-locks"]["properties"]["publicAccess"] = "Blob"
    elif state == "hns":
        runtime.resources[ACCOUNT]["properties"]["isHnsEnabled"] = True
    else:
        runtime.resources[ACCOUNT]["properties"]["networkAcls"]["ipRules"] = [{"value": "8.8.8.8", "action": "Allow"}]
    before = copy.deepcopy(runtime.resources)
    if state == "anonymous-container":
        assert not private_foundation_plan(runtime)["can_execute"]
    else:
        with pytest.raises(core.foundation.FoundationError, match="public-ipv4-required"):
            private_foundation_plan(runtime)
    assert runtime.resources == before and not runtime.writes and runtime.head_reads == 0


@pytest.mark.parametrize("error", ["remote-request-failed-401", "remote-request-failed-403", "remote-request-uncertain"])
def test_foundation_blank_ipv4_requires_live_entra_access_not_claimed_private_reuse(error):
    runtime = PrivateFoundationRuntime()
    runtime.head_failure = error
    prepared = private_foundation_plan(runtime)
    assert not prepared["can_execute"]
    assert prepared["private_reuse_access"]["verified"] is False
    assert any("authenticated-execution-path-required" in blocker for blocker in prepared["blockers"])
    assert not runtime.writes


def test_foundation_blank_ipv4_rechecks_private_access_before_writes(tmp_path):
    runtime = PrivateFoundationRuntime()
    prepared = private_foundation_plan(runtime)
    runtime.head_failure = "remote-request-failed-403"
    with pytest.raises(core.foundation.FoundationError, match="live-state-or-plan-changed"):
        core.foundation.execute(prepared, state_dir=tmp_path, expected_plan_hash=prepared["plan_hash"],
                                acknowledge_initialization_governance=True, runtime=runtime)
    assert not runtime.writes and not runtime.leases


def test_foundation_blank_ipv4_does_not_defer_missing_access_until_rbac_grant():
    runtime = PrivateFoundationRuntime()
    runtime.resources = {key: value for key, value in runtime.resources.items() if "/roleassignments/" not in key}
    runtime.head_failure = "remote-request-failed-403"
    prepared = private_foundation_plan(runtime)
    assert not prepared["can_execute"] and prepared["private_reuse_access"]["verified"] is False
    assert any("authenticated-execution-path-required" in blocker for blocker in prepared["blockers"])
    assert not runtime.writes


def test_real_storage_account_shape_without_etag_can_transition(tmp_path):
    runtime = Runtime()
    runtime.resources[ACCOUNT].pop("etag")
    prepared = plan(runtime)
    assert prepared["account_concurrency"] == "physical-hub-lease-and-frozen-storage-snapshot"
    assert "account_etag" not in prepared
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "succeeded", result
    assert "etag" not in result["close_request"]["expected_account_snapshot"]


def test_blob_transport_ignores_proxy_and_connects_to_reviewed_nic(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://public-proxy.invalid:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://public-proxy.invalid:8080")
    handlers, connections = [], []

    class Opener:
        def open(self, *args, **kwargs):
            raise AssertionError("Blob traffic must never use an environment/proxy opener")

    def build(*values):
        handlers.extend(values)
        return Opener()

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"private":true}'

    class Connection:
        def __init__(self, host, ip):
            connections.append((host, ip))

        def request(self, method, path, **kwargs):
            assert method == "GET" and path == "/hub-locks/probe"

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(probe, "build_opener", build)
    monkeypatch.setattr(probe, "PrivateHTTPSConnection", Connection)
    runner = probe.Runner({"account_url": COORDS["account_url"], "private_ip": IP})
    runner.token = lambda _: "test-token"
    assert runner.blob("GET", "probe")[1] == {"private": True}
    assert any(isinstance(handler, probe.ProxyHandler) and handler.proxies == {} for handler in handlers)
    assert connections == [(COORDS["account_url"].removeprefix("https://"), IP)]


def test_direct_private_socket_keeps_canonical_tls_hostname(monkeypatch):
    host = COORDS["account_url"].removeprefix("https://")
    connection = probe.PrivateHTTPSConnection(host, IP)
    assert connection._context.check_hostname is True
    assert connection._context.verify_mode == probe.ssl.CERT_REQUIRED
    calls = []

    class Socket:
        def getpeername(self):
            return IP, 443

        def close(self):
            calls.append("closed")

    sock = Socket()

    def create(address, **kwargs):
        calls.append(address)
        return sock

    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            assert raw is sock
            calls.append(server_hostname)
            return sock

    monkeypatch.setattr(probe.socket, "create_connection", create)
    connection._context = Context()
    connection.connect()
    assert calls == [(IP, 443), host]


class EndpointSideEffectRuntime(Runtime):
    def __init__(self, lost_response=False):
        super().__init__()
        self.resources[VNET]["properties"]["subnets"] = [copy.deepcopy(self.resources[SUBNET])]
        self.lost_response = lost_response

    def arm(self, method, identifier, api, data=None, **kwargs):
        result = super().arm(method, identifier, api, data=data, **kwargs)
        if method == "PUT" and identifier == PE:
            config_id = NIC + "/ipconfigurations/private"
            self.resources[NIC]["properties"]["ipConfigurations"][0]["id"] = config_id
            subnet = self.resources[SUBNET]
            subnet["properties"]["privateEndpoints"] = [{"id": PE}]
            subnet["properties"]["ipConfigurations"] = [{"id": config_id}]
            subnet["etag"] = '"subnet-after-own-endpoint"'
            self.resources[VNET]["properties"]["subnets"] = [copy.deepcopy(subnet)]
            self.resources[VNET]["etag"] = '"vnet-after-own-endpoint"'
            self.resources[ACCOUNT]["properties"]["privateEndpointConnections"] = [{
                "id": ACCOUNT + "/privateendpointconnections/owned",
                "properties": {"privateEndpoint": {"id": PE},
                    "privateLinkServiceConnectionState": {"status": "Approved"}}}]
            if self.lost_response:
                self.lost_response = False
                raise core.TransitionError("lost-pe-create-response")
        return result


@pytest.mark.parametrize("lost_response", [False, True])
def test_recovery_journals_exact_own_endpoint_subnet_and_parent_changes(tmp_path, lost_response):
    runtime = EndpointSideEffectRuntime(lost_response)
    prepared = plan(runtime)
    runtime.fail = None if lost_response else ZONE
    failed = execute(runtime, prepared, tmp_path)
    assert failed["status"] == "uncertain" and PE in runtime.resources, failed
    assert failed["resource_journal"][PE]["effect_hash"] == core.digest(
        next(effect for effect in prepared["effects"] if effect["id"] == PE))
    runtime.fail = None
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "succeeded", result
    assert {SUBNET, VNET, ACCOUNT} <= set(result["reconciled_observations"])


@pytest.mark.parametrize("drift", ["nsg", "other-endpoint", "delegation"])
@pytest.mark.parametrize("lost_response", [False, True])
def test_own_endpoint_recovery_does_not_adopt_unrelated_subnet_changes(tmp_path, drift, lost_response):
    runtime = EndpointSideEffectRuntime(lost_response=lost_response)
    runtime.fail = None if lost_response else ZONE
    prepared = plan(runtime)
    assert execute(runtime, prepared, tmp_path)["status"] == "uncertain"
    runtime.fail = None
    properties = runtime.resources[SUBNET]["properties"]
    if drift == "nsg":
        properties["networkSecurityGroup"] = {"id": HUB + "/providers/microsoft.network/networksecuritygroups/unreviewed"}
    elif drift == "other-endpoint":
        properties["privateEndpoints"].append({"id": PE + "-unreviewed"})
    else:
        properties["delegations"] = [{"name": "unreviewed"}]
    writes = len(runtime.writes)
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "uncertain" and result["error"] == "reviewed-private-resource-changed"
    assert len(runtime.writes) == writes


@pytest.mark.parametrize("failure", [ZONE, "close"])
def test_expired_24_hour_recovery_is_observation_only(tmp_path, monkeypatch, failure):
    runtime = Runtime()
    prepared = plan(runtime)
    runtime.fail = failure
    assert execute(runtime, prepared, tmp_path)["status"] == "uncertain"
    before = copy.deepcopy((runtime.resources, runtime.blobs, runtime.leases, runtime.writes, runtime.requests))
    runtime.fail = None
    calls = []
    original_arm, original_blob = runtime.arm, runtime.blob

    def arm(method, *args, **kwargs):
        calls.append(("arm", method))
        assert method in ("GET", "HEAD"), "Expired recovery must not mutate ARM"
        return original_arm(method, *args, **kwargs)

    def blob(method, *args, **kwargs):
        calls.append(("blob", method))
        assert method in ("GET", "HEAD"), "Expired recovery must not mutate blobs or leases"
        return original_blob(method, *args, **kwargs)

    runtime.arm, runtime.blob = arm, blob
    monkeypatch.setattr(core.time, "time", lambda: prepared["expires_at"] + 24 * 60 * 60)
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "approval-expired" and result["requires_new_approval"]
    assert result["reconciliation"]["mutations_permitted"] is False and not result["runtime_ready"]
    assert (runtime.resources, runtime.blobs, runtime.leases, runtime.writes, runtime.requests) == before
    assert calls and all(method in ("GET", "HEAD") for _, method in calls)


def test_probe_deadline_never_extends_plan_authorization(monkeypatch):
    runtime = Runtime()
    prepared = plan(runtime)
    name = "factory-one"
    request = core._request(prepared, name, prepared["writers"][name], prepared["writer_attestations"][name], IP, runtime)
    assert request["expires_at"] == prepared["expires_at"]
    monkeypatch.setattr(core.time, "time", lambda: prepared["expires_at"] + 1)
    with pytest.raises(core.TransitionError, match="transition-review-expired"):
        core._request(prepared, name, prepared["writers"][name], prepared["writer_attestations"][name], IP, runtime)
    with pytest.raises(core.TransitionError, match="probe-request-expired"):
        core.Cloud.run_probe(runtime, prepared["writers"][name], request, core._probe_bytes(ROOT))
    assert not runtime.writes


def test_expiry_after_endpoint_creation_blocks_next_arm_mutation(tmp_path, monkeypatch):
    runtime = Runtime()
    prepared = plan(runtime)
    now = [prepared["prepared_at"] + 1]
    monkeypatch.setattr(core.time, "time", lambda: now[0])
    original = runtime.arm

    def arm(method, identifier, api, **kwargs):
        result = original(method, identifier, api, **kwargs)
        if method == "PUT" and identifier == PE:
            now[0] = prepared["expires_at"] + 1
        return result

    runtime.arm = arm
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "uncertain" and result["error"] == "transition-review-expired"
    assert PE in runtime.resources and ZONE not in runtime.resources
    assert not runtime.requests


def test_runner_rechecks_deadline_immediately_before_firewall_patch(monkeypatch):
    now = [time.time()]
    start = now[0]
    monkeypatch.setattr(probe.time, "time", lambda: now[0])

    class Runner(probe.Runner):
        def __init__(self):
            self.account = {"properties": {"networkAcls": {"ipRules": [{"value": "8.8.8.8"}]},
                                          "publicNetworkAccess": "Enabled", "provisioningState": "Succeeded"}}
            self.request = {"issued_at": start, "expires_at": start + 60,
                "lock_blob": "hub", "lease_id": "lease", "registry_hashes": {}, "writer_proofs": [],
                "account_id": ACCOUNT, "expected_account_snapshot": copy.deepcopy(self.account),
                "expected_network": {k: copy.deepcopy(self.account["properties"][k])
                                     for k in ("networkAcls", "publicNetworkAccess")},
                "desired_network": {"networkAcls": {"ipRules": []}, "publicNetworkAccess": "Disabled"},
                "remote_receipt": "receipt", "plan_hash": "plan", "nonce": "nonce"}
            self.reads, self.patches = 0, 0

        def blob(self, *args, **kwargs):
            return {}, None

        def arm(self, method, identifier, *args, **kwargs):
            if method == "GET":
                self.reads += 1
                if self.reads == 2:
                    now[0] = start + 61
            else:
                self.patches += 1
            return {}, copy.deepcopy(self.account)

    runner = Runner()
    with pytest.raises(ValueError, match="probe-request-expired"):
        runner.close()
    assert runner.patches == 0


def test_native_compute_vm_without_etag_uses_identity_configuration_snapshot(tmp_path):
    runtime = Runtime()
    runtime.resources[VM].pop("etag")
    runtime.resources[ACCOUNT].pop("etag")
    prepared = plan(runtime)
    observed = prepared["writer_attestations"]["factory-one"]
    assert "vm_etag" not in observed and observed["vm_snapshot"]["identity"]["principalId"] == PRINCIPAL
    assert "etag" not in observed["vm_snapshot"]
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "succeeded", result
    assert result["close_request"]["vm_snapshot_sha256"] == core.digest(observed["vm_snapshot"])


def test_vm_configuration_drift_without_etag_stops_native_runcommand_dispatch():
    runtime = Runtime()
    runtime.resources[VM].pop("etag")
    prepared = plan(runtime)
    name = "factory-one"
    writer = prepared["writers"][name]
    request = core._request(prepared, name, writer, prepared["writer_attestations"][name], IP, runtime)
    runtime.resources[VM]["properties"]["networkProfile"] = {"networkInterfaces": [{"id": "unreviewed-nic"}]}
    runtime.read_only = False
    runtime.serialized_provisioning = True
    with pytest.raises(core.TransitionError, match="runner-vm-configuration-changed-before-dispatch"):
        core.Cloud.run_probe(runtime, writer, request, core._probe_bytes(ROOT))
    assert not runtime.writes


class NativeDNSCountersRuntime(EndpointSideEffectRuntime):
    def __init__(self, lost_dns_response=None):
        super().__init__()
        self.resources[VM].pop("etag")
        self.resources[ACCOUNT].pop("etag")
        self.add(ZONE, {"location": "global", "tags": {"owner": "central-dns"}, "properties": {
            "numberOfVirtualNetworkLinks": 3, "numberOfRecordSets": 4,
            "numberOfVirtualNetworkLinksWithRegistration": 1,
            "maxNumberOfRecordSets": 25000, "maxNumberOfVirtualNetworkLinks": 1000}})
        for index in range(3):
            self.add(ZONE + "/virtualnetworklinks/retained-" + str(index), {
                "location": "global", "properties": {"virtualNetwork": {"id": VNET + "-retained-" + str(index)},
                "registrationEnabled": index == 0}})
        self.lost_dns_response = lost_dns_response

    def arm(self, method, identifier, api, data=None, **kwargs):
        existed = identifier.lower() in self.resources
        result = super().arm(method, identifier, api, data=data, **kwargs)
        if method != "PUT" or existed:
            return result
        stage = None
        properties = self.resources[ZONE]["properties"]
        if identifier.startswith(ZONE + "/virtualnetworklinks/"):
            properties["numberOfVirtualNetworkLinks"] += 1
            stage = "link"
        elif identifier.endswith("/privatednszonegroups/default"):
            properties["numberOfRecordSets"] += 1
            stage = "group"
        if stage:
            self.resources[ZONE]["etag"] = '"dns-%d-%d"' % (
                properties["numberOfVirtualNetworkLinks"], properties["numberOfRecordSets"])
            if stage == self.lost_dns_response:
                self.lost_dns_response = None
                raise core.TransitionError("lost-dns-create-response")
        return result


def test_existing_dns_zone_accepts_exact_native_link_and_managed_record_counter_deltas(tmp_path):
    runtime = NativeDNSCountersRuntime()
    retained = {key: copy.deepcopy(value) for key, value in runtime.resources.items() if "/retained-" in key}
    result = execute(runtime, plan(runtime), tmp_path)
    assert result["status"] == "succeeded", result
    assert not runtime.leases
    properties = runtime.resources[ZONE]["properties"]
    assert properties["numberOfVirtualNetworkLinks"] == 4 and properties["numberOfRecordSets"] == 5
    assert properties["numberOfVirtualNetworkLinksWithRegistration"] == 1
    assert runtime.resources[ZONE]["tags"] == {"owner": "central-dns"}
    assert all(runtime.resources[key] == value for key, value in retained.items())
    assert len(result["dns_child_observations"]) == 3
    assert len(result["dns_zone_applied_effects"]) == 2


@pytest.mark.parametrize("lost_response", ["link", "group"])
def test_existing_dns_zone_recovers_native_counter_changes_after_lost_child_response(tmp_path, lost_response):
    runtime = NativeDNSCountersRuntime(lost_dns_response=lost_response)
    prepared = plan(runtime)
    failed = execute(runtime, prepared, tmp_path)
    assert failed["status"] == "uncertain" and failed["error"] == "lost-dns-create-response", failed
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "succeeded", result
    assert not runtime.leases
    assert runtime.resources[ZONE]["properties"]["numberOfRecordSets"] == 5


@pytest.mark.parametrize("drift", ["record-counter", "link-counter", "registration-counter",
                                  "quota", "tags", "link-target", "managed-record", "zone-etag"])
def test_existing_dns_zone_recovery_rejects_unplanned_counter_or_child_drift(tmp_path, drift):
    runtime = NativeDNSCountersRuntime()
    prepared = plan(runtime)
    runtime.fail = "factory-one"
    failed = execute(runtime, prepared, tmp_path)
    assert failed["status"] == "uncertain" and failed["error"] == "simulated-private-probe-failure", failed
    runtime.fail = None
    props = runtime.resources[ZONE]["properties"]
    if drift == "record-counter":
        props["numberOfRecordSets"] += 1
    elif drift == "link-counter":
        props["numberOfVirtualNetworkLinks"] += 1
    elif drift == "registration-counter":
        props["numberOfVirtualNetworkLinksWithRegistration"] += 1
    elif drift == "quota":
        props["maxNumberOfRecordSets"] += 1
    elif drift == "tags":
        runtime.resources[ZONE]["tags"]["owner"] = "unreviewed"
    elif drift == "zone-etag":
        runtime.resources[ZONE]["etag"] = '"unexplained-update"'
    elif drift == "link-target":
        link = next(effect["id"] for effect in prepared["effects"] if "/virtualnetworklinks/" in effect["id"])
        runtime.resources[link]["properties"]["virtualNetwork"]["id"] = VNET + "-unreviewed"
    else:
        runtime.resources[RECORD]["properties"]["ttl"] = 120
    requests, writes = len(runtime.requests), len(runtime.writes)
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "uncertain"
    assert result["error"] in ("reviewed-dns-zone-counter-or-configuration-drift",
                               "reviewed-dns-zone-unexplained-drift",
                               "journaled-dns-child-conflict", "journaled-managed-dns-record-conflict")
    assert len(runtime.requests) == requests and len(runtime.writes) == writes


class DelayedDNSLinkRuntime(NativeDNSCountersRuntime):
    def __init__(self, clock, ready_after=4):
        super().__init__()
        self.clock, self.ready_after = clock, ready_after
        self.created_link = None
        self.ready_at = None
        self.group_created_at = None

    def arm(self, method, identifier, api, data=None, **kwargs):
        if (method == "GET" and identifier == self.created_link and self.ready_at is not None
                and self.clock[0] >= self.ready_at):
            self.resources[identifier]["properties"]["virtualNetworkLinkState"] = "Completed"
            self.resources[identifier]["etag"] = '"link-ready-terminal-etag"'
        result = super().arm(method, identifier, api, data=data, **kwargs)
        if method == "PUT" and identifier.startswith(ZONE + "/virtualnetworklinks/"):
            self.created_link = identifier
            self.ready_at = self.clock[0] + self.ready_after
            self.resources[identifier]["properties"]["virtualNetworkLinkState"] = "InProgress"
            self.resources[identifier]["etag"] = '"link-provisioned-but-not-ready"'
        if method == "PUT" and identifier.endswith("/privatednszonegroups/default"):
            assert self.resources[self.created_link]["properties"]["virtualNetworkLinkState"] == "Completed"
            self.group_created_at = self.clock[0]
        return result


def test_dns_link_waits_for_actual_completed_state_before_freezing_and_probing(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(core.time, "sleep", sleep)
    runtime = DelayedDNSLinkRuntime(clock)
    prepared = plan(runtime)
    result = execute(runtime, prepared, tmp_path)
    assert result["status"] == "succeeded", result
    assert sleeps == [2, 2] and runtime.group_created_at >= runtime.ready_at
    observed = result["dns_child_observations"][runtime.created_link]["value"]
    assert observed["properties"]["virtualNetworkLinkState"] == "Completed"
    assert observed["etag"] == '"link-ready-terminal-etag"'
    assert result["dns_link_readiness"][runtime.created_link]["status"] == "ready"
    assert all(request["issued_at"] >= runtime.ready_at for request in runtime.requests)
    assert not runtime.leases


def test_interrupted_dns_link_readiness_recovers_exact_progress_without_deadline_reset(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])

    def interrupted_sleep(seconds):
        raise core.TransitionError("interrupted-dns-readiness-wait")

    monkeypatch.setattr(core.time, "sleep", interrupted_sleep)
    runtime = DelayedDNSLinkRuntime(clock)
    prepared = plan(runtime)
    failed = execute(runtime, prepared, tmp_path)
    assert failed["status"] == "uncertain" and failed["error"] == "interrupted-dns-readiness-wait", failed
    link = runtime.created_link
    original_deadline = failed["dns_link_readiness"][link]["deadline"]
    assert link not in failed["dns_child_observations"]
    assert not runtime.requests and runtime.group_created_at is None
    monkeypatch.setattr(core.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "succeeded", result
    assert result["dns_link_readiness"][link]["deadline"] == original_deadline
    assert result["dns_child_observations"][link]["value"]["properties"]["virtualNetworkLinkState"] == "Completed"


def test_dns_link_readiness_wait_is_bounded_across_recovery_without_probes(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(core.time, "sleep", sleep)
    runtime = DelayedDNSLinkRuntime(clock, ready_after=10000)
    prepared = plan(runtime)
    failed = execute(runtime, prepared, tmp_path)
    assert failed["status"] == "uncertain" and failed["error"] == "dns-link-readiness-timeout", failed
    link = runtime.created_link
    deadline = failed["dns_link_readiness"][link]["deadline"]
    assert sum(sleeps) == 120 and deadline <= prepared["expires_at"]
    count = len(sleeps)
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "uncertain" and result["error"] == "dns-link-readiness-timeout"
    assert result["dns_link_readiness"][link]["deadline"] == deadline and len(sleeps) == count
    assert not runtime.requests and runtime.group_created_at is None
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Enabled"


def test_dns_link_readiness_wait_cannot_outlive_original_consent(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])
    monkeypatch.setattr(core.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    runtime = DelayedDNSLinkRuntime(clock, ready_after=10000)
    prepared = plan(runtime)
    prepared["expires_at"] = clock[0] + 5
    prepared["plan_hash"] = core.digest({key: value for key, value in prepared.items() if key != "plan_hash"})
    failed = execute(runtime, prepared, tmp_path)
    assert failed["status"] == "uncertain" and failed["error"] == "transition-review-expired", failed
    assert failed["dns_link_readiness"][runtime.created_link]["deadline"] == prepared["expires_at"]
    assert clock[0] == prepared["expires_at"]
    assert not runtime.requests and runtime.group_created_at is None


@pytest.mark.parametrize("drift", ["target", "registration", "provisioning-failed", "other-link-state"])
def test_pending_owned_link_readiness_rejects_configuration_and_unexpected_state_drift(tmp_path, monkeypatch, drift):
    clock = [time.time()]
    monkeypatch.setattr(core.time, "time", lambda: clock[0])
    monkeypatch.setattr(core.time, "sleep", lambda _: (_ for _ in ()).throw(core.TransitionError("interrupted")))
    runtime = DelayedDNSLinkRuntime(clock)
    prepared = plan(runtime)
    assert execute(runtime, prepared, tmp_path)["status"] == "uncertain"
    properties = runtime.resources[runtime.created_link]["properties"]
    if drift == "target":
        properties["virtualNetwork"]["id"] = VNET + "-unreviewed"
    elif drift == "registration":
        properties["registrationEnabled"] = True
    elif drift == "provisioning-failed":
        properties["provisioningState"] = "Failed"
    else:
        properties["virtualNetworkLinkState"] = "Unknown"
    result = core.recover(prepared, source_root=ROOT, expected_plan_hash=prepared["plan_hash"],
                          state_dir=tmp_path, runtime=runtime)
    assert result["status"] == "uncertain"
    assert result["error"] in ("journaled-dns-child-conflict", "dns-link-readiness-invalid-or-failed")
    assert not runtime.requests and runtime.group_created_at is None


def test_reused_dns_link_must_already_be_terminal_before_plan_freezes_it():
    runtime = Runtime()
    runtime.add(ZONE, {"location": "global"})
    runtime.add(ZONE + "/virtualnetworklinks/shared-link", {"location": "global", "properties": {
        "virtualNetwork": {"id": VNET}, "registrationEnabled": False, "virtualNetworkLinkState": "InProgress"}})
    with pytest.raises(core.TransitionError, match="existing-dns-link-readiness-required"):
        plan(runtime)
    assert not runtime.writes


HUB_PE_SUBNET = VNET + "/subnets/snet-aif-hub-private-endpoints"
FACTORY_A = "11111111-1111-1111-1111-111111111111"
FACTORY_B = "22222222-2222-2222-2222-222222222222"


class SharedFactoriesRuntime(Runtime):
    def __init__(self):
        super().__init__()
        self.factories = {}
        self.add(HUB_PE_SUBNET, {"properties": {"addressPrefix": "10.20.1.0/24", "delegations": []}})
        for label, factory_id, principal, repository_id, runner_id, region in (
            ("a", FACTORY_A, "33333333-3333-3333-3333-333333333333", 101, 201, "westeurope"),
            ("b", FACTORY_B, "44444444-4444-4444-4444-444444444444", 102, 202, "northeurope"),
        ):
            rg = f"/subscriptions/{SUB}/resourcegroups/factory-{label}-common"
            vnet = rg + "/providers/microsoft.network/virtualnetworks/spoke-" + label
            subnet = vnet + "/subnets/runners"
            vm = rg + "/providers/microsoft.compute/virtualmachines/runner-" + label
            repo = "https://github.com/company/factory-" + label
            self.add(vnet, {"location": region})
            self.add(subnet, {"properties": {"delegations": []}})
            self.add(vm, {"name": "runner-" + label, "location": region, "identity": {"principalId": principal},
                          "properties": {"storageProfile": {"osDisk": {"osType": "Linux"}}}})
            self.factories[label] = {"factory_id": factory_id, "rg": rg, "vnet": vnet, "subnet": subnet,
                "vm": vm, "principal": principal, "repository": repo, "repository_id": repository_id,
                "runner_id": runner_id, "runner_name": "runner-" + label, "commit": label * 40}
        self.blobs[core.COORDINATION] = {"schema": 1, "protocol": "aifactory-physical-lock-v1",
            "enforcement": "all-writers-exclusive", "revision": 0, "writers": {}, "scopes": {}}
        self.blobs[core.REGISTRY] = {"schema": 1, "hub_resource_group_id": HUB,
                                    "inventory_complete": True, "writers": {}}
        self.register_factory("a")

    def register_factory(self, label):
        factory = self.factories[label]
        name = "writer-" + label
        self.blobs[core.COORDINATION]["writers"][name] = {
            "kind": "gha", "repository": factory["repository"], "deployment_object_id": factory["principal"],
            "runner": {"kind": "self-hosted", "os": "linux"}}
        self.blobs[core.COORDINATION]["scopes"][factory["rg"]] = {
            "scope_kind": "aifactory-owned", "target": {"factory_id": factory["factory_id"]}, "writers": [name]}
        self.blobs[core.COORDINATION]["revision"] += 1

    def provider_read(self, writer, path):
        factory = next(value for value in self.factories.values() if value["repository"] == writer["repository"])
        if "/actions/runners?" in path:
            return {"runners": [{"id": factory["runner_id"], "name": factory["runner_name"], "os": "linux", "status": "online"}]}
        if "/actions/runners/" in path:
            assert path.endswith("/" + str(factory["runner_id"]))
            return {"id": factory["runner_id"], "name": factory["runner_name"], "os": "linux", "status": "online"}
        if "/commits/" in path:
            return {"sha": factory["commit"]}
        if "/contents/" in path:
            return {"type": "file", "encoding": "base64",
                    "content": base64.b64encode((ROOT / core.PROBE).read_bytes()).decode()}
        return {"id": factory["repository_id"], "full_name": factory["repository"].removeprefix("https://github.com/"),
                "default_branch": "main"}

    def inputs(self, label):
        factory = self.factories[label]
        return {"root": ROOT, "scope": {"factory_id": factory["factory_id"]},
                "bootstrap_config": {"tenant_id": TENANT}, "expected_revision": "revision-" + label,
                "workflow_id": "workflow-" + label, "coordination": COORDS,
                "provider_serialization": {"repository": factory["repository"], "ref": "refs/heads/aifactory-initializer-lock"},
                "bindings": {"runner_vm_id": factory["vm"], "runner_subnet_id": factory["subnet"],
                    "runner_name": factory["runner_name"], "deployment_principal_id": factory["principal"],
                    "integrated_vnet_id": factory["vnet"], "hub_private_endpoint_subnet_id": HUB_PE_SUBNET,
                    "network": {"mode": "external", "owned": False, "vnet_id": VNET, "resource_group_id": HUB}}}


def test_two_factory_spokes_reuse_one_retained_hub_endpoint_and_proof_outputs(tmp_path):
    runtime = SharedFactoriesRuntime()
    adapter = core.PrivateProbeAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    first_inputs = runtime.inputs("a")
    first_plan = adapter.prepare(**first_inputs)
    assert first_plan["can_execute"], first_plan
    first = adapter.execute(first_plan, root=ROOT, workflow_id=first_inputs["workflow_id"])
    assert first["status"] == "succeeded", first
    endpoint_before = copy.deepcopy(runtime.resources[PE])
    assert endpoint_before["properties"]["subnet"]["id"] == HUB_PE_SUBNET
    assert endpoint_before["location"] == runtime.resources[VNET]["location"]
    runtime.register_factory("b")
    second_inputs = runtime.inputs("b")
    second_plan = adapter.prepare(**second_inputs)
    assert second_plan["can_execute"], second_plan
    assert second_plan["frozen_plan"]["context"]["private_endpoint_subnet_id"] == HUB_PE_SUBNET
    assert not any(effect["id"] == PE for effect in second_plan["effects"])
    assert {VNET, runtime.factories["b"]["vnet"]} <= set(second_plan["frozen_plan"]["context"]["dns_vnet_ids"])
    second = adapter.execute(second_plan, root=ROOT, workflow_id=second_inputs["workflow_id"])
    assert second["status"] == "succeeded", second
    for receipt in (first, second):
        proof = receipt["outputs"]["hub_private_access"]
        assert proof["private_endpoint_id"] == PE
        assert proof["private_endpoint_subnet_id"] == HUB_PE_SUBNET
        assert proof["private_endpoint_vnet_id"] == VNET and proof["hub_resource_group_id"] == HUB
    assert second["outputs"]["hub_private_access"]["writer_ids"] == ["writer-a", "writer-b"]
    assert runtime.resources[PE] == endpoint_before
    assert all(factory["subnet"] != HUB_PE_SUBNET for factory in runtime.factories.values())
    assert not any(HUB_PE_SUBNET.startswith(factory["rg"] + "/") for factory in runtime.factories.values())
    final_adapter = core.PrivateTransitionAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    final_plan = final_adapter.prepare(**second_inputs)
    assert final_plan["can_execute"], final_plan
    final = final_adapter.execute(final_plan, root=ROOT, workflow_id=second_inputs["workflow_id"])
    assert final["status"] == "succeeded", final
    assert final["outputs"]["hub_private_access"]["private_endpoint_subnet_id"] == HUB_PE_SUBNET
    assert final["outputs"]["hub_private_access"]["private_transition_complete"]
    assert runtime.resources[ACCOUNT]["properties"]["publicNetworkAccess"] == "Disabled"
    assert runtime.resources[PE] == endpoint_before


@pytest.mark.parametrize("phase", [core.PrivateProbeAdapter, core.PrivateTransitionAdapter])
def test_adapter_never_falls_back_to_runner_subnet_without_shared_hub_binding(tmp_path, phase):
    runtime = SharedFactoriesRuntime()
    inputs = runtime.inputs("a")
    inputs["bindings"].pop("hub_private_endpoint_subnet_id")
    adapter = phase(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    prepared = adapter.prepare(**inputs)
    assert not prepared["can_execute"]
    assert prepared["blockers"] == ["hub-private-endpoint-subnet-binding-required"]
    assert not runtime.writes


@pytest.mark.parametrize("change, error", [
    ("subnet-state", "private-endpoint-subnet-not-ready"),
    ("vnet-state", "private-endpoint-vnet-not-ready"),
    ("factory-ownership", "shared-hub-vnet-has-factory-ownership"),
    ("integrated-config", "integrated-shared-private-endpoint-retention-contract-required"),
    ("integrated-binding", "integrated-shared-private-endpoint-retention-contract-required"),
])
def test_adapter_checks_retained_hub_live_state_and_never_reinterprets_integrated(tmp_path, change, error):
    runtime = SharedFactoriesRuntime()
    inputs = runtime.inputs("a")
    if change == "subnet-state":
        runtime.resources[HUB_PE_SUBNET]["properties"]["provisioningState"] = "Updating"
    elif change == "vnet-state":
        runtime.resources[VNET]["properties"]["provisioningState"] = "Updating"
    elif change == "factory-ownership":
        runtime.resources[VNET]["tags"] = {"AIFactory.Factory_ID": FACTORY_A}
    elif change == "integrated-config":
        inputs["bootstrap_config"].update(access_hub_mode="integrated", setup_hub_access=True)
    else:
        inputs["bindings"]["network"]["mode"] = "integrated"
    before = copy.deepcopy(inputs)
    adapter = core.PrivateProbeAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    prepared = adapter.prepare(**inputs)
    assert not prepared["can_execute"] and prepared["blockers"] == [error]
    assert inputs == before and not runtime.writes and not runtime.requests


def test_direct_native_prepare_cannot_place_shared_endpoint_in_a_factory_spoke():
    runtime = SharedFactoriesRuntime()
    context = {**CONTEXT, "private_endpoint_subnet_id": runtime.factories["a"]["subnet"],
               "dns_vnet_ids": [VNET, runtime.factories["a"]["vnet"]]}
    with pytest.raises(core.TransitionError, match="private-endpoint-subnet-must-be-in-retained-connectivity-hub"):
        plan(runtime, context)
    assert not runtime.writes and not runtime.requests


@pytest.mark.parametrize("mode", ["spoke-subnet", "claimed-spoke-hub", "factory-owned"])
def test_adapter_rejects_factory_owned_or_wrong_physical_hub_pe_network(tmp_path, mode):
    runtime = SharedFactoriesRuntime()
    inputs = runtime.inputs("a")
    if mode == "factory-owned":
        inputs["bindings"]["network"]["owned"] = True
    else:
        inputs["bindings"]["hub_private_endpoint_subnet_id"] = runtime.factories["a"]["subnet"]
        if mode == "claimed-spoke-hub":
            inputs["bindings"]["network"].update(vnet_id=runtime.factories["a"]["vnet"],
                                                   resource_group_id=runtime.factories["a"]["rg"])
    adapter = core.PrivateProbeAdapter(source_root=ROOT, state_dir=tmp_path, runtime_factory=lambda *args: runtime)
    prepared = adapter.prepare(**inputs)
    assert not prepared["can_execute"]
    assert prepared["blockers"][0] in ("retained-shared-hub-network-bindings-required",
                                       "private-endpoint-subnet-must-be-in-retained-connectivity-hub")
    assert not runtime.writes
