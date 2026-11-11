from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agent_factory.azure import AzureError, AzureSession
from agent_factory.foundry_publishing import PreparationRequest
from agent_factory.m365_publishing import M365Publisher, PublicationUncertainError
from test_foundry_publishing import (
    AGENT, AGENT_URL, CLIENT, ENDPOINT, OTHER, SUB, TENANT, FakeAzure, values,
)


PUBLISH_URL = f"{ENDPOINT}/agents/{AGENT}/microsoft365/publish?api-version=v1"
DEFAULTS_URL = f"{ENDPOINT}/agents/{AGENT}/microsoft365/publishdefaults?api-version=v1"
METADATA = {
    "agentDisplayName": "Approved display name",
    "shortDescription": "Approved short description",
    "fullDescription": "Approved full description",
    "developerName": "Approved Publisher",
    "developerWebsiteUrl": "https://publisher.example",
    "privacyUrl": "https://publisher.example/privacy",
    "termsOfUseUrl": "https://publisher.example/terms",
}


class PublishingAzure(FakeAzure):
    def __init__(self):
        super().__init__()
        self.defaults = {"agentName": AGENT, "appRegistrationClientId": CLIENT}
        self.post_error = None
        self.publish_response = {"titleId": "published-title"}
        self.persist_publication = True
        self.on_defaults_read = None
        self.on_publish = None
        self.defaults_reads = 0

    def request(self, method, url, body=None, *, audience, headers=None):
        if url == AGENT_URL:
            return super().request(method, url, body, audience=audience, headers=headers)
        self.calls.append((method, url, deepcopy(body), {"audience": audience, "headers": headers}))
        if audience != "https://ai.azure.com":
            raise AssertionError("Unexpected token audience")
        if method == "GET" and url == DEFAULTS_URL:
            self.defaults_reads += 1
            if self.on_defaults_read:
                self.on_defaults_read(self, self.defaults_reads)
            return deepcopy(self.defaults)
        if method != "POST" or url != PUBLISH_URL:
            raise AssertionError("No inference, ZIP, separate bot creation, or alternate targets allowed")
        if self.post_error:
            raise self.post_error
        if self.persist_publication:
            self.defaults.update({
                **{key: value for key, value in body.items() if key in (*METADATA, "appVersion")},
                "appPublishScope": body["publishScope"],
                "titleId": "published-title", "teamsAppId": "published-teams-app",
                "recommendedNextAppVersion": "1.0.1",
            })
            self.agent["agent_endpoint"]["publish_approval_status"] = (
                "pending" if body["publishScope"] == "Tenant" else "no_approval_needed"
            )
        if self.on_publish:
            self.on_publish(self)
        return deepcopy(self.publish_response)


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.azure = PublishingAzure()
        self.sleep = Mock()
        self.publisher = M365Publisher(self.azure, sleep=self.sleep, verification_attempts=3)
        self.request = PreparationRequest.from_values(values())

    def publish(self, metadata=None, *, scope="Shared"):
        metadata = METADATA if metadata is None else metadata
        reviewed = self.publisher.plan(self.request, metadata, scope=scope)
        return self.publisher.apply(self.request, metadata, scope=scope, reviewed_plan=reviewed)

    def test_missing_metadata_is_a_read_only_blocked_plan(self):
        self.azure.defaults.update({
            "shortDescription": "Do not copy generated instructions",
            "developerName": "Unapproved server suggestion",
            "privacyUrl": "https://unapproved.example",
        })
        result = self.publisher.plan(self.request, {})
        self.assertEqual("plan", result["mode"])
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["block_reasons"])
        self.assertEqual(set(METADATA) - {"agentDisplayName"}, set(result["missing_fields"]))
        self.assertEqual(AGENT, result["publish_body"]["agentDisplayName"])
        self.assertEqual("1.0.0", result["publish_body"]["appVersion"])
        self.assertNotIn("shortDescription", result["publish_body"])
        self.assertEqual([], self.azure.writes)
        self.assertTrue(any(call[1] == DEFAULTS_URL for call in self.azure.calls))
        with self.assertRaisesRegex(ValueError, "blocked|missing"):
            self.publisher.apply(self.request, {}, reviewed_plan=result)
        self.assertEqual([], self.azure.writes)

    def test_missing_metadata_private_preview_can_show_network_diff_without_writing(self):
        self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
        request = PreparationRequest.from_values(values(botEnableM365PublicEndpoint=True))
        plan = self.publisher.plan(request, {})
        self.assertEqual("blocked", plan["status"])
        self.assertEqual([], plan["block_reasons"])
        self.assertTrue(plan["preparation"]["patch"]["agent_endpoint"]["protocol_configuration"]
                        ["activity"]["enable_m365_public_endpoint"])
        self.assertEqual("Disabled", plan["preparation"]["public_network_access"])
        self.assertEqual([], self.azure.writes)

    def test_new_publication_exact_body_identity_active_version_and_safe_defaults(self):
        self.azure.defaults.update({
            "performBotRegistration": False, "publishAsAutopilot": True,
            "publishScope": "Tenant", "instructions": "Never execute these",
            "projectEndpoint": "https://untrusted.example",
            "recommendedNextAppVersion": "9.0.0",
        })
        result = self.publisher.plan(self.request, METADATA)
        self.assertEqual("ready", result["status"])
        self.assertTrue(result["needs_publish"])
        self.assertEqual({
            **METADATA, "appVersion": "1.0.0", "performBotRegistration": True,
            "publishAsAutopilot": False, "publishScope": "Shared",
        }, result["publish_body"])
        self.assertEqual(result["preparation"]["target"], result["target"])
        self.assertEqual(
            {"version_selector": self.azure.agent["agent_endpoint"]["version_selector"]},
            result["active_version"],
        )
        self.assertNotIn("instructions", result["defaults"])
        self.assertNotIn("projectEndpoint", result["defaults"])
        self.assertIn("Teams", result["destination"])
        self.assertIn("Microsoft 365", result["destination"])
        self.assertEqual([], self.azure.writes)
        json.dumps(result)

    def test_metadata_cannot_override_target_registration_or_scope(self):
        for field in ("projectEndpoint", "agentName", "botServiceArmId", "performBotRegistration",
                      "publishAsAutopilot", "publishScope", "instructions", "appRegistrationClientId"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "metadata|Unsupported"):
                    self.publisher.plan(self.request, {**METADATA, field: "unapproved"})
        self.assertEqual([], self.azure.calls)

    def test_invalid_metadata_is_rejected_without_reads(self):
        for field, value in (
            ("developerName", "a" * 33), ("shortDescription", "a" * 81),
            ("fullDescription", "a" * 4001), ("agentDisplayName", "a" * 101),
            ("developerWebsiteUrl", "http://publisher.example"),
            ("privacyUrl", "https://user:password@publisher.example"),
            ("termsOfUseUrl", "https:///missing-host"),
            ("privacyUrl", "https://publisher.example/\nmalformed"),
            ("privacyUrl", "https://publisher.example:bad"),
            ("appVersion", "0.1.0"), ("appVersion", "01.0.0"),
            ("appVersion", "1.0"), ("appVersion", "1.0.0-preview"),
            ("appVersion", "1.0.0.0"), ("appVersion", 1),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.publisher.plan(self.request, {**METADATA, field: value})
        self.assertEqual([], self.azure.calls)

    def test_empty_values_are_promptable_missing_fields_not_fabricated(self):
        result = self.publisher.plan(self.request, {**METADATA, "privacyUrl": "  "})
        self.assertEqual(["privacyUrl"], result["missing_fields"])
        self.assertEqual("blocked", result["status"])

    def test_private_publication_preserves_pna_protocols_identity_and_routing(self):
        self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
        self.request = PreparationRequest.from_values(values(botEnableM365PublicEndpoint=True))
        original = deepcopy(self.azure.agent)
        result = self.publish()
        self.assertTrue(result["published"])
        self.assertEqual("published", result["status"])
        self.assertEqual("Disabled", self.azure.account["properties"]["publicNetworkAccess"])
        self.assertEqual(original["instance_identity"], self.azure.agent["instance_identity"])
        self.assertEqual(original["agent_endpoint"]["version_selector"],
                         result["active_version"]["version_selector"])
        self.assertEqual(original["agent_endpoint"]["version_selector"],
                         self.azure.agent["agent_endpoint"]["version_selector"])
        for key, value in original["agent_endpoint"]["protocol_configuration"].items():
            self.assertEqual(value, self.azure.agent["agent_endpoint"]["protocol_configuration"][key])
        for scheme in original["agent_endpoint"]["authorization_schemes"]:
            self.assertIn(scheme, self.azure.agent["agent_endpoint"]["authorization_schemes"])
        self.assertEqual(["PATCH", "POST"], [call[0] for call in self.azure.writes])
        self.assertEqual("published-title", result["title_id"])
        self.assertEqual("published-teams-app", result["teams_app_id"])
        self.assertEqual("no_approval_needed", result["approval_status"])
        self.assertFalse(result["store_discovery_verified"])
        self.assertFalse(result["conversation_verified"])

    def test_private_route_requires_reviewed_opt_in(self):
        self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
        with self.assertRaisesRegex(ValueError, "botEnableM365PublicEndpoint"):
            self.publisher.plan(self.request, METADATA)
        self.assertEqual([], self.azure.writes)

    def test_explicit_scope_changes_are_visible_and_preserve_unrelated_authorization(self):
        for old, scope, desired in (
            ("BotServiceRbac", "Tenant", "BotServiceTenant"),
            ("BotServiceTenant", "Shared", "BotServiceRbac"),
        ):
            with self.subTest(scope=scope):
                self.setUp()
                endpoint = self.azure.agent["agent_endpoint"]
                endpoint["authorization_schemes"].append({"type": old, "old_setting": True})
                plan = self.publisher.plan(self.request, METADATA, scope=scope)
                self.assertIn({"type": old, "old_setting": True},
                              plan["preparation"]["before"]["authorization_schemes"])
                self.assertNotIn(old, [v["type"] for v in plan["preparation"]["after"]["authorization_schemes"]])
                self.assertIn({"type": desired}, plan["preparation"]["after"]["authorization_schemes"])
                if scope == "Tenant":
                    self.assertIn("all tenant users", " ".join(plan["warnings"]))
                    self.assertIn("admin approval", " ".join(plan["warnings"]))
                result = self.publisher.apply(self.request, METADATA, scope=scope, reviewed_plan=plan)
                self.assertTrue(result["published"])
                self.assertEqual("pending_admin" if scope == "Tenant" else "published", result["status"])
                self.assertFalse(result["store_discovery_verified"])

    def test_scope_and_reviewed_action_cannot_change_on_apply(self):
        plan = self.publisher.plan(self.request, METADATA)
        with self.assertRaisesRegex((ValueError, RuntimeError), "reviewed|scope|body"):
            self.publisher.apply(self.request, METADATA, scope="Tenant", reviewed_plan=plan)
        for scope in ("Personal", "tenant", "", None):
            with self.assertRaises(ValueError):
                self.publisher.plan(self.request, METADATA, scope=scope)
        self.assertEqual([], self.azure.writes)

    def test_repeated_publication_is_noop_across_wrapper_instances(self):
        self.publish()
        self.azure.calls.clear()
        second = M365Publisher(self.azure, sleep=self.sleep)
        plan = second.plan(self.request, METADATA)
        self.assertEqual("unchanged", plan["status"])
        self.assertFalse(plan["needs_publish"])
        self.assertEqual("1.0.0", plan["publish_body"]["appVersion"])
        result = second.apply(self.request, METADATA, reviewed_plan=plan)
        self.assertEqual("unchanged", result["status"])
        self.assertTrue(result["published"])
        self.assertEqual([], self.azure.writes)

    def test_empty_metadata_uses_existing_published_metadata_without_bumping_version(self):
        self.publish()
        self.azure.calls.clear()
        plan = self.publisher.plan(self.request, {})
        self.assertEqual("unchanged", plan["status"])
        self.assertEqual([], plan["missing_fields"])
        self.assertEqual(METADATA["fullDescription"], plan["publish_body"]["fullDescription"])
        self.assertEqual([], self.azure.writes)

    def test_update_uses_recommended_version_only_for_changed_metadata(self):
        self.publish()
        self.azure.calls.clear()
        plan = self.publisher.plan(self.request, {"shortDescription": "Approved update"})
        self.assertTrue(plan["needs_publish"])
        self.assertEqual("1.0.1", plan["publish_body"]["appVersion"])
        self.assertEqual(METADATA["privacyUrl"], plan["publish_body"]["privacyUrl"])
        result = self.publisher.apply(self.request, {"shortDescription": "Approved update"}, reviewed_plan=plan)
        self.assertTrue(result["published"])
        self.assertEqual(["POST"], [call[0] for call in self.azure.writes])

    def test_update_requires_valid_new_version_or_explicit_override(self):
        self.publish()
        self.azure.calls.clear()
        for recommended in (None, "bad", "1.0.0"):
            with self.subTest(recommended=recommended):
                self.azure.defaults["recommendedNextAppVersion"] = recommended
                plan = self.publisher.plan(self.request, {"shortDescription": "Update"})
                self.assertEqual("blocked", plan["status"])
                self.assertIn("appVersion", plan["missing_fields"])
                self.assertIn("appVersion", " ".join(plan["warnings"]))
        with self.assertRaisesRegex(ValueError, "version|appVersion"):
            self.publisher.plan(self.request, {"shortDescription": "Update", "appVersion": "1.0.0"})
        explicit = self.publisher.plan(self.request, {"shortDescription": "Update", "appVersion": "2.0.0"})
        self.assertEqual("ready", explicit["status"])
        self.assertEqual("2.0.0", explicit["publish_body"]["appVersion"])
        self.assertEqual([], self.azure.writes)

    def test_unknown_published_scope_is_block_reason_not_promptable_metadata(self):
        self.publish()
        self.azure.defaults.pop("appPublishScope")
        self.azure.calls.clear()
        plan = self.publisher.plan(self.request, {})
        self.assertEqual("blocked", plan["status"])
        self.assertEqual([], plan["missing_fields"])
        self.assertIn("scope", " ".join(plan["block_reasons"]))
        with self.assertRaises(ValueError):
            self.publisher.apply(self.request, {}, reviewed_plan=plan)
        self.assertEqual([], self.azure.writes)

    def test_explicit_same_version_and_personal_scope_alias_remain_noop(self):
        self.publish()
        self.azure.defaults.update(appPublishScope="Personal", recommendedNextAppVersion="invalid")
        self.azure.calls.clear()
        result = self.publish({"appVersion": "1.0.0"})
        self.assertEqual("unchanged", result["status"])
        self.assertTrue(result["published"])
        self.assertEqual([], self.azure.writes)

    def test_scope_only_update_uses_new_version_and_requires_admin_approval(self):
        self.publish()
        self.azure.calls.clear()
        plan = self.publisher.plan(self.request, {}, scope="Tenant")
        self.assertEqual("1.0.1", plan["publish_body"]["appVersion"])
        self.assertTrue(plan["needs_publish"])
        result = self.publisher.apply(self.request, {}, scope="Tenant", reviewed_plan=plan)
        self.assertEqual("pending_admin", result["status"])
        self.assertEqual("pending", result["approval_status"])
        self.assertEqual(["PATCH", "POST"], [call[0] for call in self.azure.writes])

    def test_stale_reviewed_body_target_metadata_version_and_scope_reject_before_writes(self):
        for change in ("body", "identity", "metadata", "version", "scope", "routing", "authorization", "network"):
            with self.subTest(change=change):
                self.setUp()
                self.publish()
                plan = self.publisher.plan(self.request, {"shortDescription": "Update"})
                self.azure.calls.clear()
                if change == "body":
                    plan["publish_body"]["privacyUrl"] = "https://other.example"
                elif change == "identity":
                    self.azure.agent["instance_identity"]["client_id"] = OTHER
                elif change == "routing":
                    self.azure.agent["agent_endpoint"]["version_selector"] = {}
                elif change == "authorization":
                    self.azure.agent["agent_endpoint"]["authorization_schemes"].append({"type": "NewAuth"})
                elif change == "network":
                    self.azure.account["properties"]["publicNetworkAccess"] = "Disabled"
                else:
                    self.azure.defaults[{"metadata": "shortDescription", "version": "appVersion",
                                         "scope": "appPublishScope"}[change]] = {
                                             "metadata": "Concurrent update", "version": "3.0.0",
                                             "scope": "Tenant"}[change]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.publisher.apply(self.request, {"shortDescription": "Update"}, reviewed_plan=plan)
                self.assertEqual([], self.azure.writes)

    def test_concurrent_protocol_additions_are_preserved(self):
        plan = self.publisher.plan(self.request, METADATA)
        self.azure.agent["agent_endpoint"]["protocol_configuration"]["future"] = {"keep": True}
        self.azure.agent["agent_endpoint"]["protocols"].append("future")
        result = self.publisher.apply(self.request, METADATA, reviewed_plan=plan)
        self.assertTrue(result["published"])
        self.assertEqual({"keep": True},
                         self.azure.agent["agent_endpoint"]["protocol_configuration"]["future"])

    def test_routing_change_between_replan_and_preparation_is_rejected_before_patch(self):
        plan = self.publisher.plan(self.request, METADATA)
        def concurrent(azure, number):
            if number == 3:
                azure.agent["agent_endpoint"]["version_selector"] = {}
        self.azure.on_agent_read = concurrent
        with self.assertRaisesRegex(RuntimeError, "routing|version|reviewed"):
            self.publisher.apply(self.request, METADATA, reviewed_plan=plan)
        self.assertEqual([], self.azure.writes)

    def use_latest(self, *, traffic=100):
        self.azure.agent["agent_endpoint"]["version_selector"] = {
            "version_selection_rules": [
                {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": traffic},
            ],
        }
        self.azure.agent["versions"]["latest"].update(
            id="agent-version-7", definition={"instructions": "Never include model instructions", "tools": []},
        )

    def test_latest_preview_resolves_only_version_and_id_alongside_selector(self):
        self.use_latest()
        plan = self.publisher.plan(self.request, METADATA)
        self.assertEqual({
            "version_selector": self.azure.agent["agent_endpoint"]["version_selector"],
            "resolved_latest": {"version": "7", "id": "agent-version-7"},
        }, plan["active_version"])
        self.assertEqual(plan["active_version"], plan["preparation"]["active_version"])
        self.assertNotIn("Never include model instructions", json.dumps(plan))
        self.assertNotIn('"tools"', json.dumps(plan))
        self.assertEqual([], self.azure.writes)

    def test_latest_version_or_id_drift_requires_fresh_review_before_writes(self):
        for field in ("version", "id"):
            with self.subTest(field=field):
                self.setUp()
                self.use_latest()
                plan = self.publisher.plan(self.request, METADATA)
                self.azure.agent["versions"]["latest"][field] = "8"
                with self.assertRaisesRegex(RuntimeError, "active_version|reviewed"):
                    self.publisher.apply(self.request, METADATA, reviewed_plan=plan)
                self.assertEqual([], self.azure.writes)

    def test_fixed_route_ignores_unrelated_newer_version_before_apply(self):
        plan = self.publisher.plan(self.request, METADATA)
        self.azure.agent["versions"]["latest"] = {"version": "8", "id": "agent-version-8"}
        result = self.publisher.apply(self.request, METADATA, reviewed_plan=plan)
        self.assertTrue(result["published"])
        self.assertEqual(plan["active_version"], result["active_version"])
        self.assertNotIn("resolved_latest", result["active_version"])

    def test_latest_drift_in_preparation_fresh_read_rejects_before_patch(self):
        self.use_latest()
        plan = self.publisher.plan(self.request, METADATA)
        def concurrent(azure, number):
            if number == 3:
                azure.agent["versions"]["latest"]["version"] = "8"
        self.azure.on_agent_read = concurrent
        with self.assertRaises(PublicationUncertainError):
            self.publisher.apply(self.request, METADATA, reviewed_plan=plan)
        self.assertEqual([], self.azure.writes)

    def test_fixed_route_allows_unrelated_new_version_during_patch_readback(self):
        def concurrent(azure, number):
            if number == 4:
                azure.agent["versions"]["latest"] = {"version": "8"}
        self.azure.on_agent_read = concurrent
        result = self.publish()
        self.assertTrue(result["published"])
        self.assertEqual("8", self.azure.agent["versions"]["latest"]["version"])

    def test_post_publication_latest_drift_is_uncertain_but_fixed_route_is_unaffected(self):
        for latest in (False, True):
            with self.subTest(latest=latest):
                self.setUp()
                if latest:
                    self.use_latest()
                self.azure.on_publish = lambda azure: azure.agent["versions"].update(
                    latest={"version": "8", "id": "agent-version-8"},
                )
                if latest:
                    with self.assertRaises(PublicationUncertainError):
                        self.publish()
                else:
                    self.assertTrue(self.publish()["published"])
                self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_missing_latest_resolution_blocks_publication_without_writes(self):
        self.use_latest()
        self.azure.agent["versions"]["latest"] = {}
        with self.assertRaisesRegex(ValueError, "latest|version"):
            self.publisher.plan(self.request, METADATA)
        self.assertEqual([], self.azure.writes)

    def test_zero_traffic_latest_rule_does_not_bind_unused_version(self):
        self.use_latest(traffic=0)
        self.azure.agent["agent_endpoint"]["version_selector"]["version_selection_rules"].append(
            {"type": "FixedRatio", "agent_version": "4", "traffic_percentage": 100},
        )
        plan = self.publisher.plan(self.request, METADATA)
        self.assertNotIn("resolved_latest", plan["active_version"])
        self.azure.agent["versions"]["latest"] = {"version": "8"}
        self.assertTrue(self.publisher.apply(self.request, METADATA, reviewed_plan=plan)["published"])

    def test_defaults_identity_mismatch_or_legacy_agent_never_writes(self):
        for field in ("agentName", "appRegistrationClientId", "instance_identity"):
            with self.subTest(field=field):
                self.setUp()
                if field == "instance_identity":
                    self.azure.agent[field] = {}
                else:
                    self.azure.defaults[field] = OTHER
                with self.assertRaisesRegex(ValueError, "identity|name|legacy|client"):
                    self.publisher.plan(self.request, METADATA)
                self.assertEqual([], self.azure.writes)

    def test_registration_errors_and_transient_failures_are_uncertain_never_retried(self):
        for error in (
            AzureError(400, "POST", PUBLISH_URL, "Bot registration feature is not enabled"),
            AzureError(503, "POST", PUBLISH_URL, "Unavailable"),
            TimeoutError("Bearer secret-token-should-not-leak"),
        ):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.azure.post_error = error
                with self.assertRaises(PublicationUncertainError) as raised:
                    self.publish()
                self.assertIn("may already be prepared", str(raised.exception))
                self.assertIn("uncertain", str(raised.exception))
                self.assertNotIn("secret-token-should-not-leak", str(raised.exception))
                self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))
                if getattr(error, "status", None) == 400:
                    self.assertIn("registration", str(raised.exception).lower())

    def test_service_failure_code_and_actionable_message_are_preserved_safely(self):
        for status, code, message in (
            (400, "BotRegistrationFeatureNotEnabled", "Direct registration is disabled for this project."),
            (403, "AuthorizationFailed", "Caller lacks the required agent write permission."),
            (400, "InvalidDeveloperName", "Developer name cannot exceed length of 32."),
        ):
            with self.subTest(code=code):
                self.setUp()
                self.azure.post_error = AzureError(status, "POST", PUBLISH_URL, json.dumps({
                    "error": {"code": code, "message": message,
                              "request": {"access_token": "do-not-copy-unrelated-response-fields"}},
                }))
                with self.assertRaises(PublicationUncertainError) as raised:
                    self.publish()
                self.assertEqual(code, raised.exception.cause_code)
                self.assertEqual(message, raised.exception.cause_message)
                self.assertIn(code, str(raised.exception))
                self.assertIn(message, str(raised.exception))
                self.assertNotIn("do-not-copy-unrelated-response-fields", str(raised.exception))
                self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_cause_redacts_authentication_secrets_but_keeps_failure_reason(self):
        secrets = {
            "bearer": "bearer-secret-value",
            "access": "access-secret-value",
            "refresh": "refresh-secret-value",
            "client": "client-secret-value",
            "jwt": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ0ZXN0In0.signature",
            "credentials": "credential-secret-value",
            "basic": "basic-auth-secret-value",
        }
        diagnostic = (
            "Registration denied. Bearer " + secrets["bearer"] + "; "
            'access_token="' + secrets["access"] + '"; '
            "'refreshToken': '" + secrets["refresh"] + "'; "
            "client_secret=" + secrets["client"] + "; "
            "https://user:" + secrets["credentials"] + "@service.example; "
            "Authorization: Basic " + secrets["basic"] + "; "
            + secrets["jwt"]
        )
        self.azure.post_error = AzureError(403, "POST", PUBLISH_URL, json.dumps({
            "error": {"code": "RegistrationDenied", "message": diagnostic},
        }))
        with self.assertRaises(PublicationUncertainError) as raised:
            self.publish()
        self.assertIn("Registration denied", raised.exception.cause_message)
        for value in secrets.values():
            self.assertNotIn(value, str(raised.exception))
            self.assertNotIn(value, raised.exception.cause_message)
        self.assertIn("[REDACTED]", raised.exception.cause_message)

    def test_plain_text_feature_diagnostic_is_not_lost(self):
        self.azure.post_error = AzureError(
            400, "POST", PUBLISH_URL, "Bot registration is unsupported: enable DirectRegistrationPreview.",
        )
        with self.assertRaisesRegex(PublicationUncertainError, "DirectRegistrationPreview"):
            self.publish()

    def test_programming_errors_are_not_flattened_into_publication_uncertainty(self):
        for stage in ("preparation", "publication", "verification"):
            with self.subTest(stage=stage):
                self.setUp()
                error = TypeError("Unexpected internal programmer failure")
                if stage == "publication":
                    self.azure.post_error = error
                elif stage == "preparation":
                    def broken(azure, number):
                        if number == 3:
                            raise error
                    self.azure.on_agent_read = broken
                else:
                    def broken(azure, number):
                        if number == 4:
                            raise error
                    self.azure.on_defaults_read = broken
                with self.assertRaises(TypeError) as raised:
                    self.publish()
                self.assertIs(error, raised.exception)
                self.assertEqual(0 if stage == "preparation" else 1,
                                 sum(call[0] == "POST" for call in self.azure.calls))

    def test_success_response_without_persisted_publication_is_pending_not_success(self):
        self.azure.persist_publication = False
        result = self.publish()
        self.assertFalse(result["published"])
        self.assertEqual("pending_verification", result["status"])
        self.assertEqual("published-title", result["title_id"])
        self.assertFalse(result["store_discovery_verified"])
        self.assertFalse(result["conversation_verified"])
        self.assertEqual(2, self.sleep.call_count)
        self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_eventual_publication_is_verified_with_bounded_get_polling(self):
        self.azure.persist_publication = False
        def eventually(azure, number):
            if number == 5:
                azure.defaults.update({
                    **METADATA, "appVersion": "1.0.0", "appPublishScope": "Shared",
                    "titleId": "published-title", "teamsAppId": "published-teams-app",
                })
        self.azure.on_defaults_read = eventually
        result = self.publish()
        self.assertTrue(result["published"])
        self.assertEqual("published", result["status"])
        self.assertEqual(1, self.sleep.call_count)
        self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_post_publication_read_failure_is_uncertain_not_republished(self):
        def denied(azure, number):
            if number >= 4:
                raise AzureError(403, "GET", DEFAULTS_URL, "Do not echo Bearer hidden-token")
        self.azure.on_defaults_read = denied
        with self.assertRaises(PublicationUncertainError) as raised:
            self.publish()
        self.assertEqual(403, raised.exception.http_status)
        self.assertNotIn("hidden-token", str(raised.exception))
        self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_title_id_mismatch_does_not_confirm_the_submitted_publication(self):
        self.azure.on_publish = lambda azure: azure.defaults.update(titleId="another-title")
        result = self.publish()
        self.assertFalse(result["published"])
        self.assertEqual("pending_verification", result["status"])

    def test_returned_teams_app_id_must_match_persisted_id(self):
        for include_title in (False, True):
            with self.subTest(include_title=include_title):
                self.setUp()
                self.azure.publish_response = {
                    **({"titleId": "published-title"} if include_title else {}),
                    "teamsAppId": "different-submission-app",
                }
                result = self.publish()
                self.assertFalse(result["published"])
                self.assertEqual("pending_verification", result["status"])
                self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_matching_returned_teams_app_id_verifies_with_or_without_returned_title(self):
        for include_title in (False, True):
            with self.subTest(include_title=include_title):
                self.setUp()
                self.azure.publish_response = {
                    **({"titleId": "published-title"} if include_title else {}),
                    "teamsAppId": "published-teams-app",
                }
                result = self.publish()
                self.assertTrue(result["published"])
                self.assertEqual("published-teams-app", result["teams_app_id"])

    def test_pending_readback_retains_returned_teams_app_id_without_claiming_success(self):
        self.azure.persist_publication = False
        self.azure.publish_response["teamsAppId"] = "submitted-teams-app"
        result = self.publish()
        self.assertFalse(result["published"])
        self.assertEqual("pending_verification", result["status"])
        self.assertEqual("submitted-teams-app", result["teams_app_id"])

    def test_post_write_metadata_scope_or_version_mismatch_is_not_success(self):
        for field, value in (("privacyUrl", "https://wrong.example"), ("appPublishScope", "Tenant"),
                             ("appVersion", "9.0.0")):
            with self.subTest(field=field):
                self.setUp()
                self.azure.on_publish = lambda azure: azure.defaults.update({field: value})
                result = self.publish()
                self.assertEqual("pending_verification", result["status"])
                self.assertFalse(result["published"])
                self.assertIn("verification", " ".join(result["warnings"]))
                self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_post_write_identity_routing_and_protocol_loss_are_uncertain(self):
        for field in ("instance_identity", "version_selector", "protocol_configuration"):
            with self.subTest(field=field):
                self.setUp()
                def changed(azure):
                    if field == "instance_identity":
                        azure.agent[field]["client_id"] = OTHER
                    else:
                        azure.agent["agent_endpoint"][field] = {}
                        if field == "protocol_configuration":
                            azure.agent["agent_endpoint"]["protocols"] = []
                self.azure.on_publish = changed
                with self.assertRaises(PublicationUncertainError):
                    self.publish()
                self.assertEqual(1, sum(call[0] == "POST" for call in self.azure.calls))

    def test_defaults_change_during_preparation_blocks_post_with_prepared_warning(self):
        plan = self.publisher.plan(self.request, METADATA)
        def changed(azure, number):
            if number == 3:
                azure.defaults["titleId"] = "another-publisher"
        self.azure.on_defaults_read = changed
        with self.assertRaisesRegex(PublicationUncertainError, "prepared|uncertain"):
            self.publisher.apply(self.request, METADATA, reviewed_plan=plan)
        self.assertEqual(["PATCH"], [call[0] for call in self.azure.writes])

    def test_approval_is_read_from_endpoint_not_defaults_or_post_response(self):
        self.azure.defaults["publish_approval_status"] = "approved"
        self.azure.on_publish = lambda azure: azure.agent["agent_endpoint"].pop("publish_approval_status")
        result = self.publish(scope="Tenant")
        self.assertTrue(result["published"])
        self.assertEqual("pending_admin", result["status"])
        self.assertIsNone(result["approval_status"])

    def test_rejected_catalog_submission_is_not_presented_as_approved(self):
        self.azure.on_publish = lambda azure: azure.agent["agent_endpoint"].update(
            publish_approval_status="rejected",
        )
        result = self.publish(scope="Tenant")
        self.assertEqual("rejected", result["status"])
        self.assertTrue(result["published"])
        self.assertFalse(result["store_discovery_verified"])

    def test_explicit_not_published_endpoint_status_is_not_success(self):
        self.azure.on_publish = lambda azure: azure.agent["agent_endpoint"].update(
            publish_approval_status="not_published",
        )
        result = self.publish()
        self.assertFalse(result["published"])
        self.assertEqual("pending_verification", result["status"])
        self.assertEqual("not_published", result["approval_status"])

    def test_apply_requires_real_review_and_preserves_input_documents(self):
        with self.assertRaises(ValueError):
            self.publisher.apply(self.request, METADATA, reviewed_plan={})
        self.assertEqual([], self.azure.calls)
        plan = json.loads(json.dumps(self.publisher.plan(self.request, METADATA)))
        before = deepcopy(plan)
        metadata = deepcopy(METADATA)
        self.publisher.apply(self.request, metadata, reviewed_plan=plan)
        self.assertEqual(before, plan)
        self.assertEqual(METADATA, metadata)

    def test_existing_transport_does_not_retry_publish_post(self):
        session = AzureSession(SUB, TENANT)
        opener = Mock()
        opener.open.side_effect = HTTPError(PUBLISH_URL, 503, "Unavailable", {}, BytesIO(b"Unavailable"))
        with patch.object(session, "token", return_value="not-a-real-token"), \
                patch("agent_factory.azure.build_opener", return_value=opener), \
                patch("agent_factory.azure.time.sleep") as sleep:
            with self.assertRaises(AzureError):
                session.request("POST", PUBLISH_URL, {}, audience="https://ai.azure.com")
        self.assertEqual(1, opener.open.call_count)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
