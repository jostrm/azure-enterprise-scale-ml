"""Offline: bounded parallel reads in the resource-closure collector and a thread-safe Cloud.

The collector must build the same closure (values, digests and insertion order) whether its
read-only ARM GETs run one after another or ahead on a bounded worker pool, and any failed
read must still abort the whole closure with the code a serial walk would raise.
"""

import base64
import copy
import importlib.util
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("factory_lifecycle_parallel_reads", ROOT / "bootstrap/lib/factory_lifecycle.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)

SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
IDENTITY = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SCHEMAS = {
    "microsoft.network": {
        "virtualNetworks": "2024-05-01", "virtualNetworks/subnets": "2024-05-01",
        "virtualNetworks/subnets/delegations": "2024-05-01",
        "networkSecurityGroups": "2024-05-01", "networkSecurityGroups/securityRules": "2024-05-01",
        "networkSecurityGroups/probe": "2024-05-01",
        "privateEndpoints": "2024-05-01", "networkInterfaces": "2024-05-01",
        "networkInterfaces/ipConfigurations": "2024-05-01",
    },
    "microsoft.storage": {
        "storageAccounts": "2023-05-01", "storageAccounts/blobServices": "2023-05-01",
        "storageAccounts/blobServices/containers": "2023-05-01",
        "storageAccounts/privateEndpointConnections": "2023-05-01",
    },
    "microsoft.keyvault": {
        "vaults": "2023-07-01", "vaults/accessPolicies": "2023-07-01",
        "vaults/privateEndpointConnections": "2023-07-01",
    },
    "microsoft.compute": {"virtualMachines": "2024-07-01", "virtualMachines/metricDefinitions": "2024-07-01"},
    "microsoft.search": {"services": "2025-05-01"},
}
API = {namespace + "/" + kind.lower(): api for namespace, kinds in SCHEMAS.items() for kind, api in kinds.items()}
# networkSecurityGroups/probe has only an action: an ARM operation, never a resource.
ACTION_ONLY = {"microsoft.network/networksecuritygroups/probe"}


def group(index):
    return f"/subscriptions/{SUB}/resourceGroups/factory-{index:02d}"


class InventoryCloud:
    """A deterministic, thread-safe ARM read surface over a generated factory inventory."""

    def __init__(self, groups=2, sets=3, latency=0.0, workers=None):
        self.latency, self.failures, self.drift = latency, {}, {}
        self.gates, self.signals = {}, {}  # a gated read waits for its event; a signalling read sets one
        if workers is not None:
            self.closure_read_workers = workers
        self.lock = threading.Lock()
        self.in_flight = self.max_in_flight = 0
        self.calls = []
        self.bodies = {}
        self.groups = [group(index) for index in range(groups)]
        for scope in self.groups:
            self.bodies[scope.lower()] = {"id": scope, "name": scope.rsplit("/", 1)[1], "etag": '"rg"',
                                          "properties": {"provisioningState": "Succeeded"}}
            for item in range(sets):
                self.add_set(scope, item)
        # A cross-group reference that only reference discovery can reach.
        first, last = self.groups[0], self.groups[-1]
        self.bodies[(first + "/providers/Microsoft.Network/networkInterfaces/nic-0").lower()]["properties"][
            "peer"] = {"id": last + "/providers/Microsoft.Network/networkInterfaces/nic-0/ipConfigurations/ipconfig1"}

    def add(self, resource_id, properties=None, etag=None):
        kind = fl.resource_type_from_id(resource_id)
        self.bodies[resource_id.lower()] = {
            "id": resource_id, "name": resource_id.rsplit("/", 1)[1], "type": kind, "etag": etag or '"' + kind + '"',
            "properties": properties or {}}

    def add_set(self, scope, item):
        network = scope + "/providers/Microsoft.Network"
        vnet = f"{network}/virtualNetworks/vnet-{item}"
        subnet = vnet + "/subnets/snet-0"
        self.add(vnet)
        self.add(subnet, {"delegations": [{"id": subnet + "/delegations/web"}]})
        nsg = f"{network}/networkSecurityGroups/nsg-{item}"
        self.add(nsg, {"subnets": [{"id": subnet}]})
        for rule in range(3):
            self.add(f"{nsg}/securityRules/rule-{rule}", {"priority": 100 + rule})
        nic = f"{network}/networkInterfaces/nic-{item}"
        self.add(nic, {"ipConfigurations": [{"id": nic + "/ipConfigurations/ipconfig1", "subnet": {"id": subnet}}]})
        self.add(nic + "/ipConfigurations/ipconfig1", {"subnet": {"id": subnet}})
        storage = f"{scope}/providers/Microsoft.Storage/storageAccounts/st{item}"
        self.add(storage)
        self.add(storage + "/blobServices/default")
        for container in range(2):
            self.add(f"{storage}/blobServices/default/containers/data-{container}")
        self.add(f"{storage}/privateEndpointConnections/pec-{item}")
        vault = f"{scope}/providers/Microsoft.KeyVault/vaults/kv-{item}"
        self.add(vault, {"accessPolicies": []})
        endpoint = f"{network}/privateEndpoints/pe-{item}"
        self.add(endpoint, {"subnet": {"id": subnet}, "privateLinkServiceConnections": [
            {"properties": {"privateLinkServiceId": storage}}]})
        self.add(f"{scope}/providers/Microsoft.Compute/virtualMachines/vm-{item}", {"nic": {"id": nic}})
        if item == 0:
            self.add(f"{scope}/providers/Microsoft.Search/services/search-{item}")
        role = f"{storage}/providers/Microsoft.Authorization/roleAssignments/{item:08d}-0000-0000-0000-000000000000"
        self.bodies[role.lower()] = {"id": role, "name": role.rsplit("/", 1)[1],
                                     "type": "Microsoft.Authorization/roleAssignments",
                                     "properties": {"scope": storage}}

    def record(self, key):
        with self.lock:
            self.calls.append(key)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(self.latency)
            if key in self.signals:
                self.signals[key].set()
            if key in self.gates:
                assert self.gates[key].wait(10), "gated read was never released"
            failure = self.failures.get(key)
            if failure is not None:
                raise failure
        finally:
            with self.lock:
                self.in_flight -= 1

    def provider_schema(self, namespace):
        self.record(("provider_schema", namespace.lower()))
        return {"namespace": namespace, "resourceTypes": [
            {"resourceType": kind, "apiVersions": [api], "capabilities": "SupportsTags"}
            for kind, api in SCHEMAS[namespace.lower()].items()]}

    def provider_operations(self, namespace):
        self.record(("provider_operations", namespace.lower()))
        names = []
        for kind in SCHEMAS[namespace.lower()]:
            full = namespace.lower() + "/" + kind.lower()
            actions = ("action",) if full in ACTION_ONLY else ("read", "write", "delete")
            names.extend(full + "/" + action for action in actions)
        return names

    def list_resources(self, scope):
        self.record(("list_resources", scope.lower()))
        return [copy.deepcopy(body) for key, body in self.bodies.items()
                if fl.arm_scope(key) == scope.lower() and key != scope.lower()
                and key.count("/providers/") == 1 and len(key.split("/providers/", 1)[1].split("/")) == 3]

    def collection(self, path, api_version, extension=False):
        self.record(("collection", path.lower(), api_version, extension))
        prefix = path.lower() + "/"
        rows = [copy.deepcopy(body) for key, body in self.bodies.items()
                if key.startswith(prefix) and "/" not in key[len(prefix):]]
        if extension and path.lower().endswith("/providers/microsoft.insights/diagnosticsettings") \
                and "/subnets/" in path.lower():
            return [], "ResourceTypeNotSupported"
        return sorted(rows, key=lambda row: row["id"].lower()), None

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        assert method == "GET" and headers is None
        self.record(("arm", resource_id.lower(), api_version, tuple(allowed)))
        body = self.bodies.get(resource_id.lower())
        if body is None:
            fl.require(404 in allowed, "remote-request-failed-404")
            return 404, {}, None
        body = copy.deepcopy(body)
        body["id"] = self.drift.get(resource_id.lower(), body["id"])
        return 200, {"ETag": body.get("etag", "")}, body


def collect(cloud, scopes=None, versions=None):
    return fl.collect_resource_closure(cloud, scopes or cloud.groups, versions)


def ordered(value):
    """Insertion order is part of the contract, so compare without sorting keys."""
    return json.dumps(value)


def read_threads():
    return [thread for thread in threading.enumerate() if thread.name.startswith("aifactory-closure-read")]


def test_real_cloud_reads_closures_on_a_bounded_pool_and_fakes_stay_serial():
    assert fl.RESOURCE_CLOSURE_READ_WORKERS == 8
    assert fl.Cloud.closure_read_workers == fl.RESOURCE_CLOSURE_READ_WORKERS
    serial = InventoryCloud()
    collect(serial)
    assert serial.max_in_flight == 1 and not read_threads()


@pytest.mark.parametrize("versions", [False, True])
def test_parallel_closure_equals_serial_closure_for_the_same_responses(versions):
    serial, parallel = InventoryCloud(), InventoryCloud(workers=8)
    pinned = None
    if versions:
        # Bootstrap verification pins every root's API version, so providers load later.
        pinned = {row["id"].lower(): API[fl.resource_type_from_id(row["id"])]
                  for scope in serial.groups for row in serial.list_resources(scope)}
        serial.calls.clear()
    expected, expected_bodies = collect(serial, versions=pinned)
    actual, actual_bodies = collect(parallel, versions=pinned)
    assert actual == expected and actual_bodies == expected_bodies
    assert ordered(actual) == ordered(expected) and ordered(actual_bodies) == ordered(expected_bodies)
    assert fl.digest(actual) == fl.digest(expected)
    # Exactly the reads a serial walk makes: none skipped, none duplicated, no speculative extras.
    assert Counter(parallel.calls) == Counter(serial.calls)
    assert len(expected["resources"]) > 50 and expected["inline"] and expected["references"]
    assert any(entry.get("non_resource_metadata") for entry in expected["collections"].values())
    assert any(entry.get("unsupported") for entry in expected["collections"].values())
    assert parallel.max_in_flight > 1
    assert not read_threads()


def test_parallel_reads_never_exceed_the_worker_bound():
    for workers in (3, 8):
        cloud = InventoryCloud(latency=0.005, workers=workers)
        collect(cloud)
        assert 1 < cloud.max_in_flight <= workers
    assert not read_threads()


def failing_reads():
    cloud = InventoryCloud()
    first, last = cloud.groups[0], cloud.groups[-1]
    container = (last + "/providers/Microsoft.Storage/storageAccounts/st2/blobServices/default/containers/data-1").lower()
    return {
        "deep-resource-body": ("arm", container, "2023-05-01", (200,)),
        "child-collection": ("collection", (last + "/providers/Microsoft.Network/networkSecurityGroups/nsg-1"
                                            "/securityRules").lower(), "2024-05-01", False),
        "extension-collection": ("collection", (first + "/providers/Microsoft.KeyVault/vaults/kv-2/providers"
                                                "/Microsoft.Authorization/locks").lower(), "2016-09-01", True),
        "singleton": ("arm", (first + "/providers/Microsoft.Storage/storageAccounts/st1/blobServices/default").lower(),
                      "2023-05-01", (200, 404)),
        "provider-operations": ("provider_operations", "microsoft.search"),
        "second-scope-inventory": ("list_resources", last.lower()),
    }


@pytest.mark.parametrize("name", sorted(failing_reads()))
@pytest.mark.parametrize("failure", [fl.Blocked("remote-request-failed-503"), RuntimeError("worker crashed")])
def test_one_failed_read_aborts_the_whole_closure_with_the_serial_error(name, failure):
    key = failing_reads()[name]
    serial, parallel = InventoryCloud(), InventoryCloud(workers=8)
    serial.failures[key] = parallel.failures[key] = failure
    if key[0] == "collection" and isinstance(failure, fl.Blocked):
        # A collection that still fails after Cloud.request's own retries is recorded, not fatal (tolerant
        # inventory); serial and parallel walks record exactly the same closure.
        expected, actual = collect(serial), collect(parallel)
        assert actual == expected
        assert expected[0]["collections"][key[1]]["unsupported"] == "unreadable-remote-request-failed-503"
        assert not read_threads()
        return
    with pytest.raises(type(failure)) as expected:
        collect(serial)
    with pytest.raises(type(failure)) as actual:
        collect(parallel)
    assert str(actual.value) == str(expected.value) == str(failure)
    assert key in parallel.calls
    # Nothing keeps reading once the collector has failed.
    assert not read_threads()
    settled = len(parallel.calls)
    time.sleep(0.05)
    assert len(parallel.calls) == settled


def test_the_first_failure_in_serial_order_wins_even_when_a_later_read_fails_first():
    cloud = InventoryCloud(workers=8)
    first, last = cloud.groups[0], cloud.groups[-1]
    early = ("arm", (first + "/providers/Microsoft.Compute/virtualMachines/vm-0").lower(), "2024-07-01", (200,))
    late = ("collection", (last + "/providers/Microsoft.Search/services/search-0/providers"
                           "/Microsoft.Authorization/roleAssignments").lower(), "2022-04-01", True)
    cloud.failures[early], cloud.failures[late] = fl.Blocked("early-read-failed"), fl.Blocked("late-read-failed")
    # The early read only fails after the late read has already failed.
    cloud.gates[early] = cloud.signals[late] = threading.Event()
    with pytest.raises(fl.Blocked, match="^early-read-failed$"):
        collect(cloud)
    assert late in cloud.calls and cloud.signals[late].is_set()
    assert not read_threads()


def test_serial_guards_still_fail_closed_on_the_parallel_path():
    for workers in (None, 8):
        cloud = InventoryCloud(workers=workers)
        vault = (cloud.groups[0] + "/providers/Microsoft.KeyVault/vaults/kv-1").lower()
        cloud.drift[vault] = cloud.groups[0] + "/providers/Microsoft.KeyVault/vaults/other"
        with pytest.raises(fl.Blocked, match="^resource-closure-identity-mismatch$"):
            collect(cloud)
    assert not read_threads()


def token(exp):
    claims = base64.urlsafe_b64encode(json.dumps({"tid": TENANT, "oid": IDENTITY, "exp": exp}).encode()).decode()
    return "header." + claims.rstrip("=") + ".signature"


def test_concurrent_token_reads_share_one_cli_refresh():
    cloud = fl.Cloud({"identity": {"object_id": IDENTITY}, "target": {"tenant_id": TENANT, "subscription_id": SUB},
                      "route": {"kind": "ado"}, "locks": {"coordination_mode": "single-writer"}},
                     command_runner=lambda *args, **kwargs: None, opener=object())
    issued = []

    def command(argv, cwd=None, data=None):
        issued.append(argv)
        time.sleep(0.05)
        return json.dumps({"accessToken": token(time.time() + 3600)})

    cloud.command = command
    with ThreadPoolExecutor(max_workers=16) as pool:
        values = list(pool.map(lambda _: cloud.token(fl.ARM), range(32)))
    assert len(issued) == 1 and len(set(values)) == 1
    cloud.token_expiries[fl.ARM] = time.time()  # expiring: exactly one refresh again
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: cloud.token(fl.ARM), range(32)))
    assert len(issued) == 2
