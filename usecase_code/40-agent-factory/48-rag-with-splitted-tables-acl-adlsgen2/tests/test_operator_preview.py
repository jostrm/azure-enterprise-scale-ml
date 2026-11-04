"""Single-user preview is never evidence of restricted-user ACL acceptance."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sales_demo.configuration import readiness
from sales_demo.operator_preview import (
    PreviewSearchTransport, require_preview_policy, verified_preview_identity,
    summarize_preview_evaluation,
)
from sales_demo.identity import SalesUnavailable, UserIdentity
from test_identity import TENANT, USER, GROUP, token

spec = importlib.util.spec_from_file_location("sales_preview_entry", Path(__file__).resolve().parents[1] / "preview.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def configuration():
    return {
        "evaluation_mode": "operator-preview", "operator_preview_user_id": USER,
        "tenant_id": TENANT, "denied_test_user_ids": [], "paths_approved": True,
        "search_endpoint": "https://demo.search.windows.net",
        "embedding_endpoint": "https://models.openai.azure.com",
        "project_endpoint": "https://models.services.ai.azure.com/api/projects/demo",
        "backend_identity_client_id": GROUP, "search_identity_object_id": GROUP,
        "embedding_deployment": "text-embedding-3-large",
        "partitions": [{"id": source, "allowed_user_ids": [USER], "allowed_group_ids": []}
                       for source in ("json", "excel")],
    }


class PreviewTests(unittest.TestCase):
    def test_explicit_mode_and_one_user_only(self):
        self.assertEqual(require_preview_policy(configuration()), USER)
        for mutate in (
            lambda c: c.pop("evaluation_mode"),
            lambda c: c.update(evaluation_mode="strict"),
            lambda c: c.update(denied_test_user_ids=[USER]),
            lambda c: c["partitions"][0].update(allowed_group_ids=[GROUP]),
            lambda c: c["partitions"][1].update(allowed_user_ids=[GROUP]),
        ):
            config = copy.deepcopy(configuration())
            mutate(config)
            with self.assertRaises(ValueError):
                require_preview_policy(config)

    def test_readiness_still_defaults_to_full_acl_prerequisites(self):
        config = configuration()
        self.assertTrue(readiness(config))
        self.assertEqual(readiness(config, require_acl_test=False), [])
        config["partitions"][0]["allowed_user_ids"] = []
        self.assertTrue(readiness(config, require_acl_test=False))

    def test_authenticated_identity_must_match_bound_user(self):
        config = configuration()
        identity = UserIdentity(TENANT, USER, frozenset(), "search", "storage")
        auth = SimpleNamespace(authorize=lambda: identity)
        self.assertEqual(verified_preview_identity(config, auth), identity)
        for changed in (
            UserIdentity(TENANT, GROUP, frozenset(), "search", "storage"),
            UserIdentity(GROUP, USER, frozenset(), "search", "storage"),
        ):
            with self.assertRaises(SalesUnavailable):
                verified_preview_identity(config, SimpleNamespace(authorize=lambda: changed))

    def test_preview_transport_requires_native_header_and_disallows_mutations(self):
        config = configuration()
        session = SimpleNamespace(token=lambda audience: token(audience))
        transport = PreviewSearchTransport(config, session)
        for method, url, headers in (
            ("POST", config["search_endpoint"] + "/indexes/i/docs/search", {}),
            ("PUT", config["search_endpoint"] + "/indexes/i", {}),
            ("GET", "https://evil.example/indexers/i/status", {}),
            ("POST", config["search_endpoint"] + "/indexes/i/docs/search",
             {"x-ms-query-source-authorization": token("https://search.azure.com", oid=GROUP)}),
        ):
            with self.assertRaises(SalesUnavailable):
                transport.request(method, url, headers=headers)

    def test_preview_transport_forwards_user_token_without_elevated_read(self):
        config = configuration()
        user_token = token("https://search.azure.com")
        session = SimpleNamespace(token=lambda audience: user_token, _tokens={
            "https://search.azure.com": (9999999999, user_token),
        })
        transport = PreviewSearchTransport(config, session)
        with patch("agent_factory.data.require_private_endpoint"), patch("sales_demo.identity.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"value":[]}'
            transport.request("POST", config["search_endpoint"] + "/indexes/i/docs/search",
                              {"search": "*"}, headers={"x-ms-query-source-authorization": user_token})
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("X-ms-query-source-authorization"), user_token)
            self.assertIsNone(request.get_header("X-ms-enable-elevated-read"))

    def test_preview_cannot_turn_positive_cases_into_full_acl_pass(self):
        result = summarize_preview_evaluation({"live": True, "passed": False, "cases": [{"passed": True}]})
        self.assertTrue(result["authorized_cases_passed"])
        self.assertFalse(result["passed"])
        self.assertFalse(result["complete_acl_acceptance"])
        self.assertEqual(result["restricted_identity"]["state"], "not-tested")

    def test_preview_command_keeps_mutation_and_paid_gates(self):
        for command in ("publish", "configure", "ingest", "deploy", "resync"):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "--apply"):
                entry.run(entry.parser().parse_args([command]))
        for command in ("configure", "ingest", "deploy", "ask", "evaluate"):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "--allow-paid"):
                entry.run(entry.parser().parse_args([command, "--apply"]))


if __name__ == "__main__":
    unittest.main()
