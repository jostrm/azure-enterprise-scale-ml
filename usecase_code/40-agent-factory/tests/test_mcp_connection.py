from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid5

from agent_factory.azure import ARM, AzureError
from agent_factory.config import Target
from agent_factory import mcp_connection as connection
from agent_factory.mcp_control import build_mcp_plan


TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
CALLER = "33333333-3333-3333-3333-333333333333"
HOSTING = "44444444-4444-4444-4444-444444444444"
CLIENT = "55555555-5555-5555-5555-555555555555"
APP_OBJECT = "66666666-6666-6666-6666-666666666666"
API_SP = "77777777-7777-7777-7777-777777777777"
IMAGE = "mcr.microsoft.com/azure-sdk/azure-mcp@sha256:" + "a" * 64
ARGS = [
    "--transport", "http", "--outgoing-auth-strategy", "UseHostingEnvironmentIdentity",
    "--mode", "all", "--read-only", "--tool", "group_resource_list",
]


def fixture():
    target = Target(
        tenant_id=TENANT, subscription_id=SUB, resource_group="project",
        common_resource_group="common", account_name="foundry", project_name="project-one",
        project_endpoint="https://foundry.services.ai.azure.com/api/projects/project-one",
        location="swedencentral", model_deployment="model", embedding_deployment="embedding",
        search_name="search", storage_name="storage", identity_id="/unused-ingestion-uami",
        identity_client_id=API_SP,
    )
    vnet = f"/subscriptions/{SUB}/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/shared"
    plan = build_mcp_plan(target, {
        "name": "mcp-project", "image": IMAGE,
        "infrastructure_subnet_id": vnet + "/subnets/mcp",
        "private_endpoint_subnet_id": vnet + "/subnets/endpoints",
        "private_dns_zone_id": (
            f"/subscriptions/{SUB}/resourceGroups/dns/providers/Microsoft.Network/"
            "privateDnsZones/privatelink.swedencentral.azurecontainerapps.io"
        ),
    })
    identity = {
        "ready": True, "applied": True, "tenant_id": TENANT, "subscription_id": SUB,
        "project_resource_id": target.project_id, "project_principal_id": CALLER,
        "application_object_id": APP_OBJECT, "application_client_id": CLIENT,
        "service_principal_id": API_SP, "app_role_id": plan["app_role_id"], "audience": f"api://{CLIENT}",
    }
    return target, plan, identity


