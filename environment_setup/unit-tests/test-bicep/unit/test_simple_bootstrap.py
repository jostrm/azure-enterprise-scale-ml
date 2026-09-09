"""Offline Simple Mode contract tests. Never run the bootstrap entrypoint."""

import importlib.util
import ast
import copy
import ipaddress
import json
import os
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
    assert manifest["contractVersion"] == 2
    assert manifest["preset"] == "private-ai-foundation-v2"
    assert manifest["environment"] == "dev"
    assert manifest["hub"]["adminVM"] is False
    assert "manual" in manifest["hub"]["vpnClient"]
    assert "Premium" in manifest["services"]["Common Container Registry"]
    assert manifest["requiredSourcePaths"] == ["bootstrap", "environment_setup/aifactory"]
    assert all(manifest["configuration"][key] == "false" for key in CONFIG.SIMPLE_MODE_DISABLED)


@pytest.mark.parametrize("stage", ["preflight", "repository", "identity", "common", "hub", "project", "completed"])
def test_machine_progress_is_an_exact_allowlisted_record(stage):
    result = bash(f"AIF_SIMPLE_MODE=true; aif_simple_stage {stage}", "aif_simple_stage")
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"AIF_SIMPLE_STAGE={stage}\n"
    assert result.stderr == ""


def test_advanced_progress_is_unchanged_and_invalid_stage_data_is_not_emitted():
    result = bash("AIF_SIMPLE_MODE=false; aif_simple_stage common", "aif_simple_stage")
    assert result.returncode == 0 and result.stdout == ""
    result = bash("AIF_SIMPLE_MODE=true; aif_simple_stage sensitive-unexpected-data", "aif_simple_stage")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "sensitive-unexpected-data" not in result.stderr


@pytest.mark.parametrize("failure,stages", [
    ("common", ["common"]), ("hub", ["common", "hub"]),
    ("project", ["common", "hub", "project"]), ("none", ["common", "hub", "project"]),
])
def test_deployment_stage_records_stop_at_the_failing_phase(failure, stages):
    code = f"""AIF_SIMPLE_MODE=true; AIF_NO_WAIT=false
aif_run_github_workflow() {{ if [[ "$2" == "{failure}" ]]; then return 77; fi; }}
aif_verify_common_resource_group() {{ :; }}
aif_ensure_private_network_access() {{ if [[ "{failure}" == hub ]]; then return 78; fi; }}
aif_deploy_simple_application_gateway() {{ :; }}
aif_deploy_github
"""
    result = bash(code, "aif_simple_stage", "aif_deploy_github")
    assert (result.returncode == 0) is (failure == "none"), result.stderr
    assert result.stdout.splitlines() == [f"AIF_SIMPLE_STAGE={stage}" for stage in stages]


