from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from agent_factory.azure import AzureError
from agent_factory.config import Target
from agent_factory import mcp_control as mcp


TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
HUB = "33333333-3333-3333-3333-333333333333"
PRINCIPAL = "44444444-4444-4444-4444-444444444444"
APP_OBJECT = "55555555-5555-5555-5555-555555555555"
CLIENT = "66666666-6666-6666-6666-666666666666"
SERVER_SP = "77777777-7777-7777-7777-777777777777"
OTHER_PRINCIPAL = "88888888-8888-8888-8888-888888888888"
VNET = f"/subscriptions/{SUB}/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/shared"
IMAGE = "mcr.microsoft.com/azure-sdk/azure-mcp@sha256:" + "a" * 64


def target():
    return Target(
        tenant_id=TENANT, subscription_id=SUB, resource_group="project",
        common_resource_group="common", account_name="foundry", project_name="project-one",
        project_endpoint="https://foundry.services.ai.azure.com/api/projects/project-one",
        location="swedencentral", model_deployment="model", embedding_deployment="embedding",
        search_name="search", storage_name="storage", identity_id="/unused-project-uami",
        identity_client_id=OTHER_PRINCIPAL,
    )


def settings():
    return {
        "infrastructure_subnet_id": f"{VNET}/subnets/mcp-infrastructure",
        "private_endpoint_subnet_id": f"{VNET}/subnets/endpoints",
        "private_dns_zone_id": (
            f"/subscriptions/{HUB}/resourceGroups/hub-dns/providers/Microsoft.Network/"
            "privateDnsZones/privatelink.swedencentral.azurecontainerapps.io"
        ),
        "image": IMAGE,
    }