class FakeAzure:
    def __init__(self, target, plan):
        self.subscription_id = SUB
        self.tenant_id = TENANT
        self.calls = []
        self.role_error = None
        self.create_error = None
        self.persist_create = True
        self.app_id = target.group_id + "/providers/Microsoft.App/containerApps/" + plan["name"]
        self.environment_id = target.group_id + "/providers/Microsoft.App/managedEnvironments/" + plan["environment_name"]
        self.endpoint_id = target.group_id + "/providers/Microsoft.Network/privateEndpoints/" + plan["name"] + "-pe"
        self.connection_id = target.project_id + "/connections/aif-azure-mcp"
        role_id = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"
        guid = uuid5(UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830"), "-".join((target.group_id, self.app_id, role_id)))
        self.assignment_id = target.group_id + "/providers/Microsoft.Authorization/roleAssignments/" + str(guid)
        domain = "private-123.swedencentral.azurecontainerapps.io"
        self.url = f"https://{plan['name']}.{domain}"
        env = {
            "AZURE_TOKEN_CREDENTIALS": "managedidentitycredential",
            "AZURE_MCP_INCLUDE_PRODUCTION_CREDENTIALS": "true",
            "AZURE_MCP_COLLECT_TELEMETRY": "false",
            "AzureAd__Instance": "https://login.microsoftonline.com/",
            "AzureAd__TenantId": TENANT, "AzureAd__ClientId": CLIENT,
            "ASPNETCORE_ENVIRONMENT": "Production", "DOTNET_ENVIRONMENT": "Production",
            "ASPNETCORE_URLS": "http://0.0.0.0:8080",
            "AZURE_MCP_DANGEROUSLY_DISABLE_HTTPS_REDIRECTION": "true",
            "Logging__LogLevel__Default": "Warning",
            "Logging__LogLevel__Azure": "Warning", "Logging__LogLevel__Microsoft": "Warning",
        }
        self.resources = {
            target.project_id: {
                "id": target.project_id, "location": target.location,
                "identity": {"type": "SystemAssigned", "principalId": CALLER, "tenantId": TENANT},
            },
            self.app_id: {
                "id": self.app_id, "tags": deepcopy(plan["tags"]), "location": target.location,
                "identity": {"type": "SystemAssigned", "principalId": HOSTING, "tenantId": TENANT},
                "properties": {
                    "provisioningState": "Succeeded", "environmentId": self.environment_id,
                    "latestRevisionName": "mcp-project--abc", "latestReadyRevisionName": "mcp-project--abc",
                    "configuration": {
                        "activeRevisionsMode": "Single",
                        "ingress": {
                            "external": True, "allowInsecure": False, "targetPort": 8080, "transport": "http",
                            "fqdn": f"{plan['name']}.{domain}", "traffic": [{"latestRevision": True, "weight": 100}],
                        },
                    },
                    "template": {"containers": [{
                        "name": "azure-mcp", "image": IMAGE, "command": [], "args": list(ARGS),
                        "env": [{"name": key, "value": value} for key, value in env.items()],
                    }]},
                },
            },
            self.environment_id: {
                "id": self.environment_id, "tags": deepcopy(plan["tags"]), "location": target.location,
                "properties": {
                    "provisioningState": "Succeeded", "publicNetworkAccess": "Disabled", "defaultDomain": domain,
                    "vnetConfiguration": {"internal": True, "infrastructureSubnetId": plan["infrastructure_subnet_id"]},
                },
            },
            self.endpoint_id: {
                "id": self.endpoint_id, "tags": deepcopy(plan["tags"]), "location": target.location,
                "properties": {
                    "provisioningState": "Succeeded", "subnet": {"id": plan["private_endpoint_subnet_id"]},
                    "privateLinkServiceConnections": [{
                        "name": plan["name"] + "-environment",
                        "properties": {
                            "provisioningState": "Succeeded", "privateLinkServiceId": self.environment_id,
                            "groupIds": ["managedEnvironments"],
                            "privateLinkServiceConnectionState": {"status": "Approved"},
                        },
                    }],
                },
            },
            self.assignment_id: {
                "id": self.assignment_id,
                "properties": {
                    "roleDefinitionId": role_id, "scope": target.group_id,
                    "principalId": HOSTING, "principalType": "ServicePrincipal",
                },
            },
        }
        self.role_path = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments"
        self.role_pages = [{"value": [deepcopy(self.resources[self.assignment_id])]}]

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def arm(self, method, resource_id, body=None, *, api_version):
        self.calls.append((method, resource_id, deepcopy(body), {"api-version": api_version}))
        if method != "GET":
            raise AssertionError("Unconditional ARM writes are forbidden")
        if resource_id not in self.resources:
            raise AzureError(404, method, resource_id, "NotFound")
        return deepcopy(self.resources[resource_id])

    def request(self, method, url, body=None, *, audience, headers=None):
        self.calls.append((method, url, deepcopy(body), deepcopy(headers)))
        parsed = urlsplit(url)
        if audience != ARM or parsed.netloc != "management.azure.com":
            raise AssertionError("Operator credentials must never go to MCP or an unexpected origin")
        if method == "GET" and parsed.path == self.role_path:
            if self.role_error:
                raise AzureError(self.role_error, method, url, "Audit denied")
            query = parse_qs(parsed.query)
            if query.get("$filter") != [f"principalId eq '{HOSTING}'"]:
                raise AssertionError("The RBAC audit must filter the exact hosting principal at subscription scope")
            page = int(query.get("$skipToken", ["0"])[0])
            return deepcopy(self.role_pages[page])
        if method == "PUT" and parsed.path == self.connection_id:
            if headers != {"If-None-Match": "*"}:
                raise AssertionError("Connection create must protect against concurrent ownership collisions")
            if self.create_error:
                raise AzureError(self.create_error, method, url, "Concurrent writer")
            if self.persist_create:
                self.resources[self.connection_id] = {"id": self.connection_id, **deepcopy(body)}
            return {"id": self.connection_id, **deepcopy(body)}
        raise AssertionError(f"Unexpected request: {method} {url}")


class ConnectionTests(unittest.TestCase):
    def test_arm_region_display_names_match_the_selected_canonical_region(self):
        self.azure.resources[self.azure.environment_id]["location"] = "Sweden Central"
        self.azure.resources[self.azure.app_id]["location"] = "Sweden Central"
        self.azure.resources[self.azure.app_id]["properties"]["configuration"]["ingress"]["transport"] = "Http"
        self.assertTrue(self.configure()["infrastructure_verified"])

    def setUp(self):
        self.target, self.plan, self.identity = fixture()
        self.azure = FakeAzure(self.target, self.plan)
        self.probe = patch.object(connection, "verify_private_mcp_endpoint").start()
        self.addCleanup(patch.stopall)

    def configure(self, **kwargs):
        return connection.configure_mcp_connection(self.azure, self.target, self.plan, self.identity, **kwargs)

    def assert_rejected(self, exception=RuntimeError):
        with self.assertRaises(exception):
            self.configure(apply=True)
        self.assertEqual([], self.azure.writes)
        self.probe.assert_not_called()

    def test_read_only_default_needs_no_deployment_journal(self):
        result = self.configure()
        self.assertEqual([], self.azure.writes)
        self.assertNotIn(self.azure.connection_id, self.azure.resources)
        self.assertEqual(self.target.project_id, result["project_resource_id"])
        self.assertEqual(self.target.subscription_id, result["subscription_id"])
        self.assertEqual(self.target.resource_group, result["resource_group"])
        self.assertTrue(result["infrastructure_verified"])
        self.assertFalse(result["tool_call_verified"])
        self.assertEqual({
            "type": "mcp", "server_label": "azure-project-inventory", "server_url": self.azure.url,
            "allowed_tools": ["group_resource_list"], "require_approval": "never",
            "project_connection_id": "aif-azure-mcp",
        }, result["tool"])
        self.probe.assert_called_once_with(self.azure.url)
        self.assertTrue(all("deployments" not in call[1] for call in self.azure.calls))
        self.assertIn(self.azure.assignment_id, [call[1] for call in self.azure.calls])

    def test_apply_creates_conditionally_then_reads_persisted_connection(self):
        result = self.configure(apply=True)
        self.assertEqual(self.azure.connection_id, result["connection_id"])
        self.assertEqual(1, len(self.azure.writes))
        method, url, body, headers = self.azure.writes[0]
        self.assertEqual("PUT", method)
        self.assertEqual([connection.CONNECTION_API], parse_qs(urlsplit(url).query)["api-version"])
        self.assertEqual({"If-None-Match": "*"}, headers)
        properties = body["properties"]
        self.assertEqual("ProjectManagedIdentity", properties["authType"])
        self.assertEqual("RemoteTool", properties["category"])
        self.assertEqual(f"api://{CLIENT}", properties["audience"])
        self.assertIs(False, properties["isSharedToAll"])
        self.assertEqual(self.target.project_id, properties["metadata"]["aifactory.project_id"])
        self.assertEqual("GET", self.azure.calls[-1][0])
        self.assertEqual(self.azure.connection_id, self.azure.calls[-1][1])
        self.assertFalse(result["tool_call_verified"])

    def test_existing_exact_connection_is_idempotent_and_accepts_readonly_extras(self):
        self.configure(apply=True)
        self.azure.calls.clear()
        stored = self.azure.resources[self.azure.connection_id]
        stored["systemData"] = {"createdBy": "operator"}
        stored["properties"]["metadata"]["serviceGeneratedInfo"] = "permitted"
        stored["properties"].update({"credentials": None, "sharedUserList": [], "provisioningState": "Succeeded"})
        self.configure(apply=True)
        self.configure(apply=False)
        self.assertEqual([], self.azure.writes)

    def test_normalized_arm_ids_and_service_alias_are_accepted(self):
        properties = self.azure.resources[self.azure.app_id]["properties"]
        properties["managedEnvironmentId"] = properties.pop("environmentId").upper()
        for resource in self.azure.resources.values():
            resource["id"] = resource["id"].upper()
        assignment = self.azure.resources[self.azure.assignment_id]["properties"]
        assignment["scope"] = assignment["scope"].upper()
        assignment["roleDefinitionId"] = assignment["roleDefinitionId"].upper()
        self.azure.role_pages[0]["value"] = [deepcopy(self.azure.resources[self.azure.assignment_id])]
        self.configure()
        self.assertEqual([], self.azure.writes)

    def test_existing_connection_collisions_are_never_replaced(self):
        cases = [
            ("authType", "ApiKey"), ("category", "AzureBlob"), ("target", "https://other.example/mcp"),
            ("audience", "https://management.azure.com/"), ("isSharedToAll", True),
            ("isSharedToAll", 0), ("metadata", {"ApiType": "Azure"}),
            ("credentials", {"key": "must-not-use"}), ("sharedUserList", ["foreign-project"]),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.azure = FakeAzure(self.target, self.plan)
                self.probe.reset_mock()
                body = connection._connection_body(self.target, self.azure.url, self.identity)
                body["properties"][key] = value
                self.azure.resources[self.azure.connection_id] = {"id": self.azure.connection_id, **body}
                self.assert_rejected()

    def test_create_race_and_ambiguous_create_never_overwrite(self):
        for status in (409, 412, 403):
            with self.subTest(status=status):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.create_error = status
                with self.assertRaises(AzureError):
                    self.configure(apply=True)
                self.assertEqual(1, len(self.azure.writes))
        self.azure = FakeAzure(self.target, self.plan)
        self.azure.persist_create = False
        with self.assertRaises(AzureError):
            self.configure(apply=True)
        self.assertEqual(1, len(self.azure.writes))

    def test_wrong_project_prepared_identity_and_session_rejected_before_reads(self):
        for key, value in [
            ("ready", False), ("project_resource_id", self.target.project_id + "-other"),
            ("tenant_id", SUB), ("subscription_id", TENANT), ("app_role_id", HOSTING),
            ("audience", "https://management.azure.com/"), ("application_client_id", "not-guid"),
        ]:
            with self.subTest(key=key):
                identity = {**self.identity, key: value}
                with self.assertRaises(ValueError):
                    connection.configure_mcp_connection(self.azure, self.target, self.plan, identity, apply=True)
                self.assertEqual([], self.azure.calls)
        with self.assertRaises(ValueError):
            connection.configure_mcp_connection(
                self.azure, replace(self.target, project_name="other"), self.plan, self.identity, apply=True,
            )
        self.azure.subscription_id = TENANT
        self.assert_rejected(ValueError)

    def test_apply_requires_boolean(self):
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.configure(apply=value)
        self.assertEqual([], self.azure.calls)

    def test_live_project_mi_must_match_prepared_caller(self):
        for key, value in [
            ("principalId", HOSTING), ("tenantId", SUB), ("type", "UserAssigned"),
            ("userAssignedIdentities", {"/some/uami": {}}),
        ]:
            with self.subTest(key=key):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.resources[self.target.project_id]["identity"][key] = value
                self.assert_rejected()

    def test_owned_resources_cannot_be_foreign_or_unready(self):
        for kind in ("app_id", "environment_id", "endpoint_id"):
            for change in ("owner", "project", "region", "id", "unready"):
                with self.subTest(kind=kind, change=change):
                    self.azure = FakeAzure(self.target, self.plan)
                    resource = self.azure.resources[getattr(self.azure, kind)]
                    if change == "owner":
                        resource["tags"]["aifactory.managed_by"] = "foreign"
                    elif change == "project":
                        resource["tags"]["aifactory.project_id"] = self.target.project_id + "-other"
                    elif change == "unready":
                        resource["properties"]["provisioningState"] = "Updating"
                    else:
                        resource["location" if change == "region" else "id"] = "wrong"
                    self.assert_rejected()

    def test_image_and_exact_arguments_cannot_expand_or_disable_auth(self):
        cases = [
            ("image", IMAGE.replace("a" * 64, "b" * 64)),
            ("image", "mcr.microsoft.com/azure-sdk/azure-mcp:2.0.5"),
            ("command", ["sh", "-c"]), ("args", ARGS + ["--disable-proxy-tools"]),
            ("args", [arg for arg in ARGS if arg != "--read-only"]),
            ("args", ARGS + ["--dangerously-disable-auth"]),
            ("args", ARGS[:-1] + ["group_delete"]),
            ("args", [arg.replace("UseHostingEnvironmentIdentity", "UseOnBehalfOf") for arg in ARGS]),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.resources[self.azure.app_id]["properties"]["template"]["containers"][0][key] = value
                self.assert_rejected()

    def test_env_is_exact_secretless_inbound_and_outbound_contract(self):
        cases = [
            ("AZURE_TOKEN_CREDENTIALS", "AzureCliCredential"), ("AzureAd__TenantId", SUB),
            ("AzureAd__ClientId", HOSTING), ("AzureAd__Instance", "https://evil.example/"),
            ("AZURE_CLIENT_SECRET", "secret"), ("AZURE_CLIENT_ID", HOSTING),
            ("AZURE_MCP_DANGEROUSLY_DISABLE_AUTH", "false"), ("HTTPS_PROXY", "https://proxy.example"),
            ("DOTNET_ENVIRONMENT", "Development"), ("AZURE_MCP_INCLUDE_PRODUCTION_CREDENTIALS", "false"),
        ]
        for name, value in cases:
            with self.subTest(name=name):
                self.azure = FakeAzure(self.target, self.plan)
                env = self.azure.resources[self.azure.app_id]["properties"]["template"]["containers"][0]["env"]
                env[:] = [item for item in env if item["name"] != name]
                env.append({"name": name, "value": value})
                self.assert_rejected()
        for change in ("duplicate", "secretRef", "missing"):
            with self.subTest(change=change):
                self.azure = FakeAzure(self.target, self.plan)
                env = self.azure.resources[self.azure.app_id]["properties"]["template"]["containers"][0]["env"]
                if change == "duplicate":
                    env[-1] = deepcopy(env[0])
                elif change == "secretRef":
                    env[0]["secretRef"] = "credential"
                else:
                    env.pop()
                self.assert_rejected()

    def test_hosting_identity_must_be_system_assigned_only(self):
        for key, value in [
            ("type", "SystemAssigned, UserAssigned"), ("type", "UserAssigned"),
            ("userAssignedIdentities", {"/some/uami": {}}), ("tenantId", SUB),
            ("principalId", CALLER), ("principalId", API_SP),
        ]:
            with self.subTest(key=key, value=value):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.resources[self.azure.app_id]["identity"][key] = value
                self.assert_rejected()

    def test_configuration_sidecars_secrets_tls_and_stale_revision_are_rejected(self):
        cases = [
            (("configuration", "activeRevisionsMode"), "Multiple"),
            (("configuration", "secrets"), [{"name": "secret", "value": "unsafe"}]),
            (("configuration", "registries"), [{"identity": "/some/uami"}]),
            (("configuration", "dapr"), {"enabled": True}),
            (("configuration", "ingress", "allowInsecure"), True),
            (("configuration", "ingress", "transport"), "tcp"),
            (("configuration", "ingress", "targetPort"), 80),
            (("configuration", "ingress", "customDomains"), [{"name": "proxy.example"}]),
            (("configuration", "ingress", "traffic"), [{"revisionName": "old", "weight": 100}]),
            (("template", "initContainers"), [{"name": "proxy"}]),
            (("template", "volumes"), [{"name": "override"}]),
            (("latestReadyRevisionName",), "old"),
            (("environmentId",), "/other/environment"),
            (("managedEnvironmentId",), "/conflicting/environment"),
        ]
        for keys, value in cases:
            with self.subTest(keys=keys):
                self.azure = FakeAzure(self.target, self.plan)
                node = self.azure.resources[self.azure.app_id]["properties"]
                for key in keys[:-1]:
                    node = node[key]
                node[keys[-1]] = value
                self.assert_rejected()

    def test_environment_requires_internal_disabled_and_expected_subnet(self):
        cases = [
            ("publicNetworkAccess", "Enabled"),
            ("vnetConfiguration", {"internal": False, "infrastructureSubnetId": self.plan["infrastructure_subnet_id"]}),
            ("vnetConfiguration", {"internal": True, "infrastructureSubnetId": self.plan["private_endpoint_subnet_id"]}),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.resources[self.azure.environment_id]["properties"][key] = value
                self.assert_rejected()

    def test_private_endpoint_must_be_separate_approved_owned_environment(self):
        cases = [
            ("subnet", {"id": self.plan["infrastructure_subnet_id"]}),
            ("manualPrivateLinkServiceConnections", [{"name": "manual"}]),
            ("privateLinkServiceId", self.azure.app_id), ("groupIds", ["containerApps"]),
            ("privateLinkServiceConnectionState", {"status": "Pending"}), ("provisioningState", "Updating"),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                self.azure = FakeAzure(self.target, self.plan)
                node = self.azure.resources[self.azure.endpoint_id]["properties"]
                if key not in ("subnet", "manualPrivateLinkServiceConnections"):
                    node = node["privateLinkServiceConnections"][0]["properties"]
                node[key] = value
                self.assert_rejected()

    def test_fqdn_cannot_escape_exact_app_environment_boundary(self):
        for fqdn in [
            "evil.example", "mcp-project.evil.azurecontainerapps.io",
            "other.private-123.swedencentral.azurecontainerapps.io",
            "mcp-project.private-123.swedencentral.azurecontainerapps.io.evil.example",
            "mcp-project.private-123.swedencentral.azurecontainerapps.io/path",
            "mcp-project.private-123.swedencentral.azurecontainerapps.io:443",
        ]:
            with self.subTest(fqdn=fqdn):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.resources[self.azure.app_id]["properties"]["configuration"]["ingress"]["fqdn"] = fqdn
                self.assert_rejected()
        self.azure = FakeAzure(self.target, self.plan)
        self.azure.resources[self.azure.environment_id]["properties"]["defaultDomain"] = "private-123.eastus.azurecontainerapps.io"
        self.assert_rejected()

    def test_role_audit_rejects_missing_extra_inherited_and_foreign_permissions(self):
        for scope in ["/", f"/subscriptions/{SUB}", "/providers/Microsoft.Management/managementGroups/root",
                      self.target.group_id, self.target.group_id + "-other"]:
            with self.subTest(scope=scope):
                self.azure = FakeAzure(self.target, self.plan)
                extra = deepcopy(self.azure.role_pages[0]["value"][0])
                extra["id"] += "-extra"
                extra["properties"]["scope"] = scope
                self.azure.role_pages[0]["value"].append(extra)
                self.assert_rejected()
        self.azure = FakeAzure(self.target, self.plan)
        self.azure.role_pages = [{"value": []}]
        self.assert_rejected()

    def test_role_and_exact_bicep_assignment_must_match_on_both_reads(self):
        for source in ("list", "resource"):
            for key, value in [
                ("scope", f"/subscriptions/{SUB}"), ("principalId", CALLER),
                ("roleDefinitionId", "/providers/Microsoft.Authorization/roleDefinitions/owner"),
                ("principalType", "User"), ("condition", "unexpected"),
                ("delegatedManagedIdentityResourceId", "/uami"),
            ]:
                with self.subTest(source=source, key=key):
                    self.azure = FakeAzure(self.target, self.plan)
                    node = (self.azure.role_pages[0]["value"][0] if source == "list"
                            else self.azure.resources[self.azure.assignment_id])
                    node["properties"][key] = value
                    self.assert_rejected()
        self.azure = FakeAzure(self.target, self.plan)
        self.azure.role_pages[0]["value"][0]["id"] += "-not-bicep-owned"
        self.assert_rejected()

    def test_role_pagination_audits_all_pages_with_no_credential_forwarding(self):
        url = ARM + self.azure.role_path + "?" + urlencode({
            "api-version": connection.ROLE_API, "$filter": f"principalId eq '{HOSTING}'", "$skipToken": "1",
        })
        self.azure.role_pages[0]["nextLink"] = url
        self.azure.role_pages.append({"value": [deepcopy(self.azure.role_pages[0]["value"][0])]})
        self.assert_rejected()
        for next_link in [
            url.replace("management.azure.com", "evil.example"),
            url.replace(self.azure.role_path, "/other/path"),
            url.replace("principalId", "other"), url + "#fragment",
        ]:
            with self.subTest(next_link=next_link):
                self.azure = FakeAzure(self.target, self.plan)
                self.azure.role_pages[0]["nextLink"] = next_link
                self.assert_rejected()
                self.assertEqual(1, len([call for call in self.azure.calls if call[1].startswith(ARM)]))

    def test_role_pagination_can_finish_after_empty_page_and_rejects_loops(self):
        url = ARM + self.azure.role_path + "?" + urlencode({
            "api-version": connection.ROLE_API, "$filter": f"principalId eq '{HOSTING}'", "$skipToken": "1",
        })
        assignment = deepcopy(self.azure.role_pages[0]["value"][0])
        self.azure.role_pages = [{"value": [], "nextLink": url}, {"value": [assignment]}]
        self.configure()
        self.assertEqual([], self.azure.writes)
        self.azure.role_pages[1]["nextLink"] = url
        with self.assertRaisesRegex(RuntimeError, "pagination"):
            self.configure(apply=True)
        self.assertEqual([], self.azure.writes)

    def test_role_audit_denial_cannot_fall_back_to_resource_group(self):
        self.azure.role_error = 403
        with self.assertRaisesRegex(RuntimeError, "resource-group-only"):
            self.configure(apply=True)
        self.assertEqual([], self.azure.writes)
        self.probe.assert_not_called()

    def test_network_failure_prevents_connection_write(self):
        self.probe.side_effect = RuntimeError("Connect VPN and private DNS")
        with self.assertRaisesRegex(RuntimeError, "VPN"):
            self.configure(apply=True)
        self.assertEqual([], self.azure.writes)


class ToolVerificationTests(unittest.TestCase):
    def test_actual_scoped_inventory_is_required(self):
        target, _, _ = fixture()
        call = SimpleNamespace(
            type="mcp_call", name="group_resource_list", server_label="azure-project-inventory", error=None,
            arguments=json.dumps({"subscription": target.subscription_id, "resource-group": target.resource_group}),
            output=json.dumps({"status": 200, "results": {"resources": [
                {"id": target.group_id + "/providers/Microsoft.Search/searchServices/search"},
            ]}}),
        )
        response = SimpleNamespace(status="completed", output=[call], id="response")
        self.assertEqual(1, connection.verify_mcp_tool_response(response, target)["verified_resource_count"])
        call.output = json.dumps({"status": 403, "results": {"resources": []}})
        with self.assertRaises(RuntimeError):
            connection.verify_mcp_tool_response(response, target)
        call.output = json.dumps({"status": 200, "results": {"resources": [{"id": "/other-scope"}]}})
        with self.assertRaisesRegex(RuntimeError, "outside"):
            connection.verify_mcp_tool_response(response, target)
        response.status = "incomplete"
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            connection.verify_mcp_tool_response(response, target)


class DnsRepairTests(unittest.TestCase):
    def setUp(self):
        self.target, self.plan, _ = fixture()
        self.azure = FakeAzure(self.target, self.plan)
        self.azure.resources[self.plan["private_dns_zone_id"]] = {"id": self.plan["private_dns_zone_id"]}
        self.collection = self.azure.endpoint_id + "/privateDnsZoneGroups"
        self.azure.resources[self.collection] = {"value": []}

    def test_dns_plan_never_writes(self):
        result = connection.repair_mcp_dns(self.azure, self.target, self.plan)
        self.assertEqual("missing-association", result["status"])
        self.assertEqual([], self.azure.writes)

    def test_missing_association_create_is_concurrency_protected_and_scoped(self):
        calls = []

        def create(method, url, body, *, audience, headers):
            calls.append((method, url, body, headers))
            group_id = self.collection + "/deployedByPolicy"
            self.azure.resources[group_id] = {"id": group_id, **deepcopy(body)}
            return self.azure.resources[group_id]

        with patch.object(self.azure, "request", side_effect=create):
            result = connection.repair_mcp_dns(self.azure, self.target, self.plan, apply=True)
        self.assertTrue(result["applied"])
        self.assertEqual("PUT", calls[0][0])
        self.assertEqual({"If-None-Match": "*"}, calls[0][3])
        self.assertEqual(self.plan["private_dns_zone_id"],
                         calls[0][2]["properties"]["privateDnsZoneConfigs"][0]["properties"]["privateDnsZoneId"])

    def test_conflicting_associations_or_unapproved_pe_are_not_changed(self):
        self.azure.resources[self.collection]["value"] = [{
            "id": self.collection + "/other",
            "properties": {"privateDnsZoneConfigs": [{"properties": {"privateDnsZoneId": "/other-zone"}}]},
        }]
        with self.assertRaisesRegex(RuntimeError, "refusing replacement"):
            connection.repair_mcp_dns(self.azure, self.target, self.plan, apply=True)
        self.assertEqual([], self.azure.writes)


class PrivateProbeTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://mcp-project.private-123.swedencentral.azurecontainerapps.io"
        self.dns = patch("agent_factory.data.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("10.8.0.5", 443)),
        ]).start()
        self.tcp = patch.object(connection.socket, "create_connection", return_value=MagicMock()).start()
        self.opener = patch.object(connection, "build_opener").start()
        self.opener.return_value.open.side_effect = HTTPError(self.url, 401, "Unauthorized", {}, io.BytesIO())
        self.addCleanup(patch.stopall)

    def test_initialize_is_unauthenticated_without_proxy_and_expects_401(self):
        connection.verify_private_mcp_endpoint(self.url)
        self.tcp.assert_called_once_with((urlsplit(self.url).hostname, 443), timeout=10)
        self.assertEqual({}, self.opener.call_args.args[0].proxies)
        self.assertIsInstance(self.opener.call_args.args[1], connection._NoMcpRedirects)
        request = self.opener.return_value.open.call_args.args[0]
        self.assertEqual(self.url, request.full_url)
        self.assertEqual("POST", request.method)
        self.assertFalse(any("auth" in key.lower() or "key" in key.lower() for key in request.headers))
        self.assertEqual("initialize", json.loads(request.data)["method"])
        self.assertNotIn("tools/call", request.data.decode())

    def test_public_mixed_or_unavailable_dns_never_connects(self):
        for addresses in [["8.8.8.8"], ["10.8.0.5", "8.8.8.8"], ["127.0.0.1"], []]:
            with self.subTest(addresses=addresses):
                self.dns.return_value = [(2, 1, 6, "", (address, 443)) for address in addresses]
                with self.assertRaisesRegex(RuntimeError, "VNet/VPN"):
                    connection.verify_private_mcp_endpoint(self.url)
                self.tcp.assert_not_called()
                self.opener.assert_not_called()
        self.dns.side_effect = OSError("No DNS")
        with self.assertRaisesRegex(RuntimeError, "private DNS"):
            connection.verify_private_mcp_endpoint(self.url)

    def test_tcp_or_https_failure_gives_actionable_vpn_error(self):
        self.tcp.side_effect = OSError("Network unreachable")
        with self.assertRaisesRegex(RuntimeError, "private TCP 443"):
            connection.verify_private_mcp_endpoint(self.url)
        self.opener.assert_not_called()
        self.tcp.side_effect = None
        self.opener.return_value.open.side_effect = URLError("No route")
        with self.assertRaisesRegex(RuntimeError, "VNet/VPN"):
            connection.verify_private_mcp_endpoint(self.url)

    def test_success_redirect_forbidden_and_errors_are_not_authentication_proof(self):
        for status in (200, 202, 302, 307, 400, 403, 404, 500):
            with self.subTest(status=status):
                self.opener.return_value.open.side_effect = HTTPError(self.url, status, "status", {}, io.BytesIO())
                with self.assertRaisesRegex(RuntimeError, "expected 401"):
                    connection.verify_private_mcp_endpoint(self.url)
        self.opener.return_value.open.side_effect = None
        self.opener.return_value.open.return_value.__enter__.return_value.status = 200
        with self.assertRaisesRegex(RuntimeError, "expected 401"):
            connection.verify_private_mcp_endpoint(self.url)

    def test_redirect_handler_never_follows_auth_proxy(self):
        with self.assertRaisesRegex(RuntimeError, "redirect"):
            connection._NoMcpRedirects().redirect_request(None, None, 302, "Found", {}, self.url)

    def test_noncanonical_endpoints_are_rejected_before_network(self):
        for url in [
            self.url + "/mcp",
            self.url.replace("https:", "http:"), self.url + "?api-key=secret", self.url + "#x",
            self.url + "/other", self.url.replace("https://", "https://user:secret@"),
            self.url.replace(".io", ".io:443"), "https://evil.example/mcp",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                connection.verify_private_mcp_endpoint(url)
        self.dns.assert_not_called()
        self.tcp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
