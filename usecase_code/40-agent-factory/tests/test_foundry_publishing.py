from __future__ import annotations

from copy import deepcopy
import json
import unittest
from urllib.parse import quote

from agent_factory.azure import AzureError
from agent_factory.foundry_publishing import (
    INPUTS, FoundryPublishingPreparation, PreparationRequest,
)


SUB = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
CLIENT = "33333333-3333-3333-3333-333333333333"
SHARED = "44444444-4444-4444-4444-444444444444"
OTHER = "55555555-5555-5555-5555-555555555555"
ACCOUNT = f"/subscriptions/{SUB}/resourceGroups/test/providers/Microsoft.CognitiveServices/accounts/foundry"
PROJECT = ACCOUNT + "/projects/test-project"
ENDPOINT = "https://foundry.services.ai.azure.com/api/projects/test-project"
AGENT = "isolated-publish-test"
AGENT_URL = f"{ENDPOINT}/agents/{quote(AGENT, safe='')}?api-version=v1"
ACTIVITY = f"{ENDPOINT}/agents/{quote(AGENT, safe='')}/endpoint/protocols/activityprotocol"


def values(**changes):
    return {
        "enableBotService": True,
        "enableAIFoundry": "true",
        "deleteAllServicesForProject": False,
        "deleteAllForProject": "false",
        "dev_test_prod_sub_id": SUB,
        "tenantId": TENANT,
        "botFoundryProjectResourceId": PROJECT,
        "botFoundryAgentName": AGENT,
        "botEnableM365PublicEndpoint": False,
        **changes,
    }


class FakeAzure:
    def __init__(self):
        self.subscription_id = SUB
        self.tenant_id = TENANT
        self.calls = []
        self.arm_error = None
        self.request_error = None
        self.patch_error = None
        self.persist_patch = True
        self.on_agent_read = None
        self.agent_reads = 0
        self.project = {
            "id": PROJECT, "identity": {"tenantId": TENANT},
            "properties": {
                "endpoints": {"AI Foundry API": ENDPOINT},
                "agentIdentity": {"agentIdentityId": SHARED},
            },
        }
        self.account = {"id": ACCOUNT, "properties": {"publicNetworkAccess": "Enabled"}}
        self.agent = {
            "id": "agent-unique-id", "name": AGENT,
            "instance_identity": {"client_id": CLIENT, "object_id": OTHER},
            "blueprint": {"id": "generated-blueprint"},
            "versions": {"latest": {"version": "7"}},
            "metadata": {"owner": "operator"},
            "description": "Unmodified instructions and metadata",
            "agent_card": {"name": "Original card"},
            "agent_endpoint": {
                "protocols": ["responses", "a2a", "mcp", "invocations"],
                "protocol_configuration": {
                    "responses": {"options": {"retain": True}},
                    "a2a": {"agent_card": {"name": "A2A card"}},
                    "mcp": {"allowed_tools": ["read"]},
                    "invocations": {},
                },
                "authorization_schemes": [
                    {"type": "AzureRbac", "isolation_source": {"type": "Entra"}},
                    {"type": "AgentBlueprint", "token_validation": {"allowed_clients": [OTHER]}},
                ],
                "version_selector": {
                    "version_selection_rules": [
                        {"type": "FixedRatio", "agent_version": "4", "traffic_percentage": 100},
                    ],
                },
                "disabled": False,
                "future_setting": {"retain": [1, 2]},
            },
        }

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def arm(self, method, resource_id, body=None, api_version=None):
        self.calls.append((method, resource_id, deepcopy(body), {"api_version": api_version}))
        if method != "GET" or resource_id not in (PROJECT, ACCOUNT):
            raise AssertionError("Only exact project/account ARM reads are allowed")
        if api_version != "2025-06-01":
            raise AssertionError("Unexpected ARM API version")
        if self.arm_error:
            raise self.arm_error
        return deepcopy(self.project if resource_id == PROJECT else self.account)

    def request(self, method, url, body=None, *, audience, headers=None):
        self.calls.append((method, url, deepcopy(body), {"audience": audience, "headers": headers}))
        if url != AGENT_URL or audience != "https://ai.azure.com":
            raise AssertionError("Unexpected data-plane target or audience")
        if method not in ("GET", "PATCH"):
            raise AssertionError("No creation, deletion, publication, ZIP, or inference is allowed")
        if self.request_error:
            raise self.request_error
        if method == "GET":
            self.agent_reads += 1
            if self.on_agent_read:
                self.on_agent_read(self, self.agent_reads)
            return deepcopy(self.agent)
        if headers != {"Content-Type": "application/merge-patch+json"}:
            raise AssertionError("Expected merge patch")
        if self.patch_error:
            raise self.patch_error
        if set(body) != {"agent_endpoint"} or not set(body["agent_endpoint"]) <= {
            "protocol_configuration", "authorization_schemes",
        }:
            raise AssertionError("Patch must not include other agent fields or version routing")
        if self.persist_patch:
            self.agent["agent_endpoint"].update(deepcopy(body["agent_endpoint"]))
            self.agent["agent_endpoint"]["protocols"] = list(
                self.agent["agent_endpoint"]["protocol_configuration"],
            )
        return {}