class FakeAzure:
    def __init__(self, selected, plan):
        self.subscription_id = selected.subscription_id
        self.tenant_id = selected.tenant_id
        self.selected = selected
        self.plan = plan
        self.calls = []
        self.application = None
        self.server = None
        self.federated = []
        self.incoming = []
        self.outgoing = []
        self.delegated = []
        self.incoming_delegated = []
        self.caller_type = "ManagedIdentity"
        self.resources = {
            selected.project_id: {
                "id": selected.project_id, "location": selected.location,
                "identity": {"principalId": PRINCIPAL, "tenantId": TENANT},
            },
            VNET: {"id": VNET, "location": selected.location},
            plan["infrastructure_subnet_id"]: {
                "id": plan["infrastructure_subnet_id"],
                "properties": {
                    "addressPrefix": "10.8.0.0/27",
                    "delegations": [{"properties": {"serviceName": "Microsoft.App/environments"}}],
                    "networkSecurityGroup": {"id": "/nsg/preserve"},
                    "routeTable": {"id": "/udr/preserve"},
                },
            },
            plan["private_endpoint_subnet_id"]: {
                "id": plan["private_endpoint_subnet_id"], "properties": {"delegations": []},
            },
            plan["private_dns_zone_id"]: {"id": plan["private_dns_zone_id"]},
        }

    @property
    def writes(self):
        return [call for call in self.calls if call[1] != "GET"]

    def arm(self, method, resource_id, body=None, *, api_version):
        self.calls.append(("arm", method, resource_id, deepcopy(body)))
        if method != "GET":
            raise AssertionError("Control helper must not write ARM")
        if resource_id not in self.resources:
            raise AzureError(404, method, resource_id, "NotFound")
        return deepcopy(self.resources[resource_id])

    def request(self, method, url, body=None, *, audience, **kwargs):
        self.calls.append(("graph", method, url, deepcopy(body)))
        if audience != mcp.GRAPH:
            raise AssertionError("Wrong Graph audience")
        parsed = urlsplit(url)
        if parsed.netloc != "graph.microsoft.com" or not parsed.path.startswith("/v1.0/"):
            raise AssertionError("Unexpected Graph origin/version")
        path = parsed.path[len("/v1.0/"):]
        query = parse_qs(parsed.query)
        if method == "GET":
            if path == "applications":
                if query["$filter"] != [f"uniqueName eq '{self.plan['unique_name']}'"]:
                    raise AssertionError("Expected deterministic uniqueName lookup")
                return {"value": [deepcopy(self.application)] if self.application else []}
            if path == "servicePrincipals":
                if query["$filter"] != [f"appId eq '{CLIENT}'"]:
                    raise AssertionError("Expected exact appId lookup")
                return {"value": [deepcopy(self.server)] if self.server else []}
            if path == f"applications/{APP_OBJECT}":
                return deepcopy(self.application)
            if path == f"servicePrincipals/{SERVER_SP}":
                return deepcopy(self.server)
            if path == f"servicePrincipals/{PRINCIPAL}":
                return {"id": PRINCIPAL, "servicePrincipalType": self.caller_type}
            collections = {
                f"applications/{APP_OBJECT}/federatedIdentityCredentials": self.federated,
                f"servicePrincipals/{SERVER_SP}/appRoleAssignedTo": self.incoming,
                f"servicePrincipals/{SERVER_SP}/appRoleAssignments": self.outgoing,
                f"servicePrincipals/{SERVER_SP}/oauth2PermissionGrants": self.delegated,
                "oauth2PermissionGrants": self.incoming_delegated,
            }
            if path in collections:
                if path == "oauth2PermissionGrants":
                    if query["$filter"] != [f"resourceId eq '{SERVER_SP}'"]:
                        raise AssertionError("Expected resource-scoped incoming delegated grants lookup")
                return {"value": deepcopy(collections[path])}
        if method == "POST" and path == "applications":
            if self.application:
                raise AssertionError("Duplicate application create")
            self.application = {**deepcopy(body), "id": APP_OBJECT, "appId": CLIENT}
            return deepcopy(self.application)
        if method == "PATCH" and path == f"applications/{APP_OBJECT}":
            if body != {"identifierUris": [f"api://{CLIENT}"]}:
                raise AssertionError("Only initialize the generated appId URI")
            self.application.update(deepcopy(body))
            return {}
        if method == "POST" and path == "servicePrincipals":
            if self.server:
                raise AssertionError("Duplicate service principal create")
            self.server = {
                **deepcopy(body), "id": SERVER_SP, "appOwnerOrganizationId": TENANT,
                "servicePrincipalType": "Application", "appRoles": deepcopy(self.application["appRoles"]),
                "oauth2PermissionScopes": [], "passwordCredentials": [], "keyCredentials": [],
                "replyUrls": [],
            }
            return deepcopy(self.server)
        if method == "POST" and path == f"servicePrincipals/{PRINCIPAL}/appRoleAssignments":
            self.incoming.append({**deepcopy(body), "id": "assignment", "principalType": "ServicePrincipal"})
            return deepcopy(self.incoming[-1])
        raise AssertionError(f"Unexpected Graph call: {method} {path}")

    def owned_environment(self, *, app=False):
        env_id = f"{self.selected.group_id}/providers/Microsoft.App/managedEnvironments/{self.plan['environment_name']}"
        self.resources[env_id] = {
            "id": env_id, "location": self.selected.location, "tags": deepcopy(self.plan["tags"]),
            "properties": {
                "publicNetworkAccess": "Disabled", "vnetConfiguration": {
                    "internal": True, "infrastructureSubnetId": self.plan["infrastructure_subnet_id"],
                },
            },
        }
        if app:
            app_id = f"{self.selected.group_id}/providers/Microsoft.App/containerApps/{self.plan['name']}"
            self.resources[app_id] = {
                "id": app_id, "location": self.selected.location, "tags": deepcopy(self.plan["tags"]),
                "properties": {"managedEnvironmentId": env_id},
            }
        return env_id


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.target = target()
        self.config = settings()
        self.plan = mcp.build_mcp_plan(self.target, self.config)

    def test_default_is_deterministic_bounded_and_target_bound(self):
        self.assertEqual(self.plan, mcp.build_mcp_plan(self.target, self.config))
        self.assertLessEqual(len(self.plan["name"]), 32)
        self.assertEqual(["group_resource_list"], self.plan["tools"])
        other = replace(self.target, project_name="project-two")
        other_plan = mcp.build_mcp_plan(other, self.config)
        for key in ("name", "unique_name", "app_role_id", "project_tag"):
            self.assertNotEqual(self.plan[key], other_plan[key])
        self.assertEqual(self.plan, mcp.validate_mcp_plan(self.target, self.plan))
        with self.assertRaisesRegex(ValueError, "another project"):
            mcp.validate_mcp_plan(other, self.plan)

    def test_long_unsafe_account_stem_is_sanitized_and_truncated(self):
        selected = replace(self.target, account_name="Foundry_X" * 8, project_name="Project_One")
        plan = mcp.build_mcp_plan(selected, self.config)
        self.assertLessEqual(len(plan["name"]), 32)
        self.assertRegex(plan["name"], r"^[a-z][a-z0-9-]+[a-z0-9]$")

    def test_image_requires_exact_registry_repository_and_digest(self):
        for image in (IMAGE[:-1], IMAGE.upper(), IMAGE.replace("azure-sdk", "other"),
                      "mcr.microsoft.com/azure-sdk/azure-mcp:latest", IMAGE + "?token=x"):
            with self.subTest(image=image), self.assertRaises(ValueError):
                mcp.build_mcp_plan(self.target, {**self.config, "image": image})

    def test_tools_and_credentials_are_not_extensible_inputs(self):
        for tools in ([], ["group_list"], ["group_resource_list", "storage_account_create"],
                      "group_resource_list", ["group_resource_list"] * 2):
            with self.subTest(tools=tools), self.assertRaises(ValueError):
                mcp.build_mcp_plan(self.target, {**self.config, "tools": tools})
        with self.assertRaisesRegex(ValueError, "credentials"):
            mcp.build_mcp_plan(self.target, {**self.config, "client_secret": "never-accept"})

    def test_subnets_and_dns_are_strictly_scoped(self):
        bad = [
            {"infrastructure_subnet_id": self.config["infrastructure_subnet_id"].replace(SUB, HUB)},
            {"private_endpoint_subnet_id": self.config["private_endpoint_subnet_id"].replace("shared", "other")},
            {"private_endpoint_subnet_id": self.config["infrastructure_subnet_id"]},
            {"infrastructure_subnet_id": f"{VNET}/subnets/project-aca-002"},
            {"private_dns_zone_id": self.config["private_dns_zone_id"].replace("swedencentral", "eastus")},
            {"private_dns_zone_id": self.config["private_dns_zone_id"] + "/evil"},
            {"infrastructure_subnet_id": self.config["infrastructure_subnet_id"] + "?api-version=bad"},
        ]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                mcp.build_mcp_plan(self.target, {**self.config, **changes})
        for key in ("infrastructure_subnet_id", "private_endpoint_subnet_id", "private_dns_zone_id"):
            with self.subTest(missing=key), self.assertRaises(ValueError):
                mcp.build_mcp_plan(self.target, {k: v for k, v in self.config.items() if k != key})

    def test_arm_id_case_is_immaterial_and_explicit_names_are_checked(self):
        self.assertTrue(mcp.build_mcp_plan(self.target, {
            **self.config, "private_endpoint_subnet_id": self.config["private_endpoint_subnet_id"].upper(),
        }))
        for name in ("", "-bad", "bad-", "bad--name", "Bad", "a" * 33, "bad/name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                mcp.build_mcp_plan(self.target, {**self.config, "name": name})

    def test_modified_serialized_plan_is_rejected(self):
        for key, value in (("project_resource_id", "/other"), ("app_role_id", CLIENT),
                           ("unique_name", "unrelated"), ("tags", {}), ("environment_name", "public"),
                           ("client_secret", "never-accept")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                mcp.validate_mcp_plan(self.target, {**self.plan, key: value})


class PreflightTests(unittest.TestCase):
    def test_owned_environment_network_attachments_are_reusable_but_foreign_nics_are_not(self):
        self.session.owned_environment()
        environment_id = f"{self.target.group_id}/providers/Microsoft.App/managedEnvironments/{self.plan['environment_name']}"
        self.session.resources[environment_id]["properties"]["infrastructureResourceGroup"] = "ME_owned"
        subnet_id = self.plan["infrastructure_subnet_id"]
        self.subnet["ipConfigurations"] = [{
            "id": f"/subscriptions/{SUB}/resourceGroups/ME_owned/providers/Microsoft.Network/loadBalancers/lb/frontendIPConfigurations/frontend",
        }]
        self.subnet["serviceAssociationLinks"] = [{
            "id": subnet_id + "/serviceAssociationLinks/legionservicelink",
            "properties": {"linkedResourceType": "Microsoft.App/environments",
                           "link": subnet_id.replace("/providers/Microsoft.Network", "")},
        }]
        self.assertTrue(mcp.preflight_mcp(self.session, self.target, self.plan)["environment_exists"])
        self.subnet["ipConfigurations"][0]["id"] = self.subnet["ipConfigurations"][0]["id"].replace("ME_owned", "foreign")
        with self.assertRaisesRegex(ValueError, "outside"):
            mcp.preflight_mcp(self.session, self.target, self.plan)

    def test_existing_environment_read_uses_api_that_returns_public_network_access(self):
        self.session.owned_environment()
        with patch.object(self.session, "arm", wraps=self.session.arm) as read:
            mcp.preflight_mcp(self.session, self.target, self.plan)
        calls = [call for call in read.call_args_list if "/managedEnvironments/" in call.args[1]]
        self.assertEqual(1, len(calls))
        self.assertEqual("2025-07-01", calls[0].kwargs["api_version"])

    def setUp(self):
        self.target = target()
        self.plan = mcp.build_mcp_plan(self.target, settings())
        self.session = FakeAzure(self.target, self.plan)
        self.subnet = self.session.resources[self.plan["infrastructure_subnet_id"]]["properties"]

    def test_reads_only_project_principal_and_preserves_nsg_udr(self):
        before = deepcopy(self.session.resources)
        result = mcp.preflight_mcp(self.session, self.target, self.plan)
        self.assertEqual(PRINCIPAL, result["project_principal_id"])
        self.assertNotEqual(self.target.identity_client_id, result["project_principal_id"])
        self.assertEqual(before, self.session.resources)
        self.assertEqual([], self.session.writes)
        self.assertNotIn(self.target.account_id, [call[2] for call in self.session.calls])

    def test_cross_target_session_and_project_mismatch_fail_before_graph(self):
        self.session.subscription_id = HUB
        with self.assertRaisesRegex(ValueError, "another target"):
            mcp.preflight_mcp(self.session, self.target, self.plan)
        self.assertEqual([], self.session.calls)
        self.session.subscription_id = SUB
        self.session.resources[self.target.project_id]["id"] = self.target.account_id
        with self.assertRaisesRegex(RuntimeError, "unexpected resource ID"):
            mcp.prepare_mcp_identity(self.session, self.target, self.plan, apply=True)
        self.assertFalse(any(call[0] == "graph" for call in self.session.calls))

    def test_missing_project_identity_never_falls_back_to_account(self):
        self.session.resources[self.target.project_id]["identity"] = {}
        with self.assertRaisesRegex(ValueError, "Project identity.principalId"):
            mcp.prepare_mcp_identity(self.session, self.target, self.plan, apply=True)
        self.assertEqual([], self.session.writes)

    def test_subnet_size_and_exact_delegation(self):
        original = deepcopy(self.subnet)
        for change in (
            {"addressPrefix": "10.8.0.0/28"}, {"addressPrefix": "fd00::/64"},
            {"addressPrefix": "10.8.0.1/27"}, {"delegations": []},
            {"delegations": [{"properties": {"serviceName": "Microsoft.Web/serverFarms"}}]},
            {"delegations": original["delegations"] * 2},
        ):
            with self.subTest(change=change):
                self.subnet.clear()
                self.subnet.update({**deepcopy(original), **change})
                with self.assertRaises(ValueError):
                    mcp.prepare_mcp_identity(self.session, self.target, self.plan, apply=True)
                self.assertEqual([], self.session.writes)
        self.subnet.clear()
        self.subnet.update(original)
        self.subnet.pop("addressPrefix")
        self.subnet["addressPrefixes"] = ["10.8.0.0/26"]
        self.assertTrue(mcp.preflight_mcp(self.session, self.target, self.plan))

    def test_used_infrastructure_rejected_even_with_own_resource_name(self):
        for key in ("ipConfigurations", "privateEndpoints", "serviceAssociationLinks", "resourceNavigationLinks"):
            with self.subTest(key=key):
                self.subnet[key] = [{"id": "/some/resource"}]
                with self.assertRaisesRegex(ValueError, "in use"):
                    mcp.preflight_mcp(self.session, self.target, self.plan)
                self.subnet.pop(key)

    def test_owned_environment_reference_permits_idempotent_subnet_reuse(self):
        env_id = self.session.owned_environment(app=True)
        self.subnet["serviceAssociationLinks"] = [{"properties": {
            "linkedResourceType": "Microsoft.App/environments", "link": env_id,
        }}]
        self.assertTrue(mcp.preflight_mcp(self.session, self.target, self.plan)["environment_exists"])
        self.subnet["serviceAssociationLinks"][0]["properties"]["link"] = env_id + "-other"
        with self.assertRaisesRegex(ValueError, "in use"):
            mcp.preflight_mcp(self.session, self.target, self.plan)

    def test_public_or_other_owned_environment_is_never_converted(self):
        env_id = self.session.owned_environment()
        env = self.session.resources[env_id]
        original = deepcopy(env)
        for change in (
            {"tags": {}}, {"tags": {**self.plan["tags"], mcp.ARM_PROJECT_KEY: "/other-project"}},
            {"location": "eastus"},
            {"properties": {**original["properties"], "publicNetworkAccess": "Enabled"}},
            {"properties": {"publicNetworkAccess": "Disabled", "vnetConfiguration": {
                "internal": False, "infrastructureSubnetId": self.plan["infrastructure_subnet_id"],
            }}},
            {"properties": {"publicNetworkAccess": "Disabled", "vnetConfiguration": {
                "internal": True, "infrastructureSubnetId": f"{VNET}/subnets/other",
            }}},
        ):
            with self.subTest(change=change):
                env.clear()
                env.update({**deepcopy(original), **change})
                with self.assertRaises(RuntimeError):
                    mcp.prepare_mcp_identity(self.session, self.target, self.plan, apply=True)
                self.assertEqual([], self.session.writes)

    def test_app_collision_and_vnet_region_and_endpoint_delegation(self):
        self.session.owned_environment(app=True)
        app_id = f"{self.target.group_id}/providers/Microsoft.App/containerApps/{self.plan['name']}"
        self.session.resources[app_id]["tags"] = {}
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            mcp.preflight_mcp(self.session, self.target, self.plan)
        self.session.resources[app_id]["tags"] = self.plan["tags"]
        self.session.resources[VNET]["location"] = "eastus"
        with self.assertRaisesRegex(RuntimeError, "VNet region"):
            mcp.preflight_mcp(self.session, self.target, self.plan)
        self.session.resources[VNET]["location"] = self.target.location
        self.session.resources[self.plan["private_endpoint_subnet_id"]]["properties"]["delegations"] = [{}]
        with self.assertRaisesRegex(ValueError, "must not be delegated"):
            mcp.preflight_mcp(self.session, self.target, self.plan)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.target = target()
        self.plan = mcp.build_mcp_plan(self.target, settings())
        self.session = FakeAzure(self.target, self.plan)

    def prepare(self, apply=False):
        return mcp.prepare_mcp_identity(self.session, self.target, self.plan, apply=apply)

    def test_dry_run_never_creates(self):
        result = self.prepare()
        self.assertFalse(result["ready"])
        self.assertFalse(result["applied"])
        self.assertIsNone(result["application_client_id"])
        self.assertEqual([], self.session.writes)
        with self.assertRaises(ValueError):
            self.prepare(apply="true")

    def test_create_is_secretless_single_tenant_and_one_managed_identity_caller(self):
        result = self.prepare(apply=True)
        self.assertTrue(result["ready"])
        self.assertEqual(f"api://{CLIENT}", result["audience"])
        self.assertEqual(CLIENT, result["application_client_id"])
        self.assertEqual(PRINCIPAL, result["project_principal_id"])
        self.assertEqual(["POST", "PATCH", "POST", "POST"], [call[1] for call in self.session.writes])
        app = self.session.application
        self.assertEqual("AzureADMyOrg", app["signInAudience"])
        self.assertEqual(2, app["api"]["requestedAccessTokenVersion"])
        self.assertEqual([], app["api"]["preAuthorizedApplications"])
        self.assertEqual([], app["api"]["oauth2PermissionScopes"])
        self.assertEqual([], app["passwordCredentials"])
        self.assertEqual([], app["keyCredentials"])
        self.assertEqual([], app["requiredResourceAccess"])
        self.assertEqual(["Application"], app["appRoles"][0]["allowedMemberTypes"])
        self.assertEqual("Mcp.Tools.ReadWrite.All", app["appRoles"][0]["value"])
        self.assertTrue(self.session.server["appRoleAssignmentRequired"])
        assignment = self.session.incoming[0]
        self.assertEqual(PRINCIPAL, assignment["principalId"])
        self.assertEqual(SERVER_SP, assignment["resourceId"])
        self.assertEqual(self.plan["app_role_id"], assignment["appRoleId"])
        self.assertNotIn("accessToken", json.dumps(result))
        self.assertNotIn("passwordCredentials", json.dumps(result))
        self.assertNotIn("keyCredentials", json.dumps(result))
        self.assertFalse(any(call[0] == "arm" and call[1] != "GET" for call in self.session.calls))

    def test_reuse_is_idempotent_and_preserves_non_owned_metadata(self):
        result = self.prepare(apply=True)
        self.session.application["tags"].append("someone-else:metadata")
        self.session.application["displayName"] = "Administrator's custom display name"
        self.session.server["tags"].append("other:tag")
        before = deepcopy((self.session.application, self.session.server, self.session.incoming))
        self.session.calls.clear()
        self.assertEqual(result, self.prepare(apply=True))
        self.assertEqual([], self.session.writes)
        self.assertEqual(before, (self.session.application, self.session.server, self.session.incoming))
        self.assertTrue(self.prepare()["ready"])

    def test_incomplete_owned_application_can_resume_without_duplicate_create(self):
        self.prepare(apply=True)
        self.session.application["identifierUris"] = []
        self.session.server = None
        self.session.incoming = []
        self.session.calls.clear()
        self.assertTrue(self.prepare(apply=True)["ready"])
        self.assertFalse(any(call[1] == "POST" and urlsplit(call[2]).path == "/v1.0/applications"
                             for call in self.session.writes))

    def test_application_collisions_and_permission_changes_fail_before_writes(self):
        self.prepare(apply=True)
        original = deepcopy(self.session.application)
        changes = (
            {"tags": []}, {"tags": [mcp.OWNER_TAG, "aifactory-project:other"]},
            {"signInAudience": "AzureADMultipleOrgs"}, {"passwordCredentials": [{"hint": "sensitive"}]},
            {"keyCredentials": [{"keyId": OTHER_PRINCIPAL}]},
            {"requiredResourceAccess": [{"resourceAppId": OTHER_PRINCIPAL}]},
            {"identifierUris": ["api://another-application"]},
            {"api": {**original["api"], "requestedAccessTokenVersion": 1}},
            {"api": {**original["api"], "preAuthorizedApplications": [{"appId": OTHER_PRINCIPAL}]}},
            {"api": {**original["api"], "oauth2PermissionScopes": [{"value": "user_impersonation"}]}},
            {"api": {**original["api"], "knownClientApplications": [OTHER_PRINCIPAL]}},
            {"appRoles": original["appRoles"] + [{**original["appRoles"][0], "id": OTHER_PRINCIPAL}]},
            {"appRoles": [{**original["appRoles"][0], "allowedMemberTypes": ["User", "Application"]}]},
            {"appRoles": [{**original["appRoles"][0], "value": "Admin.All"}]},
            {"appRoles": [{**original["appRoles"][0], "isEnabled": False}]},
            {"publicClient": {"redirectUris": ["http://localhost"]}},
            {"web": {"implicitGrantSettings": {"enableIdTokenIssuance": True}}},
            {"isFallbackPublicClient": True},
        )
        for change in changes:
            with self.subTest(change=change):
                self.session.application = {**deepcopy(original), **change}
                self.session.calls.clear()
                with self.assertRaises(RuntimeError):
                    self.prepare(apply=True)
                self.assertEqual([], self.session.writes)

    def test_federation_is_rejected_without_returning_credential_details(self):
        self.prepare(apply=True)
        self.session.federated = [{"issuer": "sensitive-value-must-not-leak"}]
        self.session.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "federated") as caught:
            self.prepare(apply=True)
        self.assertNotIn("sensitive-value", str(caught.exception))
        self.assertEqual([], self.session.writes)

    def test_service_principal_mismatches_are_never_fixed_by_overwriting(self):
        self.prepare(apply=True)
        original = deepcopy(self.session.server)
        changes = (
            {"tags": []}, {"appRoleAssignmentRequired": False}, {"accountEnabled": False},
            {"appOwnerOrganizationId": HUB}, {"servicePrincipalType": "ManagedIdentity"},
            {"passwordCredentials": [{"hint": "secret"}]}, {"keyCredentials": [{"keyId": CLIENT}]},
            {"oauth2PermissionScopes": [{"value": "delegated"}]}, {"appRoles": []},
            {"replyUrls": ["http://localhost"]},
        )
        for change in changes:
            with self.subTest(change=change):
                self.session.server = {**deepcopy(original), **change}
                self.session.calls.clear()
                with self.assertRaises(RuntimeError):
                    self.prepare(apply=True)
                self.assertEqual([], self.session.writes)

    def test_one_caller_only_and_no_user_or_outbound_grants(self):
        self.prepare(apply=True)
        expected = deepcopy(self.session.incoming[0])
        for change in (
            {"principalId": OTHER_PRINCIPAL}, {"appRoleId": OTHER_PRINCIPAL},
            {"resourceId": OTHER_PRINCIPAL}, {"principalType": "User"},
        ):
            with self.subTest(change=change):
                self.session.incoming = [{**expected, **change}]
                self.session.calls.clear()
                with self.assertRaisesRegex(RuntimeError, "exact project's"):
                    self.prepare(apply=True)
                self.assertEqual([], self.session.writes)
        self.session.incoming = [expected, deepcopy(expected)]
        with self.assertRaises(RuntimeError):
            self.prepare(apply=True)
        self.session.incoming = [expected]
        for attr in ("outgoing", "delegated", "incoming_delegated"):
            with self.subTest(attr=attr):
                setattr(self.session, attr, [{"id": "unrelated-grant"}])
                self.session.calls.clear()
                with self.assertRaises(RuntimeError):
                    self.prepare(apply=True)
                self.assertEqual([], self.session.writes)
                setattr(self.session, attr, [])

    def test_non_managed_identity_caller_and_authorization_denial_fail_closed(self):
        self.session.caller_type = "Application"
        with self.assertRaisesRegex(RuntimeError, "not a managed-identity"):
            self.prepare(apply=True)
        self.assertEqual([], self.session.writes)
        error = AzureError(403, "GET", mcp.GRAPH, "Authorization_RequestDenied")
        with patch.object(self.session, "request", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Entra administrator.*AppRoleAssignment.ReadWrite.All"):
                self.prepare(apply=True)

    def test_mutating_graph_error_has_no_blind_post_retry(self):
        original = self.session.request
        posts = []

        def fail_post(method, url, body=None, **kwargs):
            if method == "POST":
                posts.append(url)
                raise AzureError(503, method, url, "ServiceUnavailable")
            return original(method, url, body, **kwargs)

        with patch.object(self.session, "request", side_effect=fail_post):
            with self.assertRaises(AzureError):
                self.prepare(apply=True)
        self.assertEqual(1, len(posts))

    def test_graph_pagination_bounds_origin_and_exact_lookup(self):
        for continuation in (
            "https://attacker.invalid/v1.0/applications",
            "https://graph.microsoft.com:443/v1.0/applications",
            "http://graph.microsoft.com/v1.0/applications",
            "https://graph.microsoft.com@attacker.invalid/v1.0/applications",
            "https://graph.microsoft.com/beta/applications",
            "https://graph.microsoft.com/v1.0/applications#fragment",
        ):
            with self.subTest(continuation=continuation):
                with patch.object(self.session, "request", return_value={
                    "value": [], "@odata.nextLink": continuation,
                }) as request:
                    with self.assertRaises(RuntimeError):
                        mcp._graph_pages(self.session, "applications")
                    self.assertEqual(1, request.call_count)
        with patch.object(self.session, "request", return_value={
            "value": [], "@odata.nextLink": f"{mcp.GRAPH}/v1.0/applications",
        }) as request:
            with self.assertRaisesRegex(RuntimeError, "repeated"):
                mcp._graph_pages(self.session, "applications")
            self.assertEqual(1, request.call_count)
        with patch.object(mcp, "MAX_GRAPH_PAGES", 2), patch.object(
            self.session, "request", side_effect=[
                {"value": [], "@odata.nextLink": f"{mcp.GRAPH}/v1.0/applications?$skiptoken={i}"}
                for i in range(3)
            ],
        ) as request:
            with self.assertRaisesRegex(RuntimeError, "page limit"):
                mcp._graph_pages(self.session, "applications")
            self.assertEqual(2, request.call_count)
        with patch.object(self.session, "request", return_value={
            "value": [{"uniqueName": "wrong"}],
        }):
            with self.assertRaisesRegex(RuntimeError, "non-matching"):
                mcp._find(self.session, "applications", "uniqueName", "a'b", "id,uniqueName")
        with patch.object(self.session, "request", return_value={
            "value": [],
        }) as request:
            mcp._find(self.session, "applications", "uniqueName", "a'b", "id")
            query = parse_qs(urlsplit(request.call_args.args[1]).query)
            self.assertEqual(["uniqueName eq 'a''b'"], query["$filter"])

    def test_duplicates_on_later_graph_page_fail_without_mutation(self):
        with patch.object(self.session, "request", side_effect=[
            {"value": [{"uniqueName": "exact"}],
             "@odata.nextLink": f"{mcp.GRAPH}/v1.0/applications?$skiptoken=next"},
            {"value": [{"uniqueName": "exact"}]},
        ]):
            with self.assertRaisesRegex(RuntimeError, "collision"):
                mcp._find(self.session, "applications", "uniqueName", "exact", "id")

    def test_parameter_document_is_exact_and_target_bound(self):
        identity = self.prepare(apply=True)
        document = mcp.build_mcp_parameters(
            self.target, self.plan, identity, central_dns_zone_by_policy_in_hub=True,
        )
        values = {key: item["value"] for key, item in document["parameters"].items()}
        self.assertEqual({
            "projectResourceGroup", "name", "location", "infrastructureSubnetId",
            "privateEndpointSubnetId", "tenantId", "entraApiApplicationClientId", "containerImage",
            "allowedTools", "privateDnsZoneResourceId", "centralDnsZoneByPolicyInHub", "tags",
        }, values.keys())
        self.assertEqual(CLIENT, values["entraApiApplicationClientId"])
        self.assertEqual(self.plan["tags"], values["tags"])
        self.assertEqual(self.target.resource_group, values["projectResourceGroup"])
        self.assertTrue(values["centralDnsZoneByPolicyInHub"])
        self.assertNotIn("principalId", json.dumps(document))
        for bad_identity in (
            {**identity, "ready": False}, {**identity, "project_resource_id": self.target.account_id},
            {**identity, "audience": "https://management.azure.com"},
        ):
            with self.assertRaises(ValueError):
                mcp.build_mcp_parameters(
                    self.target, self.plan, bad_identity, central_dns_zone_by_policy_in_hub=False,
                )
        with self.assertRaises(ValueError):
            mcp.build_mcp_parameters(
                self.target, self.plan, identity, central_dns_zone_by_policy_in_hub="false",
            )


if __name__ == "__main__":
    unittest.main()
