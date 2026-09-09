"""Offline Simple Mode contract tests. Never run the bootstrap entrypoint."""

import importlib.util
import ipaddress
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap/lib"
SCRIPT = (LIB / "create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
SPEC = importlib.util.spec_from_file_location("simple_config", LIB / "aifactory_scaleset_config.py")
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


def settings():
    return {
        "simple_mode": "true", "topology": "s", "access_hub_mode": "integrated",
        "network_mode": "priv", "dev_vnet_cidr": "172.16.0.0/20",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "dev_subscription_id": "22222222-2222-2222-2222-222222222222",
        "stage_subscription_id": "22222222-2222-2222-2222-222222222222",
        "prod_subscription_id": "22222222-2222-2222-2222-222222222222",
        "location": "swedencentral", "location_short": "sdc", "prefix": "acme-",
        "scaleset_suffix": "-001", "project_number": "001", "cost_center": "123456",
        "team_group_id": "33333333-3333-3333-3333-333333333333",
        "team_group_name": "acme-prj001-team", "team_member_email": "owner@example.org",
        "seeding_subscription_id": "22222222-2222-2222-2222-222222222222",
        "seeding_resource_group": "rg-acme-bootstrap-sdc-001", "seeding_keyvault_name": "kvacmesdc001",
        "enable_public_genai_access": "false", "allow_public_access_behind_vnet": "false",
        "enable_public_perimeter": "false", "add_bastion": "false",
        "hub_subscription_id": "22222222-2222-2222-2222-222222222222",
        "hub_resource_group": "acme-esml-common-sdc-dev-001",
        "github_repository": "owner/acme-ai", "runner_mode": "github-hosted",
        "ado_tenant_id": "", "dev_service_connection": "",
        "stage_service_connection": "", "prod_service_connection": "",
    }


def function(name):
    start = SCRIPT.index(f"{name}() {{")
    end = SCRIPT.find("\naif_", start + 1)
    return SCRIPT[start:end if end != -1 else None]


def bash(code, *names, cwd=None):
    executable = shutil.which("bash")
    if not executable:
        pytest.skip("Git Bash required for isolated function tests")
    # All external cloud commands are overridden by failing mocks.
    prefix = """set -euo pipefail
aif_info() { :; }; aif_success() { :; }; aif_section() { :; }
aif_error() { printf '%s\\n' "$*" >&2; }
az() { echo UNEXPECTED_AZ >&2; return 91; }
gh() { echo UNEXPECTED_GH >&2; return 92; }
"""
    return subprocess.run(
        [executable, "-c", prefix + "\n".join(function(name) for name in names) + "\n" + code],
        capture_output=True, text=True, timeout=15, cwd=cwd,
    )


def test_manifest_is_secretless_dev_only_and_deterministic():
    manifest = CONFIG.simple_mode_manifest()
    assert manifest == CONFIG.simple_mode_manifest()
    assert manifest["contractVersion"] == 1
    assert manifest["preset"] == "private-ai-foundation-v1"
    assert manifest["environment"] == "dev"
    assert manifest["hub"]["adminVM"] is False
    assert "manual" in manifest["hub"]["vpnClient"]
    assert "Premium" in manifest["services"]["Common Container Registry"]
    assert manifest["requiredSourcePaths"] == ["bootstrap", "environment_setup/aifactory"]
    assert all(manifest["configuration"][key] == "false" for key in CONFIG.SIMPLE_MODE_DISABLED)


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_preset_exports_preserve_aliases_types_costs_and_private_flags(tmp_path, route):
    (tmp_path / "aifactory").mkdir()
    output = tmp_path / "aifactory/variables.json"
    shutil.copyfile(ROOT / "environment_setup/aifactory/variables.json", output)
    if route == "gha":
        target = tmp_path / ".env"
        shutil.copyfile(ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template", target)
        CONFIG.apply_gha(tmp_path, settings())
    else:
        target = tmp_path / "aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
        target.parent.mkdir(parents=True)
        target.write_text("variables:\n", encoding="utf-8")
        CONFIG.apply_ado(tmp_path, settings())
    values = json.loads(output.read_text(encoding="utf-8"))["dev"]
    assert values["enableAIFactoryHub"] is True
    assert values["centralDnsZoneByPolicyInHub"] is False
    assert values["scaling-mode"] == "own-subscriptions"
    assert values["tag_costceter_common"] == values["tag_costcenter"] == "123456"
    assert values["test_sub_id"] == values["prod_sub_id"] == values["dev_sub_id"]
    assert values["project_number_000"] == "001"
    assert all(values[key] == "false" for key in CONFIG.SIMPLE_MODE_DISABLED)
    assert all(values[key] == "false" for key in (
        "allowPublicAccessWhenBehindVnet", "enablePublicGenAIAccess", "enablePublicAccessWithPerimeter"))
    for key in ("tags", "tagsProject"):
        assert json.loads(values[key])["CostCenter"] == "123456"
        assert "$(" not in values[key]
    text = target.read_text(encoding="utf-8")
    if route == "gha":
        for key, value in {
            "SCALING_MODE": "own-subscriptions", "ENABLE_AI_FACTORY_HUB": "true",
            "CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB": "false", "TAG_COSTCETER_COMMON": "123456",
            "TAG_COSTCENTER": "123456", "ENABLE_AI_FOUNDRY": "true",
            "ENABLE_FOUNDRY_CAPHOST": "false", "DEPLOY_MODEL_GPT_X": "false",
            "DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE": "false",
            "SKU_AISEARCH_DEV": "standard", "GITHUB_NEW_REPO_VISIBILITY": "private",
            "COMMON_VNET_CIDR": "172.16.XX.0/20", "DEV_CIDR_RANGE": "0",
            "STAGE_CIDR_RANGE": "16", "PROD_CIDR_RANGE": "32",
        }.items():
            assert re.search(rf"^{key}=\"{re.escape(value)}\"", text, re.MULTILINE), key
    else:
        assert '  enableAIFactoryHub: "true"' in text
        assert '  tag_costcenter: "123456"' in text


def test_all_three_configured_networks_are_peerable(monkeypatch, capsys):
    values = CONFIG.simple_mode_values()
    networks = []
    for selector in ("dev_cidr_range", "test_cidr_range", "prod_cidr_range"):
        octet = values[selector]
        network = ipaddress.ip_network(values["common_vnet_cidr"].replace("XX", octet))
        subnets = [ipaddress.ip_network(values[key].replace("XX", octet)) for key in (
            "common_subnet_cidr", "common_subnet_scoring_cidr",
            "common_pbi_subnet_cidr", "common_bastion_subnet_cidr")]
        assert all(subnet.subnet_of(network) and subnet.prefixlen == 26 for subnet in subnets)
        assert not any(a.overlaps(b) for i, a in enumerate(subnets) for b in subnets[i + 1:])
        networks.append(network)
    assert not any(a.overlaps(b) for i, a in enumerate(networks) for b in networks[i + 1:])
    preflight = ROOT / "environment_setup/aifactory/bicep/scripts/preflight.sh"
    code = preflight.read_text(encoding="utf-8").split(
        'out="$(PF_CIDR="$_cidr_data" "$PYBIN" - <<\'PY\' 2>/dev/null\n', 1)[1].split("\nPY\n", 1)[0]
    data = [f"ENV|{label}|{values[key]}" for label, key in (
        ("Dev", "dev_cidr_range"), ("Stage", "test_cidr_range"), ("Prod", "prod_cidr_range"))]
    data += [f"VNET|{values['common_vnet_cidr']}"]
    data += [f"{role}|{values[key]}|{minimum}" for role, key, minimum in (
        ("common", "common_subnet_cidr", 28), ("scoring", "common_subnet_scoring_cidr", 28),
        ("pbi", "common_pbi_subnet_cidr", 28), ("bastion", "common_bastion_subnet_cidr", 26))]
    monkeypatch.setenv("PF_CIDR", "\n".join(data))
    exec(compile(code, str(preflight), "exec"), {})
    assert capsys.readouterr().out == ""


def test_integrated_reservations_are_idempotent_and_reject_conflicting_gateways():
    existing = [{"name": f"common{i}", "addressPrefix": f"172.16.0.{i * 64}/26"} for i in range(4)]
    plan = CONFIG.simple_mode_hub_subnets("172.16.0.0/20", existing)
    assert plan == {"GatewaySubnet": "172.16.1.0/27", "snet-dns-private-resolver": "172.16.1.32/28"}
    existing += [{"name": name, "addressPrefix": prefix} for name, prefix in plan.items()]
    assert CONFIG.simple_mode_hub_subnets("172.16.0.0/20", existing) == plan
    with pytest.raises(ValueError, match="another range"):
        CONFIG.simple_mode_hub_subnets("172.16.0.0/20", [
            {"name": "GatewaySubnet", "addressPrefix": "172.16.15.224/27"}])
    with pytest.raises(ValueError, match="overlaps"):
        CONFIG.simple_mode_hub_subnets("172.16.0.0/20", [
            {"name": "unrelated", "addressPrefix": "172.16.1.0/24"}])
    with pytest.raises(ValueError, match="no room"):
        CONFIG.simple_mode_hub_subnets("172.16.0.0/20", [
            {"name": "unrelated-high-subnet", "addressPrefix": "172.16.15.0/26"}])


def test_real_append_allocator_fits_full_project_after_low_gateway_and_resolver():
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell required for extracted allocator checks")
    allocator = ROOT / "environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1"
    code = r"""
$ErrorActionPreference='Stop'
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__ALLOCATOR__',[ref]$null,[ref]$null)
$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]},$false) |
  ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
function Get-Subnet {
  param([string]$IPAddress,[int]$MaskBits)
  $bytes=[System.Net.IPAddress]::Parse($IPAddress).GetAddressBytes()
  [array]::Reverse($bytes)
  $n=[BitConverter]::ToUInt32($bytes,0)
  $size=[math]::Pow(2,32-$MaskBits)
  $first=[uint32]([math]::Floor($n/$size)*$size)
  [pscustomobject]@{
    NetworkAddress=ConvertTo-DottedDecimalIP "$first"
    BroadcastAddress=ConvertTo-DottedDecimalIP "$([uint32]($first+$size-1))"
  }
}
$required=@{}
foreach($p in $ast.ParamBlock.Parameters) {
  $name=$p.Name.VariablePath.UserPath
  if($name -like '*SubnetCidrAll') {
    $required[$name -replace 'All$','']=$p.DefaultValue.SafeGetValue()
  }
}
$possible=@{}
$required.Values | Select-Object -Unique | ForEach-Object {
  $possible[$_]=Get-SubnetFitting -addressSpace '172.16.0.0/20' -cidrNotation $_
}
$result=New-SubnetScheme -map $required -startIp '172.16.1.48' -possibleValuesMap $possible 6>$null
ConvertTo-Json -InputObject $result -Compress
""".replace("__ALLOCATOR__", str(allocator).replace("'", "''"))
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", code],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    project = [ipaddress.ip_network(value) for value in json.loads(result.stdout).values()]
    assert sorted(subnet.prefixlen for subnet in project) == [23, 23, 24, 25, 26, 26, 26, 27]
    common = [ipaddress.ip_network(f"172.16.0.{i * 64}/26") for i in range(4)]
    hub = [ipaddress.ip_network(prefix) for prefix in CONFIG.simple_mode_hub_subnets("172.16.0.0/20", []).values()]
    subnets = common + hub + project
    assert all(subnet.subnet_of(ipaddress.ip_network("172.16.0.0/20")) for subnet in subnets)
    assert not any(a.overlaps(b) for i, a in enumerate(subnets) for b in subnets[i + 1:])


def test_simple_optin_defaults_and_advanced_preservation():
    defaults = "AIF_ROUTE=gha; AIF_NO_WAIT=false; AIF_PREPARE_ONLY=false; AIF_DRY_RUN=false;\n"
    result = bash(defaults + """AIF_SIMPLE_MODE=true
aif_simple_mode_defaults
printf '%s\\n' "$AIF_COST_CENTER" "$AIF_DEV_VNET_CIDR" "$AIF_SETUP_HUB_ACCESS" "$AIF_CONFIGURE_VPN_CLIENT"
""", "aif_simple_mode_defaults")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["123456", "172.16.0.0/20", "true", "false"]
    result = bash(defaults + """AIF_SIMPLE_MODE=false; AIF_NETWORK_MODE=advanced
aif_simple_mode_defaults; echo "$AIF_NETWORK_MODE"
""", "aif_simple_mode_defaults")
    assert result.returncode == 0 and result.stdout.strip() == "advanced"
    result = bash(defaults + "AIF_SIMPLE_MODE=true; AIF_IDENTITY_MODE=sp; aif_simple_mode_defaults",
                  "aif_simple_mode_defaults")
    assert result.returncode != 0 and "requires AIF_IDENTITY_MODE=c" in result.stderr


@pytest.mark.parametrize("value,expected", [("true", "true"), ("false", "false"), ("y", "true"), ("n", "false")])
def test_noninteractive_boolean_contract(value, expected):
    result = bash(
        f'AIF_NON_INTERACTIVE=true; ANSWER={value}; aif_prompt_yes_no ANSWER test n; echo "$ANSWER"',
        "aif_prompt_choice", "aif_prompt_yes_no")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_missing_azure_auth_never_opens_login_noninteractively():
    result = bash("""AIF_NON_INTERACTIVE=true; AIF_DRY_RUN=false
AIF_TENANT_ID=tenant; AIF_DEV_SUBSCRIPTION_ID=subscription
az() { printf '%s\\n' "$*" >&2; return 1; }
aif_ensure_azure_login
""", "aif_ensure_azure_login")
    assert result.returncode != 0
    assert "Sign in explicitly" in result.stderr
    assert "login --tenant" not in result.stderr
    assert "UNEXPECTED_" not in result.stderr


def test_disabled_first_party_services_do_not_materialize_workspaces():
    result = bash("AIF_SIMPLE_MODE=true; aif_ensure_first_party_enterprise_apps",
                  "aif_ensure_first_party_enterprise_apps")
    assert result.returncode == 0, result.stderr
    assert "UNEXPECTED_" not in result.stderr


def test_manual_vpn_artifact_never_installs_or_imports_a_client(tmp_path):
    (tmp_path / "state").mkdir()
    with zipfile.ZipFile(tmp_path / "fixture.zip", "w") as archive:
        archive.writestr("AzureVPN/azurevpnconfig.xml",
                         "<AzVpnProfile><name>VNet</name><clientconfig /></AzVpnProfile>")
    code = f"""AIF_SIMPLE_MODE=true; AIF_CONFIGURE_VPN_CLIENT=false
AIF_HUB_SUBSCRIPTION_ID=sub; AIF_HUB_RESOURCE_GROUP=group; AIF_VPN_GATEWAY_NAME=gateway
AIF_PREFIX=acme-; AIF_SCALESET_SUFFIX=001; AIF_REPO_ROOT=.; AIF_STATE_DIR=state
AIF_SCALESET_LIB_DIR='{LIB}'; AIF_PYTHON=(python)
az() {{ printf '%s\\n' 'https://example.invalid/profile?redacted'; }}
powershell.exe() {{ echo UNEXPECTED_INSTALL >&2; return 93; }}
winget.exe() {{ echo UNEXPECTED_INSTALL >&2; return 94; }}
AzureVpn.exe() {{ echo UNEXPECTED_IMPORT >&2; return 95; }}
curl() {{
  while (( $# )); do
    if [[ "$1" == --output ]]; then cp fixture.zip "$2"; return; fi
    shift
  done
  return 96
}}
aif_configure_windows_vpn_client
"""
    result = bash(code, "aif_configure_windows_vpn_client", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "UNEXPECTED_" not in result.stderr
    assert "example.invalid" not in result.stdout + result.stderr
    profile = tmp_path / ".aifactory-access/azurevpnconfig.xml"
    assert profile.is_file()
    assert "<name>AI Factory acme-001</name>" in profile.read_text(encoding="utf-8")


def test_remote_contract_rejects_old_or_divergent_source(tmp_path):
    expected = tmp_path / "source"
    checkout = tmp_path / "published"
    relative = Path("bootstrap/lib/aifactory_scaleset_config.py")
    (expected / relative).parent.mkdir(parents=True)
    (checkout / relative).parent.mkdir(parents=True)
    (expected / relative).write_text("AIF_SIMPLE_MODE_CONTRACT_VERSION = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lacks Simple Mode"):
        CONFIG.verify_simple_mode_source(expected, checkout)
    (checkout / relative).write_text("AIF_SIMPLE_MODE_CONTRACT_VERSION = 1\n# stale\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        CONFIG.verify_simple_mode_source(expected, checkout)
    shutil.copyfile(expected / relative, checkout / relative)
    CONFIG.verify_simple_mode_source(expected, checkout)
    (expected / "bootstrap/required.sh").write_text("new behavior\n", encoding="utf-8")
    with pytest.raises(ValueError, match="required.sh"):
        CONFIG.verify_simple_mode_source(expected, checkout)


def test_source_auth_and_dev_only_ordering_and_manual_vpn_artifact():
    main = function("aif_scaleset_main")
    assert main.index("gh auth status") < main.index("aif_ensure_target_repository")
    assert main.index("aif_sync_submodule_and_templates") < main.index("aif_register_resource_providers")
    sync = function("aif_sync_submodule_and_templates")
    assert sync.index("--verify-simple-mode-source") < sync.index("cp azure-enterprise-scale-ml/bootstrap/")
    deploy = function("aif_deploy_github")
    assert deploy.index("aif_verify_common_resource_group") < deploy.index("aif_ensure_private_network_access")
    assert deploy.index("aif_ensure_private_network_access") < deploy.index("infra-project.yml project")
    assert "--raw-field deploy_stage=false" in deploy and "--raw-field deploy_prod=false" in deploy
    assert "--private" in function("aif_ensure_target_repository")
    profile = function("aif_configure_windows_vpn_client")
    assert 'if [[ "$AIF_CONFIGURE_VPN_CLIENT" == "true" ]]' in profile
    assert 'chmod 600 "$artifact_dir/azurevpnconfig.xml"' in profile
    assert "/.aifactory-access/" in function("aif_write_state_and_configure")
    assert 'echo "$profile_url"' not in profile
