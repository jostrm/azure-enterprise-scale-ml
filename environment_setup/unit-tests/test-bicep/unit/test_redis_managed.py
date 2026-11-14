"""Managed Redis deployment contracts, compiled ARM and real mocked CI commands."""
from functools import lru_cache
import itertools
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys

import pytest

from base.step_sandbox import provide_step_helpers
from domain.pipeline_contracts import ADO_SERVICES, GHA_PHASE, evaluate, load_pipeline, objects
from unit.test_capacity_preflight import bash_executable


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
DEFAULTS = {
    "enableRedisManaged": False,
    "skuRedisManagedDev": "Balanced_B1",
    "skuRedisManagedStageProd": "Balanced_B5",
    "highAvailabilityRedisManaged": "Enabled",
    "evictionPolicyRedisManaged": "NoEviction",
    "clusteringPolicyRedisManaged": "OSSCluster",
}
ALIASES = dict(zip(DEFAULTS, (
    "ENABLE_REDIS_MANAGED", "SKU_REDIS_MANAGED_DEV", "SKU_REDIS_MANAGED_STAGEPROD",
    "HIGH_AVAILABILITY_REDIS_MANAGED", "EVICTION_POLICY_REDIS_MANAGED", "CLUSTERING_POLICY_REDIS_MANAGED",
)))
ZONE = "privatelink.redis.azure.net"


def step(path, name):
    return next(s for s in objects(load_pipeline(path))
                if s.get("name", s.get("displayName")) == name)


def contract():
    return runpy.run_path(str(BICEP / "scripts/redis_managed_config.py"))


