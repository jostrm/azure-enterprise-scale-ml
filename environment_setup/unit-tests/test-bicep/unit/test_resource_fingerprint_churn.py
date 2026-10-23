"""Offline: resource fingerprints ignore what the platform and subscription governance change on their own.

Observed on AI Factory runners from 2026-10-15 to 2026-10-23 (Azure Resource Graph change history): every
deallocate/start rewrites a VM's provisioning state, its view of the OS disk's size and type, and its etag, and a
NIC's default outbound flag, DNS suffix and etag; the OS disk's state and ownership time follow the VM. MCAPS
governance sets runner OS disks to Standard HDD and removes their tags, and Defender for Cloud retries its MDE.Linux
extension, which a VM body embeds. The first night after COMMON must not read as a changed reviewed resource; any
other change still must.
"""

import copy

import pytest

from .test_resource_closure_parallel_reads import InventoryCloud, collect, fl


SCOPE = "/subscriptions/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/resourceGroups/aif-125-esml-common-sdc-dev-001"
VM = SCOPE + "/providers/Microsoft.Compute/virtualMachines/runner-gha-sdc-dev-001"
DISK = SCOPE + "/providers/Microsoft.Compute/disks/runner-gha-sdc-dev-001-os"
NIC = SCOPE + "/providers/Microsoft.Network/networkInterfaces/runner-gha-sdc-dev-001-nic"
DEFENDER = "Microsoft.Azure.AzureDefenderForServers"


def defender(force="f1", state="Failed", version="1.0"):
    return {"id": VM + "/extensions/MDE.Linux", "name": "MDE.Linux", "location": "swedencentral",
            "type": "Microsoft.Compute/virtualMachines/extensions",
            "properties": {"autoUpgradeMinorVersion": True, "forceUpdateTag": force, "provisioningState": state,
                           "publisher": DEFENDER, "type": "MDE.Linux", "typeHandlerVersion": version,
                           "settings": {"azureResourceId": VM.lower()}}}


def runner_vm(*, running=True, state="Succeeded", etag='"3"', extension=None):
    os_disk = {"osType": "Linux", "name": "runner-gha-sdc-dev-001-os", "createOption": "FromImage",
               "managedDisk": {"id": DISK}, "deleteOption": "Detach"}
    if running:  # Compute leaves out the size and type of a deallocated VM's OS disk
        os_disk["diskSizeGB"] = 128
        os_disk["managedDisk"]["storageAccountType"] = "StandardSSD_LRS"
    return {"id": VM, "name": "runner-gha-sdc-dev-001", "type": "Microsoft.Compute/virtualMachines",
            "location": "swedencentral", "etag": etag,
            "properties": {"hardwareProfile": {"vmSize": "Standard_D4s_v5"}, "provisioningState": state,
                           "storageProfile": {"osDisk": os_disk},
                           "osProfile": {"linuxConfiguration": {"patchSettings": {
                               "patchMode": "AutomaticByPlatform", "assessmentMode": "AutomaticByPlatform"}}},
                           "networkProfile": {"networkInterfaces": [{"id": NIC}]}},
            "resources": [extension or defender()]}


def os_disk(*, sku="StandardSSD_LRS", tags=None, state="Attached", owned="2026-10-23T01:40:00Z", mbps=100):
    return {"id": DISK, "name": "runner-gha-sdc-dev-001-os", "type": "Microsoft.Compute/disks",
            "location": "swedencentral", "managedBy": VM, "sku": {"name": sku, "tier": "Standard"},
            "tags": {"aifactory-runner-owner": "ff5d88eb"} if tags is None else tags,
            "properties": {"osType": "Linux", "diskSizeGB": 128, "diskIOPSReadWrite": 500, "diskMBpsReadWrite": mbps,
                           "encryption": {"type": "EncryptionAtRestWithPlatformKey"}, "diskState": state,
                           "LastOwnershipUpdateTime": owned, "provisioningState": "Succeeded"}}