@pytest.mark.skipif(os.name != "nt", reason="Native .cmd execution requires Windows Git Bash")
def test_native_azure_cmd_resolves_for_parent_and_child_bash(tmp_path):
    cli = tmp_path / "native-cli"
    cli.mkdir()
    (cli / "az.cmd").write_bytes(b"@echo off\r\necho mock-native-cli %*\r\n")
    code = """AIF_AZURE_CLI_CMD=''
aif_is_windows() { return 0; }
command() {
  if [[ "$1" == -v && "$2" == az ]]; then return 1; fi
  if [[ "$1" == -v && "$2" == az.cmd ]]; then printf '%s/native-cli/az.cmd\\n' "$PWD"; return 0; fi
  builtin command "$@"
}
aif_resolve_azure_cli
az parent-probe "argument with spaces"
bash -c 'az child-probe'
"""
    result = bash(code, "aif_resolve_azure_cli", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "mock-native-cli parent-probe" in result.stdout
    assert "argument with spaces" in result.stdout
    assert "mock-native-cli child-probe" in result.stdout
    assert "UNEXPECTED_" not in result.stderr


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
            "ENABLE_FOUNDRY_CAPHOST": "true", "ENABLE_COSMOS_DB": "true",
            "DEPLOY_MODEL_GPT_X": "false",
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
    assert plan == {"GatewaySubnet": "172.16.1.0/27", "snet-dns-private-resolver": "172.16.1.32/28",
                    "snet-application-gateway": "172.16.2.0/24"}
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
$result=New-SubnetScheme -map $required -startIp '172.16.3.0' -possibleValuesMap $possible 6>$null
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
    defaults = ("AIF_ROUTE=gha; AIF_NO_WAIT=false; AIF_PREPARE_ONLY=false; AIF_DRY_RUN=false;\n"
                f"AIF_SUBMODULE_REF={'a' * 40};\n")
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


@pytest.mark.parametrize("ref", ["", "release/v1.24", "not-a-commit", "a" * 39])
def test_simple_mode_requires_an_immutable_published_commit(ref):
    result = bash(f"AIF_SIMPLE_MODE=true; AIF_SUBMODULE_REF='{ref}'; aif_simple_mode_defaults",
                  "aif_simple_mode_defaults")
    assert result.returncode != 0 and "verified published" in result.stderr


@pytest.mark.parametrize("matches", [True, False])
def test_simple_checkout_uses_exact_commit_and_checks_head(tmp_path, matches):
    sha = "a" * 40
    actual = sha if matches else "b" * 40
    code = f"""AIF_SIMPLE_MODE=true; AIF_SUBMODULE_REF={sha}; AIF_SUBMODULE_BRANCH=release/v1.24
AIF_SUBMODULE_URL=https://example.invalid/accelerator; AIF_REPO_ROOT=.; AIF_DRY_RUN=true
AIF_SCALESET_LIB_DIR=unused; AIF_PYTHON=(true)
aif_mutate() {{ printf '%s\\n' "$*"; }}
git() {{ if [[ "$*" == *"rev-parse HEAD" ]]; then echo {actual}; else return 1; fi; }}
aif_sync_submodule_and_templates
"""
    result = bash(code, "aif_sync_submodule_and_templates", cwd=tmp_path)
    assert f"fetch origin {sha}" in result.stdout
    assert f"checkout --detach {sha}" in result.stdout
    assert "pull --ff-only" not in result.stdout
    if matches:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0 and "does not match" in result.stderr


def test_manifest_and_source_hashes_are_stable_and_sensitive_to_changes(tmp_path):
    assert len(CONFIG.simple_mode_manifest_sha256()) == 64
    assert CONFIG.simple_mode_manifest_sha256() == CONFIG.simple_mode_manifest_sha256()
    source = tmp_path / "bootstrap/lib/example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"example\n")
    first = CONFIG.simple_mode_source_sha256(tmp_path)
    source.write_bytes(b"example\r\n")
    assert CONFIG.simple_mode_source_sha256(tmp_path) == first
    source.write_bytes(b"different\n")
    assert CONFIG.simple_mode_source_sha256(tmp_path) != first


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
    (expected / relative).write_text("AIF_SIMPLE_MODE_CONTRACT_VERSION = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lacks Simple Mode"):
        CONFIG.verify_simple_mode_source(expected, checkout)
    (checkout / relative).write_text("AIF_SIMPLE_MODE_CONTRACT_VERSION = 2\n# stale\n", encoding="utf-8")
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


def test_resource_catalog_is_literal_scoped_and_dependency_complete():
    tree = ast.parse((LIB / "aifactory_scaleset_config.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SIMPLE_MODE_RESOURCE_CATALOG" for target in node.targets))
    catalog = ast.literal_eval(node.value)
    assert catalog == CONFIG.simple_mode_manifest()["resourceCatalog"]
    assert set(catalog) == {"hub", "common", "project"}
    all_ids = {item["id"] for entries in catalog.values() for item in entries}
    assert len(all_ids) == sum(map(len, catalog.values()))
    assert all(set(item["dependencies"]) <= all_ids for entries in catalog.values() for item in entries)
    assert {item["id"] for item in catalog["project"] if item["required"]} == {
        "storage", "key-vault", "managed-identities", "foundry",
        "foundry-capability-host", "ai-search", "cosmos-db"}
    assert {item["id"] for item in catalog["common"]} >= {"log-analytics", "common-registry"}
    assert next(item for item in catalog["hub"] if item["id"] == "application-gateway")["required"]
    manifest_function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                             and node.name == "simple_mode_manifest")
    returned = next(node.value for node in manifest_function.body if isinstance(node, ast.Return))
    values = {key.value: value for key, value in zip(returned.keys, returned.values)}
    assert isinstance(values["resourceCatalog"], ast.Name)
    assert values["resourceCatalog"].id == "SIMPLE_MODE_RESOURCE_CATALOG"
    assert ast.literal_eval(values["appGatewayInputs"]) == {
        "app_gateway_backend_fqdn": "AIF_APP_GATEWAY_BACKEND_FQDN",
        "app_gateway_hostname": "AIF_APP_GATEWAY_HOSTNAME",
        "app_gateway_certificate_secret_id": "AIF_APP_GATEWAY_CERT_SECRET_ID",
    }