@lru_cache
def compiled(relative):
    compiler = shutil.which("bicep")
    assert compiler, "Install the existing Bicep CLI before running compiler contracts"
    result = subprocess.run([compiler, "build", str(BICEP / relative), "--stdout", "--no-restore"],
                            text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr
    if relative in ("modules/common/CmnAIfactoryNaming.bicep", "esml-genai-1/04-databases.bicep"):
        assert "BCP037" not in result.stderr and "BCP318" not in result.stderr, result.stderr
    return json.loads(result.stdout)


def resources(template):
    values = template["resources"]
    return list(values.values()) if isinstance(values, dict) else values


def deployment(template, marker):
    return next(r for r in resources(template) if marker in r.get("name", ""))


@pytest.mark.parametrize("enabled", [True, False, None])
@pytest.mark.parametrize("provider,path", [("github", GHA_PHASE), ("azure-devops", ADO_SERVICES)])
@pytest.mark.parametrize("environment", ["dev", "test", "stage", "prod"])
def test_json_export_then_actual_database_command(tmp_path, enabled, provider, path, environment):
    values = DEFAULTS | {"skuRedisManagedDev": "Balanced_B10", "evictionPolicyRedisManaged": "AllKeysLFU"}
    values.pop("enableRedisManaged")
    if enabled is not None:
        values["enableRedisManaged"] = enabled
    config = tmp_path / "variables.json"
    config.write_text(json.dumps({"dev": values, "stage_prod": {"skuRedisManagedStageProd": "Balanced_B0"}}))
    github_env = tmp_path / "github-env"
    command = [sys.executable, str(BICEP / "scripts/apply-json-config-overrides.py"),
               "--file", str(config), "--environment", environment, "--format", provider]
    if provider == "github":
        command += ["--github-workflow", str(GHA_PHASE)]
    exported = subprocess.run(command, env=os.environ | {"GITHUB_ENV": str(github_env)},
                              text=True, capture_output=True, timeout=30)
    assert exported.returncode == 0, exported.stderr
    if provider == "github":
        actual = dict(re.findall(r"(?m)^(\w+)<<[^\n]+\n([^\n]*)\n[^\n]+", github_env.read_text()))
    else:
        actual = dict(re.findall(r"##vso\[task.setvariable variable=(\w+)\](.*)", exported.stdout))
    assert actual.get("enableRedisManaged", "false") == ("true" if enabled else "false")
    actual = {k: str(v).lower() if isinstance(v, bool) else v for k, v in DEFAULTS.items()} | actual
    actual["dev_test_prod"] = "test" if environment == "stage" else environment
    selected = step(path, "64-databases")
    source = selected.get("run", selected.get("inputs", {}).get("inlineScript"))
    source = re.sub(r"\$\((\w+)\)|\$\{\{\s*env\.(\w+)\s*\}\}",
                    lambda m: actual.get(m[1] or m[2], "unused"), source)
    capture = """
set -euo pipefail
az() {
  if [ "$1 $2" = "account set" ]; then return 0; fi
  if [ "$1 $2 $3" != "deployment sub create" ]; then return 99; fi
  printf 'ARG:%s\\n' "$@"
}
"""
    provide_step_helpers(tmp_path)   # the step sources the shared retry helper from the accelerator checkout
    result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-s"], input=capture + source,
                            text=True, capture_output=True, timeout=30, cwd=tmp_path,
                            env=os.environ | {"PrjDepl": "", "MSYS_NO_PATHCONV": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    args = [line[4:] for line in result.stdout.splitlines() if line.startswith("ARG:")]
    for key in DEFAULTS:
        assert args.count(f"{key}={actual[key]}") == 1
    assert not any("redisManagedExists" in arg for arg in args)


@pytest.mark.parametrize("enabled,legacy", list(itertools.product((False, True), repeat=2)))
def test_database_step_selects_managed_independently(enabled, legacy):
    for path in (GHA_PHASE, ADO_SERVICES):
        selected = step(path, "64-databases")
        flags = {"enableRedisManaged": str(enabled).lower(), "enableRedisCache": str(legacy).lower(),
                 "deleteAllServicesForProject": "false", "debug_disable_64_databases": "false",
                 "enableAFoundryCaphost": "false", "enableAIFoundry": "false"}
        expression = selected.get("if", selected.get("condition"))
        expression = expression.replace("${{ parameters.phase }}", "infra")
        context = {"inputs.phase": "infra"} | {f"{prefix}.{key}": value
                                               for prefix in ("env", "variables") for key, value in flags.items()}
        assert evaluate(expression, context)
        flags["deleteAllServicesForProject"] = "true"
        context.update({"env.deleteAllServicesForProject": "true", "variables.deleteAllServicesForProject": "true"})
        assert not evaluate(expression, context)


@pytest.mark.parametrize("environment", ["dev", "test", "stage", "prod"])
def test_selected_validation_and_disabled_settings_are_lossless(environment):
    validate = contract()["validate"]
    active = "skuRedisManagedDev" if environment == "dev" else "skuRedisManagedStageProd"
    inactive = "skuRedisManagedStageProd" if environment == "dev" else "skuRedisManagedDev"
    values = DEFAULTS | {"enableRedisManaged": True, inactive: "future-sku"}
    original = dict(values)
    validate(values, environment, "AzureCloud")
    assert values == original
    with pytest.raises(ValueError, match=active):
        validate(values | {active: "Enterprise_E10"}, environment, "AzureCloud")
    with pytest.raises(ValueError, match="commercial Azure"):
        validate(values, environment, "AzureUSGovernment")
    validate(values | {"enableRedisManaged": False, active: "invalid"}, environment, "AzureChinaCloud")


@pytest.mark.parametrize("value", ["yes", "", 0, 1, None, {}, []])
def test_invalid_enable_is_not_coerced(value):
    with pytest.raises(ValueError, match="enableRedisManaged"):
        contract()["validate"](DEFAULTS | {"enableRedisManaged": value}, "dev")


@pytest.mark.parametrize("key", list(DEFAULTS)[1:])
def test_invalid_active_configuration_fails_before_export(key, capsys):
    selected = runpy.run_path(str(BICEP / "scripts/apply-json-config-overrides.py"))["selected_values"]
    environment = "prod" if key.endswith("StageProd") else "dev"
    with pytest.raises(SystemExit):
        selected({"dev": DEFAULTS | {"enableRedisManaged": True, key: "unsupported"}}, environment)
    assert key in capsys.readouterr().err


def test_public_defaults_and_aliases():
    config = json.loads((ROOT / "environment_setup/aifactory/variables.json").read_text())
    ado = load_pipeline(BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml")["variables"]
    gha = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    template = (GHA_PHASE.parent / ".env.template").read_text()
    registration = (GHA_PHASE.parent / "03a-GH-create-or-update-github-variables.sh").read_text()
    for key, value in DEFAULTS.items():
        text = str(value).lower() if isinstance(value, bool) else value
        assert config["dev"][key] == value
        assert ado[key] == text
        assert f'vars.{ALIASES[key]}' in gha[key]
        assert f'{ALIASES[key]}="{text}"' in template
        assert f'"{ALIASES[key]}"' in registration


def test_older_ado_configuration_gets_disabled_defaults():
    keys = {key.upper() for key in DEFAULTS} | set(ALIASES.values())
    env = {key: value for key, value in os.environ.items() if key.upper() not in keys}
    result = subprocess.run([sys.executable, str(BICEP / "scripts/redis_managed_config.py"),
                             "--environment", "dev", "--cloud", "", "--azure-devops"],
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    actual = dict(re.findall(r"##vso\[task.setvariable variable=(\w+)\](.*)", result.stdout))
    assert actual == {k: str(v).lower() if isinstance(v, bool) else v for k, v in DEFAULTS.items()}


@pytest.mark.parametrize("sku", ["Balanced_B0", "Balanced_B1", "Balanced_B5", "Balanced_B10"])
def test_both_sku_controls_accept_supported_managed_subset(sku):
    contract()["validate"](DEFAULTS | {"enableRedisManaged": True,
                                       "skuRedisManagedDev": sku, "skuRedisManagedStageProd": sku})


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_switch_alone_never_authorizes_existing_cleanup(tmp_path, enabled):
    source = (BICEP / "scripts/delete-services-if-disabled.sh").read_text(encoding="utf-8")
    capture = f"""
export enableRedisManaged={enabled} enableRedisCache=false redisExists=true
export enableDeleteForDisabledResources=false deleteAllServicesForProject=false deleteAllForProject=false
az() {{
  if [ "$1 $2" = "account set" ]; then return 0; fi
  echo UNAUTHORIZED_AZ_CALL; return 99
}}
python() {{ echo UNAUTHORIZED_HELPER_CALL; return 99; }}
"""
    result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-s"], input=capture + source,
                            text=True, encoding="utf-8", capture_output=True, timeout=30, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skipping all resource deletion" in result.stdout
    assert "UNAUTHORIZED_" not in result.stdout


def test_compiled_resource_and_security_contract():
    phase = compiled("esml-genai-1/04-databases.bicep")
    managed = deployment(phase, "'04-RedisManaged-")
    assert managed["condition"] == "[parameters('enableRedisManaged')]"
    assert managed["properties"]["mode"] == "Incremental"
    assert "spAndMI2Array" in managed["properties"]["parameters"]["principalIds"]["value"]
    child = managed["properties"]["template"]
    by_type = {r["type"]: r for r in resources(child)}
    cluster = by_type["Microsoft.Cache/redisEnterprise"]
    database = by_type["Microsoft.Cache/redisEnterprise/databases"]
    access = by_type["Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments"]
    assert all(r["apiVersion"] == "2025-07-01" for r in (cluster, database, access))
    assert cluster["sku"] == {"name": "[parameters('skuName')]"}
    assert child["parameters"]["skuName"]["allowedValues"] == ["Balanced_B0", "Balanced_B1", "Balanced_B5", "Balanced_B10"]
    assert cluster["properties"]["publicNetworkAccess"] == "Disabled"
    assert cluster["properties"]["minimumTlsVersion"] == "1.2"
    assert database["properties"]["port"] == 10000
    assert database["properties"]["accessKeysAuthentication"] == "Disabled"
    assert database["properties"]["clientProtocol"] == "Encrypted"
    assert access["properties"]["accessPolicyName"] == "default"
    assert "replace(guid(" in access["name"]
    pe = by_type["Microsoft.Network/privateEndpoints"]
    assert "condition" not in pe
    assert pe["properties"]["privateLinkServiceConnections"][0]["properties"]["groupIds"] == ["redisEnterprise"]
    assert child["outputs"]["dnsConfig"]["value"][0]["type"] == "redisManaged"
    assert ".hostName" in child["outputs"]["hostName"]["value"]
    assert "listKeys" not in json.dumps(child)
    assert not any("secrets" in r["type"].lower() for r in resources(child))
    diagnostics = [r for r in resources(child) if r["type"] == "Microsoft.Insights/diagnosticSettings"]
    assert any(r["properties"].get("metrics") == [{"category": "AllMetrics", "enabled": True}] for r in diagnostics)
    assert any(r["properties"].get("logs") == [{"category": "ConnectionEvents", "enabled": True}] for r in diagnostics)
    dns = deployment(phase, "'04-privDnsRedisManaged-")
    assert dns["condition"] == "[and(parameters('enableRedisManaged'), not(parameters('centralDnsZoneByPolicyInHub')))]"
    assert phase["outputs"]["redisManagedConnection"]["value"].startswith("[if(parameters('enableRedisManaged'),")
    assert "enableRedisManaged" not in deployment(phase, "'04-RedisCache4")["condition"]


def test_compiled_dns_and_naming_isolation():
    names = compiled("modules/common/CmnAIfactoryNaming.bicep")
    assert "redis-managed-" in names["variables"]["redisManagedName"]
    assert names["variables"]["redisManagedName"] != names["variables"]["redisName"]
    catalog = compiled("modules/common/CmnPrivateDnsZones.bicep")["variables"]["privateLinksDnsZones"]
    assert catalog["redisManaged"]["name"] == ZONE
    assert catalog["redis"]["name"] == "privatelink.redis.cache.windows.net"
    foundation = compiled("esml-genai-1/01-foundation.bicep")
    create = deployment(foundation, "createNewPrivateDnsZones")
    assert create["condition"] == "[equals(parameters('centralDnsZoneByPolicyInHub'), false())]"
    entries = create["properties"]["parameters"]["privateLinksDnsZones"]["value"]
    entry = next(e for e in entries if "redisManaged.name" in e["name"])
    assert entry["exists"] == "[parameters('zoneRedisManagedExists')]"
    assert entry["ensureLink"] == "[not(parameters('zoneRedisManagedLinkExists'))]"
    common = compiled("esml-common/main/13-rgLevel.bicep")
    assert ZONE in json.dumps(common)


@pytest.mark.parametrize("enabled,cloud,success", [("true", "AzureCloud", True),
                                                  ("true", "AzureUSGovernment", False),
                                                  ("false", "AzureUSGovernment", True)])
@pytest.mark.parametrize("path,name", [(ADO_SERVICES, "00_validate_RedisManaged"),
                                      (GHA_PHASE, "00_Validate_RedisManaged")])
def test_mandatory_guard_uses_effective_values(tmp_path, path, name, enabled, cloud, success):
    guard = step(path, name)
    source = guard.get("run", guard.get("inputs", {}).get("inlineScript"))
    source = source.replace("$(System.DefaultWorkingDirectory)/", "")
    source = source.replace("azure-enterprise-scale-ml/environment_setup", ROOT.as_posix() + "/environment_setup")
    source = source.replace("$(dev_test_prod)", "prod").replace("${{ env.dev_test_prod }}", "prod")
    env = os.environ | {key: str(v) for key, v in DEFAULTS.items()}
    env.update(enableRedisManaged=enabled, ENABLEREDISMANAGED=enabled)
    capture = f'export enableRedisManaged={shlex.quote(enabled)}\naz() {{ printf "{cloud}\\r\\n"; }}\n'
    result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-s"], input=capture + source,
                            text=True, capture_output=True, timeout=30, cwd=tmp_path, env=env)
    assert (result.returncode == 0) == success, result.stdout + result.stderr


def test_bootstrap_selection_and_central_zone_inventory():
    bootstrap = runpy.run_path(str(ROOT / "bootstrap/lib/aifactory_scaleset_config.py"))
    assert bootstrap["simple_mode_values"]()["enableRedisManaged"] is False
    selected = bootstrap["simple_mode_values"](project_resources=["redis-managed"])
    assert selected["enableRedisManaged"] is True
    assert selected["enableRedisCache"] == "false"
    assert "Microsoft.Cache" in bootstrap["simple_mode_project_providers"](["redis-managed"])
    dns = runpy.run_path(str(ROOT / "bootstrap/lib/aifactory_private_dns.py"))
    config = dns["configuration"]("sub", "dns", "swedencentral", "sdc")
    assert {"name": ZONE} in config["zones"]
    assert not any(ZONE in item["value"] for item in config["assignmentParameters"].values())


@pytest.mark.parametrize("environment,enabled,dev,prod,expected", [
    ("dev", "false", "invalid", "invalid", 0),
    ("dev", "true", "Balanced_B1", "invalid", 0),
    ("test", "true", "invalid", "Balanced_B5", 0),
    ("prod", "true", "Balanced_B1", "invalid", 1),
])
def test_preflight_validates_only_active_settings(tmp_path, environment, enabled, dev, prod, expected):
    env = os.environ | {"enableRedisManaged": enabled, "skuRedisManagedDev": dev,
                        "skuRedisManagedStageProd": prod, "enableAIFoundry": "false",
                        "enableAISearch": "false", "enablePostgreSQL": "false", "enableContainerApps": "false",
                        "PREFLIGHT_SKIP": "false", "PREFLIGHT_WARN_ONLY": "true"}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.pathsep.join(
        entry for entry in os.environ["PATH"].split(os.pathsep) if "WindowsApps" not in entry)
    result = subprocess.run([bash_executable(), str(BICEP / "scripts/preflight.sh"),
                             "--skip-azure-lookups", "--environment", environment],
                            env=env, text=True, capture_output=True, timeout=60, cwd=tmp_path)
    assert result.returncode == expected, result.stdout + result.stderr
    assert ("REDIS_MANAGED_CONFIG_INVALID" in result.stdout) == bool(expected)


@pytest.mark.parametrize("linked,denied", [(False, False), (True, False), (False, True)])
@pytest.mark.parametrize("path", [GHA_PHASE, ADO_SERVICES])
@pytest.mark.parametrize("enabled,validation_disabled", [(True, False), (False, True)])
def test_dns_discovery_preserves_existing_custom_named_link(
        tmp_path, path, linked, denied, enabled, validation_disabled):
    values = {"centralDnsZoneByPolicyInHub": "false", "dev_test_prod_sub_id": "project-sub",
              "vnetResourceGroup_resolved": "network-rg", "vnetNameFull_resolved": "spoke",
              "commonResourceGroup_param": "different-common-rg",
              "enableRedisManaged": str(enabled).lower(),
              "debug_disable_validation_tasks": str(validation_disabled).lower(),
              "deleteAllServicesForProject": "false", "debug_disable_61_foundation": "false"}
    context = {"inputs.phase": "infra"} | {f"{prefix}.{key}": value
                                            for prefix in ("env", "variables") for key, value in values.items()}
    for selected in (step(path, "61-foundation"),
                     step(path, "15_Check_Private_DNS_Zones" if path == GHA_PHASE
                          else "05a_Check if Private DNS Zones exist")):
        condition = selected.get("if", selected.get("condition"))
        if condition:
            assert evaluate(condition.replace("${{ parameters.phase }}", "infra"), context)
    vnet = "/subscriptions/project-sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/spoke"
    if path == GHA_PHASE:
        selected = step(path, "15_Check_Private_DNS_Zones")
        source = re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", lambda m: values.get(m[1], "unused"), selected["run"])
        source = source.replace('"$GITHUB_ENV"', shlex.quote((tmp_path / "github-env").as_posix()))
        zone_response = "return 17" if denied else "printf '1\\r\\n'"
        capture = f"""
export DNS_MANAGED_BY_POLICY=false
az() {{
  if [ "$1 $2 $3 $4 $5" = "network private-dns link vnet list" ]; then
    printf '%s\\n' '{vnet.upper() if linked else ""}'; return
  fi
  if [ "$1 $2 $3 $4" = "network private-dns zone list" ]; then
    {zone_response}; return
  fi
}}
"""
        result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-s"], input=capture + source,
                                text=True, capture_output=True, timeout=30, cwd=tmp_path)
        if not denied:
            assert f"zoneRedisManagedLinkExists={str(linked).lower()}" in (tmp_path / "github-env").read_text()
    else:
        source = step(path, "05a_Check if Private DNS Zones exist")["inputs"]["inlineScript"]
        source = re.sub(r"\$\((\w+)\)", lambda m: values.get(m[1], "unused"), source)
        capture = f"""
function az {{
  if ($args[0] -eq 'account') {{ $global:LASTEXITCODE=0; return }}
  if ($args -contains 'privatelink.redis.azure.net') {{
    if ($args -notcontains 'network-rg') {{ throw 'Wrong DNS scope' }}
    if ({'$true' if denied else '$false'}) {{ $global:LASTEXITCODE=17; return 'AuthorizationFailed' }}
    $global:LASTEXITCODE=0
    if ($args -contains 'link') {{
      return '[{{"name":"custom-bootstrap-link","virtualNetwork":{{"id":"{vnet.upper() if linked else "other-vnet"}"}}}}]'
    }}
    return '{{}}'
  }}
  $global:LASTEXITCODE=0
  return ''
}}
"""
        pwsh = shutil.which("pwsh")
        assert pwsh, "PowerShell is required for offline ADO script contracts"
        result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", capture + source],
                                text=True, capture_output=True, timeout=30, cwd=tmp_path)
        if not denied:
            assert f"variable=zoneRedisManagedLinkExists]{str(linked).lower()}" in result.stdout
    assert (result.returncode != 0) is denied, result.stdout + result.stderr
