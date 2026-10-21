"""Offline APIM runner tests. Every Azure operation uses a fake CLI."""

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("apim_gateway_deployment", SCRIPTS / "apim-gateway-deployment.py")
gw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gw)
from apim_gateway_config import GatewayError, json_document, legacy_config, load_config, validate_config

SUB = "11111111-1111-1111-1111-111111111111"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PRINCIPAL = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RG = f"/subscriptions/{SUB}/resourceGroups/gateway-rg"
NET = f"/subscriptions/{SUB}/resourceGroups/network-rg/providers/Microsoft.Network"
VNET = NET + "/virtualNetworks/hub"
INTEGRATION = VNET + "/subnets/apim-outbound"
PE_SUBNET = VNET + "/subnets/private-endpoints"
NSG = NET + "/networkSecurityGroups/apim-nsg"
BACKEND = f"/subscriptions/{SUB}/resourceGroups/ai-rg/providers/Microsoft.CognitiveServices/accounts/aoai-one"


@pytest.fixture(autouse=True)
def no_live_cli(monkeypatch):
    monkeypatch.setattr(gw.subprocess, "run", Mock(side_effect=AssertionError("Live Azure CLI is forbidden")))


@pytest.fixture
def local_area():
    # Keep even test-generated files inside this isolated worktree, never in OS temporary paths.
    area = ROOT / ".apim-runner-unit" / gw.uuid.uuid4().hex
    area.mkdir(parents=True)
    try:
        yield area
    finally:
        shutil.rmtree(area)
        try:
            area.parent.rmdir()
        except OSError:
            pass


@pytest.fixture
def modules(local_area):
    root = local_area / "maintained"
    root.mkdir()
    (root / "main.bicep").write_text("targetScope = 'subscription'\nmodule config './config.bicep' = {}\n", encoding="utf-8")
    (root / "config.bicep").write_text("var policy = loadTextContent('./policy.xml')\n", encoding="utf-8")
    (root / "policy.xml").write_text("<policies />", encoding="utf-8")
    for name in ("service-main.bicep", "private-endpoint-main.bicep", "network-main.bicep"):
        (root / name).write_text("targetScope = 'subscription'\n", encoding="utf-8")
    return root


def config(managed=False, create=False):
    c = {"schemaVersion": 1, "environment": "dev", "tenantId": TENANT, "subscriptionId": SUB,
         "resourceGroup": "gateway-rg", "location": "swedencentral", "serviceName": "apim-gateway",
         "api": {"apiId": "chat-api", "apiPath": "openai", "backendPoolName": "chat-pool",
                 "aggregateTokensPerMinute": 100000,
                 "azureOpenAIBackends": [{"name": "aoai-one", "endpoint": "https://aoai-one.openai.azure.com",
                                         "resourceId": BACKEND, "weight": 1}]}}
    if managed:
        c.update(serviceMode="managed", publisherName="AI Factory", publisherEmail="owner@example.org",
                 ownershipId="gateway-dev")
        c["network"] = {"integrationSubnetId": INTEGRATION, "createIntegrationSubnet": create,
                        "integrationSubnetPrefix": "10.0.1.0/27", "networkSecurityGroupId": NSG,
                        "privateEndpointSubnetId": PE_SUBNET, "privateEndpointName": "pe-apim"}
    return validate_config(c, "dev")


def resource(rid, properties=None, **kwargs):
    return {"id": rid, "location": "swedencentral", "properties": properties or {}, **kwargs}


def subnet(rid=INTEGRATION):
    if rid == PE_SUBNET:
        return resource(rid, {"addressPrefix": "10.0.2.0/24", "delegations": []})
    return resource(rid, {"addressPrefix": "10.0.1.0/27", "networkSecurityGroup": {"id": NSG},
                          "delegations": [{"properties": {"serviceName": "Microsoft.Web/serverFarms"}}]})


def service(c, public="Disabled"):
    properties = {"provisioningState": "Succeeded", "publicNetworkAccess": public}
    if c["serviceMode"] == "managed":
        properties.update(publisherName=c["publisherName"], publisherEmail=c["publisherEmail"],
                          developerPortalStatus="Disabled", virtualNetworkType="External",
                          virtualNetworkConfiguration={"subnetResourceId": INTEGRATION})
    return resource(gw.service_id(c), properties, sku={"name": c["sku"], "capacity": c["skuCapacity"]},
                    identity={"type": "SystemAssigned", "principalId": PRINCIPAL},
                    tags={gw.OWNER_TAG: c.get("ownershipId", "")})


def private_endpoint(c, status="Approved"):
    return resource(RG + "/providers/Microsoft.Network/privateEndpoints/pe-apim",
                    {"subnet": {"id": PE_SUBNET}, "provisioningState": "Succeeded",
                     "privateLinkServiceConnections": [{"properties": {
                         "privateLinkServiceId": gw.service_id(c), "groupIds": ["gateway"],
                         "privateLinkServiceConnectionState": {"status": status}}}]},
                    tags={gw.OWNER_TAG: c["ownershipId"]})


class FakeCLI:
    def __init__(self, c, *, existing=True, integration=True, pe=False):
        self.c = c
        self.calls = []
        self.preview_hook = None
        self.preview_result = None
        self.create_hook = None
        self.pe_status = "Approved"
        self.zone_groups = []
        self.resources = {
            RG: resource(RG),
            BACKEND: resource(BACKEND, {"endpoint": c["api"]["azureOpenAIBackends"][0]["endpoint"]}, kind="OpenAI"),
            VNET: resource(VNET, {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}),
            NSG: resource(NSG), PE_SUBNET: subnet(PE_SUBNET),
        }
        if existing:
            self.resources[gw.service_id(c)] = service(c)
        if integration:
            self.resources[INTEGRATION] = subnet()
        if pe:
            endpoint = private_endpoint(c)
            self.resources[endpoint["id"]] = endpoint

    def read(self, args, allow_missing=False):
        self.calls.append(("read", list(args)))
        if args[:2] == ["account", "show"]:
            return {"id": SUB, "tenantId": TENANT, "state": "Enabled"}
        rid = args[args.index("--url") + 1].split("management.azure.com", 1)[1].split("?", 1)[0]
        if rid == VNET + "/subnets":
            return {"value": [copy.deepcopy(value) for key, value in self.resources.items()
                              if key.startswith(VNET + "/subnets/")]}
        if rid.endswith("/privateDnsZoneGroups"):
            return {"value": copy.deepcopy(self.zone_groups)}
        if rid in self.resources:
            return copy.deepcopy(self.resources[rid])
        if allow_missing:
            return None
        raise GatewayError("not-found", "Synthetic missing resource.")

    def invoke(self, args, timeout):
        self.calls.append(("invoke", list(args)))
        assert args[:2] == ["deployment", "sub"]
        parameter_file = Path(args[args.index("--parameters") + 1][1:])
        phase = parameter_file.name.split(".parameters.json")[0]
        values = {k: v["value"] for k, v in json.loads(parameter_file.read_text())["parameters"].items()}
        if args[2] == "what-if":
            if self.preview_hook:
                self.preview_hook(phase)
            if self.preview_result is not None:
                return copy.deepcopy(self.preview_result)
            target = {"network": INTEGRATION, "private-endpoint": RG + "/providers/Microsoft.Network/privateEndpoints/pe-apim",
                      "configuration": gw.service_id(self.c) + "/apis/" + self.c["api"]["apiId"]}.get(phase, gw.service_id(self.c))
            return {"status": "Succeeded", "changes": [{"changeType": "Modify", "resourceId": target,
                "before": {"properties": {"token": "OLD-MUST-NOT-LEAK"}},
                "after": {"properties": {"token": "NEW-MUST-NOT-LEAK"}},
                "delta": [{"path": "properties.token", "propertyChangeType": "Modify",
                           "before": "OLD-MUST-NOT-LEAK", "after": "NEW-MUST-NOT-LEAK"}]}]}
        assert args[2] == "create"
        if self.create_hook:
            self.create_hook(phase)
        if phase == "network":
            self.resources[INTEGRATION] = subnet()
        if phase.startswith("service-"):
            self.resources[gw.service_id(self.c)] = service(self.c, values["publicNetworkAccess"])
        if phase == "private-endpoint":
            pe = private_endpoint(self.c, self.pe_status)
            self.resources[pe["id"]] = pe
            if self.c["network"]["privateDnsMode"] == "existingZone":
                self.zone_groups = [zone_group(self.c)]
        return {"properties": {"provisioningState": "Succeeded"}}

    @property
    def writes(self):
        return [args for _, args in self.calls if args[:3] == ["deployment", "sub", "create"]]

    @property
    def write_phases(self):
        return [Path(args[args.index("--parameters") + 1][1:]).name.split(".parameters.json")[0] for args in self.writes]