@pytest.mark.parametrize("selection", [[], ["application-insights"]])
def test_optional_selections_drive_every_linked_flag(selection):
    selected = CONFIG.simple_mode_project_resources(json.dumps(selection))
    required = {"storage", "key-vault", "managed-identities", "foundry",
                "foundry-capability-host", "ai-search", "cosmos-db"}
    assert set(selected) == set(selection) | required
    values = CONFIG.simple_mode_values(project_resources=json.dumps(selection), repository_visibility="public")
    for flag in ("enableAIFoundry", "enableAFoundryCaphost", "enableAISearch",
                 "enableAISearchSharedPrivateLink", "enableCosmosDB",
                 "enableAIFactoryCreatedDefaultProjectForAIFv2"):
        assert values[flag] == "true"
    assert values["enableApplicationInsights"] == str("application-insights" in selection).lower()
    assert all(values[flag] == "false" for flag in ("addAIFoundry", "updateAIFoundry", "addAISearch"))
    assert values["GITHUB_NEW_REPO_VISIBILITY"] == "public"
    assert all(values[flag] == "false" for flag in ("enablePublicGenAIAccess",
               "allowPublicAccessWhenBehindVnet", "enablePublicAccessWithPerimeter"))


@pytest.mark.parametrize("selection", ['{"foundry":true}', '"foundry"', '["sql"]', '[1]', ""])
def test_project_resource_input_rejects_invalid_shape_and_unknown_ids(selection):
    with pytest.raises(ValueError):
        CONFIG.simple_mode_project_resources(selection)


def test_empty_selection_keeps_required_private_foundry_bundle(tmp_path):
    (tmp_path / "aifactory").mkdir()
    shutil.copyfile(ROOT / "environment_setup/aifactory/variables.json", tmp_path / "aifactory/variables.json")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    state = settings() | {"simple_project_resources_json": "[]", "github_repository_visibility": "public"}
    CONFIG.apply_gha(tmp_path, state)
    values = json.loads((tmp_path / "aifactory/variables.json").read_text())["dev"]
    assert values["enableApplicationInsights"] == "false"
    for key in ("enableAIFoundry", "enableAFoundryCaphost", "enableAISearch", "enableCosmosDB"):
        assert values[key] == "true"
    env = (tmp_path / ".env").read_text()
    assert 'ENABLE_APPLICATION_INSIGHTS="false"' in env
    assert 'ENABLE_FOUNDRY_CAPHOST="true"' in env
    assert 'ENABLE_AI_SEARCH="true"' in env
    assert 'ENABLE_COSMOS_DB="true"' in env
    assert 'GITHUB_NEW_REPO_VISIBILITY="public"' in env
    assert 'ENABLE_PUBLIC_GENAI_ACCESS="false"' in env
    assert '"simple_project_resources_json"' in function("aif_write_state_and_configure")
    assert '"github_repository_visibility"' in function("aif_write_state_and_configure")


