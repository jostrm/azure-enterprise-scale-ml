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
REGISTRY_ID = f"/subscriptions/{SUB}/resourceGroups/common-rg/providers/Microsoft.ContainerRegistry/registries/acrcommon"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/hub/providers/Microsoft.Network/virtualNetworks/hub/subnets/snet-aigw"
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
        }
        self.add(PROJECT_ID, {"id": PROJECT_ID, "name": "aifacct001/aifproj001", "identity": {"principalId": guid(1)},
                              "properties": {"endpoints": {"AI Foundry API": "https://aifacct001.services.ai.azure.com/api/projects/aifproj001"}}})
        self.add(f"{PROJECT_ID}/providers/Microsoft.ManagedIdentity/identities/default", {"properties": {"clientId": guid(2)}})
        self.add(ENV_ID, {"id": ENV_ID, "properties": {"vnetConfiguration": {"internal": True},
                                                       "defaultDomain": "internal.swedencentral.azurecontainerapps.io"}})

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
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                integration.run(request(**changes), apply=True)
        self.assertEqual([], arm.calls)


class IntegrationTests(unittest.TestCase):
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

    def test_registration_without_subnet_fails_before_registering(self):
        arm = FakeArm()
        with self.assertRaisesRegex(ValueError, "aiGatewaySkuOutboundSubnetId"):
            gw.McpGatewayIntegration(arm, sleep=lambda _: None).run(request(aiGatewaySkuOutboundSubnetId=""), apply=True)
        self.assertFalse([call for call in arm.calls if "/toolServers/" in call[1] and call[0] == "PUT"])

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


class LauncherTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("mcp_gateway_launcher", ROOT / "45-aifactory-mcp-gateway" / "deploy.py")
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)

    def args(self, command="apply", apply=True):
        return type("Args", (), {"command": command, "apply": apply})()

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
        self.assertEqual(set(VALUES) | {"aifactoryMcpContainerAppsEnvironment", "aiGatewaySkuResourceId", "projectResourceGroup"},
                         set(self.launcher.INPUTS))


if __name__ == "__main__":
    unittest.main()