class RequestTests(unittest.TestCase):
    def test_exact_launcher_inputs(self):
        self.assertEqual((
            "enableBotService", "enableAIFoundry", "deleteAllServicesForProject",
            "deleteAllForProject", "dev_test_prod_sub_id", "tenantId",
            "botFoundryProjectResourceId", "botFoundryAgentName", "botEnableM365PublicEndpoint",
        ), INPUTS)

    def test_flags_accept_bools_and_case_insensitive_strings(self):
        for enabled in (True, "true", " TRUE "):
            request = PreparationRequest.from_values(values(enableBotService=enabled))
            self.assertEqual(SUB, request.subscription_id)
            self.assertEqual(TENANT, request.tenant_id)
        for disabled in (False, "false", " FALSE "):
            request = PreparationRequest.from_values(values(botEnableM365PublicEndpoint=disabled))
            self.assertFalse(request.enable_m365_public_endpoint)

    def test_disabled_and_unconfigured_make_zero_calls_even_in_apply(self):
        for changes in (
            {"enableBotService": False},
            {"enableBotService": "false", "dev_test_prod_sub_id": "", "tenantId": ""},
            {"botFoundryProjectResourceId": "", "botFoundryAgentName": ""},
            {"botFoundryProjectResourceId": "$(botFoundryProjectResourceId)",
             "botFoundryAgentName": "$(botFoundryAgentName)"},
        ):
            with self.subTest(changes=changes):
                azure = FakeAzure()
                request = PreparationRequest.from_values(values(**changes))
                result = FoundryPublishingPreparation(azure).run(request, apply=True)
                self.assertEqual("skipped", result["status"])
                self.assertTrue(result["reason"])
                self.assertFalse(result["published"])
                self.assertEqual([], azure.calls)
                json.dumps(result)

    def test_unresolved_optional_flag_is_false(self):
        request = PreparationRequest.from_values(values(
            botEnableM365PublicEndpoint="$(botEnableM365PublicEndpoint)",
        ))
        self.assertFalse(request.enable_m365_public_endpoint)

    def test_invalid_requests_fail_before_azure_access(self):
        cases = [
            {"botFoundryProjectResourceId": ""},
            {"botFoundryAgentName": "$(botFoundryAgentName)"},
            {"dev_test_prod_sub_id": "not-a-guid"},
            {"tenantId": ""},
            {"tenantId": "urn:uuid:" + TENANT},
            {"botFoundryProjectResourceId": PROJECT.replace(SUB, OTHER)},
            {"botFoundryProjectResourceId": PROJECT + "/"},
            {"botFoundryProjectResourceId": PROJECT + "?api-version=x"},
            {"botFoundryProjectResourceId": "https://management.azure.com" + PROJECT},
            {"botFoundryProjectResourceId": PROJECT.replace("/projects/", "/applications/")},
            {"botFoundryProjectResourceId": PROJECT.replace("test-project", "..")},
            {"botFoundryAgentName": "../other"},
            {"botFoundryAgentName": "agent?query"},
            {"botFoundryAgentName": "agent%2Fother"},
            {"botFoundryAgentName": "-agent"},
            {"botFoundryAgentName": "a" * 64},
            {"enableAIFoundry": False},
            {"deleteAllForProject": True},
            {"deleteAllServicesForProject": "true"},
        ]
        for flag in (
            "enableBotService", "enableAIFoundry", "deleteAllForProject",
            "deleteAllServicesForProject", "botEnableM365PublicEndpoint",
        ):
            cases.extend({flag: value} for value in ("yes", "1", 1, [], {}))
        for changes in cases:
            with self.subTest(changes=changes):
                azure = FakeAzure()
                with self.assertRaises(ValueError):
                    request = PreparationRequest.from_values(values(**changes))
                    FoundryPublishingPreparation(azure).run(request, apply=True)
                self.assertEqual([], azure.calls)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.azure = FakeAzure()

    def run_preparation(self, *, apply=False, reviewed_plan=None, **changes):
        request = PreparationRequest.from_values(values(**changes))
        service = FoundryPublishingPreparation(self.azure)
        if apply is True:
            if reviewed_plan is None:
                reviewed_plan = service.run(request)
            return service.run(request, apply=True, reviewed_plan=reviewed_plan)
        return service.run(request, apply=apply)

    def test_plan_is_bound_read_only_and_preserves_every_existing_setting(self):
        before = deepcopy(self.azure.agent)
        result = self.run_preparation()
        self.assertEqual("planned", result["status"])
        self.assertEqual("plan", result["mode"])
        self.assertTrue(result["changed"])
        self.assertFalse(result["applied"])
        self.assertFalse(result["published"])
        self.assertFalse(result["teams_verified"])
        self.assertTrue(result["remaining_manual_publication"])
        for key, expected in {
            "subscription_id": SUB, "tenant_id": TENANT, "project_resource_id": PROJECT,
            "agent_name": AGENT, "client_id": CLIENT, "activity_url": ACTIVITY,
        }.items():
            self.assertEqual(expected, result[key])
        expected = deepcopy(before["agent_endpoint"])
        expected["protocol_configuration"]["activity"] = {}
        expected["authorization_schemes"].append({"type": "BotServiceRbac"})
        expected["protocols"].append("activity")
        self.assertEqual(before["agent_endpoint"], result["before"])
        self.assertEqual(expected, result["after"])
        self.assertEqual({
            "subscription_id": SUB, "tenant_id": TENANT,
            "project_resource_id": PROJECT, "account_resource_id": ACCOUNT,
            "project_endpoint": ENDPOINT, "agent_name": AGENT,
            "agent_id": before["id"], "client_id": CLIENT,
            "instance_identity": before["instance_identity"], "blueprint": before["blueprint"],
        }, result["target"])
        self.assertNotIn("versions", result["target"])
        self.assertNotIn("metadata", result["target"])
        self.assertEqual({"agent_endpoint": {
            "protocol_configuration": expected["protocol_configuration"],
            "authorization_schemes": expected["authorization_schemes"],
        }}, result["patch"])
        self.assertEqual(before, self.azure.agent)
        self.assertEqual([], self.azure.writes)
        json.dumps(result)

    def test_session_binding_mismatch_fails_before_reads(self):
        for field in ("subscription_id", "tenant_id"):
            with self.subTest(field=field):
                self.azure = FakeAzure()
                setattr(self.azure, field, OTHER)
                with self.assertRaisesRegex(ValueError, "session"):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.calls)

    def test_wrong_project_id_or_tenant_blocks_data_plane_access(self):
        for field in ("id", "tenant"):
            with self.subTest(field=field):
                self.azure = FakeAzure()
                if field == "id":
                    self.azure.project["id"] = PROJECT + "-other"
                else:
                    self.azure.project["identity"]["tenantId"] = OTHER
                with self.assertRaisesRegex(ValueError, "project|tenant"):
                    self.run_preparation(apply=True)
                self.assertFalse(any(call[1].startswith("https://") for call in self.azure.calls))
                self.assertEqual([], self.azure.writes)

    def test_wrong_account_id_or_unverifiable_pna_is_rejected(self):
        for change in (
            {"id": ACCOUNT + "-other"},
            {"properties": {}},
            {"properties": {"publicNetworkAccess": "unexpected"}},
        ):
            with self.subTest(change=change):
                self.azure = FakeAzure()
                self.azure.account.update(change)
                with self.assertRaisesRegex(ValueError, "account|publicNetworkAccess"):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.writes)

    def test_only_exact_project_endpoint_is_accepted(self):
        for endpoint in (
            "http://foundry.services.ai.azure.com/api/projects/test-project",
            ENDPOINT + "/", ENDPOINT + "?x=y", ENDPOINT + "#fragment",
            ENDPOINT.replace("foundry.services", "different.services"),
            ENDPOINT.replace("test-project", "different"),
            ENDPOINT.replace("https://", "https://user:password@"),
            ENDPOINT.replace(".com/", ".com:443/"),
            ENDPOINT.replace(".com/", ".com.evil.invalid/"),
            ENDPOINT.replace("/api/", "/api/../api/"),
            ENDPOINT.replace("/test-project", "/%74est-project"),
            "", None,
        ):
            with self.subTest(endpoint=endpoint):
                self.azure = FakeAzure()
                self.azure.project["properties"]["endpoints"]["AI Foundry API"] = endpoint
                with self.assertRaisesRegex(ValueError, "endpoint"):
                    self.run_preparation(apply=True)
                self.assertFalse(any(call[1].startswith("https://") for call in self.azure.calls))
                self.assertEqual([], self.azure.writes)

    def test_legacy_or_invalid_instance_identity_is_never_recreated(self):
        for identity in (None, {}, {"client_id": ""}, {"client_id": "not-a-guid"},
                         {"client_id": SHARED}, {"client_id": SHARED.upper()}):
            with self.subTest(identity=identity):
                self.azure = FakeAzure()
                self.azure.agent["instance_identity"] = identity
                with self.assertRaisesRegex(ValueError, "identity|legacy|GUID"):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.writes)

    def test_mismatched_agent_name_is_rejected(self):
        self.azure.agent["name"] = "other-agent"
        with self.assertRaisesRegex(ValueError, "agent name"):
            self.run_preparation(apply=True)
        self.assertEqual([], self.azure.writes)

    def test_existing_tenant_authorization_requires_operator_handling(self):
        for existing_rbac in (False, True):
            with self.subTest(existing_rbac=existing_rbac):
                self.azure = FakeAzure()
                schemes = self.azure.agent["agent_endpoint"]["authorization_schemes"]
                schemes.append({"type": "BotServiceTenant", "tenant": TENANT})
                if existing_rbac:
                    schemes.append({"type": "BotServiceRbac"})
                with self.assertRaisesRegex(ValueError, "BotServiceTenant.*operator"):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.writes)

    def test_private_project_requires_explicit_opt_in(self):
        self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
        with self.assertRaisesRegex(ValueError, "botEnableM365PublicEndpoint=true"):
            self.run_preparation(apply=True)
        self.assertEqual([], self.azure.writes)

    def test_private_opt_in_only_enables_source_filtered_activity_route(self):
        self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
        result = self.run_preparation(apply=True, botEnableM365PublicEndpoint="true")
        self.assertTrue(result["after"]["protocol_configuration"]["activity"]["enable_m365_public_endpoint"])
        self.assertEqual("Disabled", self.azure.account["properties"]["publicNetworkAccess"])
        self.assertEqual(1, len(self.azure.writes))
        self.assertEqual("PATCH", self.azure.writes[0][0])

    def test_false_does_not_revoke_existing_public_route_or_activity_options(self):
        self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
        activity = {"enable_m365_public_endpoint": True, "future": {"retain": True}}
        self.azure.agent["agent_endpoint"]["protocol_configuration"]["activity"] = activity
        result = self.run_preparation(apply=True)
        self.assertEqual(activity, result["after"]["protocol_configuration"]["activity"])
        self.assertNotIn("protocol_configuration", result["patch"]["agent_endpoint"])

    def test_opt_in_retains_activity_options_and_authorization_details(self):
        endpoint = self.azure.agent["agent_endpoint"]
        endpoint["protocol_configuration"]["activity"] = {"enable_m365_public_endpoint": False, "option": 8}
        endpoint["authorization_schemes"].append({"type": "BotServiceRbac", "future": ["retain"]})
        result = self.run_preparation(apply=True, botEnableM365PublicEndpoint=True)
        self.assertEqual({"enable_m365_public_endpoint": True, "option": 8},
                         result["after"]["protocol_configuration"]["activity"])
        self.assertNotIn("authorization_schemes", result["patch"]["agent_endpoint"])

    def test_unknown_protocol_configuration_is_preserved(self):
        endpoint = self.azure.agent["agent_endpoint"]
        endpoint["protocol_configuration"]["future_protocol"] = {"nested": [1, {"x": 2}]}
        endpoint["protocols"].append("future_protocol")
        result = self.run_preparation(apply=True)
        self.assertEqual({"nested": [1, {"x": 2}]},
                         result["after"]["protocol_configuration"]["future_protocol"])

    def test_protocol_list_without_matching_configuration_is_rejected(self):
        for protocol in ("future_protocol", "activity", {"protocol": "future_protocol"}):
            with self.subTest(protocol=protocol):
                self.azure = FakeAzure()
                self.azure.agent["agent_endpoint"]["protocols"].append(protocol)
                with self.assertRaisesRegex(ValueError, "protocol"):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.writes)

    def test_missing_or_malformed_configuration_is_not_silently_overwritten(self):
        for key, value in (
            ("protocol_configuration", None), ("protocol_configuration", []),
            ("authorization_schemes", None), ("authorization_schemes", "AzureRbac"),
            ("authorization_schemes", ["AzureRbac"]),
            ("authorization_schemes", [{}]), ("protocols", "responses"),
        ):
            with self.subTest(key=key, value=value):
                self.azure = FakeAzure()
                self.azure.agent["agent_endpoint"][key] = value
                with self.assertRaises(ValueError):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.writes)

    def test_apply_rereads_then_uses_exact_minimal_merge_patch(self):
        original = deepcopy(self.azure.agent)
        result = self.run_preparation(apply=True)
        self.assertEqual("prepared", result["status"])
        self.assertEqual("apply", result["mode"])
        self.assertTrue(result["applied"])
        self.assertFalse(result["published"])
        self.assertFalse(result["teams_verified"])
        self.assertEqual(3, self.azure.agent_reads)
        self.assertEqual([(
            "PATCH", AGENT_URL, result["patch"],
            {"audience": "https://ai.azure.com", "headers": {"Content-Type": "application/merge-patch+json"}},
        )], self.azure.writes)
        self.assertEqual("GET", self.azure.calls[-1][0])
        for key in ("versions", "metadata", "agent_card", "blueprint", "instance_identity", "description"):
            self.assertEqual(original[key], self.azure.agent[key])
        for key in ("version_selector", "disabled", "future_setting"):
            self.assertEqual(original["agent_endpoint"][key], self.azure.agent["agent_endpoint"][key])

    def test_idempotent_no_op_never_sends_patch(self):
        self.run_preparation(apply=True)
        self.azure.calls.clear()
        result = self.run_preparation(apply=True)
        self.assertEqual("unchanged", result["status"])
        self.assertEqual("apply", result["mode"])
        self.assertFalse(result["changed"])
        self.assertFalse(result["applied"])
        self.assertEqual({}, result["patch"])
        self.assertEqual([], self.azure.writes)

    def test_apply_preserves_concurrent_protocol_auth_and_version_changes(self):
        def concurrent(azure, number):
            if number == 2:
                endpoint = azure.agent["agent_endpoint"]
                endpoint["protocol_configuration"]["concurrent"] = {"option": "keep"}
                endpoint["protocols"].append("concurrent")
                endpoint["authorization_schemes"].append({"type": "FutureAuth", "option": "keep"})
                endpoint["version_selector"] = {"version_selection_rules": [{"type": "Latest"}]}
        self.azure.on_agent_read = concurrent
        result = self.run_preparation(apply=True)
        self.assertEqual({"option": "keep"}, result["after"]["protocol_configuration"]["concurrent"])
        self.assertIn({"type": "FutureAuth", "option": "keep"}, result["after"]["authorization_schemes"])
        self.assertEqual({"version_selection_rules": [{"type": "Latest"}]}, result["after"]["version_selector"])
        self.assertTrue(result["warnings"])
        self.assertIn("protocol_configuration", " ".join(result["warnings"]))
        self.assertIn("authorization_schemes", " ".join(result["warnings"]))

    def test_apply_requires_reviewed_plan_before_azure_access(self):
        request = PreparationRequest.from_values(values())
        with self.assertRaisesRegex(ValueError, "reviewed.plan"):
            FoundryPublishingPreparation(self.azure).run(request, apply=True)
        self.assertEqual([], self.azure.calls)

    def test_reviewed_identity_or_target_mismatch_rejects_before_writes(self):
        original = self.run_preparation()
        for field in (
            "subscription_id", "tenant_id", "project_resource_id", "account_resource_id",
            "project_endpoint", "agent_name", "agent_id", "client_id", "instance_identity", "blueprint",
        ):
            with self.subTest(field=field):
                plan = deepcopy(original)
                plan["target"][field] = "different-reviewed-target"
                with self.assertRaisesRegex(RuntimeError, "reviewed.*identity|reviewed.*target|binding"):
                    self.run_preparation(apply=True, reviewed_plan=plan)
                self.assertEqual([], self.azure.writes)

    def test_reviewed_plan_is_json_roundtrippable_and_not_mutated(self):
        plan = json.loads(json.dumps(self.run_preparation()))
        reviewed = deepcopy(plan)
        self.azure.agent["agent_endpoint"]["protocol_configuration"]["concurrent"] = {"keep": True}
        self.azure.agent["agent_endpoint"]["protocols"].append("concurrent")
        result = self.run_preparation(apply=True, reviewed_plan=plan)
        self.assertEqual(reviewed, plan)
        self.assertEqual(plan["target"], result["target"])
        self.assertTrue(result["warnings"])
        self.assertEqual({"keep": True}, result["patch"]["agent_endpoint"]["protocol_configuration"]["concurrent"])
        json.dumps(result)

    def test_apply_does_not_trust_reviewed_patch_or_agent_definitions(self):
        plan = self.run_preparation()
        plan["patch"] = {"name": "another-agent", "agent_endpoint": {"version_selector": {}}}
        plan["after"] = {"authorization_schemes": [{"type": "BotServiceTenant"}]}
        result = self.run_preparation(apply=True, reviewed_plan=plan)
        self.assertEqual({"agent_endpoint"}, set(result["patch"]))
        self.assertNotIn("version_selector", result["patch"]["agent_endpoint"])
        self.assertNotIn({"type": "BotServiceTenant"}, result["after"]["authorization_schemes"])

    def test_apply_cannot_expand_network_opt_in_beyond_reviewed_request(self):
        plan = self.run_preparation()
        with self.assertRaisesRegex(ValueError, "reviewed.*opt|reviewed.*network"):
            self.run_preparation(apply=True, reviewed_plan=plan, botEnableM365PublicEndpoint=True)
        self.assertEqual([], self.azure.writes)

    def test_malformed_reviewed_plan_rejects_before_writes(self):
        original = self.run_preparation()
        for plan in (
            {}, [], {"target": original["target"]},
            {**original, "mode": "apply"},
            {**original, "before": None},
        ):
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):
                    self.run_preparation(apply=True, reviewed_plan=plan)
                self.assertEqual([], self.azure.writes)

    def test_reviewed_exact_no_op_has_no_patch_and_no_drift_warning(self):
        self.run_preparation(apply=True)
        plan = self.run_preparation()
        self.azure.calls.clear()
        result = self.run_preparation(apply=True, reviewed_plan=plan)
        self.assertEqual("apply", result["mode"])
        self.assertEqual("unchanged", result["status"])
        self.assertEqual(plan["target"], result["target"])
        self.assertEqual({}, result["patch"])
        self.assertEqual([], result["warnings"])
        self.assertEqual([], self.azure.writes)

    def test_concurrent_identity_replacement_is_rejected_before_patch(self):
        for field in ("client_id", "id", "blueprint", "object_id"):
            with self.subTest(field=field):
                self.azure = FakeAzure()
                def concurrent(azure, number):
                    if number == 2:
                        if field in ("client_id", "object_id"):
                            azure.agent["instance_identity"][field] = OTHER
                            if field == "object_id":
                                azure.agent["instance_identity"][field] = CLIENT
                        else:
                            azure.agent[field] = "replacement"
                self.azure.on_agent_read = concurrent
                with self.assertRaisesRegex(RuntimeError, "identity|binding"):
                    self.run_preparation(apply=True)
                self.assertEqual([], self.azure.writes)

    def test_concurrent_tenant_scheme_is_rejected_before_patch(self):
        def concurrent(azure, number):
            if number == 2:
                azure.agent["agent_endpoint"]["authorization_schemes"].append({"type": "BotServiceTenant"})
        self.azure.on_agent_read = concurrent
        with self.assertRaisesRegex(ValueError, "BotServiceTenant"):
            self.run_preparation(apply=True)
        self.assertEqual([], self.azure.writes)

    def test_concurrent_preparation_becomes_no_op(self):
        def concurrent(azure, number):
            if number == 2:
                endpoint = azure.agent["agent_endpoint"]
                endpoint["protocol_configuration"]["activity"] = {}
                endpoint["protocols"].append("activity")
                endpoint["authorization_schemes"].append({"type": "BotServiceRbac"})
        self.azure.on_agent_read = concurrent
        result = self.run_preparation(apply=True)
        self.assertEqual("unchanged", result["status"])
        self.assertEqual([], self.azure.writes)

    def test_concurrent_private_pna_requires_fresh_opt_in(self):
        original_arm = self.azure.arm
        reads = 0
        def changed_arm(method, resource_id, body=None, api_version=None):
            nonlocal reads
            if resource_id == ACCOUNT:
                reads += 1
                if reads == 2:
                    self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
            return original_arm(method, resource_id, body, api_version)
        self.azure.arm = changed_arm
        with self.assertRaisesRegex(ValueError, "botEnableM365PublicEndpoint=true"):
            self.run_preparation(apply=True)
        self.assertEqual([], self.azure.writes)

    def test_successful_http_patch_without_persisted_change_fails_verification(self):
        self.azure.persist_patch = False
        with self.assertRaisesRegex(RuntimeError, "verification|not applied"):
            self.run_preparation(apply=True)
        self.assertEqual(1, len(self.azure.writes))

    def test_readback_identity_routing_and_config_drift_are_errors(self):
        for field in ("identity", "version_selector", "disabled", "protocol", "authorization", "metadata"):
            with self.subTest(field=field):
                self.azure = FakeAzure()
                def changed(azure, number):
                    if number != 3:
                        return
                    endpoint = azure.agent["agent_endpoint"]
                    if field == "identity":
                        azure.agent["instance_identity"]["client_id"] = OTHER
                    elif field == "protocol":
                        endpoint["protocol_configuration"]["responses"] = {}
                    elif field == "authorization":
                        endpoint["authorization_schemes"] = [{"type": "BotServiceRbac"}]
                    elif field == "metadata":
                        azure.agent["metadata"] = {}
                    else:
                        endpoint[field] = None
                self.azure.on_agent_read = changed
                with self.assertRaisesRegex(RuntimeError, "verification|identity|preserved|routing"):
                    self.run_preparation(apply=True)

    def test_arm_and_data_plane_auth_errors_propagate(self):
        for stage in ("arm", "request", "patch", "readback"):
            for status in (401, 403):
                with self.subTest(stage=stage, status=status):
                    self.azure = FakeAzure()
                    error = AzureError(status, "GET", AGENT_URL, "Denied")
                    if stage == "readback":
                        def denied(azure, number):
                            if number == 3:
                                raise error
                        self.azure.on_agent_read = denied
                    else:
                        setattr(self.azure, stage + "_error", error)
                    with self.assertRaises(AzureError) as raised:
                        self.run_preparation(apply=True)
                    self.assertIs(error, raised.exception)

    def test_readback_public_route_and_unknown_endpoint_drift_fail(self):
        for field in ("route", "future_setting", "protocols", "pna"):
            with self.subTest(field=field):
                self.azure = FakeAzure()
                def changed(azure, number):
                    if number != 3:
                        return
                    endpoint = azure.agent["agent_endpoint"]
                    if field == "route":
                        endpoint["protocol_configuration"]["activity"]["enable_m365_public_endpoint"] = False
                    elif field == "protocols":
                        endpoint["protocols"].remove("activity")
                    elif field == "pna":
                        azure.account["properties"]["publicNetworkAccess"] = "Disabled"
                    else:
                        endpoint[field] = {}
                self.azure.on_agent_read = changed
                if field == "pna":
                    original_arm = self.azure.arm
                    reads = 0
                    def changed_arm(method, resource_id, body=None, api_version=None):
                        nonlocal reads
                        if resource_id == ACCOUNT:
                            reads += 1
                            if reads == 3:
                                self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
                        return original_arm(method, resource_id, body, api_version)
                    self.azure.arm = changed_arm
                with self.assertRaisesRegex(RuntimeError, "verification"):
                    self.run_preparation(apply=True, botEnableM365PublicEndpoint=True)

    def test_apply_requires_real_boolean_not_a_truthy_string(self):
        with self.assertRaisesRegex(ValueError, "apply"):
            self.run_preparation(apply="false")
        self.assertEqual([], self.azure.calls)

    def test_no_publication_or_zip_or_inference_or_arm_writes(self):
        self.run_preparation(apply=True)
        self.assertTrue(all(call[0] in ("GET", "PATCH") for call in self.azure.calls))
        self.assertTrue(all(call[1] in (PROJECT, ACCOUNT, AGENT_URL) for call in self.azure.calls))


if __name__ == "__main__":
    unittest.main()