@pytest.mark.parametrize("requested,existing,empty,success", [
    ("public", "PUBLIC", True, True), ("private", "PRIVATE", True, True),
    ("public", "PRIVATE", True, False), ("private", "PUBLIC", True, False),
    ("public", "PUBLIC", False, False),
])
def test_existing_repository_visibility_is_checked_never_changed(requested, existing, empty, success):
    details = json.dumps({"visibility": existing, "isEmpty": empty})
    result = bash(f"""AIF_PYTHON=(python); GITHUB_REPOSITORY=owner/repo
GITHUB_REPOSITORY_VISIBILITY={requested}
gh() {{ if [[ "$1 $2" == "repo view" ]]; then printf '%s\\n' '{details}'; else echo MUTATION >&2; return 99; fi; }}
aif_ensure_simple_github_repository
""", "aif_ensure_simple_github_repository")
    assert (result.returncode == 0) is success
    assert "MUTATION" not in result.stderr


@pytest.mark.parametrize("visibility", ["private", "public"])
def test_new_repository_uses_requested_visibility(visibility):
    result = bash(f"""GITHUB_REPOSITORY=owner/repo; GITHUB_REPOSITORY_VISIBILITY={visibility}
gh() {{ return 1; }}
aif_mutate() {{ printf '%s\\n' "$*"; }}
aif_ensure_simple_github_repository
""", "aif_ensure_simple_github_repository")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"gh repo create owner/repo --{visibility}"


