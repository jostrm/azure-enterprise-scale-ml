"""Defender for Cloud compute baseline for every VM, VM scale set and AKS cluster AI Factory provisions.

These Defender for Cloud recommendations must not come back for a newly provisioned machine:

- encryption at host (``securityProfile.encryptionAtHost``; AKS node pools ``enableEncryptionAtHost``);
- Generation 2 images with Trusted Launch (``securityType`` TrustedLaunch, Secure Boot and vTPM). The
  microsoft-dsvm ``dsvm-win-2022:winserver-2022`` and ``dsvm-win-2019:server-2019`` images are
  Generation 1 only (``az vm image show --query hyperVGeneration`` returns V1), so no module may use them;
- the Guest Configuration extension with a system-assigned identity, and Guest Attestation;
- periodic assessment of missing system updates (``patchSettings.assessmentMode`` AutomaticByPlatform);
- SSD-backed managed disks (never ``Standard_LRS``, which is HDD);
- AKS: Defender profile, Azure Policy add-on and control-plane diagnostic logs in Log Analytics.

Azure Backup is opt-in (``enableVmBackup``). Every check reads the compiled ARM template, the runner
bootstrap or the scripts, so a new module or script that creates a VM fails here until it follows the
baseline. Bicep sources under ``debug/`` are vendored samples and are not deployed.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from base.arm_expressions import arm_value, compile_bicep, nested_parameters, parameters_with_defaults, resources


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
BOOTSTRAP = ROOT / "bootstrap"
CLS = BICEP / "copy_to_local_settings"
VM_TYPE = "Microsoft.Compute/virtualMachines"
EXTENSION_TYPE = "Microsoft.Compute/virtualMachines/extensions"
CLUSTER_TYPE = "Microsoft.ContainerService/managedClusters"
DEPLOYMENT_TYPE = "Microsoft.Resources/deployments"
WORKSPACE = ("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-cmn"
             "/providers/Microsoft.OperationalInsights/workspaces/la-cmn")

# Every image a VM module or runner may use, each verified read-only on 2026-10-23 with
# `az vm image show --urn <urn>:<latest> --query "{gen:hyperVGeneration, features:features}"`.
GEN2_IMAGES = {
    ("MicrosoftWindowsServer", "WindowsServer", "2022-datacenter-azure-edition"):
        "V2, SecurityType=TrustedLaunchAndConfidentialVmSupported",
    ("Canonical", "ubuntu-24_04-lts", "server"): "V2, SecurityType=TrustedLaunchSupported",
}
GEN1_ONLY = {
    ("microsoft-dsvm", "dsvm-win-2022", "winserver-2022"),
    ("microsoft-dsvm", "dsvm-win-2019", "server-2019"),
    ("microsoft-dsvm", "dsvm-win-2019", "winserver-2019"),
    ("microsoft-dsvm", "dsvm-windows", "server-2016"),
    ("microsoft-dsvm", "dsvm-windows", "server-2019"),
}
SSD_DISKS = {"Premium_LRS", "StandardSSD_LRS", "Premium_ZRS", "StandardSSD_ZRS", "PremiumV2_LRS"}

# Every non-debug Bicep file that declares a VM (not an `existing` reference) -> its OS.
VM_MODULES = {
    "modules/virtualMachinePrivate.bicep": "Windows",
    "modules/virtualMachinePublic.bicep": "Windows",
    "esml-common/modules-common/avdSessionHost.bicep": "Windows",
    "esml-common/modules-common/cloudflareTunnelVm.bicep": "Linux",
}
GUEST_CONFIGURATION = {
    "Windows": ("AzurePolicyforWindows", "ConfigurationforWindows"),
    "Linux": ("AzurePolicyforLinux", "ConfigurationForLinux"),
}
ATTESTATION_PUBLISHER = {
    "Windows": "Microsoft.Azure.Security.WindowsAttestation",
    "Linux": "Microsoft.Azure.Security.LinuxAttestation",
}
# kube-apiserver and kube-audit are left out on purpose: high volume and Log Analytics cost.
AKS_LOG_CATEGORIES = {"kube-audit-admin", "kube-controller-manager", "kube-scheduler", "cluster-autoscaler", "guard"}


def _union(*items):
    if all(isinstance(item, dict) for item in items):
        merged = {}
        for item in items:
            merged.update(item)
        return merged
    return list(dict.fromkeys(element for item in items for element in item))


# Deployment functions the compiled VM modules use; values only need to be stable.
STUBS = {
    "union": _union,
    "resourceId": lambda *parts: "/".join(str(part) for part in parts),
    "extensionResourceId": lambda *parts: "/".join(str(part) for part in parts),
    "uniqueString": lambda *parts: "abcde12345",
    "concat": lambda *parts: "".join(str(part) for part in parts),
    "base64": lambda text: text,
    "string": str,
    "bool": bool,
    "coalesce": lambda *items: next((item for item in items if item is not None), None),
    "resourceGroup": lambda: {"name": "rg-test", "id": "/subscriptions/s/resourceGroups/rg-test",
                              "location": "swedencentral"},
    "subscription": lambda: {"subscriptionId": "s", "id": "/subscriptions/s"},
    "environment": lambda: {"suffixes": {"storage": "core.windows.net"}},
}


def resolve(node, parameters, template):
    """Evaluate a compiled property tree the way ARM would, for the parameters given."""
    if isinstance(node, dict):
        return {key: resolve(value, parameters, template) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve(value, parameters, template) for value in node]
    if isinstance(node, str) and node.startswith("[") and not node.startswith("[["):
        return resolve(arm_value(node, parameters, template, STUBS), parameters, template)
    return node


def required_values(template):
    """A value for each parameter without a default, by declared type."""
    values = {}
    for name, declared in template.get("parameters", {}).items():
        if "defaultValue" in declared:
            continue
        kind = declared["type"].lower()
        values[name] = {"string": f"{name.lower()}-value-0001", "securestring": "secret-value",
                        "bool": False, "int": 1, "object": {}, "array": []}[kind]
    return values


def module_parameters(template, **overrides):
    return parameters_with_defaults(template, {**required_values(template), **overrides}, STUBS)


def declared(template, resource_type):
    return [item for item in resources(template) if item["type"] == resource_type and not item.get("existing")]


def deployed(item, parameters, template):
    return "condition" not in item or bool(arm_value(item["condition"], parameters, template, STUBS))


def nested(template, contains_type):
    """Module deployments whose inline template declares a resource of contains_type."""
    return [item for item in declared(template, DEPLOYMENT_TYPE)
            if any(child["type"] == contains_type for child in resources(item["properties"]["template"]))]


def vm_resource(path, **overrides):
    template = compile_bicep(BICEP / path)
    parameters = module_parameters(template, **overrides)
    machines = declared(template, VM_TYPE)
    assert len(machines) == 1, f"{path}: expected one VM declaration, found {len(machines)}"
    return template, parameters, machines[0]


def vm_properties(vm, parameters, template):
    """The VM properties these checks read. osProfile keeps only its *Configuration objects:
    customData scripts are multi-line literals that the offline evaluator does not parse."""
    raw = dict(vm["properties"])
    profile = raw.pop("osProfile")
    properties = resolve(raw, parameters, template)
    properties["osProfile"] = {key: resolve(value, parameters, template)
                               for key, value in profile.items() if key.endswith("Configuration")}
    return properties


def non_debug_bicep():
    for path in sorted(BICEP.rglob("*.bicep")):
        relative = path.relative_to(BICEP).as_posix()
        if "debug/" in relative or relative.startswith("debug") or "/.graph-work-" in relative:
            continue
        yield relative, path.read_text(encoding="utf-8")


def test_every_vm_or_scale_set_declaration_is_under_this_baseline():
    found = set()
    for relative, text in non_debug_bicep():
        for match in re.finditer(r"resource\s+\w+\s+'Microsoft\.Compute/(virtualMachines|virtualMachineScaleSets)@"
                                 r"[^']+'\s*=", text):
            assert match[1] == "virtualMachines", f"{relative}: VM scale sets need this baseline first"
            found.add(relative)
    assert found == set(VM_MODULES), "a new VM module must join VM_MODULES and follow the baseline"


@pytest.mark.parametrize("path,os_type", VM_MODULES.items())
def test_vm_uses_a_generation_2_image_with_trusted_launch_and_encryption_at_host(path, os_type):
    template, parameters, vm = vm_resource(path)
    properties = vm_properties(vm, parameters, template)
    image = properties["storageProfile"]["imageReference"]
    key = (image["publisher"], image["offer"], image["sku"])
    assert key not in GEN1_ONLY, f"{path}: {key} is a Generation 1 image"
    assert key in GEN2_IMAGES, f"{path}: {key} is not a verified Generation 2 image"
    assert properties["securityProfile"] == {
        "encryptionAtHost": True, "securityType": "TrustedLaunch",
        "uefiSettings": {"secureBootEnabled": True, "vTpmEnabled": True},
    }


@pytest.mark.parametrize("path,os_type", VM_MODULES.items())
def test_vm_has_identity_update_assessment_and_ssd_disks(path, os_type):
    template, parameters, vm = vm_resource(path)
    assert "SystemAssigned" in resolve(vm["identity"], parameters, template)["type"]
    properties = vm_properties(vm, parameters, template)
    configuration = properties["osProfile"]["windowsConfiguration" if os_type == "Windows" else "linuxConfiguration"]
    assert configuration["patchSettings"]["assessmentMode"] == "AutomaticByPlatform"
    if os_type == "Windows":
        assert configuration["patchSettings"]["patchMode"] in ("AutomaticByOS", "AutomaticByPlatform")
    disks = [properties["storageProfile"]["osDisk"], *properties["storageProfile"].get("dataDisks", [])]
    for disk in disks:
        assert disk["managedDisk"]["storageAccountType"] in SSD_DISKS, f"{path}: HDD or unset disk {disk}"


@pytest.mark.parametrize("path,os_type", VM_MODULES.items())
def test_vm_installs_guest_configuration_and_guest_attestation(path, os_type):
    template, parameters, _ = vm_resource(path)
    modules = nested(template, EXTENSION_TYPE)
    security = [item for item in modules
                if any("GuestAttestation" in str(child.get("name")) for child in resources(item["properties"]["template"]))]
    assert len(security) == 1, f"{path}: deploy modules/vmSecurityExtensions.bicep once"
    assert deployed(security[0], parameters, template)
    passed = nested_parameters(security[0], parameters, template, STUBS)
    assert passed["osType"] == os_type


@pytest.mark.parametrize("os_type", ["Windows", "Linux"])
def test_security_extensions_module_installs_both_extensions(os_type):
    template = compile_bicep(BICEP / "modules/vmSecurityExtensions.bicep")
    parameters = module_parameters(template, osType=os_type)
    extensions = {}
    for item in declared(template, EXTENSION_TYPE):
        if deployed(item, parameters, template):
            extensions[arm_value(item["name"], parameters, template, STUBS).rsplit("/", 1)[-1]] = (
                resolve(item["properties"], parameters, template))
    name, extension_type = GUEST_CONFIGURATION[os_type]
    assert set(extensions) == {name, "GuestAttestation"}
    assert extensions[name]["publisher"] == "Microsoft.GuestConfiguration"
    assert extensions[name]["type"] == extension_type
    assert extensions["GuestAttestation"]["publisher"] == ATTESTATION_PUBLISHER[os_type]
    assert extensions["GuestAttestation"]["type"] == "GuestAttestation"
    for extension in extensions.values():
        assert extension["autoUpgradeMinorVersion"] is True
        assert extension["enableAutomaticUpgrade"] is True


def test_encryption_at_host_can_be_opted_out_without_losing_trusted_launch():
    template, parameters, vm = vm_resource("modules/virtualMachinePrivate.bicep", enableEncryptionAtHost=False)
    profile = vm_properties(vm, parameters, template)["securityProfile"]
    assert profile["encryptionAtHost"] is False
    assert profile["securityType"] == "TrustedLaunch"


def test_existing_private_vm_is_never_put_again():
    """An existing VM (often a Gen1 DSVM, sometimes the ADO agent itself) cannot change image,
    security type or encryption at host in place, and its password is not rotated by a redeploy."""
    path = "modules/virtualMachinePrivate.bicep"
    template = compile_bicep(BICEP / path)
    for exists in (False, True):
        parameters = module_parameters(template, vmExists=exists)
        for item in resources(template):
            if item.get("existing"):
                continue
            if item["type"] in (VM_TYPE, "Microsoft.Network/networkInterfaces", EXTENSION_TYPE,
                                "Microsoft.KeyVault/vaults/secrets", "Microsoft.DevTestLab/schedules"):
                assert deployed(item, parameters, template) is (not exists), (item["type"], exists)
        security = nested(template, EXTENSION_TYPE)[0]
        assert deployed(security, parameters, template) is (not exists)


@pytest.mark.parametrize("path", sorted(VM_MODULES))
def test_azure_backup_is_opt_in(path):
    template = compile_bicep(BICEP / path)
    backup = nested(template, "Microsoft.RecoveryServices/vaults")
    assert len(backup) == 1, f"{path}: deploy modules/vmBackup.bicep for enableVmBackup"
    assert not deployed(backup[0], module_parameters(template), template)
    assert deployed(backup[0], module_parameters(template, enableVmBackup=True), template)


def test_backup_module_protects_the_vm_with_an_enhanced_daily_policy():
    template = compile_bicep(BICEP / "modules/vmBackup.bicep")
    parameters = module_parameters(template, vmName="dsvm-cmn-sdc-dev-001")
    by_type = {item["type"]: item for item in resources(template) if not item.get("existing")}
    vault = by_type["Microsoft.RecoveryServices/vaults"]
    assert resolve(vault["sku"], parameters, template)["name"] == "RS0"
    policy = resolve(by_type["Microsoft.RecoveryServices/vaults/backupPolicies"]["properties"], parameters, template)
    # Trusted Launch VMs can only be protected by the Enhanced (V2) policy.
    assert policy["backupManagementType"] == "AzureIaasVM"
    assert policy["policyType"] == "V2"
    assert policy["schedulePolicy"]["schedulePolicyType"] == "SimpleSchedulePolicyV2"
    assert policy["schedulePolicy"]["scheduleRunFrequency"] == "Daily"
    assert policy["retentionPolicy"]["dailySchedule"]["retentionDuration"]["count"] >= 7
    item = by_type["Microsoft.RecoveryServices/vaults/backupFabrics/protectionContainers/protectedItems"]
    name = arm_value(item["name"], parameters, template, STUBS)
    assert name.endswith("/Azure/iaasvmcontainer;iaasvmcontainerv2;rg-test;dsvm-cmn-sdc-dev-001"
                         "/vm;iaasvmcontainerv2;rg-test;dsvm-cmn-sdc-dev-001")
    properties = resolve(item["properties"], parameters, template)
    assert properties["protectedItemType"] == "Microsoft.Compute/virtualMachines"
    assert properties["sourceResourceId"].endswith("Microsoft.Compute/virtualMachines/dsvm-cmn-sdc-dev-001")


def aks(**overrides):
    template = compile_bicep(BICEP / "modules/aksCluster.bicep")
    pools = [{"name": "agentpool", "count": 1, "vmSize": "Standard_D4s_v5", "mode": "System"}]
    parameters = module_parameters(template, agentPoolProfiles=pools, **overrides)
    return template, parameters


def test_aks_cluster_enables_defender_policy_and_node_encryption_at_host():
    template, parameters = aks(logAnalyticsWorkspaceResourceId=WORKSPACE)
    cluster = declared(template, CLUSTER_TYPE)[0]
    properties = resolve(cluster["properties"], parameters, template)
    assert properties["securityProfile"]["defender"] == {
        "logAnalyticsWorkspaceResourceId": WORKSPACE, "securityMonitoring": {"enabled": True}}
    assert properties["addonProfiles"]["azurepolicy"]["enabled"] is True
    assert [pool["enableEncryptionAtHost"] for pool in properties["agentPoolProfiles"]] == [True]
    assert properties["agentPoolProfiles"][0]["vmSize"] == "Standard_D4s_v5"


def test_aks_cluster_sends_control_plane_logs_to_log_analytics():
    template, parameters = aks(logAnalyticsWorkspaceResourceId=WORKSPACE)
    settings = declared(template, "Microsoft.Insights/diagnosticSettings")
    assert len(settings) == 1 and deployed(settings[0], parameters, template)
    properties = resolve(settings[0]["properties"], parameters, template)
    assert properties["workspaceId"] == WORKSPACE
    assert {log["category"] for log in properties["logs"] if log["enabled"]} == AKS_LOG_CATEGORIES
    without, without_parameters = aks()
    assert not deployed(declared(without, "Microsoft.Insights/diagnosticSettings")[0], without_parameters, without)
    assert resolve(declared(without, CLUSTER_TYPE)[0]["properties"], without_parameters, without)[
        "securityProfile"] is None


def test_aks_node_encryption_at_host_can_be_opted_out():
    template, parameters = aks(enableEncryptionAtHost=False)
    properties = resolve(declared(template, CLUSTER_TYPE)[0]["properties"], parameters, template)
    assert [pool["enableEncryptionAtHost"] for pool in properties["agentPoolProfiles"]] == [False]


def module_block(text, symbol):
    match = re.search(rf"^module {symbol} '[^']+'.*?^\}}", text, re.M | re.S)
    assert match, symbol
    return match[0]


@pytest.mark.parametrize("path,symbols", [
    ("esml-genai-1/05-compute-services.bicep", ("aksDev", "aksTestProd")),
    ("modules/machineLearningAks.bicep", ("aksDev", "aksTestProd")),
])
def test_aks_callers_pass_the_workspace_and_encryption_at_host(path, symbols):
    text = (BICEP / path).read_text(encoding="utf-8")
    for symbol in symbols:
        block = module_block(text, symbol)
        assert re.search(r"^\s+logAnalyticsWorkspaceResourceId: \S", block, re.M), (path, symbol)
        assert re.search(r"^\s+enableEncryptionAtHost: enableEncryptionAtHost$", block, re.M), (path, symbol)


def test_ml_data_platform_passes_the_workspace_to_the_aml_aks_module():
    block = module_block((BICEP / "esml-genai-1/07-ml-data-platform.bicep").read_text(encoding="utf-8"), "amlv2Aks")
    assert re.search(r"^\s+logAnalyticsWorkspaceResourceId: \S", block, re.M)
    assert re.search(r"^\s+enableEncryptionAtHost: enableEncryptionAtHost$", block, re.M)


@pytest.mark.parametrize("path,symbol,exists", [
    ("esml-common/main/13-rgLevel.bicep", "vmPrivate", "adminVmExists"),
    ("esml-genai-1/02-core-infrastructure.bicep", "vmPrivate", "vmExists"),
])
def test_entrypoints_forward_the_vm_baseline_switches(path, symbol, exists):
    block = module_block((BICEP / path).read_text(encoding="utf-8"), symbol)
    for line in ("enableEncryptionAtHost: enableEncryptionAtHost", "enableVmBackup: enableVmBackup",
                 f"vmExists: {exists}"):
        assert re.search(rf"^\s+{re.escape(line)}$", block, re.M), (path, line)


def test_common_pipelines_detect_an_existing_admin_vm_before_deploying():
    ado = (CLS / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-1-aif-cmn.yaml").read_text(encoding="utf-8")
    gha = (CLS / "github-actions/infra-common.yml").read_text(encoding="utf-8")
    assert ado.count('bash "scripts/admin-vm-exists.sh"') == 1
    assert ado.count('--parameters adminVmExists="$adminVmExists"') == 1
    assert gha.count('bash "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/admin-vm-exists.sh"') == 3
    assert gha.count('--parameters adminVmExists="$adminVmExists"') == 3


def bash():
    git = shutil.which("git")
    candidate = Path(git).parent.parent / "usr" / "bin" / "bash.exe" if git and os.name == "nt" else None
    found = str(candidate) if candidate and candidate.is_file() else shutil.which("bash")
    assert found, "Bash runs the admin VM existence helper"
    return found


def run_with_fake_az(script, args, fake_az, tmp_path):
    (tmp_path / "az").write_text("#!/usr/bin/env bash\n" + fake_az, encoding="utf-8", newline="\n")
    (tmp_path / "az").chmod(0o755)
    shell = Path(bash()).as_posix()
    command = f'export PATH="$PWD:/usr/bin:/bin:$PATH"; "{shell}" "{script.as_posix()}" ' + " ".join(f'"{arg}"' for arg in args)
    return subprocess.run([bash(), "--noprofile", "--norc", "-c", command], cwd=tmp_path,
                          capture_output=True, text=True, timeout=30)


ADMIN_ARGS = ["true", "sub-1", "", "acme-", "esml-common", "sdc", "dev", "-001", "-001"]


@pytest.mark.parametrize("listed,expected", [("1", "true"), ("0", "false")])
def test_admin_vm_helper_mirrors_the_13_rglevel_names(tmp_path, listed, expected):
    fake = f'echo "$*" >> az.log\necho {listed}\n'
    result = run_with_fake_az(BICEP / "scripts/admin-vm-exists.sh", ADMIN_ARGS, fake, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
    call = (tmp_path / "az.log").read_text(encoding="utf-8")
    assert "vm list --subscription sub-1 --resource-group acme-esml-common-sdc-dev-001" in call
    assert "[?name=='dsvm-cmn-sdc-dev-001']" in call


def test_admin_vm_helper_honours_the_rg_override_and_disabled_vm(tmp_path):
    fake = 'echo "$*" >> az.log\necho 0\n'
    override = ADMIN_ARGS.copy()
    override[2] = "my-common-rg"
    result = run_with_fake_az(BICEP / "scripts/admin-vm-exists.sh", override, fake, tmp_path)
    assert result.returncode == 0 and "--resource-group my-common-rg " in (tmp_path / "az.log").read_text()
    (tmp_path / "az.log").unlink()
    disabled = ["false", *ADMIN_ARGS[1:]]
    result = run_with_fake_az(BICEP / "scripts/admin-vm-exists.sh", disabled, fake, tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == "false"
    assert not (tmp_path / "az.log").exists(), "no Azure read when the admin VM is disabled"


def test_admin_vm_helper_fails_closed_when_azure_cannot_be_read(tmp_path):
    result = run_with_fake_az(BICEP / "scripts/admin-vm-exists.sh", ADMIN_ARGS, "exit 3\n", tmp_path)
    assert result.returncode != 0 and result.stdout.strip() == ""


ENSURE = BICEP / "scripts/ensure-encryption-at-host.sh"
FEATURE_AZ = ('echo "$*" >> az.log\n'
              'case "$*" in "feature show"*) cat state;; "feature register"*) printf Registered > state;; esac\n')


def ensure_feature(tmp_path, state, *args):
    (tmp_path / "state").write_text(state, encoding="utf-8")
    result = run_with_fake_az(ENSURE, list(args), FEATURE_AZ, tmp_path)
    log = tmp_path / "az.log"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    if log.exists():
        log.unlink()
    return result, calls


def test_pipelines_register_encryption_at_host_before_creating_vms_or_aks(tmp_path):
    result, calls = ensure_feature(tmp_path, "NotRegistered", "true", "sub-2", "false", "true")
    assert result.returncode == 0, result.stderr
    assert any(call.startswith("feature register") and "--subscription sub-2" in call
               and "--namespace Microsoft.Compute" in call and "--name EncryptionAtHost" in call for call in calls)
    assert any(call.startswith("provider register") and "--namespace Microsoft.Compute" in call for call in calls)
    result, calls = ensure_feature(tmp_path, "Registered", "true", "sub-2", "true")
    assert result.returncode == 0 and not any("register" in call for call in calls)


@pytest.mark.parametrize("args", [("false", "sub-2", "true"), ("true", "sub-2", "false", "false"), ("true", "sub-2")])
def test_feature_check_is_skipped_when_nothing_needs_encryption_at_host(tmp_path, args):
    result, calls = ensure_feature(tmp_path, "NotRegistered", *args)
    assert result.returncode == 0 and calls == []


def test_feature_check_fails_with_the_opt_out_when_registration_is_not_allowed(tmp_path):
    (tmp_path / "state").write_text("NotRegistered", encoding="utf-8")
    fake = 'case "$*" in "feature show"*) cat state;; "feature register"*) exit 1;; esac\n'
    result = run_with_fake_az(ENSURE, ["true", "sub-2", "true"], fake, tmp_path)
    assert result.returncode != 0
    assert "ENABLE_ENCRYPTION_AT_HOST" in result.stdout + result.stderr


def test_every_deployment_that_forwards_encryption_at_host_checks_the_feature_first():
    ado_common = (CLS / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-1-aif-cmn.yaml").read_text(encoding="utf-8")
    ado_project = (CLS / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8")
    gha_common = (CLS / "github-actions/infra-common.yml").read_text(encoding="utf-8")
    gha_project = (CLS / "github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
    for text, script in ((ado_common, 'bash "scripts/ensure-encryption-at-host.sh"'),
                         (ado_project, 'bash "scripts/ensure-encryption-at-host.sh"'),
                         (gha_common, 'bash "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/ensure-encryption-at-host.sh"'),
                         (gha_project, 'bash "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/ensure-encryption-at-host.sh"')):
        assert text.count(script) == text.count("--parameters enableEncryptionAtHost="), script

def test_runner_vm_image_is_generation_2():
    source = (BOOTSTRAP / "lib/runner_bootstrap.py").read_text(encoding="utf-8")
    image = ast.literal_eval(re.search(r"^IMAGE = (\{.*\})$", source, re.M)[1])
    assert (image["publisher"], image["offer"], image["sku"]) in GEN2_IMAGES
    assert '"managedDisk": {"storageAccountType": "StandardSSD_LRS"}' in source


def test_no_script_creates_a_vm_without_the_baseline():
    """Scripts that create a VM or scale set with the CLI or PowerShell need every baseline flag."""
    flags = ("--security-type TrustedLaunch", "--enable-secure-boot", "--enable-vtpm", "--encryption-at-host",
             "--assign-identity")
    for path in sorted([*BOOTSTRAP.rglob("*"), *(ROOT / "environment_setup").rglob("*")]):
        relative = path.relative_to(ROOT).as_posix()
        if (not path.is_file() or path.suffix not in (".sh", ".ps1", ".azcli", ".yml", ".yaml", ".py")
                or "/debug/" in relative or "/unit-tests/" in relative or "/.graph-work-" in relative):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"\baz (?:vm|vmss) create\b(?:[^\n]*\\\n)*[^\n]*", text):
            missing = [flag for flag in flags if flag not in match[0]]
            assert not missing, f"{relative}: {match[0][:60]} lacks {missing}"
        assert not re.search(r"\bNew-AzVM(?:ss)?\b", text), f"{relative}: use the Bicep VM modules instead"


def feature_function_output(state, tmp_path):
    source = (BOOTSTRAP / "lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    name = "aif_register_encryption_at_host_feature"
    body = name + "() {" + source.split("\n" + name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    (tmp_path / "state").write_text(state, encoding="utf-8")
    script = "\n".join([
        "set -euo pipefail", "AIF_DRY_RUN=false", 'export PATH="/usr/bin:/bin:$PATH"',
        "aif_info() { :; }; aif_warn() { printf 'WARN:%s\\n' \"$*\"; }; sleep() { :; }",
        "az() { printf '%s\\n' \"$*\" >> az.log;"
        " case \"$*\" in 'feature show'*) cat state;; 'feature register'*) printf Registered > state;; esac; }",
        body, f"{name} sub-1",
    ])
    result = subprocess.run([bash(), "--noprofile", "--norc", "-c", script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    log = tmp_path / "az.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_bootstrap_registers_encryption_at_host_once(tmp_path):
    calls = feature_function_output("NotRegistered", tmp_path)
    assert any(call.startswith("feature register") and "--namespace Microsoft.Compute" in call
               and "--name EncryptionAtHost" in call and "--subscription sub-1" in call for call in calls)
    assert any(call.startswith("provider register") and "--namespace Microsoft.Compute" in call for call in calls)
    (tmp_path / "az.log").unlink()
    calls = feature_function_output("Registered", tmp_path)
    assert not any(call.startswith(("feature register", "provider register")) for call in calls), calls


def test_bootstrap_runs_the_feature_registration_for_the_dev_subscription():
    source = (BOOTSTRAP / "lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    assert re.search(r'^\s+aif_register_encryption_at_host_feature "\$AIF_DEV_SUBSCRIPTION_ID"$', source, re.M)
