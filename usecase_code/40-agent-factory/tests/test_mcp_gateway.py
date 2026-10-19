"""Offline contracts for the opt-in project001 Dev AI Factory MCP & AI Gateway integration."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_factory.azure import ARM, AzureError  # noqa: E402
from agent_factory import mcp_gateway as gw  # noqa: E402

SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
APP_REG = "33333333-3333-4333-8333-333333333333"
GROUP = "aif-esml-project001-sdc-dev-001-rg"
GROUP_ID = f"/subscriptions/{SUB}/resourceGroups/{GROUP}"
ACCOUNT_ID = f"{GROUP_ID}/providers/Microsoft.CognitiveServices/accounts/aifacct001"
PROJECT_ID = f"{ACCOUNT_ID}/projects/aifproj001"
ENV_ID = f"{GROUP_ID}/providers/Microsoft.App/managedEnvironments/aca-env-prj001"
PE_ID = f"{GROUP_ID}/providers/Microsoft.Network/privateEndpoints/aca-env-prj001-pend"
ACA_ZONE = f"/subscriptions/{SUB}/resourceGroups/dns/providers/Microsoft.Network/privateDnsZones/privatelink.swedencentral.azurecontainerapps.io"
ADOPTED_APP = f"{GROUP_ID}/providers/Microsoft.App/containerApps/aifactory-mcp-project001-dev"
REGISTRY_ID = f"/subscriptions/{SUB}/resourceGroups/common-rg/providers/Microsoft.ContainerRegistry/registries/acrcommon"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/hub/providers/Microsoft.Network/virtualNetworks/hub/subnets/snet-aigw"
CLASSIC_APIM = f"/subscriptions/{SUB}/resourceGroups/common-rg/providers/Microsoft.ApiManagement/service/apim-classic"
OTHER_APIM = f"/subscriptions/{SUB}/resourceGroups/common-rg/providers/Microsoft.ApiManagement/service/apim-other"
DIGEST = "a" * 64
VALUES = {
    "enableAIFactoryMCP": "true", "enableAIGatewaySKU": "true", "addAIFactoryMCP2AIGatewaySKU": "true",
    "enableContainerApps": "true", "enableAIFoundry": "true", "deleteAllServicesForProject": "false",
    "deleteAllForProject": "false", "dev_test_prod_sub_id": SUB, "tenantId": TENANT, "dev_test_prod": "dev",
    "project_number_000": "001", "admin_location": "swedencentral", "admin_aifactoryPrefixRG": "aif-",
    "projectPrefix": "esml-", "admin_locationSuffix": "sdc", "admin_aifactorySuffixRG": "-001", "projectSuffix": "-rg",
    "aifactoryMcpImage": f"acrcommon.azurecr.io/aifactory-mcp@sha256:{DIGEST}",
    "aifactoryMcpApiImage": f"acrcommon.azurecr.io/aifactory-api@sha256:{DIGEST}",
    "aifactoryMcpEntraAppId": APP_REG, "aiGatewaySkuOutboundSubnetId": SUBNET,
}


def guid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-{n:012d}"


class FakeArm:
    """Records calls; GET of unknown IDs is 404; never supports DELETE."""

    def __init__(self, resources=None):
        self.calls: list[tuple] = []
        self.counter = 10
        self.resources = {key.lower(): value for key, value in (resources or {}).items()}
        self.lists = {
            f"{GROUP_ID}/resources": [
                {"id": ACCOUNT_ID, "name": "aifacct001", "type": "Microsoft.CognitiveServices/accounts", "kind": "AIServices", "location": "swedencentral"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Search/searchServices/srch001", "name": "srch001", "type": "Microsoft.Search/searchServices"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Storage/storageAccounts/saprj0011001", "name": "saprj0011001", "type": "Microsoft.Storage/storageAccounts"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Storage/storageAccounts/saprj0012001", "name": "saprj0012001", "type": "Microsoft.Storage/storageAccounts"},
                {"id": ENV_ID, "name": "aca-env-prj001", "type": "Microsoft.App/managedEnvironments"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Insights/components/appi001", "name": "appi001", "type": "Microsoft.Insights/components"},
            ],
            f"{ACCOUNT_ID}/projects": [{"id": PROJECT_ID, "name": "aifacct001/aifproj001"}],
            f"{ACCOUNT_ID}/deployments": [
                {"name": "gpt-chat", "sku": {"name": "DataZoneStandard", "capacity": 20},
                 "properties": {"provisioningState": "Succeeded", "model": {"format": "OpenAI", "name": "gpt-x", "version": "1"}}},
                {"name": "text-embedding-3-large", "properties": {"provisioningState": "Succeeded",
                                                                  "model": {"format": "OpenAI", "name": "text-embedding-3-large"}}},
            ],
            "/providers/Microsoft.ContainerRegistry/registries": [
                {"id": REGISTRY_ID, "properties": {"loginServer": "acrcommon.azurecr.io"}}],
            "/providers/Microsoft.Authorization/roleAssignments": [],
            f"{PE_ID}/privateDnsZoneGroups": [
                {"name": "default", "properties": {"privateDnsZoneConfigs": [
                    {"name": "aca", "properties": {"privateDnsZoneId": ACA_ZONE}}]}}],
        }
        self.add(PROJECT_ID, {"id": PROJECT_ID, "name": "aifacct001/aifproj001", "identity": {"principalId": guid(1)},
                              "properties": {"endpoints": {"AI Foundry API": "https://aifacct001.services.ai.azure.com/api/projects/aifproj001"}}})
        self.add(f"{PROJECT_ID}/providers/Microsoft.ManagedIdentity/identities/default", {"properties": {"clientId": guid(2)}})
        self.add(ENV_ID, {"id": ENV_ID, "properties": {
            "vnetConfiguration": {"internal": True}, "defaultDomain": "internal.swedencentral.azurecontainerapps.io",
            "privateEndpointConnections": [{"properties": {
                "privateEndpoint": {"id": PE_ID}, "privateLinkServiceConnectionState": {"status": "Approved"}}}]}})

    def add(self, resource_id, body):
        self.resources[resource_id.lower()] = body

    def _write(self, method, resource_id, body):
        current = copy.deepcopy(self.resources.get(resource_id.lower(), {}))
        stored = {**current, **copy.deepcopy(body or {}), "id": resource_id}
        if method == "PATCH":
            stored["properties"] = {**current.get("properties", {}), **body.get("properties", {})}
        if "/Microsoft.ApiManagement/service/" in resource_id and "/workspaces/" not in resource_id:
            self.counter += 1
            stored.setdefault("identity", {})["principalId"] = current.get("identity", {}).get("principalId", guid(self.counter))
            stored["properties"] = {**stored.get("properties", {}), "provisioningState": "Succeeded",
                                    "gatewayUrl": "https://aigw.azure-api.net"}
            self.add(f"{resource_id}/providers/Microsoft.ManagedIdentity/identities/default",
                     {"properties": {"clientId": guid(self.counter + 50)}})
        if "/userAssignedIdentities/" in resource_id:
            stored["properties"] = {"principalId": guid(90), "clientId": guid(91)}
        if "/containerApps/" in resource_id:
            name = resource_id.rsplit("/", 1)[1]
            stored["properties"]["provisioningState"] = "Succeeded"
            stored["properties"]["configuration"]["ingress"]["fqdn"] = f"{name}.internal.swedencentral.azurecontainerapps.io"
        self.add(resource_id, stored)
        return copy.deepcopy(stored)

    def arm(self, method, resource_id, body=None, api_version="x"):
        self.calls.append((method, resource_id, api_version, copy.deepcopy(body)))
        if method == "GET":
            if resource_id.lower() in self.resources:
                return copy.deepcopy(self.resources[resource_id.lower()])
            raise AzureError(404, method, resource_id, "NotFound")
        if method == "POST" and resource_id.endswith("/listSecrets"):
            return {"value": [{"name": gw.API_KEY_SECRET, "value": "existing-api-key"}]}
        if method in {"PUT", "PATCH"}:
            return self._write(method, resource_id, body)
        raise AssertionError(f"Unexpected {method}")

    def request(self, method, url, body=None, *, audience=ARM, headers=None):
        resource_id = url[len(ARM):].split("?", 1)[0]
        self.calls.append((method, resource_id, "headers", copy.deepcopy(headers), copy.deepcopy(body)))
        if method != "PUT":
            raise AssertionError(f"Unexpected {method}")
        return self._write(method, resource_id, body)

    def pages(self, url, *, audience=ARM, field="value"):
        self.calls.append(("LIST", url))
        path = url[len(ARM):].split("?", 1)[0]
        for key, items in self.lists.items():
            if path.endswith(key) or path == key:
                return copy.deepcopy(items)
        return []

    def writes(self):
        return [call for call in self.calls if call[0] in {"PUT", "PATCH", "POST", "DELETE"}]

    def creates(self):
        return [call for call in self.calls if len(call) == 5 and call[2] == "headers"]

    def body(self, suffix):
        matches = [call for call in self.calls if call[0] == "PUT" and call[1].endswith(suffix)]
        assert matches, f"no PUT for {suffix}"
        return matches[-1][-1]


def request(**changes):
    return gw.IntegrationRequest.from_values({**VALUES, **changes})


def with_classic_apim(arm, resource_id=CLASSIC_APIM, principal=guid(40), client=guid(41)):
    """An existing classic APIM gateway (any non-AIGateway SKU) with a system-assigned identity."""
    arm.add(resource_id, {"id": resource_id, "sku": {"name": "Developer"},
                          "identity": {"type": "SystemAssigned", "principalId": principal}, "properties": {}})
    arm.add(f"{resource_id}/providers/Microsoft.ManagedIdentity/identities/default", {"properties": {"clientId": client}})
    return arm


def mcp_env(arm):
    app = arm.body("/containerApps/aifactory-mcp-p001-dev")
    return {item["name"]: item for item in app["properties"]["template"]["containers"][0]["env"]}


def caller_pairs(env):
    auth = json.loads(env["AIFACTORY_APPLICATION_AUTH_JSON"]["value"])
    return [(item["object_id"], item["client_id"]) for item in auth["identities"]]


MCP_ONLY = {"enableAIGatewaySKU": "false", "addAIFactoryMCP2AIGatewaySKU": "false", "aiGatewaySkuOutboundSubnetId": ""}
ADOPT = {**MCP_ONLY, "aifactoryMcpContainerAppResourceId": ADOPTED_APP, "aifactoryMcpImage": "", "aifactoryMcpApiImage": ""}
APIM_VARS = {"addAIFactoryMCP2APIM": "true", "apimGatewayResourceGroup": "common-rg", "apimGatewayServiceName": "apim-classic"}
OPERATOR = guid(30)
ADOPTED_IMAGE = f"acrcommon.azurecr.io/aifactory-mcp@sha256:{'b' * 64}"


def identity_entry(object_id, client_id):
    return {"object_id": object_id, "client_id": client_id, "scope_keys": [gw.SCOPE_KEY],
            "allowed_tools": list(gw.READ_ONLY_TOOLS)}


def with_adopted_app(arm, callers=((guid(1), guid(2)),), audience=APP_REG, tags=None, containers=None):
    """A Container App deployed outside this integration (for example by mcp/deploy/rollout.py)."""
    settings = {"scopes": {gw.SCOPE_KEY: {}}, "factory": {"writes_enabled": False},
                "auth": {"client_id": audience, "audience": audience, "grants": [
                    {"object_id": object_id, "scopes": [gw.SCOPE_KEY], "permissions": ["factory.read"]}
                    for object_id in (OPERATOR, *(pair[0] for pair in callers))]}}
    auth = {"audience": audience, "required_role": gw.REQUIRED_ROLE,
            "identities": [identity_entry(*pair) for pair in callers]}
    arm.add(ADOPTED_APP, {
        "id": ADOPTED_APP, "location": "swedencentral",
        "tags": {"aifactory.managed_by": "aifactory-mcp", "app-onboard-skill": "true"} if tags is None else tags,
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {"mi-aifactory-mcp-dev": {}}},
        "properties": {
            "environmentId": ENV_ID, "provisioningState": "Succeeded",
            "latestRevisionName": "aifactory-mcp-project001-dev--apim-caller-20261019",
            "configuration": {"ingress": {"external": True,
                                          "fqdn": "aifactory-mcp-project001-dev.internal.swedencentral.azurecontainerapps.io"},
                              "secrets": [{"name": gw.API_KEY_SECRET, "keyVaultUrl": "https://kv.vault.azure.net/secrets/key"}]},
            "template": {"revisionSuffix": "apim-caller-20261019", "scale": {"minReplicas": 1, "maxReplicas": 1},
                         "containers": containers if containers is not None else [
                             {"name": "mcp", "image": ADOPTED_IMAGE, "env": [
                                 {"name": "AIFACTORY_PILOT_CONFIG_JSON", "value": json.dumps(settings)},
                                 {"name": "AIFACTORY_APPLICATION_AUTH_JSON", "value": json.dumps(auth)},
                                 {"name": "AIFACTORY_API_KEY", "secretRef": gw.API_KEY_SECRET}]},
                             {"name": "factory-api", "image": ADOPTED_IMAGE.replace("mcp@", "api@"),
                              "env": [{"name": "AIFACTORY_API_KEY", "secretRef": gw.API_KEY_SECRET}]}]},
        }})
    return arm


def adopted_env(arm):
    patches = [call for call in arm.calls if call[0] == "PATCH" and call[1] == ADOPTED_APP]
    assert len(patches) == 1, f"expected one PATCH of the adopted app, got {len(patches)}"
    template = patches[0][3]["properties"]["template"]
    return template, {item["name"]: item for item in template["containers"][0]["env"]}


class DecisionTests(unittest.TestCase):
    def test_values_derive_the_project_group_and_unset_macros_are_false(self):
        parsed = request()
        self.assertEqual(GROUP, parsed.resource_group)
        self.assertEqual("aif", parsed.factory_key)
        unset = gw.IntegrationRequest.from_values({**VALUES, "enableAIFactoryMCP": "$(enableAIFactoryMCP)",
                                                   "enableAIGatewaySKU": None, "addAIFactoryMCP2AIGatewaySKU": ""})
        self.assertFalse(unset.any_enabled)
        for value in ("True", "1", "yes"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "true or false"):
                request(enableAIGatewaySKU=value)

    def test_disabled_non_dev_and_invalid_requests_never_touch_azure(self):
        arm = FakeArm()
        integration = gw.McpGatewayIntegration(arm)
        off = dict.fromkeys(gw.FLAGS, "false")
        self.assertEqual("skipped", integration.run(request(**off), apply=True)["mode"])
        self.assertEqual("skipped", integration.run(request(dev_test_prod="test"), apply=True)["mode"])
        for changes, message in (
            ({"project_number_000": "002"}, "project001"),
            ({"enableAIFactoryMCP": "false"}, "addAIFactoryMCP2AIGatewaySKU requires"),
            ({"enableContainerApps": "false"}, "enableContainerApps=true and enableAIFoundry=true"),
            ({"enableAIFoundry": "false"}, "enableAIGatewaySKU requires enableAIFoundry"),
            ({"aifactoryMcpImage": "acrcommon.azurecr.io/aifactory-mcp:latest"}, "digest-pinned"),
            ({"aifactoryMcpEntraAppId": ""}, "aifactoryMcpEntraAppId"),
            ({"deleteAllForProject": "true"}, "conflict"),
            ({"aiGatewaySkuResourceId": "/subscriptions/x/gateway"}, "aiGatewaySkuResourceId"),
            ({"aiGatewaySkuOutboundSubnetId": "not-a-subnet-resource-id"}, "aiGatewaySkuOutboundSubnetId"),
            ({"aifactoryMcpClassicApimResourceIds": f"{CLASSIC_APIM},/subscriptions/x/apim"},
             "aifactoryMcpClassicApimResourceIds must"),
            ({"aifactoryMcpClassicApimResourceIds": CLASSIC_APIM, "enableAIFactoryMCP": "false",
              "addAIFactoryMCP2AIGatewaySKU": "false"}, "aifactoryMcpClassicApimResourceIds requires enableAIFactoryMCP"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                integration.run(request(**changes), apply=True)
        self.assertEqual([], arm.calls)

    def test_classic_apim_caller_ids_are_trimmed_and_deduplicated(self):
        parsed = request(aifactoryMcpClassicApimResourceIds=(
            f" {CLASSIC_APIM} ,,{CLASSIC_APIM.replace('common-rg', 'COMMON-RG')}, {OTHER_APIM}"))
        self.assertEqual((CLASSIC_APIM, OTHER_APIM), parsed.classic_apim_ids)
        self.assertEqual((), request().classic_apim_ids)
        self.assertEqual((), request(aifactoryMcpClassicApimResourceIds="$(aifactoryMcpClassicApimResourceIds)").classic_apim_ids)

    def test_the_ai_gateway_pipeline_apim_joins_the_callers_automatically(self):
        parsed = request(**APIM_VARS, aifactoryMcpClassicApimResourceIds=f"{OTHER_APIM},{CLASSIC_APIM}")
        self.assertEqual(CLASSIC_APIM, parsed.apim_id)
        self.assertEqual((OTHER_APIM, CLASSIC_APIM), parsed.apim_caller_ids)
        other_sub = "44444444-4444-4444-8444-444444444444"
        self.assertTrue(request(**APIM_VARS, apimGatewaySubscriptionId=other_sub).apim_id.startswith(f"/subscriptions/{other_sub}/"))
        self.assertEqual((CLASSIC_APIM,), request(**{**APIM_VARS, "addAIFactoryMCP2APIM": "false"},
                                                  aifactoryMcpClassicApimResourceIds=CLASSIC_APIM).apim_caller_ids)

    def test_invalid_adoption_and_apim_requests_never_touch_azure(self):
        arm = FakeArm()
        integration = gw.McpGatewayIntegration(arm)
        for changes, message in (
            ({**ADOPT, "aifactoryMcpContainerAppResourceId": "/subscriptions/x/containerApps/app"},
             "aifactoryMcpContainerAppResourceId must"),
            ({**ADOPT, "aifactoryMcpContainerAppResourceId": ADOPTED_APP.replace(GROUP, "other-rg")},
             "project resource group"),
            ({"aifactoryMcpContainerAppResourceId": ADOPTED_APP, "enableAIFactoryMCP": "false",
              "addAIFactoryMCP2AIGatewaySKU": "false"}, "aifactoryMcpContainerAppResourceId requires enableAIFactoryMCP"),
            ({**APIM_VARS, "enableAIFactoryMCP": "false", "addAIFactoryMCP2AIGatewaySKU": "false"},
             "addAIFactoryMCP2APIM requires enableAIFactoryMCP"),
            ({**MCP_ONLY, **APIM_VARS, "apimGatewayServiceName": ""}, "apimGatewayResourceGroup and apimGatewayServiceName"),
            ({**MCP_ONLY, **APIM_VARS, "apimGatewaySubscriptionId": "nope"}, "apimGatewaySubscriptionId must be a GUID"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                integration.run(request(**changes), apply=True)
        self.assertEqual([], arm.calls)
        self.assertTrue(gw.decide(request(**ADOPT)).act, "an adopted app needs no image variables")


class IntegrationTests(unittest.TestCase):
    def test_gateway_only_needs_foundry_but_not_mcp_runtime_dependencies(self):
        arm = FakeArm()
        arm.lists[f"{GROUP_ID}/resources"] = arm.lists[f"{GROUP_ID}/resources"][:1]
        arm.lists[f"{ACCOUNT_ID}/projects"] = []
        arm.lists[f"{ACCOUNT_ID}/deployments"] = []

        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(
            enableAIFactoryMCP="false", addAIFactoryMCP2AIGatewaySKU="false",
            enableContainerApps="false", aifactoryMcpImage="", aifactoryMcpApiImage="",
            aifactoryMcpEntraAppId="", aiGatewaySkuOutboundSubnetId=""), apply=True)

        self.assertEqual("apply", result["mode"])
        self.assertEqual([ACCOUNT_ID], arm.body("/modelProviders/aifacct001")["properties"]["foundry"]["resourceIds"])
        self.assertFalse(any("/containerApps/" in call[1] or "/projects?" in call[1] for call in arm.calls))

    def test_plan_reads_only_and_lists_every_intended_owned_write(self):
        arm = FakeArm()
        result = gw.McpGatewayIntegration(arm).run(request(), apply=False)
        self.assertEqual([], arm.writes())
        actions = {item["action"] for item in result["actions"]}
        self.assertLessEqual({"create"}, actions)
        self.assertFalse(result["mutations"])

    def test_apply_creates_owned_gateway_private_mcp_and_exact_read_only_registration(self):
        arm = FakeArm()
        tokens = iter(["generated-secret-value"])
        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: next(tokens)).run(request(), apply=True)
        self.assertFalse([call for call in arm.calls if call[0] == "DELETE"])
        gateway_put = arm.creates()[0]
        self.assertEqual({"If-None-Match": "*"}, gateway_put[3])
        self.assertEqual({"name": "AIGateway", "capacity": 1}, gateway_put[4]["sku"])
        self.assertEqual(gw.OWNER_VALUE, gateway_put[4]["tags"][gw.OWNER_TAG])
        self.assertEqual({"virtualNetworkType": "External", "virtualNetworkConfiguration": {"subnetResourceId": SUBNET}},
                         gateway_put[4]["properties"])
        roles = [call[3]["properties"]["roleDefinitionId"].rsplit("/", 1)[1] for call in arm.calls
                 if call[0] == "PUT" and "/roleAssignments/" in call[1]]
        self.assertEqual(sorted([gw.AZURE_AI_USER_ROLE, gw.ACR_PULL_ROLE]), sorted(roles))
        provider = arm.body("/modelProviders/aifacct001")["properties"]
        self.assertEqual("Foundry", provider["kind"])
        self.assertEqual([ACCOUNT_ID], provider["foundry"]["resourceIds"])
        app = arm.body("/containerApps/aifactory-mcp-p001-dev")
        self.assertEqual(ENV_ID, app["properties"]["environmentId"])
        self.assertTrue(app["properties"]["configuration"]["ingress"]["external"])
        containers = {item["name"]: item for item in app["properties"]["template"]["containers"]}
        self.assertEqual({"mcp", "factory-api"}, set(containers))
        env = {item["name"]: item for item in containers["mcp"]["env"]}
        self.assertEqual({"secretRef": gw.API_KEY_SECRET}, {k: v for k, v in env["AIFACTORY_API_KEY"].items() if k != "name"})
        auth = json.loads(env["AIFACTORY_APPLICATION_AUTH_JSON"]["value"])
        self.assertEqual(APP_REG, auth["audience"])
        self.assertEqual([{"object_id": guid(1), "client_id": guid(2)}, {"object_id": guid(11), "client_id": guid(61)}],
                         [{key: item[key] for key in ("object_id", "client_id")} for item in auth["identities"]])
        self.assertTrue(all(item["allowed_tools"] == list(gw.READ_ONLY_TOOLS) for item in auth["identities"]))
        settings = json.loads(env["AIFACTORY_PILOT_CONFIG_JSON"]["value"])
        self.assertFalse(settings["factory"]["writes_enabled"])
        self.assertEqual("https://srch001.search.windows.net", settings["azure"]["search_endpoint"])
        self.assertEqual("https://saprj0012001.blob.core.windows.net", settings["azure"]["storage_endpoint"])
        server = arm.body("/toolServers/aifactory-mcp-p001-dev")["properties"]
        self.assertEqual(["aifactory_factory_health", "aifactory_factory_capabilities", "aifactory_factory_skills"],
                         server["allowList"])
        endpoint = server["endpoints"][0]
        self.assertEqual({"type": "managedIdentity", "managedIdentity": {"resource": APP_REG}}, endpoint["credentials"])
        self.assertEqual("https://aifactory-mcp-p001-dev.internal.swedencentral.azurecontainerapps.io/mcp",
                         endpoint["mcp"]["url"])
        self.assertIn(gw.MARKER, server["description"])
        self.assertNotIn("generated-secret-value", json.dumps(result))
        self.assertTrue(result["prerequisites"])
        self.assertTrue(result["outputs"]["tool_server_url"].endswith("/default/toolservers/aifactory-mcp-p001-dev/mcp"))

    def test_rerun_is_idempotent_reuses_the_api_key_and_never_recreates_roles(self):
        arm = FakeArm()
        integration = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "first-key")
        integration.run(request(), apply=True)
        assignments = [{"properties": {"roleDefinitionId": call[3]["properties"]["roleDefinitionId"]}}
                       for call in arm.calls if call[0] == "PUT" and "/roleAssignments/" in call[1]]
        arm.lists["/providers/Microsoft.Authorization/roleAssignments"] = assignments
        arm.calls.clear()
        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "must-not-be-used").run(request(), apply=True)
        self.assertFalse([call for call in arm.calls if call[0] == "PUT" and "/roleAssignments/" in call[1]])
        self.assertFalse(arm.creates(), "gateway must not be re-created")
        app = arm.body("/containerApps/aifactory-mcp-p001-dev")
        self.assertEqual("existing-api-key", app["properties"]["configuration"]["secrets"][0]["value"])
        unchanged = {item["resource"].rsplit("/", 1)[-1] for item in result["actions"] if item["action"] == "unchanged"}
        self.assertLessEqual({"aifacct001", "aifactory-mcp-p001-dev"}, unchanged)

    def test_foreign_resources_with_derived_names_are_refused(self):
        names = gw.names(request())
        for resource_id, body, message in (
            (names["gateway_id"], {"sku": {"name": "AIGateway"}, "identity": {"principalId": guid(5)}}, "not owned"),
            (names["app_id"], {"tags": {"owner": "someone"}}, "not owned"),
        ):
            with self.subTest(resource=resource_id.rsplit("/", 1)[1]):
                arm = FakeArm({resource_id: body})
                with self.assertRaisesRegex(ValueError, message):
                    gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(), apply=True)
                self.assertFalse([call for call in arm.calls if call[0] in {"PUT", "PATCH"} and call[1] == resource_id])

    def test_adopted_gateway_is_never_modified_and_needs_outbound_integration_for_private_mcp(self):
        gateway_id = f"/subscriptions/{SUB}/resourceGroups/shared/providers/Microsoft.ApiManagement/service/shared-aigw"
        arm = FakeArm({gateway_id: {"id": gateway_id, "sku": {"name": "AIGateway"}, "identity": {"principalId": guid(7)},
                                    "properties": {"gatewayUrl": "https://shared-aigw.azure-api.net"}},
                       f"{gateway_id}/providers/Microsoft.ManagedIdentity/identities/default": {"properties": {"clientId": guid(8)}}})
        with self.assertRaisesRegex(ValueError, "outbound VNet integration"):
            gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(aiGatewaySkuResourceId=gateway_id), apply=True)
        self.assertFalse([call for call in arm.calls if call[0] in {"PUT", "PATCH"} and call[1] == gateway_id])

    def test_registration_without_subnet_fails_before_any_write(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                arm = FakeArm()
                with self.assertRaisesRegex(ValueError, "aiGatewaySkuOutboundSubnetId"):
                    gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(
                        request(aiGatewaySkuOutboundSubnetId=""), apply=apply)
                self.assertEqual([], arm.writes())
                self.assertTrue(any(call[0] == "GET" and call[1] == gw.names(request())["gateway_id"]
                                    for call in arm.calls))

    def test_implicit_owned_gateway_reuses_existing_subnet_when_optional_parameters_are_omitted(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                arm = FakeArm()
                integration = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "key")
                integration.run(request(), apply=True)
                gateway_id = gw.names(request())["gateway_id"]
                arm.calls.clear()

                result = integration.run(request(aiGatewaySkuResourceId="", aiGatewaySkuOutboundSubnetId=""),
                                         apply=apply)

                self.assertEqual("apply" if apply else "plan", result["mode"])
                self.assertEqual(gateway_id, result["outputs"]["gateway_id"])
                self.assertTrue(any(call[0] == "GET" and call[1] == gateway_id for call in arm.calls))
                self.assertFalse(any(call[0] in {"PUT", "PATCH"} and call[1] == gateway_id for call in arm.calls))
                self.assertEqual(SUBNET, arm.resources[gateway_id.lower()]["properties"]
                                 ["virtualNetworkConfiguration"]["subnetResourceId"])
                if not apply:
                    self.assertEqual([], arm.writes())

    def test_implicit_owned_gateway_without_any_subnet_fails_before_writes(self):
        gateway_id = gw.names(request())["gateway_id"]
        for apply in (False, True):
            with self.subTest(apply=apply):
                arm = FakeArm({gateway_id: {
                    "id": gateway_id, "sku": {"name": "AIGateway"}, "tags": dict(gw.OWNER_TAGS),
                    "identity": {"principalId": guid(7)}, "properties": {},
                }})
                with self.assertRaisesRegex(ValueError, "outbound VNet integration"):
                    gw.McpGatewayIntegration(arm).run(request(aiGatewaySkuOutboundSubnetId=""), apply=apply)
                self.assertEqual([], arm.writes())

    def test_adopted_gateway_can_use_its_existing_subnet_without_a_parameter(self):
        arm = FakeArm()
        integration = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "key")
        integration.run(request(), apply=True)
        arm.calls.clear()

        result = integration.run(request(aiGatewaySkuResourceId=gw.names(request())["gateway_id"],
                                         aiGatewaySkuOutboundSubnetId=""), apply=False)

        self.assertEqual("plan", result["mode"])
        self.assertEqual([], arm.writes())
        self.assertTrue(any("/toolServers/" in item["resource"] for item in result["actions"]))

    def test_gateway_only_plan_has_no_mcp_dependency_reads_or_writes(self):
        arm = FakeArm()
        arm.lists[f"{GROUP_ID}/resources"] = arm.lists[f"{GROUP_ID}/resources"][:1]
        arm.lists[f"{ACCOUNT_ID}/projects"] = []
        arm.lists[f"{ACCOUNT_ID}/deployments"] = []

        result = gw.McpGatewayIntegration(arm).run(request(
            enableAIFactoryMCP="false", addAIFactoryMCP2AIGatewaySKU="false",
            enableContainerApps="false", aiGatewaySkuOutboundSubnetId=""), apply=False)

        self.assertEqual("plan", result["mode"])
        self.assertEqual([], arm.writes())
        self.assertFalse(any("/containerApps/" in call[1] or "/projects?" in call[1] or "/deployments?" in call[1]
                             for call in arm.calls))

    def test_existing_gateway_with_a_different_requested_subnet_is_refused_before_writes(self):
        gateway_id = gw.names(request())["gateway_id"]
        arm = FakeArm({gateway_id: {
            "id": gateway_id, "sku": {"name": "AIGateway"}, "tags": dict(gw.OWNER_TAGS),
            "identity": {"principalId": guid(7)},
            "properties": {"virtualNetworkConfiguration": {"subnetResourceId": SUBNET + "-other"}},
        }})
        arm.add(f"{gateway_id}/providers/Microsoft.ManagedIdentity/identities/default",
                {"properties": {"clientId": guid(8)}})
        with self.assertRaisesRegex(ValueError, "different.*subnet"):
            gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(), apply=True)
        self.assertEqual([], arm.writes())

    def test_plan_can_register_after_planned_owned_gateway_subnet_configuration(self):
        gateway_id = gw.names(request())["gateway_id"]
        arm = FakeArm({gateway_id: {
            "id": gateway_id, "sku": {"name": "AIGateway"}, "tags": dict(gw.OWNER_TAGS),
            "identity": {"principalId": guid(7)}, "properties": {},
        }})
        result = gw.McpGatewayIntegration(arm).run(request(), apply=False)
        self.assertEqual([], arm.writes())
        self.assertIn({"resource": f"{gateway_id} outbound subnet", "action": "update"}, result["actions"])
        self.assertTrue(any("/toolServers/" in item["resource"] for item in result["actions"]))

    def test_registration_comparison_checks_every_governed_endpoint_field(self):
        desired = gw.tool_server_body(APP_REG, "https://mcp.example/mcp")
        endpoint = desired["properties"]["endpoints"][0]
        for field, value in (
            ("type", "rest"),
            ("blocked", ["aifactory_factory_health"]),
            ("endpoints", [endpoint, {**endpoint, "namespace": "unexpected"}]),
            ("endpoints", [{**endpoint, "kind": "rest"}]),
            ("endpoints", [{**endpoint, "required": False}]),
        ):
            with self.subTest(field=field, value=value):
                current = copy.deepcopy(desired)
                current["properties"][field] = value
                self.assertFalse(gw._same_server(current, desired))
        self.assertTrue(gw._same_server({**desired, "id": "server-metadata"}, desired))

    def test_owned_registration_with_blocked_read_tool_is_reconciled(self):
        arm = FakeArm()
        integration = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "key")
        integration.run(request(), apply=True)
        server_id = f"{gw.names(request())['gateway_id']}/workspaces/default/toolServers/aifactory-mcp-p001-dev"
        arm.resources[server_id.lower()]["properties"]["blocked"] = ["aifactory_factory_health"]
        arm.calls.clear()

        integration.run(request(), apply=True)

        self.assertEqual([], arm.body("/toolServers/aifactory-mcp-p001-dev")["properties"]["blocked"])

    def test_classic_apim_identities_join_the_mcp_callers_without_touching_the_apim(self):
        values = {**MCP_ONLY, "aifactoryMcpClassicApimResourceIds": CLASSIC_APIM}
        for apply in (False, True):
            with self.subTest(apply=apply):
                arm = with_classic_apim(FakeArm())
                result = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(
                    request(**values), apply=apply)
                self.assertFalse([call for call in arm.writes() if call[1].lower().startswith(CLASSIC_APIM.lower())])
                self.assertIn(CLASSIC_APIM, {item["resource"] for item in result["actions"]})
                self.assertTrue(any(gw.REQUIRED_ROLE in item and APP_REG in item and guid(40) in item
                                    for item in result["prerequisites"]))
                if not apply:
                    self.assertEqual([], arm.writes())
                    continue
                env = mcp_env(arm)
                self.assertEqual([(guid(1), guid(2)), (guid(40), guid(41))], caller_pairs(env))
                settings = json.loads(env["AIFACTORY_PILOT_CONFIG_JSON"]["value"])
                self.assertEqual([guid(1), guid(40)], [grant["object_id"] for grant in settings["auth"]["grants"]])

    def test_classic_apim_callers_follow_the_native_gateway_without_duplicates(self):
        native = gw.names(request())["gateway_id"]
        arm = with_classic_apim(with_classic_apim(FakeArm()), OTHER_APIM, principal=guid(42), client=guid(43))
        gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(request(
            aifactoryMcpClassicApimResourceIds=f"{CLASSIC_APIM},{native},{OTHER_APIM}"), apply=True)
        self.assertEqual([(guid(1), guid(2)), (guid(11), guid(61)), (guid(40), guid(41)), (guid(42), guid(43))],
                         caller_pairs(mcp_env(arm)))

    def test_classic_apim_sharing_an_identity_with_another_caller_is_listed_once(self):
        arm = with_classic_apim(with_classic_apim(FakeArm()), OTHER_APIM)
        gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(request(
            **MCP_ONLY, aifactoryMcpClassicApimResourceIds=f"{CLASSIC_APIM},{OTHER_APIM}"), apply=True)
        self.assertEqual([(guid(1), guid(2)), (guid(40), guid(41))], caller_pairs(mcp_env(arm)))

    def test_missing_or_identity_less_classic_apim_fails_before_any_write(self):
        for label, arm, message in (
            ("missing", FakeArm(), "aifactoryMcpClassicApimResourceIds.*does not exist"),
            ("no identity", FakeArm({CLASSIC_APIM: {"id": CLASSIC_APIM, "identity": {"type": "None"}}}),
             "system-assigned managed identity"),
        ):
            for apply in (False, True):
                with self.subTest(case=label, apply=apply):
                    arm.calls.clear()
                    with self.assertRaisesRegex(ValueError, message):
                        gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(
                            request(aifactoryMcpClassicApimResourceIds=CLASSIC_APIM), apply=apply)
                    self.assertEqual([], arm.writes())

    def test_public_container_apps_environment_is_refused(self):
        arm = FakeArm()
        arm.add(ENV_ID, {"id": ENV_ID, "properties": {"vnetConfiguration": {"internal": False}, "defaultDomain": "x"}})
        with self.assertRaisesRegex(ValueError, "internal"):
            gw.McpGatewayIntegration(arm).run(request(), apply=False)

    def test_runtime_settings_satisfy_the_mcp_image_settings_model(self):
        agent = ROOT / "40-aifactory-agent"
        if not importlib.util.find_spec("pydantic"):
            self.skipTest("pydantic is required to validate the image settings model")
        sys.path.insert(0, str(agent))
        try:
            from aifactory_agent.config import Settings
        finally:
            sys.path.remove(str(agent))
        arm = FakeArm()
        gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(request(), apply=True)
        env = {item["name"]: item for item in arm.body("/containerApps/aifactory-mcp-p001-dev")
               ["properties"]["template"]["containers"][0]["env"]}
        settings = Settings.model_validate(json.loads(env["AIFACTORY_PILOT_CONFIG_JSON"]["value"]))
        self.assertEqual(["project001-dev"], list(settings.scopes))


class AdoptionTests(unittest.TestCase):
    """aifactoryMcpContainerAppResourceId: an MCP app deployed outside the pipeline gains callers, nothing else."""

    def test_adopted_app_keeps_its_runtime_and_only_gains_the_missing_callers(self):
        arm = with_classic_apim(with_adopted_app(FakeArm()))
        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "never").run(
            request(**ADOPT, aifactoryMcpClassicApimResourceIds=CLASSIC_APIM), apply=True)

        self.assertEqual([("PATCH", ADOPTED_APP)], [call[:2] for call in arm.writes()])
        template, env = adopted_env(arm)
        self.assertEqual({"properties"}, set(arm.writes()[0][3]), "tags, identity, ingress and secrets stay untouched")
        self.assertEqual([ADOPTED_IMAGE, ADOPTED_IMAGE.replace("mcp@", "api@")],
                         [item["image"] for item in template["containers"]])
        self.assertEqual({"secretRef": gw.API_KEY_SECRET}, {k: v for k, v in env["AIFACTORY_API_KEY"].items() if k != "name"})
        self.assertNotEqual("apim-caller-20261019", template["revisionSuffix"], "a reused suffix would be rejected")
        self.assertEqual([(guid(1), guid(2)), (guid(40), guid(41))], caller_pairs(env))
        settings = json.loads(env["AIFACTORY_PILOT_CONFIG_JSON"]["value"])
        self.assertEqual([OPERATOR, guid(1), guid(40)], [grant["object_id"] for grant in settings["auth"]["grants"]])
        self.assertEqual("https://aifactory-mcp-project001-dev.internal.swedencentral.azurecontainerapps.io/mcp",
                         result["outputs"]["mcp_url"])
        self.assertFalse([call for call in arm.calls if "/containerApps/aifactory-mcp-p001-dev" in call[1]
                          or "/userAssignedIdentities/" in call[1] or "/roleAssignments" in call[1]])

    def test_adopted_app_with_every_caller_is_unchanged_and_plan_never_writes(self):
        arm = with_classic_apim(with_adopted_app(FakeArm(), callers=((guid(1), guid(2)), (guid(40), guid(41)))))
        values = {**ADOPT, "aifactoryMcpClassicApimResourceIds": CLASSIC_APIM}
        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(**values), apply=True)
        self.assertEqual([], arm.writes())
        self.assertIn({"resource": ADOPTED_APP, "action": "unchanged", "detail": "adopted; every caller is present"},
                      result["actions"])

        arm = with_classic_apim(with_adopted_app(FakeArm()))
        result = gw.McpGatewayIntegration(arm).run(request(**values), apply=False)
        self.assertEqual([], arm.writes())
        planned = next(item for item in result["actions"] if item["resource"] == ADOPTED_APP)
        self.assertEqual("update", planned["action"])
        self.assertIn(guid(40), planned["detail"])

    def test_adopted_app_feeds_the_native_gateway_registration(self):
        arm = with_adopted_app(FakeArm())
        gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(
            request(aifactoryMcpContainerAppResourceId=ADOPTED_APP), apply=True)
        _, env = adopted_env(arm)
        self.assertEqual([(guid(1), guid(2)), (guid(11), guid(61))], caller_pairs(env))
        endpoint = arm.body("/toolServers/aifactory-mcp-p001-dev")["properties"]["endpoints"][0]
        self.assertEqual("https://aifactory-mcp-project001-dev.internal.swedencentral.azurecontainerapps.io/mcp",
                         endpoint["mcp"]["url"])

    def test_unsafe_adoptions_are_refused_before_any_write(self):
        other_env = f"{GROUP_ID}/providers/Microsoft.App/managedEnvironments/aca-env-other"
        for label, arm, message in (
            ("missing", FakeArm(), "aifactoryMcpContainerAppResourceId.*does not exist"),
            ("pipeline-managed", with_adopted_app(FakeArm(), tags=dict(gw.OWNER_TAGS)), "pipeline-managed"),
            ("other audience", with_adopted_app(FakeArm(), audience=guid(99)), "audience"),
            ("no mcp container", with_adopted_app(FakeArm(), containers=[{"name": "web", "image": "x", "env": []}]),
             "'mcp' container"),
        ):
            for apply in (False, True):
                with self.subTest(case=label, apply=apply):
                    arm.calls.clear()
                    with self.assertRaisesRegex(ValueError, message):
                        gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(**ADOPT), apply=apply)
                    self.assertEqual([], arm.writes())
        arm = with_adopted_app(FakeArm())
        arm.lists[f"{GROUP_ID}/resources"].append({"id": other_env, "name": "aca-env-other", "type": "Microsoft.App/managedEnvironments"})
        gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(**ADOPT), apply=False)
        self.assertTrue(any(call[0] == "GET" and call[1] == ENV_ID for call in arm.calls),
                        "the adopted app selects its own environment")
        with self.assertRaisesRegex(ValueError, "runs in environment aca-env-prj001"):
            gw.McpGatewayIntegration(arm).run(request(**ADOPT, aifactoryMcpContainerAppsEnvironment="aca-env-other"),
                                              apply=False)


class AppRolePrerequisiteTests(unittest.TestCase):
    """Pipelines never write Graph: each caller gets the exact admin-run app-role deployment command."""

    def command(self, principal):
        return (f"az deployment group create --subscription {SUB} --resource-group {GROUP} "
                f"--name aifactory-mcp-app-role-{principal[:8]} --template-file {gw.APP_ROLE_TEMPLATE} "
                f"--parameters mcpEntraAppId={APP_REG} callerPrincipalId={principal}")

    def test_every_mcp_caller_gets_its_exact_admin_command(self):
        arm = with_classic_apim(FakeArm())
        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(
            request(aifactoryMcpClassicApimResourceIds=CLASSIC_APIM), apply=True)
        for principal in (guid(1), guid(40), guid(11)):  # Foundry project, classic APIM, native AI Gateway
            with self.subTest(principal=principal):
                self.assertTrue(any(self.command(principal) in item for item in result["prerequisites"]),
                                result["prerequisites"])
        self.assertTrue((ROOT.parents[1] / gw.APP_ROLE_TEMPLATE).is_file())

    def test_the_apim_step_prints_the_command_for_the_apim_identity(self):
        arm = with_classic_apim(FakeArm())
        gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(
            request(**MCP_ONLY, **APIM_VARS), apply=True)
        result = gw.McpGatewayIntegration(arm).apim_parameters(request(**MCP_ONLY, **APIM_VARS))
        self.assertTrue(any(self.command(guid(40)) in item for item in result["prerequisites"]))

    def test_the_template_is_admin_run_only_and_assigns_the_role_by_value(self):
        template = (ROOT.parents[1] / gw.APP_ROLE_TEMPLATE).read_text(encoding="utf-8")
        for fragment in ("extension 'br:mcr.microsoft.com/bicep/extensions/microsoftgraph/v1.0:1.0.0'",
                         "'Microsoft.Graph/servicePrincipals@v1.0' existing", "appId: mcpEntraAppId",
                         "'Microsoft.Graph/appRoleAssignedTo@v1.0'", "role.value == appRoleValue",
                         "principalId: callerPrincipalId", "resourceId: mcpServicePrincipal.id",
                         f"param appRoleValue string = '{gw.REQUIRED_ROLE}'"):
            self.assertIn(fragment, template)
        pipelines = ROOT.parents[1] / "environment_setup/aifactory/bicep/copy_to_local_settings"
        name = Path(gw.APP_ROLE_TEMPLATE).name
        self.assertFalse([path for path in pipelines.rglob("*.y*ml") if name in path.read_text(encoding="utf-8")],
                         "no pipeline may deploy the Graph template")


class PrivateNetworkTests(unittest.TestCase):
    """APIM and the AI Gateway reach the MCP through its environment's private endpoint and private DNS."""

    def test_environment_without_an_approved_private_endpoint_is_refused_before_writes(self):
        for connections in ([], [{"properties": {"privateEndpoint": {"id": PE_ID},
                                                  "privateLinkServiceConnectionState": {"status": "Pending"}}}]):
            with self.subTest(connections=connections):
                arm = FakeArm()
                arm.resources[ENV_ID.lower()]["properties"]["privateEndpointConnections"] = connections
                with self.assertRaisesRegex(ValueError, "approved private endpoint"):
                    gw.McpGatewayIntegration(arm).run(request(**MCP_ONLY), apply=True)
                self.assertEqual([], arm.writes())

    def test_private_dns_registration_is_reported_and_its_absence_is_a_prerequisite(self):
        arm = FakeArm()
        result = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(request(**MCP_ONLY), apply=True)
        self.assertEqual(PE_ID, result["outputs"]["mcp_private_endpoint_id"])
        self.assertFalse(any("private DNS" in item for item in result["prerequisites"]))

        arm = FakeArm()
        arm.lists[f"{PE_ID}/privateDnsZoneGroups"] = []
        result = gw.McpGatewayIntegration(arm).run(request(**MCP_ONLY), apply=False)
        self.assertTrue(any("private DNS" in item and "privatelink.swedencentral.azurecontainerapps.io" in item
                            for item in result["prerequisites"]))