def test_public_staging_excludes_configs_snapshots_keys_and_vpn_profiles(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("Local Git required for isolated staging verification")
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    files = [".env", ".env.backup", "aifactory/variables.json", "aifactory/variables.snapshot.json",
             "aifactory/2026-variables.json.bak", "aifactory/variables.yaml", ".aifactory-access/azurevpnconfig.xml",
             "aifactory/azurevpnconfig.xml", "aifactory/certificate.pfx", "aifactory/private.key"]
    for relative in files + ["aifactory/app.py", ".github/workflows/infra.yml"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("# preserve user exclusions\nuser-private", encoding="utf-8")
    result = bash("AIF_SIMPLE_MODE=true; AIF_REPO_ROOT=.; aif_protect_simple_generated_files",
                  "aif_protect_simple_generated_files", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    subprocess.run([git, "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    staged = subprocess.run([git, "-C", str(tmp_path), "diff", "--cached", "--name-only"],
                            check=True, capture_output=True, text=True).stdout.splitlines()
    assert set(staged) == {".gitignore", "aifactory/app.py", ".github/workflows/infra.yml"}
    assert "user-private\n" in (tmp_path / ".gitignore").read_text()
    commit = function("aif_commit_and_push")
    assert commit.index("aif_protect_simple_generated_files") < commit.index("git add")


def gateway_inputs():
    return ("api.factory.example", "backend.factory.example",
            "https://kv-private.vault.azure.net/secrets/frontend")


def certificate_metadata():
    return {"attributes": {"enabled": True, "expires": "2099-01-01T00:00:00Z"},
            "sid": gateway_inputs()[2] + "/version",
            "policy": {"keyProperties": {"exportable": True},
                       "secretProperties": {"contentType": "application/x-pkcs12"},
                       "x509CertificateProperties": {"subjectAlternativeNames": {"dnsNames": ["api.factory.example"]}}}}


@pytest.mark.parametrize("inputs", [
    ("", "", ""), ("api.factory.example", "", gateway_inputs()[2]),
    ("api.factory.example", "1.2.3.4", gateway_inputs()[2]),
    ("api.factory.example", "https://backend.example", gateway_inputs()[2]),
    ("api.factory.example", "api.factory.example", gateway_inputs()[2]),
    ("api.factory.example", "backend.api.factory.example", gateway_inputs()[2]),
    (*gateway_inputs()[:2], gateway_inputs()[2] + "/version"),
    (*gateway_inputs()[:2], gateway_inputs()[2] + "?token=not-accepted"),
    ("kv-private.vault.azure.net", gateway_inputs()[1], gateway_inputs()[2]),
])
def test_gateway_rejects_missing_or_unsafe_inputs(inputs):
    with pytest.raises(ValueError):
        CONFIG.simple_mode_gateway_inputs(*inputs)


def test_gateway_certificate_metadata_and_host_specific_dns():
    gateway = CONFIG.simple_mode_gateway_inputs(*gateway_inputs())
    assert gateway["dns_zone"] == gateway["hostname"] and gateway["dns_record"] == "@"
    certificate = certificate_metadata()
    CONFIG.validate_simple_gateway_certificate(gateway, certificate)
    certificate["policy"]["x509CertificateProperties"]["subjectAlternativeNames"]["dnsNames"] = ["*.factory.example"]
    CONFIG.validate_simple_gateway_certificate(gateway, certificate)
    invalid = []
    for key, value in [("enabled", False), ("expires", "2020-01-01T00:00:00Z"), ("notBefore", "2099-01-01T00:00:00Z")]:
        copy_cert = copy.deepcopy(certificate)
        copy_cert["attributes"][key] = value
        invalid.append(copy_cert)
    copy_cert = copy.deepcopy(certificate)
    copy_cert["policy"]["keyProperties"]["exportable"] = False
    invalid.append(copy_cert)
    copy_cert = copy.deepcopy(certificate)
    copy_cert["sid"] = "https://another.vault.azure.net/secrets/frontend/version"
    invalid.append(copy_cert)
    copy_cert = copy.deepcopy(certificate)
    copy_cert["policy"]["x509CertificateProperties"]["subjectAlternativeNames"]["dnsNames"] = ["*.example"]
    invalid.append(copy_cert)
    for metadata in invalid:
        with pytest.raises(ValueError):
            CONFIG.validate_simple_gateway_certificate(gateway, metadata)


def test_gateway_missing_inputs_fail_before_cloud_or_repository_commands():
    result = bash(f"""AIF_PYTHON=(python); AIF_SCALESET_LIB_DIR='{LIB}'
AIF_SIMPLE_PROJECT_RESOURCES_JSON='[]'; GITHUB_REPOSITORY_VISIBILITY=public
aif_simple_gateway_config
""", "aif_simple_gateway_config")
    assert result.returncode != 0
    assert "AIF_APP_GATEWAY_HOSTNAME" in result.stderr
    assert "UNEXPECTED_" not in result.stderr
    main = function("aif_scaleset_main")
    assert main.index("aif_simple_gateway_config") < main.index("gh auth status")
    assert main.index("aif_validate_simple_gateway_prerequisites") < main.index("aif_ensure_target_repository")
    preflight = function("aif_validate_simple_gateway_prerequisites")
    assert "EnableApplicationGatewayNetworkIsolation" in preflight
    assert "keyvault certificate show" in preflight and "keyvault secret show" not in preflight


def test_gateway_unregistered_feature_stops_before_other_calls():
    result = bash("""AIF_SIMPLE_MODE=true; AIF_DEV_SUBSCRIPTION_ID=sub
az() { if [[ "$1 $2" == "feature show" ]]; then echo NotRegistered; else echo MUTATION >&2; return 99; fi; }
aif_validate_simple_gateway_prerequisites
""", "aif_validate_simple_gateway_prerequisites")
    assert result.returncode != 0 and "already Registered" in result.stderr
    assert "MUTATION" not in result.stderr


@pytest.mark.parametrize("address,health,expected", [
    ("172.16.4.10", "Healthy", True), ("backend.factory.example", "Healthy", True),
    ("172.16.4.10", "Unhealthy", False), ("8.8.8.8", "Healthy", False), ("public.example", "Healthy", False),
])
def test_gateway_health_requires_private_healthy_backend(address, health, expected):
    payload = {"backendAddressPools": [{"backendHttpSettingsCollection": [{"servers": [
        {"address": address, "health": health}]}]}]}
    assert CONFIG.simple_mode_gateway_healthy(payload, "backend.factory.example") is expected
    assert CONFIG.simple_mode_gateway_healthy({}, "backend.factory.example") is False


def test_gateway_runtime_reserves_subnet_before_project_and_verifies_health():
    access = function("aif_ensure_private_network_access")
    assert "aif_prepare_simple_application_gateway" in access
    deploy = function("aif_deploy_github")
    assert deploy.index("aif_ensure_private_network_access") < deploy.index("infra-project.yml project")
    assert deploy.index("infra-project.yml project") < deploy.index("aif_deploy_simple_application_gateway")
    prepare = function("aif_prepare_simple_application_gateway")
    assert 'ServicePrincipal "Key Vault Secrets User" "$AIF_APP_GATEWAY_CERT_VAULT_ID"' in prepare
    assert '"Approved"' in prepare
    assert "show-backend-health" in function("aif_deploy_simple_application_gateway")
    gateway = (LIB / "simple-app-gateway.bicep").read_text()
    network = (LIB / "simple-app-gateway-network.bicep").read_text()
    assert "publicIP" not in gateway and "protocol: 'Http'" not in gateway
    assert "WAF_v2" in gateway and "mode: 'Prevention'" in gateway
    assert "AppGwSslPolicy20220101S" in gateway and "keyVaultSecretId: certificateSecretId" in gateway
    assert "minCapacity: 1, maxCapacity: 2" in gateway
    assert "172.16.2.0/24" in network and "DenyOtherOutbound" in network
    assert "serviceName: 'Microsoft.Network/applicationGateways'" in network
    core = (ROOT / "environment_setup/aifactory/bicep/esml-genai-1/02-core-infrastructure.bicep").read_text()
    assert "param enableApplicationInsights bool = true" in core
    assert "applicationInsightsRGmode.bicep' = if (enableApplicationInsights)" in core
    workflow = (ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
    assert '--parameters enableApplicationInsights="${{ env.enableApplicationInsights }}"' in workflow


@pytest.mark.parametrize("rbac,success", [(True, True), (False, False)])
def test_gateway_preflight_reads_only_selected_vault_and_certificate_metadata(tmp_path, rbac, success):
    (tmp_path / "state").mkdir()
    state = settings()
    vault_id = f"/subscriptions/{state['dev_subscription_id']}/resourceGroups/certs/providers/Microsoft.KeyVault/vaults/kv-private"
    vault = json.dumps({"id": vault_id, "tenantId": state["tenant_id"], "rbac": rbac})
    certificate = json.dumps(certificate_metadata())
    host, backend, uri = gateway_inputs()
    result = bash(f"""AIF_SIMPLE_MODE=true; AIF_PYTHON=(python); AIF_SCALESET_LIB_DIR='{LIB}'
AIF_STATE_DIR=state; AIF_TENANT_ID={state['tenant_id']}; AIF_DEV_SUBSCRIPTION_ID={state['dev_subscription_id']}
AIF_SIMPLE_PROJECT_RESOURCES_JSON='[]'; GITHUB_REPOSITORY_VISIBILITY=public
AIF_APP_GATEWAY_HOSTNAME={host}; AIF_APP_GATEWAY_BACKEND_FQDN={backend}; AIF_APP_GATEWAY_CERT_SECRET_ID={uri}
az() {{
  if [[ "$1 $2" == 'feature show' ]]; then echo Registered
  elif [[ "$1 $2" == 'keyvault show' ]]; then printf '%s\\n' '{vault}'
  elif [[ "$1 $2 $3" == 'keyvault certificate show' ]]; then printf '%s\\n' '{certificate}'
  else echo MUTATION >&2; return 99
  fi
}}
aif_validate_simple_gateway_prerequisites
""", "aif_simple_gateway_config", "aif_validate_simple_gateway_prerequisites", cwd=tmp_path)
    assert (result.returncode == 0) is success, result.stderr
    assert "MUTATION" not in result.stderr
    assert uri not in result.stdout + result.stderr