def nic(*, outbound=True, suffix="abc.gx.internal.cloudapp.net", etag='W/"1"', subnet="snet-esml-cmn-001"):
    properties = {"ipConfigurations": [{"name": "private", "properties": {
                      "privateIPAllocationMethod": "Dynamic", "subnet": {"id": SCOPE + "/subnets/" + subnet}}}],
                  "macAddress": "7C-ED-8D-25-5A-09", "primary": True, "virtualMachine": {"id": VM},
                  "defaultOutboundConnectivityEnabled": outbound, "dnsSettings": {"dnsServers": []}}
    if suffix:
        properties["dnsSettings"]["internalDomainNameSuffix"] = suffix
    return {"id": NIC, "name": "runner-gha-sdc-dev-001-nic", "type": "Microsoft.Network/networkInterfaces",
            "location": "swedencentral", "etag": etag, "properties": properties}


def test_a_night_and_a_defender_retry_leave_the_runner_vm_fingerprint_unchanged():
    reviewed = runner_vm()
    morning = runner_vm(running=False, state="Updating", etag='"26"',
                        extension=defender(force="f2", state="Updating", version="1.1"))
    assert fl.resource_digest(morning) == fl.resource_digest(reviewed)
    assert fl.resource_etag(morning, {}) is None and fl.resource_etag(reviewed, {"ETag": '"3"'}) is None


@pytest.mark.parametrize("change", ["size", "patch", "identity", "disk", "nic"])
def test_a_real_vm_change_still_changes_its_fingerprint(change):
    body = runner_vm()
    properties = body["properties"]
    if change == "size":
        properties["hardwareProfile"]["vmSize"] = "Standard_D2s_v5"
    elif change == "patch":
        properties["osProfile"]["linuxConfiguration"]["patchSettings"]["patchMode"] = "ImageDefault"
    elif change == "identity":
        body["identity"] = {"type": "SystemAssigned"}
    elif change == "disk":
        properties["storageProfile"]["osDisk"]["managedDisk"]["id"] = DISK + "-other"
    else:
        properties["networkProfile"]["networkInterfaces"][0]["id"] = NIC + "-other"
    assert fl.resource_digest(body) != fl.resource_digest(runner_vm())


def test_governance_hdd_downgrade_and_power_cycles_leave_the_os_disk_fingerprint_unchanged():
    morning = os_disk(sku="Standard_LRS", tags={}, state="Reserved", owned="2026-10-24T08:21:00Z", mbps=60)
    assert fl.resource_digest(morning) == fl.resource_digest(os_disk())
    assert fl.resource_etag(morning, {}) is None


@pytest.mark.parametrize("field, value", [("diskSizeGB", 256), ("osType", "Windows"),
                                          ("encryption", {"type": "EncryptionAtRestWithCustomerKey"})])
def test_a_real_disk_change_still_changes_its_fingerprint(field, value):
    body = os_disk()
    body["properties"][field] = value
    assert fl.resource_digest(body) != fl.resource_digest(os_disk())


def test_a_power_cycle_leaves_the_nic_fingerprint_unchanged_but_a_new_subnet_does_not():
    reviewed = nic()
    assert fl.resource_digest(nic(outbound=False, suffix=None, etag='W/"2"')) == fl.resource_digest(reviewed)
    assert fl.resource_etag(reviewed, {}) is None
    assert fl.resource_digest(nic(subnet="snet-other")) != fl.resource_digest(reviewed)