class ApimMcpTests(unittest.TestCase):
    """addAIFactoryMCP2APIM: the AI gateway pipeline publishes the MCP on the classic APIM (GET only here)."""

    def values(self, **changes):
        return request(**{**MCP_ONLY, **APIM_VARS, **changes})

    def owned_mcp(self, arm, callers):
        """The pipeline-managed MCP app as step 71 leaves it."""
        integration = gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k")
        integration.run(self.values(**({} if callers else {"addAIFactoryMCP2APIM": "false"})), apply=True)
        arm.calls.clear()
        return integration

    def test_disabled_and_non_dev_runs_are_skipped_without_azure(self):
        arm = FakeArm()
        integration = gw.McpGatewayIntegration(arm)
        self.assertEqual("skipped", integration.apim_parameters(self.values(addAIFactoryMCP2APIM="false"))["mode"])
        self.assertEqual("skipped", integration.apim_parameters(self.values(dev_test_prod="prod"))["mode"])
        with self.assertRaisesRegex(ValueError, "addAIFactoryMCP2APIM requires enableAIFactoryMCP"):
            integration.apim_parameters(self.values(enableAIFactoryMCP="false"))
        self.assertEqual([], arm.calls)

    def test_parameters_point_the_apim_api_at_the_mcp_that_accepts_the_apim_identity(self):
        arm = with_classic_apim(FakeArm())
        integration = self.owned_mcp(arm, callers=True)
        result = integration.apim_parameters(self.values())
        self.assertEqual([], arm.writes())
        self.assertEqual("parameters", result["mode"])
        parameters = {key: value["value"] for key, value in result["parameters"]["parameters"].items()}
        self.assertEqual({
            "apimServiceName": "apim-classic", "mcpServerName": gw.APIM_MCP_SERVER,
            "displayName": "Enterprise Scale AI Factory",
            "mcpServerBaseUrl": "https://aifactory-mcp-p001-dev.internal.swedencentral.azurecontainerapps.io",
            "mcpEntraAppId": APP_REG, "clientSubscriptionName": gw.APIM_MCP_CLIENT_SUBSCRIPTION,
            "clientSubscriptionState": "active",
        }, {key: value for key, value in parameters.items() if key != "mcpDescription"})
        self.assertIn("Read-only", parameters["mcpDescription"])
        self.assertEqual(CLASSIC_APIM, result["apim_id"])
        # The pipeline deploys to exactly the APIM the launcher resolved (no second derivation in bash).
        self.assertEqual((SUB, "common-rg"), (result["apim_subscription_id"], result["apim_resource_group"]))

    def test_a_suspended_client_subscription_stays_suspended(self):
        arm = with_classic_apim(FakeArm())
        integration = self.owned_mcp(arm, callers=True)
        arm.add(f"{CLASSIC_APIM}/subscriptions/{gw.APIM_MCP_CLIENT_SUBSCRIPTION}", {"properties": {"state": "suspended"}})
        result = integration.apim_parameters(self.values())
        self.assertEqual("suspended", result["parameters"]["parameters"]["clientSubscriptionState"]["value"])
        self.assertEqual([], arm.writes())
        self.assertTrue(any(gw.REQUIRED_ROLE in item and guid(40) in item for item in result["prerequisites"]))

    def test_adopted_mcp_is_published_by_its_own_origin(self):
        arm = with_classic_apim(with_adopted_app(FakeArm(), callers=((guid(1), guid(2)), (guid(40), guid(41)))))
        result = gw.McpGatewayIntegration(arm).apim_parameters(self.values(**ADOPT))
        self.assertEqual("https://aifactory-mcp-project001-dev.internal.swedencentral.azurecontainerapps.io",
                         result["parameters"]["parameters"]["mcpServerBaseUrl"]["value"])

    def test_missing_mcp_or_not_yet_admitted_apim_fail_with_the_next_step(self):
        arm = with_classic_apim(FakeArm())
        with self.assertRaisesRegex(ValueError, "does not exist yet.*project001 Dev pipeline"):
            gw.McpGatewayIntegration(arm).apim_parameters(self.values())
        integration = self.owned_mcp(arm, callers=False)
        with self.assertRaisesRegex(ValueError, "does not accept.*addAIFactoryMCP2APIM"):
            integration.apim_parameters(self.values())
        self.assertEqual([], arm.writes())
        with self.assertRaisesRegex(ValueError, "apim-missing does not exist"):
            gw.McpGatewayIntegration(FakeArm()).apim_parameters(self.values(apimGatewayServiceName="apim-missing"))


class LauncherTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("mcp_gateway_launcher", ROOT / "45-aifactory-mcp-gateway" / "deploy.py")
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)

    def args(self, command="apply", apply=True, output=None):
        return type("Args", (), {"command": command, "apply": apply, "output": output})()

    def test_apim_parameters_writes_the_module_parameters_file_and_skips_quietly(self):
        import tempfile
        arm = with_classic_apim(FakeArm())
        gw.McpGatewayIntegration(arm, sleep=lambda _: None, token=lambda: "k").run(request(**MCP_ONLY, **APIM_VARS), apply=True)
        sessions = []

        def factory(*values):
            sessions.append(values)
            return arm

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "apim-mcp.parameters.json"
            # The MCP always lives in project001, whichever project the shared variables name.
            environ = {**VALUES, **MCP_ONLY, **APIM_VARS, "project_number_000": "004"}
            result = self.launcher.run(self.args("apim-parameters", False, str(output)), environ, factory)
            self.assertEqual("parameters", result["mode"])
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("apim-classic", written["parameters"]["apimServiceName"]["value"])
            self.assertEqual([(SUB, TENANT)], sessions)

            skipped = Path(folder) / "skipped.json"
            result = self.launcher.run(self.args("apim-parameters", False, str(skipped)),
                                       {**environ, "addAIFactoryMCP2APIM": "false"}, factory)
            self.assertEqual("skipped", result["mode"])
            self.assertFalse(skipped.exists())
            self.assertEqual(1, len(sessions))

    def test_disabled_and_invalid_runs_stop_before_any_session(self):
        sessions = []
        factory = lambda *values: sessions.append(values)  # noqa: E731
        environ = {**VALUES, **dict.fromkeys(gw.FLAGS, "false")}
        self.assertEqual("skipped", self.launcher.run(self.args(), environ, factory)["mode"])
        with self.assertRaisesRegex(ValueError, "project001"):
            self.launcher.run(self.args(), {**VALUES, "project_number_000": "007"}, factory)
        with self.assertRaisesRegex(ValueError, "--apply"):
            self.launcher.run(self.args(apply=False), VALUES, factory)
        self.assertEqual("validated", self.launcher.run(self.args("validate", False), VALUES, factory)["mode"])
        self.assertEqual([], sessions)

    def test_every_pipeline_input_is_read_by_name(self):
        self.assertEqual(set(VALUES) | {"aifactoryMcpContainerAppsEnvironment", "aiGatewaySkuResourceId", "projectResourceGroup",
                                        "aifactoryMcpClassicApimResourceIds", "aifactoryMcpContainerAppResourceId",
                                        "addAIFactoryMCP2APIM", "apimGatewaySubscriptionId", "apimGatewayResourceGroup",
                                        "apimGatewayServiceName"},
                         set(self.launcher.INPUTS))


if __name__ == "__main__":
    unittest.main()
