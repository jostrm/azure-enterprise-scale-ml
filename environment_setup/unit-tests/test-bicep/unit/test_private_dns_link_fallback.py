"""Spoke links to shared private DNS zones must fall back to public DNS (offline only).

A factory spoke is linked to every shared privatelink zone, including Azure Monitor zones
that stay empty without an Azure Monitor Private Link Scope. A link with the default
resolution policy turns public names such as swedencentral-0.in.applicationinsights.azure.com
into NXDOMAIN inside the spoke and silently drops Application Insights telemetry. The Bicep
zone modules already link with NxDomainRedirect; both bootstrap paths must do the same.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
SCRIPT = (LIB / "create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
sys.path.insert(0, str(LIB))
SPEC = importlib.util.spec_from_file_location("registered_prerequisites_dns_fallback", LIB / "registered_prerequisites.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

SUB = "22222222-2222-2222-2222-222222222222"
SPOKE = (f"/subscriptions/{SUB}/resourceGroups/acme-esml-common-sdc-dev-001"
         "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")
LINK = "link-acme-dev-001"


def function(name):
    start = SCRIPT.index(f"{name}() {{")
    end = SCRIPT.find("\naif_", start + 1)
    return SCRIPT[start:end if end != -1 else None]


def bash(code, *names, cwd):
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        executable = str(candidate) if candidate.is_file() else None
    else:
        executable = shutil.which("bash")
    if not executable:
        pytest.skip("Git Bash required for isolated function tests")
    prefix = """set -euo pipefail
