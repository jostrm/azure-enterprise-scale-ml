"""Offline identity boundary unit tests; these are not live ACL evidence."""
import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sales_demo.identity import (
    DelegatedAuthorization, ManagedIdentitySearchTransport, SalesUnavailable, backend_credential,
    AzureCliTokenProvider, GraphTransport, GROUP_PATH, GRAPH,
)


TENANT = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
GROUP = "33333333-3333-3333-3333-333333333333"


def token(resource, **changes):
    claims = {"tid": TENANT, "oid": USER, "aud": resource, "scp": "User.Read",
              "exp": int(time.time()) + 3600, **changes}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class Provider:
    def __init__(self, changes=None):
        self.calls = []
        self.changes = changes or {}

    def token(self, resource):
        self.calls.append(resource)
        return token(resource, **self.changes.get(resource, {}))


class Graph:
    def __init__(self):
        self.calls = []
        self.user = USER
        self.groups = [GROUP]

    def get(self, url, bearer):
        self.calls.append((url, bearer))
        if url.endswith("/me?$select=id"):
            return {"id": self.user}
        return {"value": [{"id": group} for group in self.groups]}


class IdentityTests(unittest.TestCase):
    def test_graph_authenticates_identity_and_refreshes_membership(self):
        provider, graph = Provider(), Graph()
        auth = DelegatedAuthorization(TENANT, provider, graph)
        first = auth.authorize()
        graph.groups = []
        second = auth.authorize()
        self.assertEqual(first.oid, USER)
        self.assertEqual(first.group_ids, frozenset({GROUP}))
        self.assertFalse(second.group_ids)
        self.assertEqual(len(provider.calls), 6)
        self.assertTrue(all("$count=true" in url for url, _ in graph.calls if GROUP_PATH in url))
        self.assertNotIn(first.search_token, repr(first))

    def test_mismatched_or_app_only_tokens_never_establish_user(self):
        variants = [
            {"oid": GROUP}, {"tid": GROUP}, {"scp": ""}, {"idtyp": "app"},
            {"exp": 1}, {"aud": "https://attacker.example"},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                auth = DelegatedAuthorization(
                    TENANT, Provider({"https://storage.azure.com": changes}), Graph())
                with self.assertRaisesRegex(SalesUnavailable, "^Sales data unavailable\\.$"):
                    auth.authorize()

    def test_unverified_claims_do_not_replace_graph_me(self):
        graph = Graph()
        graph.user = GROUP
        with self.assertRaises(SalesUnavailable):
            DelegatedAuthorization(TENANT, Provider(), graph).authorize()

    def test_group_paging_rejects_redirect_cycle_and_empty_middle(self):
        for next_link in [
            "https://attacker.example/groups",
            "https://graph.microsoft.com/v1.0/me/transitiveMemberOf/microsoft.graph.group?$select=id&$top=999",
        ]:
            graph = Graph()
            original = graph.get

            def get(url, bearer):
                if "/me?" in url:
                    return original(url, bearer)
                return {"value": [{"id": GROUP}], "@odata.nextLink": next_link}

            graph.get = get
            with self.assertRaises(SalesUnavailable):
                DelegatedAuthorization(TENANT, Provider(), graph).authorize()
        graph = Graph()
        graph.get = lambda url, bearer: (
            {"id": USER} if "/me?" in url else
            {"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/transitiveMemberOf/microsoft.graph.group?$skiptoken=1"}
        )
        with self.assertRaises(SalesUnavailable):
            DelegatedAuthorization(TENANT, Provider(), graph).authorize()

    def test_backend_is_explicit_managed_identity_only(self):
        with self.assertRaises(ValueError):
            backend_credential("")
        with patch("azure.identity.ManagedIdentityCredential") as credential:
            backend_credential(GROUP)
            credential.assert_called_once_with(client_id=GROUP)

    def test_backend_transport_never_accepts_unscoped_or_operator_fallback_requests(self):
        config = {"search_endpoint": "https://demo.search.windows.net", "backend_identity_client_id": GROUP}
        with patch("sales_demo.identity.backend_credential") as credential:
            transport = ManagedIdentitySearchTransport(config)
            credential.assert_called_once_with(GROUP)
            for method, url, headers in [
                ("POST", "https://evil.example/indexes/i/docs/search", {"x-ms-query-source-authorization": "u"}),
                ("POST", "https://demo.search.windows.net/indexes/i/docs/search", {}),
                ("PUT", "https://demo.search.windows.net/indexes/i", {}),
                ("POST", "https://demo.search.windows.net/indexers/i/run", {}),
                ("GET", "https://demo.search.windows.net/indexers/i/status", {"Authorization": "Bearer operator"}),
            ]:
                with self.subTest(url=url, method=method), self.assertRaises(SalesUnavailable):
                    transport.request(method, url, headers=headers)
            credential.return_value.get_token.assert_not_called()

    def test_backend_unavailable_does_not_switch_to_cli(self):
        config = {"search_endpoint": "https://demo.search.windows.net", "backend_identity_client_id": GROUP}
        with patch("sales_demo.identity.backend_credential") as credential, patch(
            "sales_demo.identity.subprocess.run"
        ) as cli, patch("agent_factory.data.require_private_endpoint"):
            credential.return_value.get_token.side_effect = RuntimeError("MI unavailable")
            transport = ManagedIdentitySearchTransport(config)
            with self.assertRaises(RuntimeError):
                transport.request("POST", config["search_endpoint"] + "/indexes/i/docs/search",
                                  headers={"x-ms-query-source-authorization": "user"})
            cli.assert_not_called()

    def test_separate_cli_profiles_use_separate_subprocess_environments(self):
        directory = Path(__file__).resolve().parent
        with patch("sales_demo.identity.shutil.which", return_value="az"), patch(
            "sales_demo.identity.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps({
                "tenant": TENANT, "accessToken": token("https://search.azure.com")})),
        ) as cli:
            provider = AzureCliTokenProvider(TENANT, GROUP, config_dir=directory)
            provider.token("https://search.azure.com")
            self.assertEqual(cli.call_args.kwargs["env"]["AZURE_CONFIG_DIR"], str(directory))
            self.assertIn("--tenant", cli.call_args.args[0])
            self.assertNotIn("--subscription", cli.call_args.args[0])

    def test_graph_cast_queries_carry_advanced_query_consistency_header(self):
        with patch("sales_demo.identity.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"value":[]}'
            GraphTransport().get(GRAPH + GROUP_PATH + "?$count=true", "trusted-local-token")
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("Consistencylevel"), "eventual")


if __name__ == "__main__":
    unittest.main()