def test_defender_extension_counts_only_its_identity_and_other_extensions_count_whole():
    reviewed = defender()
    assert fl.resource_digest(defender(force="f9", state="Updating", version="1.2")) == fl.resource_digest(reviewed)
    for field, value in (("publisher", "Contoso.Security"), ("type", "MDE.Windows")):
        changed = defender()
        changed["properties"][field] = value
        assert fl.resource_digest(changed) != fl.resource_digest(reviewed)
    moved = defender()
    moved["properties"]["settings"]["azureResourceId"] = VM.lower() + "-other"
    assert fl.resource_digest(moved) != fl.resource_digest(reviewed)
    script = defender()
    script["properties"]["publisher"] = "Microsoft.Azure.Extensions"
    retried = copy.deepcopy(script)
    retried["properties"]["forceUpdateTag"] = "f2"
    assert fl.resource_digest(retried) != fl.resource_digest(script)


def baseline_extension(publisher, extension_type, name, state="Succeeded", version="1.0"):
    return {"id": VM + "/extensions/" + name, "name": name, "location": "swedencentral",
            "type": "Microsoft.Compute/virtualMachines/extensions",
            "properties": {"autoUpgradeMinorVersion": True, "enableAutomaticUpgrade": True, "provisioningState": state,
                           "publisher": publisher, "type": extension_type, "typeHandlerVersion": version,
                           "settings": {}}}


@pytest.mark.parametrize("publisher, extension_type, name", [
    ("Microsoft.Azure.Security.LinuxAttestation", "GuestAttestation", "GuestAttestation"),
    ("Microsoft.GuestConfiguration", "ConfigurationForLinux", "AzurePolicyforLinux"),
])
def test_auto_upgraded_baseline_extensions_count_only_their_identity(publisher, extension_type, name):
    """The Defender for Cloud baseline installs these with enableAutomaticUpgrade: the platform upgrades them."""
    reviewed = baseline_extension(publisher, extension_type, name)
    upgraded = baseline_extension(publisher, extension_type, name, state="Updating", version="1.4")
    assert fl.resource_digest(upgraded) == fl.resource_digest(reviewed)
    for field, value in (("publisher", "Contoso.Security"), ("type", "Other")):
        changed = baseline_extension(publisher, extension_type, name)
        changed["properties"][field] = value
        assert fl.resource_digest(changed) != fl.resource_digest(reviewed)

def test_other_resources_keep_their_raw_fingerprint_and_etag():
    body = {"id": SCOPE + "/providers/Microsoft.Storage/storageAccounts/st", "type": "Microsoft.Storage/storageAccounts",
            "etag": '"7"', "sku": {"name": "Standard_LRS"}, "tags": {"a": "b"},
            "properties": {"provisioningState": "Succeeded"}}
    assert fl.resource_digest(body) == fl.digest(body)
    assert fl.resource_etag(body, {}) == '"7"'
    assert fl.resource_etag({"type": body["type"]}, {"ETag": '"8"'}) == '"8"'


def test_fingerprints_never_change_the_body_they_read():
    bodies = [runner_vm(), os_disk(), nic(), defender()]
    before = copy.deepcopy(bodies)
    for body in bodies:
        fl.resource_digest(body)
        fl.resource_etag(body, {})
    assert bodies == before


def test_resource_closure_is_unchanged_by_a_night_and_still_sees_a_resize():
    cloud = InventoryCloud(groups=1, sets=2)
    reviewed, _ = collect(cloud)
    vms = [body for body in cloud.bodies.values() if body.get("type") == "microsoft.compute/virtualmachines"]
    nics = [body for body in cloud.bodies.values() if body.get("type") == "microsoft.network/networkinterfaces"]
    assert vms and nics
    for body in vms:
        body["etag"] = '"26"'
        body["properties"]["provisioningState"] = "Updating"
    for body in nics:
        body["etag"] = 'W/"night"'
        body["properties"]["defaultOutboundConnectivityEnabled"] = False
    morning, _ = collect(cloud)
    assert morning == reviewed and fl.digest(morning) == fl.digest(reviewed)
    vms[0]["properties"]["hardwareProfile"] = {"vmSize": "Standard_D2s_v5"}
    resized, _ = collect(cloud)
    key = vms[0]["id"].lower()
    assert resized["resources"][key]["body_hash"] != reviewed["resources"][key]["body_hash"]