aif_info() { :; }; aif_success() { :; }; aif_section() { :; }
aif_error() { printf '%s\\n' "$*" >&2; }
gh() { echo UNEXPECTED_GH >&2; return 92; }
"""
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"BASH_ENV", "ENV", "SHELLOPTS"}}
    return subprocess.run(
        [executable, "--noprofile", "--norc", "-s"],
        input=prefix + "\n".join(function(name) for name in names) + "\n" + code,
        capture_output=True, text=True, timeout=30, cwd=cwd, env=environment,
    )


# Windows Azure CLI output ends lines with CRLF; the mock reproduces that.
AZ_MOCK = r"""AIF_HUB_SUBSCRIPTION_ID=hub-sub; AIF_HUB_RESOURCE_GROUP=hub-dns
value_of() { local key="$1"; shift; while (($#)); do [[ "$1" == "$key" ]] && { printf '%s' "$2"; return 0; }; shift; done; return 1; }
az() {
  printf '%s\n' "$*" >> calls.log
  if [[ "$1 $2 $3 $4" == 'network private-dns zone list' ]]; then
    printf 'privatelink.monitor.azure.com\r\nprivatelink.blob.core.windows.net\r\nprivatelink.vaultcore.azure.net\r\n'
    return 0
  fi
  [[ "$1 $2 $3 $4" == 'network private-dns link vnet' ]] || { echo "UNEXPECTED_AZ $*" >&2; return 91; }
  local zone
  zone="$(value_of --zone-name "$@")"
  case "$5" in
    show)
      case "$zone" in
        privatelink.blob.core.windows.net) printf 'Default\r\n' ;;
        privatelink.vaultcore.azure.net) printf 'NxDomainRedirect\r\n' ;;
        privatelink.monitor.azure.com) echo "ResourceNotFound" >&2; return 3 ;;
        *) echo "UNEXPECTED_ZONE $zone" >&2; return 93 ;;
      esac ;;
    create|update) : ;;
    *) echo "UNEXPECTED_AZ $*" >&2; return 91 ;;
  esac
}
"""


def writes(log):
    calls = [line.split(" ") for line in log.read_text(encoding="utf-8").splitlines()]
    return [call for call in calls if call[:4] == ["network", "private-dns", "link", "vnet"]
            and call[4] in ("create", "update")]


def option(call, name):
    return call[call.index(name) + 1]


def test_spoke_links_fall_back_to_public_dns_and_existing_links_are_reconciled(tmp_path):
    result = bash(AZ_MOCK + f"aif_link_spoke_private_dns_zones '{SPOKE}' '{LINK}'\n",
                  "aif_link_spoke_private_dns_zones", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "UNEXPECTED_" not in result.stderr
    changes = writes(tmp_path / "calls.log")
    assert [(call[4], option(call, "--zone-name")) for call in changes] == [
        ("create", "privatelink.monitor.azure.com"),
        ("update", "privatelink.blob.core.windows.net"),
    ]
    for call in changes:
        assert option(call, "--resolution-policy") == "NxDomainRedirect"
        assert (option(call, "--subscription"), option(call, "--resource-group"), option(call, "--name")) == (
            "hub-sub", "hub-dns", LINK)
    create = changes[0]
    assert option(create, "--virtual-network") == SPOKE
    assert option(create, "--registration-enabled") == "false"
    assert "--registration-enabled" not in changes[1] and "--virtual-network" not in changes[1]


def test_external_hub_access_links_spoke_through_the_fallback_helper():
    access = function("aif_ensure_private_network_access")
    external = access.split('elif [[ "$AIF_ACCESS_HUB_MODE" == "integrated" ]]; then', 1)[0]
    assert 'aif_link_spoke_private_dns_zones "$spoke_vnet_id" "link-${AIF_PREFIX%-}-dev-${AIF_SCALESET_SUFFIX}"' in external
    assert "private-dns link vnet create" not in access


def test_every_bootstrap_private_dns_link_create_requests_nxdomain_redirect():
    lines = SCRIPT.splitlines()
    commands = []
    for index, line in enumerate(lines):
        if "az network private-dns link vnet create" in line:
            command = [line]
            while command[-1].rstrip().endswith("\\"):
                index += 1
                command.append(lines[index])
            commands.append(" ".join(command))
    assert commands
    assert all(re.search(r"--resolution-policy\s+NxDomainRedirect\b", command) for command in commands)


class _Runtime:
    def __init__(self, links):
        self.links = links

    def arm(self, method, identifier, api, allowed=(200,), **_):
        assert method == "GET"
        if "/virtualnetworklinks/" in identifier.lower():
            return 404, {}, None
        return 200, {}, {"id": identifier, "location": "global", "properties": {"provisioningState": "Succeeded"}}

    def collection(self, identifier, api):
        zone = identifier.split("/privateDnsZones/", 1)[1].split("/", 1)[0]
        return self.links.get(zone, [])


VNET = f"/subscriptions/{SUB}/resourcegroups/common/providers/microsoft.network/virtualnetworks/common-vnet"
RG = f"/subscriptions/{SUB}/resourcegroups/common"
CONTEXT = {"location_short": "sdc"}
TARGET = {"location": "swedencentral"}


def _link(zone, **properties):
    return {"id": f"{RG}/providers/Microsoft.Network/privateDnsZones/{zone}/virtualNetworkLinks/existing",
            "location": "global",
            "properties": {"registrationEnabled": False, "virtualNetwork": {"id": VNET},
                           "provisioningState": "Succeeded", **properties}}


def test_registered_prerequisites_create_spoke_links_with_public_dns_fallback():
    builder = core.Builder(_Runtime({}))
    core._private_dns(builder, VNET, RG, CONTEXT, TARGET, {"owner": "test"})
    links = [effect for effect in builder.effects
             if effect["kind"] == "arm-create" and "/virtualNetworkLinks/" in effect["id"]]
    zones = {effect["id"].split("/privateDnsZones/", 1)[1].split("/", 1)[0] for effect in links}
    assert "privatelink.monitor.azure.com" in zones and builder.blockers == []
    for effect in links:
        assert effect["api"] == core.PRIVATE_DNS_LINK_API == "2024-06-01"
        assert effect["body"]["properties"] == {
            "registrationEnabled": False, "resolutionPolicy": "NxDomainRedirect", "virtualNetwork": {"id": VNET}}


def test_registered_prerequisites_keep_existing_default_policy_links_compatible():
    existing = {"privatelink.monitor.azure.com": [_link("privatelink.monitor.azure.com")],
                "privatelink.blob.core.windows.net": [_link("privatelink.blob.core.windows.net",
                                                            resolutionPolicy="Default")]}
    builder = core.Builder(_Runtime(existing))
    core._private_dns(builder, VNET, RG, CONTEXT, TARGET, {"owner": "test"})
    created = {effect["id"].split("/privateDnsZones/", 1)[1].split("/", 1)[0] for effect in builder.effects
               if "/virtualNetworkLinks/" in effect["id"]}
    assert builder.blockers == []
    assert not created & set(existing)


def test_registered_prerequisites_still_block_incompatible_existing_links():
    existing = {"privatelink.monitor.azure.com": [_link("privatelink.monitor.azure.com", registrationEnabled=True)]}
    builder = core.Builder(_Runtime(existing))
    core._private_dns(builder, VNET, RG, CONTEXT, TARGET, {"owner": "test"})
    assert builder.blockers == ["existing-private-dns-link-incompatible:" + existing["privatelink.monitor.azure.com"][0]["id"]]
