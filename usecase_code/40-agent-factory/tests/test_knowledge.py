import copy
import json
import unittest
from unittest.mock import patch

from agent_factory.azure import AzureError
from agent_factory.config import Target
from agent_factory import data, knowledge


def target():
    return Target(
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id="22222222-2222-2222-2222-222222222222",
        resource_group="project-rg", common_resource_group="common-rg",
        account_name="foundry-account", project_name="project-001",
        project_endpoint="https://foundry-account.services.ai.azure.com/api/projects/project-001",
        location="swedencentral", model_deployment="chat", embedding_deployment="",
        search_name="project-search", storage_name="aifstorage2001",
        identity_id="/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/project-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/project-mi",
        identity_client_id="33333333-3333-3333-3333-333333333333",
    )


class FakeSession:
    def __init__(self):
        self.calls = []
        self.resources = {}
        self.index = data.index_schema("aif-kaggle-rag-v1")
        self.count = 2
        self.semantic = True
        self.service = {"sku": {"name": "basic"}, "properties": {"publicNetworkAccess": "disabled", "semanticSearch": "free"}}
        self.retrieve_response = {
            "references": [{"type": "searchIndex", "docKey": "known-document", "id": "0", "activitySource": 0}],
            "response": [{"content": [{"type": "text", "text": '[{"content":"Use the VPN client."}]'}]}],
            "activity": [{"type": "searchIndex", "id": 0, "count": 1}],
        }

    def request(self, method, url, body=None, **kwargs):
        self.calls.append((method, url, copy.deepcopy(body), kwargs))
        if "/docs/search?" in url:
            if body.get("queryType") == "semantic":
                return {"value": [{"id": "known-document", "@search.rerankerScore": 3.1}]} if self.semantic else {"value": []}
            return {"@odata.count": self.count, "value": [{"id": "known-document", "topic": "VPN", "content": "Use VPN."}]} if self.count else {"@odata.count": 0, "value": []}
        if "/indexes/" in url:
            return self.index
        if "/retrieve?" in url:
            return self.retrieve_response
        if method == "GET":
            if url not in self.resources:
                raise AzureError(404, method, url, "missing")
            return copy.deepcopy(self.resources[url])
        if method == "PUT":
            self.resources[url] = copy.deepcopy(body)
            return copy.deepcopy(body)
        raise AssertionError((method, url, body))

    def arm(self, method, resource_id, body=None, api_version=None):
        if "/Microsoft.Search/searchServices/" in resource_id:
            self.calls.append((method, resource_id, copy.deepcopy(body), {"api_version": api_version}))
            return self.service
        return self.request(method, resource_id, body, api_version=api_version)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        private = patch.object(knowledge, "require_private_endpoint")
        private.start()
        self.addCleanup(private.stop)

    def configure(self):
        return knowledge.configure_knowledge(self.session, target())

    def test_basic_existing_index_bodies_and_mcp_scope(self):
        result = self.configure()
        put_calls = [(url, body) for method, url, body, _ in self.session.calls if method == "PUT"]
        self.assertEqual(len(put_calls), 3)
        source = next(body for url, body in put_calls if "/knowledgesources/" in url)
        self.assertEqual(source["kind"], "searchIndex")
        self.assertEqual(source["searchIndexParameters"]["searchIndexName"], "aif-kaggle-rag-v1")
        self.assertNotIn("azureBlob", json.dumps(put_calls))
        self.assertNotIn("embedding", json.dumps(put_calls))
        self.assertNotIn("sample_ground_truth", json.dumps(put_calls))
        base = next(body for url, body in put_calls if "/knowledgebases/" in url)
        self.assertEqual(base["retrievalReasoningEffort"], {"kind": "minimal"})
        self.assertEqual(base["outputMode"], "extractiveData")
        self.assertNotIn("models", base)
        connection = next(body["properties"] for url, body in put_calls if "/connections/" in url)
        self.assertEqual(connection["authType"], "ProjectManagedIdentity")
        self.assertEqual(connection["category"], "RemoteTool")
        self.assertEqual(connection["audience"], "https://search.azure.com/")
        self.assertFalse(connection["isSharedToAll"])
        self.assertEqual(connection["metadata"], {"ApiType": "Azure"})
        self.assertIn(f"{target().project_id}/connections/", result["connection_id"])
        tool = result["tool"]
        self.assertEqual(tool["project_connection_id"], result["connection_name"])
        self.assertEqual(tool["allowed_tools"], ["knowledge_base_retrieve"])
        self.assertEqual(tool["require_approval"], "never")
        self.assertEqual(tool["server_url"], connection["target"])
        self.assertTrue(tool["server_url"].startswith(target().search_endpoint))
        self.assertIn("api-version=2026-08-01-preview", tool["server_url"])
        self.assertFalse(result["retrieval_verified"])
        self.assertFalse(result["embeddings_required"])
        self.assertFalse(any(method in {"PATCH", "DELETE"} for method, *_ in self.session.calls))

    def test_rerun_is_read_only(self):
        self.configure()
        self.session.calls.clear()
        self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_zero_docs_refused_before_any_wiring(self):
        self.session.count = 0
        with self.assertRaisesRegex(RuntimeError, "no searchable"):
            self.configure()
        self.assertFalse(self.session.resources)

    def test_semantic_disabled_or_quota_refused_without_upgrade(self):
        self.session.service["properties"]["semanticSearch"] = "disabled"
        with self.assertRaisesRegex(ValueError, "semantic ranking"):
            self.configure()
        self.session.service["properties"]["semanticSearch"] = "free"
        self.session.semantic = False
        with self.assertRaisesRegex(RuntimeError, "quota-exhausted"):
            self.configure()
        self.assertFalse(self.session.resources)

    def test_public_search_refused(self):
        self.session.service["properties"]["publicNetworkAccess"] = "enabled"
        with self.assertRaisesRegex(ValueError, "public network"):
            self.configure()
        self.assertFalse(self.session.resources)

    def test_missing_semantic_schema_refused(self):
        self.session.index["semantic"] = {}
        with self.assertRaisesRegex(ValueError, "semantic"):
            self.configure()
        self.assertFalse(self.session.resources)

    def test_source_collision_not_overwritten(self):
        url = data.search_url(target(), "knowledgesources/aif-kaggle-source")
        self.session.resources[url] = {"name": "aif-kaggle-source", "kind": "azureBlob", "description": "other owner"}
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_knowledge_base_with_extra_source_refused(self):
        self.configure()
        url = data.search_url(target(), "knowledgebases/aif-kaggle-knowledge")
        self.session.resources[url]["knowledgeSources"].append({"name": "unrelated-source"})
        self.session.calls.clear()
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_connection_collision_not_overwritten(self):
        self.configure()
        connection_id = f"{target().project_id}/connections/aif-knowledge-mcp"
        self.session.resources[connection_id]["properties"]["authType"] = "ApiKey"
        self.session.calls.clear()
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_errors_are_not_treated_as_missing(self):
        with patch.object(self.session, "arm", side_effect=AzureError(403, "GET", "resource", "forbidden")):
            with self.assertRaises(AzureError):
                self.configure()
        self.assertFalse(self.session.resources)

    def test_default_response_fields_compatible_but_active_features_not(self):
        expected = {"name": "source"}
        self.assertTrue(knowledge._compatible({**expected, "enableFreshness": False, "enableImageServing": False}, expected))
        self.assertFalse(knowledge._compatible({**expected, "enableImageServing": True}, expected))
        self.assertFalse(knowledge._compatible({**expected, "baseFilter": "leak eq true"}, expected))

    def test_real_retrieval_requires_references_and_content(self):
        self.configure()
        result = knowledge.verify_retrieval(self.session, target(), "How to connect VPN?")
        self.assertTrue(result["retrieval_verified"])
        self.assertEqual(result["reference_count"], 1)
        post = [body for method, url, body, _ in self.session.calls if method == "POST" and "/retrieve?" in url][-1]
        self.assertEqual(post["intents"], [{"type": "semantic", "search": "How to connect VPN?"}])
        self.assertTrue(post["knowledgeSourceParams"][0]["includeReferences"])
        self.assertNotIn("Use the VPN", json.dumps(result))
        for response in (
            {}, {"references": []},
            {"references": [{"type": "searchIndex", "docKey": "id"}], "response": [{"content": [{"type": "text", "text": "[]"}]}]},
            {"references": [{"type": "searchIndex", "docKey": "id"}], "response": [{"content": [{"type": "text", "text": "No results."}]}]},
            {"references": [{"type": "searchIndex", "docKey": "id"}], "response": [{"content": [{"type": "text", "text": '[{"content":""}]'}]}]},
            {**self.session.retrieve_response, "activity": [{"error": {"message": "index offline"}}]},
        ):
            self.session.retrieve_response = response
            with self.assertRaises(RuntimeError):
                knowledge.verify_retrieval(self.session, target(), "VPN")

    def test_retrieval_refuses_external_source_before_query(self):
        self.configure()
        url = data.search_url(target(), "knowledgesources/aif-kaggle-source")
        self.session.resources[url]["kind"] = "mcpServer"
        self.session.calls.clear()
        with self.assertRaisesRegex(ValueError, "local Search"):
            knowledge.verify_retrieval(self.session, target(), "private query")
        self.assertFalse(any(method == "POST" for method, *_ in self.session.calls))


if __name__ == "__main__":
    unittest.main()