def deployment(local_area, modules, c=None, **kwargs):
    c = c or config()
    fake = FakeCLI(c, **kwargs)
    runner = gw.Deployment(c, gw.Artifacts(local_area / "output", module_root=modules), fake,
                           module_root=modules, sleep=lambda _: None, poll_attempts=2)
    return runner, fake


def apply(runner):
    preview = runner.execute("what-if")
    return runner.execute("apply", runner.plan["planDigest"], approve_initial=True,
                          approved_preview=preview["previewDigest"])


def test_foundry_backend_uses_reported_openai_endpoint_not_generic_account_endpoint(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.resources[BACKEND] = resource(BACKEND, {
        "endpoint": "https://aoai-one.cognitiveservices.azure.com/",
        "endpoints": {"OpenAI Language Model Instance API": "https://aoai-one.openai.azure.com/"}
    }, kind="AIServices")
    runner.inventory()
    assert not fake.writes


@pytest.mark.parametrize("reported", [None, {}, {
    "OpenAI Language Model Instance API": "https://different-account.openai.azure.com/"
}, {"Azure OpenAI": "https://aoai-one.openai.azure.com/"}])
def test_foundry_backend_never_guesses_or_accepts_mismatched_openai_origin(local_area, modules, reported):
    runner, fake = deployment(local_area, modules)
    fake.resources[BACKEND] = resource(BACKEND, {
        "endpoint": "https://aoai-one.openai.azure.com/",
        "endpoints": reported
    }, kind="AIServices")
    with pytest.raises(GatewayError):
        runner.inventory()
    assert not fake.writes


def zone_group(c, name="default", zone=None):
    return resource(RG + "/providers/Microsoft.Network/privateEndpoints/pe-apim/privateDnsZoneGroups/" + name,
                    {"provisioningState": "Succeeded", "privateDnsZoneConfigs": [
                        {"name": "privatelink.azure-api.net", "properties": {
                            "privateDnsZoneId": zone or c["network"]["privateDnsZoneId"]}}]})


def test_default_cli_is_strictly_offline(local_area, modules, capsys):
    consumer = local_area / "consumer"
    consumer.mkdir()
    source = consumer / "gateway.json"
    source.write_text(json.dumps(config()), encoding="utf-8")
    cli = Mock()
    cli.read.side_effect = AssertionError("Offline means no authentication or CLI")
    cli.invoke.side_effect = AssertionError("Offline means no compilation via CLI")
    result = gw.main(["--environment", "dev", "--config", str(source), "--output-dir", str(local_area / "artifacts")],
                     cli=cli, environ={}, module_root=modules)
    assert result == 0
    cli.read.assert_not_called()
    cli.invoke.assert_not_called()
    plan = json.loads((local_area / "artifacts" / "plan.json").read_text())
    assert plan["offline"] and not plan["armPreviewExecuted"]
    assert plan["estimatedPricing"]["amount"] is None
    assert "planDigest" in capsys.readouterr().out


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(environment="prod"),
    lambda c: c.update(tenantId="not-a-guid"),
    lambda c: c.update(subscriptionId=SUB + "?token=secret"),
    lambda c: c.update(serviceMod="managed"),
    lambda c: c["api"].update(aggregateTokenPerMinute=5),
    lambda c: c["api"].update(backendPoolName='pool" onerror="secret'),
    lambda c: c["api"].update(apiPath="../admin"),
    lambda c: c["api"].update(retryCount=51),
    lambda c: c["api"].update(callerTokensPerMinute=True),
    lambda c: c["api"].update(aggregateTokensPerMinute=0),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(key="secret"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(weight=1001),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(resourceId=BACKEND + "/../other"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(resourceId=BACKEND + "?sig=secret"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(resourceId=NSG),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(endpoint="https://user:secret@aoai-one.openai.azure.com"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(endpoint="https://aoai-one.openai.azure.com?key=secret"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(endpoint="https://aoai-one.openai.azure.com/#secret"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(endpoint="https://evil.example.org"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(endpoint="https://aoai-one.openai.azure.com\n"),
    lambda c: c["api"]["azureOpenAIBackends"].append(copy.deepcopy(c["api"]["azureOpenAIBackends"][0])),
    lambda c: c.update(tags={"aifactory-gateway-owner": "adopt"}),
])
def test_strict_configuration_rejects_unsafe_or_unknown_fields(mutation):
    c = config()
    mutation(c)
    with pytest.raises(GatewayError):
        validate_config(c, "dev")


@pytest.mark.parametrize("field", ["AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"])
def test_pipeline_target_must_match(field):
    with pytest.raises(GatewayError, match="cross-target"):
        validate_config(config(), "dev", {field: "22222222-2222-2222-2222-222222222222"})


def test_duplicate_json_fields_are_rejected():
    with pytest.raises(GatewayError, match="Duplicate"):
        json_document('{"serviceMode":"existing","serviceMode":"managed"}')


def test_legacy_defaults_remain_existing_only():
    env = {"ENABLE_APIM": "true", "AZURE_TENANT_ID": TENANT, "AZURE_SUBSCRIPTION_ID": SUB,
           "AZURE_LOCATION": "swedencentral", "APIM_GATEWAY_RESOURCE_GROUP": "gateway-rg",
           "APIM_GATEWAY_SERVICE_NAME": "apim-gateway", "APIM_GATEWAY_AGGREGATE_TPM": "100000",
           "APIM_GATEWAY_BACKENDS_JSON": json.dumps(config()["api"]["azureOpenAIBackends"]),
           "APIM_GATEWAY_SERVICE_MODE": "managed"}
    c = validate_config(legacy_config("dev", env), "dev", env)
    assert c["serviceMode"] == "existing"
    assert c["sku"] == "StandardV2" and c["skuCapacity"] == 1
    assert c["api"]["retryCount"] == 2 and c["api"]["callerTokensPerMinute"] == 10000
    assert "network" not in c


def test_legacy_configuration_ignores_factory_tags_it_never_deploys():
    # Existing mode never writes tags, and factory TAGS often hold commas ("true,true,true").
    env = {"ENABLE_APIM": "true", "AZURE_TENANT_ID": TENANT, "AZURE_SUBSCRIPTION_ID": SUB,
           "AZURE_LOCATION": "swedencentral", "APIM_GATEWAY_RESOURCE_GROUP": "gateway-rg",
           "APIM_GATEWAY_SERVICE_NAME": "apim-gateway", "APIM_GATEWAY_AGGREGATE_TPM": "100000",
           "APIM_GATEWAY_BACKENDS_JSON": json.dumps(config()["api"]["azureOpenAIBackends"]),
           "APIM_GATEWAY_TAGS_JSON": '{"AIF-Networking":"true,true,true"}',
           "TAGS": '{"AIF-Networking":"true,true,true"}'}
    assert load_config(None, "dev", env)["tags"] == {}


def test_source_digest_does_not_depend_on_checkout_line_endings(local_area):
    # A Windows checkout (CRLF) and the Linux agent (LF) must produce the same planDigest.
    roots = {}
    for name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        root = roots[name] = local_area / name
        root.mkdir()
        for filename, lines in {
            "main.bicep": ["targetScope = 'subscription'", "module config './config.bicep' = {}"],
            "config.bicep": ["var policy = loadTextContent('./policy.xml')"],
            "policy.xml": ["<policies>", "</policies>"],
        }.items():
            (root / filename).write_bytes((newline.join(lines) + newline).encode("utf-8"))
    assert gw.source_manifest(roots["lf"]) == gw.source_manifest(roots["crlf"])


def test_wrong_auth_fails_before_preview_or_write(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.read = Mock(return_value={"id": SUB, "tenantId": PRINCIPAL, "state": "Enabled"})
    with pytest.raises(GatewayError, match="Authenticated"):
        apply(runner)
    assert not fake.writes


def test_missing_existing_service_never_provisions(local_area, modules):
    runner, fake = deployment(local_area, modules, existing=False)
    with pytest.raises(GatewayError, match="never provisions"):
        apply(runner)
    assert not fake.writes


def test_existing_defaults_only_apply_configuration(local_area, modules):
    runner, fake = deployment(local_area, modules)
    original = copy.deepcopy(fake.resources[gw.service_id(runner.c)])
    receipt = apply(runner)
    assert fake.write_phases == ["configuration"]
    assert fake.resources[gw.service_id(runner.c)] == original
    assert receipt["foundryApiManagementResourceId"] == original["id"]
    params = json.loads((local_area / "output" / "configuration.parameters.json").read_text())["parameters"]
    assert params["apimManagedIdentityPrincipalId"]["value"] == PRINCIPAL
    assert not any(args[:3] == ["rest", "--method", "patch"] for _, args in fake.calls)


@pytest.mark.parametrize("sku", [{"name": "BasicV2", "capacity": 1}, {"name": "StandardV2", "capacity": 2}])
def test_existing_sku_and_capacity_changes_require_reviewed_lifecycle(local_area, modules, sku):
    runner, fake = deployment(local_area, modules)
    fake.resources[gw.service_id(runner.c)]["sku"] = sku
    with pytest.raises(GatewayError, match="reviewed managed lifecycle"):
        apply(runner)
    assert not fake.writes


def test_explicit_identity_must_equal_actual(local_area, modules):
    c = config()
    c["api"]["managedIdentityPrincipalId"] = TENANT
    runner, fake = deployment(local_area, modules, c)
    with pytest.raises(GatewayError, match="actual APIM"):
        apply(runner)
    assert not fake.writes


def test_managed_ownership_collision_is_fail_closed(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True))
    fake.resources[gw.service_id(runner.c)]["tags"] = {gw.OWNER_TAG: "another-owner"}
    with pytest.raises(GatewayError, match="ownership"):
        apply(runner)
    assert not fake.writes


@pytest.mark.parametrize("mutation", [
    lambda s: s["properties"].update(addressPrefix="10.0.1.0/28"),
    lambda s: s["properties"].update(addressPrefix="10.0.3.0/27"),
    lambda s: s["properties"].update(networkSecurityGroup={"id": NSG + "-other"}),
    lambda s: s["properties"].update(routeTable={"id": NET + "/routeTables/unapproved"}),
    lambda s: s["properties"].update(delegations=[]),
    lambda s: s["properties"].update(delegations=[{"properties": {"serviceName": "Microsoft.App/environments"}}]),
    lambda s: s["properties"].update(ipConfigurations=[{"id": "unknown-interface"}]),
    lambda s: s["properties"].update(serviceAssociationLinks=[{"properties": {"link": "other-service"}}]),
])
def test_existing_integration_requires_exact_safe_inventory(local_area, modules, mutation):
    runner, fake = deployment(local_area, modules, config(managed=True))
    mutation(fake.resources[INTEGRATION])
    with pytest.raises(GatewayError):
        apply(runner)
    assert not fake.writes


@pytest.mark.parametrize("prefix", ["10.0.1.0/28", "10.0.1.3/27", "2001:db8::/64"])
def test_invalid_create_prefix_rejected_offline(prefix):
    c = config(managed=True, create=True)
    c["network"]["integrationSubnetPrefix"] = prefix
    with pytest.raises(GatewayError):
        validate_config(c, "dev")


@pytest.mark.parametrize("prefix", ["10.1.0.0/27", "10.0.2.0/27"])
def test_create_prefix_containment_and_overlap_checked_before_writes(local_area, modules, prefix):
    c = config(managed=True, create=True)
    c["network"]["integrationSubnetPrefix"] = prefix
    runner, fake = deployment(local_area, modules, c, existing=False, integration=False)
    with pytest.raises(GatewayError):
        apply(runner)
    assert not fake.writes


def test_new_subnet_name_collision_requires_replan(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True, create=True), existing=False)
    with pytest.raises(GatewayError, match="already exists"):
        apply(runner)
    assert not fake.writes


def test_managed_create_requires_separate_transient_exposure_consent(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    preview = runner.execute("what-if")
    with pytest.raises(GatewayError, match="approve-initial-public-bootstrap"):
        runner.execute("apply", runner.plan["planDigest"], approved_preview=preview["previewDigest"])
    assert not fake.writes


def test_full_managed_lifecycle_has_secure_boundary_before_configuration(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True, create=True), existing=False, integration=False)
    def boundary(phase):
        if phase == "configuration":
            assert fake.resources[gw.service_id(runner.c)]["properties"]["publicNetworkAccess"] == "Disabled"
            assert fake.resources[runner.pe_id()]["properties"]["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]["status"] == "Approved"
    fake.create_hook = boundary
    receipt = apply(runner)
    assert fake.write_phases == ["network"]
    assert "createIntegrationSubnet=false" in receipt["nextAction"]
    c = copy.deepcopy(runner.c)
    c["network"]["createIntegrationSubnet"] = False
    runner = gw.Deployment(c, runner.artifacts, fake, module_root=modules, sleep=lambda _: None)
    for phase in ("service-bootstrap", "private-endpoint", "service-lockdown", "configuration"):
        before = len(fake.writes)
        receipt = apply(runner)
        assert len(fake.writes) == before + 1
        assert fake.write_phases[-1] == phase
    assert fake.write_phases == ["network", "service-bootstrap", "private-endpoint", "service-lockdown", "configuration"]
    assert receipt["status"] == "phase-applied"
    assert receipt["lifecycleComplete"]
    assert not receipt["publicBootstrapMayBeActive"]
    operations = [args[2] for kind, args in fake.calls if kind == "invoke"]
    assert operations == ["what-if", "what-if", "create"] * 5
    assert "MUST-NOT-LEAK" not in "".join(p.read_text() for p in (local_area / "output").glob("*.json"))


def test_gateway_is_configured_only_after_an_applied_configuration_phase(local_area, modules):
    # Pipelines publish the MCP or Kong on a managed APIM only when this flag is true.
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    assert runner.execute("plan")["gatewayConfigured"] is False
    assert runner.execute("what-if")["gatewayConfigured"] is False
    assert apply(runner)["gatewayConfigured"] is False
    assert fake.write_phases == ["service-bootstrap"]
    while fake.write_phases[-1] != "configuration":
        receipt = apply(runner)
        assert receipt["gatewayConfigured"] is (fake.write_phases[-1] == "configuration")
    fake.preview_result = {"status": "Succeeded", "changes": []}
    repeat = apply(runner)
    assert repeat["status"] == "phase-no-changes" and repeat["gatewayConfigured"] is True


def test_blocked_runs_never_report_a_configured_gateway(local_area, modules):
    runner, fake = deployment(local_area, modules, existing=False)
    with pytest.raises(GatewayError):
        apply(runner)
    receipt = json.loads((local_area / "output" / "receipt.json").read_text())
    assert receipt["status"] == "blocked" and receipt["gatewayConfigured"] is False


def test_main_prints_the_configured_flag_for_the_pipeline(local_area, modules, capsys):
    consumer = local_area / "consumer"
    consumer.mkdir()
    source = consumer / "gateway.json"
    source.write_text(json.dumps(config()), encoding="utf-8")
    assert gw.main(["--environment", "dev", "--config", str(source), "--output-dir", str(local_area / "artifacts")],
                   cli=Mock(), environ={}, module_root=modules) == 0
    assert json.loads(capsys.readouterr().out)["gatewayConfigured"] is False


@pytest.mark.parametrize("name,value", [
    ("APIM_GATEWAY_SUBSCRIPTION_ID", "22222222-2222-2222-2222-222222222222"),
    ("APIM_GATEWAY_RESOURCE_GROUP", "other-rg"),
    ("APIM_GATEWAY_SERVICE_NAME", "other-apim"),
])
def test_config_file_and_apim_gateway_variables_must_name_the_same_apim(local_area, name, value):
    # The MCP and Kong steps read the apimGateway* variables, so they must not point at another APIM.
    source = local_area / "gateway.json"
    source.write_text(json.dumps(config()), encoding="utf-8")
    with pytest.raises(GatewayError, match="apimGateway") as error:
        load_config(str(source), "dev", {name: value})
    assert error.value.code == "target-mismatch"


@pytest.mark.parametrize("variables", [
    {},
    {"APIM_GATEWAY_SUBSCRIPTION_ID": "", "APIM_GATEWAY_RESOURCE_GROUP": "", "APIM_GATEWAY_SERVICE_NAME": ""},
    {"APIM_GATEWAY_SUBSCRIPTION_ID": SUB.upper(), "APIM_GATEWAY_RESOURCE_GROUP": "GATEWAY-RG",
     "APIM_GATEWAY_SERVICE_NAME": "APIM-Gateway"},
])
def test_config_file_accepts_empty_or_matching_apim_gateway_variables(local_area, variables):
    source = local_area / "gateway.json"
    source.write_text(json.dumps(config()), encoding="utf-8")
    assert load_config(str(source), "dev", variables)["serviceName"] == "apim-gateway"


@pytest.mark.parametrize("public", ["Enabled", "Disabled"])
def test_existing_managed_never_redeploys_enabled(local_area, modules, public):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    fake.resources[gw.service_id(runner.c)]["properties"]["publicNetworkAccess"] = public
    apply(runner)
    assert fake.write_phases == (["service-lockdown"] if public == "Enabled" else ["configuration"])
    assert not (local_area / "output" / "service-bootstrap.parameters.json").exists()
    if public == "Enabled":
        values = json.loads((local_area / "output" / "service-lockdown.parameters.json").read_text())["parameters"]
        assert values["publicNetworkAccess"]["value"] == "Disabled"
    else:
        assert not (local_area / "output" / "service-lockdown.parameters.json").exists()


def test_pending_endpoint_blocks_configuration_no_bypass_cleanup_or_retries(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    fake.pe_status = "Pending"
    apply(runner)
    with pytest.raises(GatewayError, match="not Approved"):
        apply(runner)
    assert fake.write_phases == ["service-bootstrap", "private-endpoint"]
    receipt = json.loads((local_area / "output" / "receipt.json").read_text())
    assert receipt["publicBootstrapMayBeActive"] and not receipt["automaticCleanup"]
    assert receipt["failedPhase"] == "verify-private-endpoint"
    assert not any("approve" in args or "delete" in args for _, args in fake.calls)


def test_secure_verification_failure_blocks_configuration(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    fake.resources[gw.service_id(runner.c)]["properties"]["publicNetworkAccess"] = "Enabled"
    original = fake.invoke
    def not_actually_private(args, timeout):
        result = original(args, timeout)
        if args[:3] == ["deployment", "sub", "create"] and fake.write_phases[-1] == "service-lockdown":
            fake.resources[gw.service_id(runner.c)]["properties"]["publicNetworkAccess"] = "Enabled"
        return result
    fake.invoke = not_actually_private
    with pytest.raises(GatewayError, match="not Disabled"):
        apply(runner)
    assert "configuration" not in fake.write_phases


def test_what_if_new_service_reports_unresolved_dependencies_no_writes(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    receipt = runner.execute("what-if")
    assert receipt["status"] == "what-if-phase" and not receipt["fullAzurePreview"]
    assert "configuration" in receipt["unresolvedPhases"]
    assert not fake.writes
    assert [args[2] for kind, args in fake.calls if kind == "invoke"] == ["what-if"]


def test_network_what_if_is_partial_and_read_only(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True, create=True), existing=False, integration=False)
    receipt = runner.execute("what-if")
    assert receipt["status"] == "what-if-phase"
    assert receipt["phases"][0]["phase"] == "network"
    assert not fake.writes


def test_missing_or_mismatched_digest_blocks_all_azure_calls(local_area, modules):
    runner, fake = deployment(local_area, modules)
    with pytest.raises(GatewayError, match="approved-plan"):
        runner.execute("apply", "0" * 64)
    assert fake.calls == []


@pytest.mark.parametrize("filename", ["policy.xml", "config.bicep", "network-main.bicep"])
def test_digest_covers_transitive_maintained_sources(local_area, modules, filename):
    runner, fake = deployment(local_area, modules)
    digest = runner.plan["planDigest"]
    (modules / filename).write_text("changed", encoding="utf-8")
    assert gw.review_plan(runner.c, modules)["planDigest"] != digest
    with pytest.raises(GatewayError, match="changed"):
        apply(runner)
    assert not fake.writes


def test_dependency_file_tamper_between_preview_and_write_blocks_write(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.preview_hook = lambda phase: (modules / "policy.xml").write_text("tampered", encoding="utf-8")
    with pytest.raises(GatewayError, match="changed"):
        apply(runner)
    assert not fake.writes


def test_parameter_tamper_between_preview_and_write_blocks_write(local_area, modules):
    runner, fake = deployment(local_area, modules)
    def tamper(phase):
        path = local_area / "output" / (phase + ".parameters.json")
        content = json.loads(path.read_text())
        content["parameters"]["apiId"]["value"] = "unreviewed"
        path.write_text(json.dumps(content), encoding="utf-8")
    fake.preview_hook = tamper
    with pytest.raises(GatewayError, match="parameters changed"):
        apply(runner)
    assert not fake.writes


def test_service_appearing_during_bootstrap_preview_is_never_enabled(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    preview = runner.execute("what-if")
    def race(phase):
        if phase == "service-bootstrap":
            fake.resources[gw.service_id(runner.c)] = service(runner.c)
    fake.preview_hook = race
    with pytest.raises(GatewayError, match="Refusing to enable"):
        runner.execute("apply", runner.plan["planDigest"], approve_initial=True, approved_preview=preview["previewDigest"])
    assert not fake.writes


def test_preview_failure_means_no_resource_write(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.invoke = Mock(return_value={"status": "Failed", "error": {"message": "secret"}})
    with pytest.raises(GatewayError, match="what-if"):
        apply(runner)
    assert fake.invoke.call_count == 1
    assert not fake.writes


def test_delete_preview_is_not_applied(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.invoke = Mock(return_value={"status": "Succeeded", "changes": [{"changeType": "Delete"}]})
    with pytest.raises(GatewayError, match="deletion"):
        apply(runner)
    assert fake.invoke.call_count == 1


def test_cli_uses_argument_arrays_bounded_timeout_and_no_shell():
    command = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    cli = gw.AzureCLI(run=command, platform="linux", which=lambda _: "/usr/bin/az")
    cli.invoke(["deployment", "sub", "what-if", "--parameters", "@consumer path;not-a-shell.json"], timeout=600)
    args, kwargs = command.call_args
    assert isinstance(args[0], list)
    assert args[0][-1] == "@consumer path;not-a-shell.json"
    assert kwargs["shell"] is False and kwargs["timeout"] == 600
    assert kwargs["capture_output"] is True


def test_windows_az_cmd_uses_bundled_python_without_batch_shell(local_area):
    launcher = local_area / "CLI" / "wbin" / "az.cmd"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("not executed", encoding="utf-8")
    python = launcher.parent.parent / "python.exe"
    python.write_bytes(b"not executed")
    command = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    cli = gw.AzureCLI(run=command, platform="win32", which=lambda _: str(launcher))
    cli.invoke(["account", "show"])
    args, kwargs = command.call_args
    assert args[0][:3] == [str(python), "-IBm", "azure.cli"]
    assert kwargs["shell"] is False
    python.unlink()
    with pytest.raises(GatewayError, match="fallback is forbidden"):
        cli.invoke(["account", "show"])


@pytest.mark.parametrize("error,code", [
    ("ERROR: (AuthorizationFailed) BEARER-SECRET", "auth-denied"),
    ("ERROR: (RequestDisallowedByPolicy) BEARER-SECRET", "policy-denied"),
    ("ERROR: (ResourceNotFound) BEARER-SECRET", "not-found"),
    ("anything BEARER-SECRET", "cli-failed"),
])
def test_cli_errors_are_classified_without_raw_output(error, code):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout="BEARER-SECRET", stderr=error))
    cli = gw.AzureCLI(run=run, platform="linux", which=lambda _: "/usr/bin/az")
    with pytest.raises(GatewayError) as caught:
        cli.invoke(["deployment", "sub", "create"])
    assert caught.value.code == code
    assert "BEARER-SECRET" not in str(caught.value)
    assert run.call_count == 1


def test_retries_are_only_transient_reads():
    failure = SimpleNamespace(returncode=1, stdout="", stderr="ERROR: (TooManyRequests) secret")
    success = SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")
    run = Mock(side_effect=[failure, success])
    cli = gw.AzureCLI(run=run, sleep=lambda _: None, platform="linux", which=lambda _: "/usr/bin/az")
    assert cli.read(["rest", "--method", "get", "--url", "https://management.azure.com/"]) == {"ok": True}
    assert run.call_count == 2
    run.reset_mock(side_effect=True)
    run.return_value = failure
    with pytest.raises(GatewayError):
        cli.invoke(["deployment", "sub", "create"])
    assert run.call_count == 1
    with pytest.raises(GatewayError, match="Only GET"):
        cli.read(["rest", "--method", "patch"])


def test_ambiguous_timeout_does_not_retry_write():
    run = Mock(side_effect=subprocess.TimeoutExpired(["az", "deployment"], 7200, output="secret", stderr="secret"))
    cli = gw.AzureCLI(run=run, platform="linux", which=lambda _: "/usr/bin/az")
    with pytest.raises(GatewayError) as caught:
        cli.invoke(["deployment", "sub", "create"], timeout=7200)
    assert caught.value.code == "cli-timeout"
    assert "secret" not in str(caught.value)
    assert run.call_count == 1


def test_unexpected_exception_propagates_without_logging_raw_values(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.invoke = Mock(side_effect=RuntimeError("token=DO-NOT-LOG"))
    with pytest.raises(RuntimeError, match="DO-NOT-LOG"):
        apply(runner)
    receipt = (local_area / "output" / "receipt.json").read_text()
    assert "DO-NOT-LOG" not in receipt
    assert not fake.writes


def test_output_cannot_overwrite_config_or_module_sources(local_area, modules):
    source = local_area / "consumer" / "gateway.json"
    source.parent.mkdir()
    source.write_text(json.dumps(config()), encoding="utf-8")
    with pytest.raises(GatewayError, match="configuration directory"):
        gw.Artifacts(source.parent / "generated", source, modules)
    with pytest.raises(GatewayError, match="module/script"):
        gw.Artifacts(modules / "generated", source, modules)


def test_plan_does_not_rewrite_consumer_and_writes_are_atomic(local_area, modules):
    runner, fake = deployment(local_area, modules)
    result = runner.execute("plan")
    assert result["status"] == "offline-plan" and not fake.calls
    assert not list((local_area / "output").glob("*.pending"))
    assert not list((local_area / "output").glob("variables.json"))


@pytest.mark.parametrize("field,value", [
    ("integrationSubnetId", INTEGRATION.replace(SUB, TENANT)),
    ("privateEndpointSubnetId", PE_SUBNET.replace("/hub/", "/other/")),
    ("privateEndpointSubnetId", INTEGRATION),
    ("networkSecurityGroupId", NSG + "#secret"),
    ("networkSecurityGroupId", NSG.replace("/network-rg/", "/../")),
    ("routeTableId", NSG),
    ("privateDnsMode", "typo"),
    ("privateDnsMode", []),
    ("privateDnsZoneId", NET + "/privateDnsZones/privatelink.azure-api.net"),
    ("createIntegrationSubnet", "true"),
])
def test_network_fields_are_strict_and_cross_target_safe(field, value):
    c = config(managed=True)
    c["network"][field] = value
    with pytest.raises(GatewayError):
        validate_config(c, "dev")


def test_resource_ids_are_case_insensitive_without_allowing_url_data():
    c = config(managed=True)
    c["network"]["integrationSubnetId"] = INTEGRATION.replace("/subnets/", "/Subnets/")
    c["network"]["privateEndpointSubnetId"] = PE_SUBNET.replace("/virtualNetworks/", "/VirtualNetworks/")
    assert validate_config(c, "dev")["network"]["integrationSubnetId"].endswith("/apim-outbound")


@pytest.mark.parametrize("mutation", [
    lambda pe: pe.update(tags={gw.OWNER_TAG: "different"}),
    lambda pe: pe["properties"].update(subnet={"id": INTEGRATION}),
    lambda pe: pe["properties"]["privateLinkServiceConnections"][0]["properties"].update(groupIds=["other"]),
    lambda pe: pe["properties"]["privateLinkServiceConnections"][0]["properties"].update(privateLinkServiceId=BACKEND),
])
def test_private_endpoint_collision_before_any_write(local_area, modules, mutation):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    mutation(fake.resources[runner.pe_id()])
    with pytest.raises(GatewayError):
        apply(runner)
    assert not fake.writes


def test_managed_service_cannot_remove_additional_identity(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    fake.resources[gw.service_id(runner.c)]["identity"]["type"] = "SystemAssigned, UserAssigned"
    with pytest.raises(GatewayError, match="additional identities"):
        apply(runner)
    assert not fake.writes


def test_new_subnet_race_is_detected_after_preview(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True, create=True), existing=False, integration=False)
    fake.preview_hook = lambda phase: fake.resources.update({INTEGRATION: subnet()})
    with pytest.raises(GatewayError, match="already exists"):
        apply(runner)
    assert not fake.writes


def test_identity_changed_during_preview_requires_new_review(local_area, modules):
    runner, fake = deployment(local_area, modules)
    preview = runner.execute("what-if")
    def swap(phase):
        fake.resources[gw.service_id(runner.c)]["identity"]["principalId"] = TENANT
    fake.preview_hook = swap
    with pytest.raises(GatewayError, match="identity changed"):
        runner.execute("apply", runner.plan["planDigest"], approved_preview=preview["previewDigest"])
    assert not fake.writes


def test_existing_zone_mode_only_passes_the_declared_zone(local_area, modules):
    c = config(managed=True)
    c["network"].update(privateDnsMode="existingZone", privateDnsZoneId=NET + "/privateDnsZones/privatelink.azure-api.net")
    c = validate_config(c, "dev")
    runner, fake = deployment(local_area, modules, c, pe=True)
    fake.resources[c["network"]["privateDnsZoneId"]] = resource(c["network"]["privateDnsZoneId"], location="global")
    apply(runner)
    parameters = runner.parameters("private-endpoint")
    assert parameters["privateDnsZoneId"] == c["network"]["privateDnsZoneId"]
    assert parameters["privateDnsMode"] == "existingZone"


def test_owned_endpoint_collision_appearing_after_preview_blocks_write(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True))
    def collision(phase):
        if phase == "private-endpoint":
            other = private_endpoint(runner.c)
            other["tags"] = {gw.OWNER_TAG: "someone-else"}
            fake.resources[other["id"]] = other
    fake.preview_hook = collision
    with pytest.raises(GatewayError, match="ownership"):
        apply(runner)
    assert not fake.writes


def test_new_service_failure_is_not_retried_and_preserves_exposure_receipt(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    def fail(phase):
        raise GatewayError("policy-denied", "Governance blocked the write; reconcile the operation.")
    fake.create_hook = fail
    with pytest.raises(GatewayError, match="Governance"):
        apply(runner)
    assert fake.write_phases == ["service-bootstrap"]
    receipt = json.loads((local_area / "output" / "receipt.json").read_text())
    assert receipt["publicBootstrapMayBeActive"]
    assert receipt["phases"][-1]["status"] == "deployment-started"


def test_repeated_managed_apply_never_bootstraps_again(local_area, modules):
    c = config(managed=True)
    runner, fake = deployment(local_area, modules, c, existing=False)
    apply(runner)
    first = len(fake.writes)
    repeat = gw.Deployment(c, runner.artifacts, fake, module_root=modules, sleep=lambda _: None)
    apply(repeat)
    repeat_phases = fake.write_phases[first:]
    assert repeat_phases == ["private-endpoint"]


def test_all_transitive_sources_and_real_template_parameter_contract_are_offline(local_area):
    c = config(managed=True)
    runner = gw.Deployment(c, gw.Artifacts(local_area / "contract"), cli=Mock())
    runner.service = service(c)
    for phase, filename in gw.PHASE_TEMPLATES.items():
        source = (gw.MODULE_ROOT / filename).read_text(encoding="utf-8")
        declared = set(gw.re.findall(r"^param (\w+) ", source, gw.re.M))
        if phase != "configuration":
            assert set(runner.parameters(phase)) == declared
            continue
        # main.bicep is shared with the classic pipeline step: the runner passes exactly the parameters
        # that step passes, and every other main.bicep parameter (policy package, MCP servers) keeps its default.
        classic = {"apimServiceName", "apimResourceGroupName", "apimSubscriptionId", "apiId", "apiPath",
                   "backendPoolName", "aggregateTokensPerMinute", "callerTokensPerMinute", "retryCount",
                   "assignOpenAIUserRole", "apimManagedIdentityPrincipalId", "azureOpenAIBackends"}
        assert set(runner.parameters(phase)) == classic
        defaulted = set(gw.re.findall(r"^param (\w+) [^=\n]+=", source, gw.re.M))
        assert declared - classic <= defaulted
    manifest = runner.plan["sourceHashes"]
    for filename in ("main.bicep", "apim-configuration.bicep", "policy.xml", "openai-role-assignment.bicep",
                     "apim-service.bicep", "network-subnet.bicep", "private-endpoint.bicep"):
        assert any(name.endswith("/" + filename) for name in manifest)
    runner.cli.read.assert_not_called()
    runner.cli.invoke.assert_not_called()


def test_invalid_cli_argument_values_are_not_reflected_in_errors(capsys):
    assert gw.main(["--environment", "DO-NOT-LOG", "--output-dir", "."]) == 1
    captured = capsys.readouterr()
    assert "DO-NOT-LOG" not in captured.err + captured.out
    assert "arguments-invalid" in captured.err


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("wrapper", [
    'ERROR: Not Found({"error":{"code":"ResourceNotFound","message":"BEARER-SECRET"}})',
    'ERROR: (ResourceNotFound) BEARER-SECRET',
    '{"error":{"code":"ResourceGroupNotFound","message":"BEARER-SECRET"}}',
])
def test_real_cli_missing_envelopes_allow_absence_only(stream, wrapper):
    result = SimpleNamespace(returncode=1, stdout="", stderr="")
    setattr(result, stream, wrapper)
    run = Mock(return_value=result)
    cli = gw.AzureCLI(run=run, platform="linux", which=lambda _: "az")
    assert cli.read(["rest", "--method", "get"], allow_missing=True) is None
    assert run.call_count == 1


@pytest.mark.parametrize("wrapper", [
    'ERROR: Forbidden({"error":{"code":"AuthorizationFailed","message":"ResourceNotFound"}})',
    'ERROR: Forbidden({"error":{"code":"ResourceNotFound","message":"BEARER-SECRET"}})',
    'ERROR: Bad Request({"error":{"code":"InvalidRequest","message":"(ResourceNotFound)"}})',
    'ERROR: Not Found({"error":{"code":"NotFound","message":"backend object not found"}})',
    'ERROR: (NotFound) unrelated service result',
    '{"message":"(ResourceNotFound)","details":{"error":{"code":"ResourceNotFound"}}}',
    'Service says NotFound or (ResourceNotFound) for a nested object',
    'ERROR: Forbidden({"error":{"code":"Forbidden","details":[{"code":"ResourceNotFound"}]}})',
])
def test_missing_detection_never_matches_arbitrary_service_text(wrapper):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr=wrapper))
    cli = gw.AzureCLI(run=run, platform="linux", which=lambda _: "az")
    with pytest.raises(GatewayError) as caught:
        cli.read(["rest", "--method", "get"], allow_missing=True)
    assert caught.value.code != "not-found"
    assert run.call_count == 1


@pytest.mark.parametrize("wrapper", [
    'ERROR: Too Many Requests({"error":{"code":"TooManyRequests","message":"BEARER-SECRET"}})',
    'ERROR: Service Unavailable({"error":{"code":"ServiceUnavailable","message":"BEARER-SECRET"}})',
    'ERROR: Service Unavailable({"error":{"code":"503","message":"BEARER-SECRET"}})',
    'ERROR: (TooManyRequests) BEARER-SECRET',
])
def test_real_cli_throttling_has_bounded_read_only_retries(wrapper):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr=wrapper))
    sleeps = Mock()
    cli = gw.AzureCLI(run=run, sleep=sleeps, platform="linux", which=lambda _: "az")
    with pytest.raises(GatewayError) as caught:
        cli.read(["rest", "--method", "get"], allow_missing=True)
    assert caught.value.code == "read-transient"
    assert "BEARER-SECRET" not in str(caught.value)
    assert run.call_count == 3
    assert [call.args[0] for call in sleeps.call_args_list] == [1, 2]
    for verb in ("what-if", "create"):
        run.reset_mock()
        with pytest.raises(GatewayError):
            cli.invoke(["deployment", "sub", verb])
        assert run.call_count == 1


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(tenantId="00000000-0000-0000-0000-000000000000"),
    lambda c: c.update(subscriptionId="00000000-0000-0000-0000-000000000000"),
    lambda c: c["api"].update(managedIdentityPrincipalId="00000000-0000-0000-0000-000000000000"),
    lambda c: c["api"]["azureOpenAIBackends"][0].update(resourceId=BACKEND.replace(SUB, "00000000-0000-0000-0000-000000000000")),
    lambda c: c.update(skuCapacity=11),
])
def test_zero_guids_and_invalid_standardv2_capacity_rejected(mutation):
    c = config()
    mutation(c)
    with pytest.raises(GatewayError):
        validate_config(c, "dev")


def test_standardv2_maximum_supported_capacity():
    c = config(managed=True)
    c["skuCapacity"] = 10
    assert validate_config(c, "dev")["skuCapacity"] == 10


def test_secure_custom_service_preserved_without_service_or_pe_put(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    current = fake.resources[gw.service_id(runner.c)]
    current["properties"].update(
        hostnameConfigurations=[{"type": "Proxy", "hostName": "custom.example.org", "keyVaultId": "DO-NOT-LOG"}],
        customProperties={"custom": "PRESERVE-ME"}, certificates=[{"encodedCertificate": "SECRET"}],
        developerPortalStatus="Enabled")
    original = copy.deepcopy(current)
    receipt = apply(runner)
    assert fake.write_phases == ["configuration"]
    assert fake.resources[gw.service_id(runner.c)] == original
    assert receipt["currentPhase"] == "configuration"
    assert "SECRET" not in (local_area / "output" / "receipt.json").read_text()


@pytest.mark.parametrize("settings", [
    {"hostnameConfigurations": [{"type": "Proxy", "hostName": "custom.example.org"}]},
    {"hostnameConfigurations": [{"type": "DeveloperPortal", "hostName": "apim-gateway.azure-api.net"}]},
    {"hostnameConfigurations": [{"type": "Proxy", "hostName": "apim-gateway.azure-api.net", "keyVaultId": "SECRET"}]},
    {"additionalLocations": [{"location": "other-region"}]},
    {"certificates": [{"encodedCertificate": "SECRET"}]},
    {"customProperties": {"setting": "SECRET"}},
    {"developerPortalStatus": "Enabled"},
    {"apiVersionConstraint": {"minApiVersion": "2024-05-01"}},
    {"notificationSenderEmail": "custom@example.org"},
    {"unmodeledWritableSetting": {"value": "SECRET"}},
    {"disableGateway": True},
])
def test_enabled_custom_service_blocked_before_any_writes(local_area, modules, settings):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=False)
    fake.resources[gw.service_id(runner.c)]["properties"].update(publicNetworkAccess="Enabled", **settings)
    with pytest.raises(GatewayError) as caught:
        apply(runner)
    assert caught.value.code == "service-customized"
    assert not fake.writes
    assert not any(kind == "invoke" for kind, _ in fake.calls)
    receipt = json.loads((local_area / "output" / "receipt.json").read_text())
    assert receipt["publicBootstrapMayBeActive"]
    assert "SECRET" not in json.dumps(receipt)


def test_generated_azure_fields_do_not_block_safe_lockdown(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    current = fake.resources[gw.service_id(runner.c)]
    current.update(name=runner.c["serviceName"], type="Microsoft.ApiManagement/service", etag="opaque", zones=[])
    current["identity"]["tenantId"] = TENANT
    current["properties"]["virtualNetworkConfiguration"].update(vnetid=TENANT, subnetname="apim-outbound")
    current["properties"].update(
        publicNetworkAccess="Enabled", createdAtUtc="2026-01-01T00:00:00Z", platformVersion="stv2",
        gatewayUrl="https://apim-gateway.azure-api.net", developerPortalUrl="https://apim-gateway.developer.azure-api.net",
        additionalLocations=[], certificates=[], customProperties={}, apiVersionConstraint={"minApiVersion": None},
        notificationSenderEmail="apimgmt-noreply@mail.windowsazure.com",
        privateEndpointConnections=[{"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}}],
        hostnameConfigurations=[{"type": "Proxy", "hostName": "apim-gateway.azure-api.net", "certificateSource": "BuiltIn",
                                 "defaultSslBinding": True, "negotiateClientCertificate": False,
                                 "certificate": {"subject": "*.azure-api.net", "expiry": "2027-01-01", "thumbprint": "HASH"}}])
    receipt = apply(runner)
    assert fake.write_phases == ["service-lockdown"]
    assert receipt["unresolvedPhases"] == ["configuration"]
    assert not receipt["publicBootstrapMayBeActive"]


@pytest.mark.parametrize("mutation", [
    lambda r: r["sku"].update(capacity=2),
    lambda r: r["properties"].update(publisherName="Not the owner"),
    lambda r: r["properties"].update(virtualNetworkType="None"),
    lambda r: r["properties"].update(virtualNetworkConfiguration={"subnetResourceId": PE_SUBNET}),
])
def test_owner_marker_alone_does_not_adopt_mismatched_service(local_area, modules, mutation):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    mutation(fake.resources[gw.service_id(runner.c)])
    with pytest.raises(GatewayError):
        apply(runner)
    assert not fake.writes


def test_missing_preview_approval_blocks_without_any_azure_calls(local_area, modules):
    runner, fake = deployment(local_area, modules)
    with pytest.raises(GatewayError, match="approved-preview"):
        runner.execute("apply", runner.plan["planDigest"])
    assert not fake.calls


def test_plan_digest_cannot_authorize_preview_or_multiple_phases(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    with pytest.raises(GatewayError, match="approved-preview"):
        runner.execute("apply", runner.plan["planDigest"], approve_initial=True, approved_preview=runner.plan["planDigest"])
    assert not fake.writes


def test_phase_preview_is_read_only_and_exactly_bound(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    review = runner.execute("what-if")
    saved = json.loads((local_area / "output" / review["previewArtifact"]).read_text())
    assert saved["previewDigest"] == review["previewDigest"]
    assert saved["phase"] == "service-bootstrap"
    assert saved["planDigest"] == runner.plan["planDigest"]
    assert saved["parametersHash"] == gw.value_hash(runner.parameters("service-bootstrap", "Enabled"))
    assert saved["unresolvedPhases"] == ["private-endpoint", "service-lockdown", "configuration"]
    assert not review["lifecycleComplete"] and not saved["fullAzurePreview"]
    assert not fake.writes
    receipt = runner.execute("apply", review["planDigest"], approve_initial=True, approved_preview=review["previewDigest"])
    assert fake.write_phases == ["service-bootstrap"]
    assert receipt["publicBootstrapMayBeActive"]
    assert receipt["unresolvedPhases"] == ["private-endpoint", "service-lockdown", "configuration"]
    assert not receipt["lifecycleComplete"]
    assert "Rerun what-if" in receipt["nextAction"]
    with pytest.raises(GatewayError, match="approved-preview"):
        runner.execute("apply", review["planDigest"], approve_initial=True, approved_preview=review["previewDigest"])
    assert fake.write_phases == ["service-bootstrap"]


def configuration_preview(runner, value="NEW-SECRET"):
    return {"status": "Succeeded", "changes": [{
        "resourceId": gw.service_id(runner.c) + "/apis/" + runner.c["api"]["apiId"],
        "changeType": "Modify",
        "before": {"properties": {"credentials": {"token": "OLD-SECRET"}}},
        "after": {"properties": {"credentials": {"token": value}}},
        "delta": [{"path": "properties.credentials", "propertyChangeType": "Modify", "children": [
            {"path": "token", "propertyChangeType": "Modify", "before": "OLD-SECRET", "after": value}]}],
    }]}


def test_preview_retains_nested_paths_types_hashes_and_value_sensitive_digest(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.preview_result = configuration_preview(runner)
    first = runner.execute("what-if")
    artifact = json.loads((local_area / "output" / first["previewArtifact"]).read_text())
    nested = artifact["changes"][0]["delta"][0]["children"][0]
    assert nested["path"] == "token" and nested["propertyChangeType"] == "Modify"
    assert nested["before"] == {"type": "string", "sha256": gw.value_hash("OLD-SECRET")}
    assert nested["after"] == {"type": "string", "sha256": gw.value_hash("NEW-SECRET")}
    assert "SECRET" not in json.dumps(artifact)
    fake.preview_result = configuration_preview(runner, "DIFFERENT-SECRET")
    with pytest.raises(GatewayError, match="approved-preview"):
        runner.execute("apply", first["planDigest"], approved_preview=first["previewDigest"])
    assert not fake.writes
    changed = json.loads((local_area / "output" / "receipt.json").read_text())
    assert changed["previewDigest"] != first["previewDigest"]


@pytest.mark.parametrize("mutation", [
    lambda p: p["changes"][0].update(changeType="Delete"),
    lambda p: p["changes"][0].update(changeType="Deploy"),
    lambda p: p["changes"][0].update(changeType=[]),
    lambda p: p["changes"][0].update(unsupportedReason="Opaque expression"),
    lambda p: p["changes"][0].update(opaqueChanges={"token": "SECRET"}),
    lambda p: p["changes"][0].update(delta=None),
    lambda p: p["changes"][0].update(delta={}),
    lambda p: p["changes"][0]["delta"][0]["children"][0].update(propertyChangeType="Delete"),
    lambda p: p["changes"][0]["delta"][0]["children"][0].update(propertyChangeType="Unknown"),
    lambda p: p["changes"][0]["delta"][0].update(children="opaque"),
    lambda p: p["changes"][0]["delta"][0]["children"][0].update(unsupported="hidden"),
    lambda p: p["changes"][0].update(resourceId=NSG),
    lambda p: p["changes"][0].update(resourceId=gw.service_id(config()) + "?sig=SECRET"),
    lambda p: p["changes"].append(copy.deepcopy(p["changes"][0])),
])
def test_destructive_or_uninspectable_preview_never_applies(local_area, modules, mutation):
    runner, fake = deployment(local_area, modules)
    fake.preview_result = configuration_preview(runner)
    mutation(fake.preview_result)
    with pytest.raises(GatewayError):
        runner.execute("apply", runner.plan["planDigest"], approved_preview="a" * 64)
    assert not fake.writes
    assert "SECRET" not in (local_area / "output" / "receipt.json").read_text()


def test_no_change_preview_does_not_claim_a_deployment(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.preview_result = {"status": "Succeeded", "changes": [{
        "resourceId": gw.service_id(runner.c) + "/apis/" + runner.c["api"]["apiId"],
        "changeType": "NoChange", "before": {"a": 1}, "after": {"a": 1}, "delta": None,
        "unsupportedReason": None}]}
    receipt = apply(runner)
    assert receipt["status"] == "phase-no-changes"
    assert not receipt["resourceWritesAttempted"]
    assert not receipt["lifecycleComplete"] and not receipt["fullAzurePreview"]
    assert receipt["phases"][0]["status"] == "no-changes"
    assert not fake.writes


def existing_zone_config():
    c = config(managed=True)
    c["network"].update(privateDnsMode="existingZone", privateDnsZoneId=NET + "/privateDnsZones/privatelink.azure-api.net")
    return validate_config(c, "dev")


@pytest.mark.parametrize("variant", ["other-name", "other-zone", "multiple", "extra-zone", "pending"])
def test_zone_group_conflicts_block_before_preview_or_writes(local_area, modules, variant):
    c = existing_zone_config()
    runner, fake = deployment(local_area, modules, c, pe=True)
    fake.resources[c["network"]["privateDnsZoneId"]] = resource(c["network"]["privateDnsZoneId"], location="global")
    group = zone_group(c)
    if variant == "other-name":
        group = zone_group(c, "policy-managed")
    if variant == "other-zone":
        group = zone_group(c, zone=c["network"]["privateDnsZoneId"].replace("network-rg", "policy-rg"))
    if variant == "extra-zone":
        group["properties"]["privateDnsZoneConfigs"].append(copy.deepcopy(group["properties"]["privateDnsZoneConfigs"][0]))
    if variant == "pending":
        group["properties"]["provisioningState"] = "Updating"
    fake.zone_groups = [group, copy.deepcopy(group)] if variant == "multiple" else [group]
    with pytest.raises(GatewayError) as caught:
        apply(runner)
    assert caught.value.code == "dns-collision"
    assert not any(kind == "invoke" for kind, _ in fake.calls)


def test_exact_existing_zone_group_reused_without_endpoint_write(local_area, modules):
    c = existing_zone_config()
    runner, fake = deployment(local_area, modules, c, pe=True)
    fake.resources[c["network"]["privateDnsZoneId"]] = resource(c["network"]["privateDnsZoneId"], location="global")
    fake.zone_groups = [zone_group(c)]
    apply(runner)
    assert fake.write_phases == ["configuration"]


def test_missing_zone_group_requires_its_own_reviewed_phase(local_area, modules):
    c = existing_zone_config()
    runner, fake = deployment(local_area, modules, c, pe=True)
    fake.resources[c["network"]["privateDnsZoneId"]] = resource(c["network"]["privateDnsZoneId"], location="global")
    receipt = apply(runner)
    assert fake.write_phases == ["private-endpoint"]
    assert receipt["unresolvedPhases"] == ["configuration"]
    assert fake.zone_groups == [zone_group(c)]


def test_zone_group_race_checked_again_before_write(local_area, modules):
    c = existing_zone_config()
    runner, fake = deployment(local_area, modules, c, pe=True)
    fake.resources[c["network"]["privateDnsZoneId"]] = resource(c["network"]["privateDnsZoneId"], location="global")
    reviewed = runner.execute("what-if")
    fake.preview_hook = lambda _: fake.zone_groups.append(zone_group(c, "policy-owned"))
    with pytest.raises(GatewayError) as caught:
        runner.execute("apply", reviewed["planDigest"], approved_preview=reviewed["previewDigest"])
    assert caught.value.code == "dns-collision"
    assert not fake.writes


def test_policy_mode_never_reads_or_adopts_zone_groups(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    fake.zone_groups = [{"id": "policy-owned"}]
    apply(runner)
    assert fake.write_phases == ["configuration"]
    assert not any("/privateDnsZoneGroups" in str(args) for _, args in fake.calls)


@pytest.mark.parametrize("public", ["Enabled", "Disabled"])
def test_existing_pending_endpoint_cannot_be_approved_by_runner(local_area, modules, public):
    runner, fake = deployment(local_area, modules, config(managed=True), pe=True)
    fake.resources[gw.service_id(runner.c)]["properties"]["publicNetworkAccess"] = public
    fake.resources[runner.pe_id()]["properties"]["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]["status"] = "Pending"
    with pytest.raises(GatewayError, match="not Approved"):
        apply(runner)
    assert not fake.writes
    assert not any(kind == "invoke" for kind, _ in fake.calls)


def test_expected_local_fault_gets_controlled_receipt(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.invoke = Mock(side_effect=OSError("PRIVATE-PATH"))
    with pytest.raises(GatewayError) as caught:
        runner.execute("what-if")
    assert caught.value.code == "local-failure"
    receipt = (local_area / "output" / "receipt.json").read_text()
    assert "PRIVATE-PATH" not in receipt
    assert "local-failure" in receipt


def test_real_what_if_null_optional_fields_are_inspectable(local_area, modules):
    runner, fake = deployment(local_area, modules)
    fake.preview_result = configuration_preview(runner)
    child = fake.preview_result["changes"][0]["delta"][0]["children"][0]
    child["children"] = None
    fake.preview_result["changes"][0]["unsupportedReason"] = None
    receipt = apply(runner)
    assert receipt["status"] == "phase-applied"
    assert fake.write_phases == ["configuration"]


def test_create_preview_with_full_resource_payload_is_accepted(local_area, modules):
    runner, fake = deployment(local_area, modules, config(managed=True), existing=False)
    fake.preview_result = {"status": "Succeeded", "changes": [{
        "changeType": "Create", "resourceId": gw.service_id(runner.c), "before": None,
        "after": {"properties": {"publicNetworkAccess": "Enabled"}}, "delta": None, "unsupportedReason": None}]}
    receipt = apply(runner)
    assert receipt["publicBootstrapMayBeActive"]
    assert fake.write_phases == ["service-bootstrap"]


def test_main_accepts_both_approval_arguments_and_prints_phase_digest(local_area, modules, capsys):
    consumer = local_area / "consumer"
    consumer.mkdir()
    path = consumer / "gateway.json"
    c = config()
    path.write_text(json.dumps(c), encoding="utf-8")
    fake = FakeCLI(c)
    args = ["--environment", "dev", "--config", str(path), "--output-dir", str(local_area / "artifacts")]
    assert gw.main(args + ["--action", "what-if"], cli=fake, environ={}, module_root=modules) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["phase"] == "configuration" and result["previewDigest"]
    assert gw.main(args + ["--action", "apply", "--approved-plan", result["planDigest"],
                          "--approved-preview", result["previewDigest"]], cli=fake, environ={}, module_root=modules) == 0
    assert fake.write_phases == ["configuration"]


def test_main_does_not_swallow_programmer_errors(local_area, modules, monkeypatch):
    consumer = local_area / "consumer"
    consumer.mkdir()
    path = consumer / "gateway.json"
    path.write_text(json.dumps(config()), encoding="utf-8")
    monkeypatch.setattr(gw.Deployment, "execute", Mock(side_effect=TypeError("programmer error")))
    with pytest.raises(TypeError, match="programmer error"):
        gw.main(["--environment", "dev", "--config", str(path), "--output-dir", str(local_area / "artifacts")],
                cli=Mock(), environ={}, module_root=modules)
