import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sales_demo.search import API_VERSION, SearchClient, build_definitions, correlate_evidence


STORAGE_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/saleslake"


def configuration():
    return {
        "owner": "aif48-project001-dev", "dataset": "car-sales", "version": "v1",
        "search_endpoint": "https://demo.search.windows.net",
        "storage_resource_id": STORAGE_ID, "storage_account": "saleslake",
        "container": "lake", "project_prefix": "projects/project001",
        "embedding_endpoint": "https://models.openai.azure.com",
        "embedding_deployment": "text-embedding-3-large",
        "partitions": [
            {"id": "json", "input_path": "ingestion/json/retail/sales-json/data.json"},
            {"id": "excel", "input_path": "ingestion/excel/retail/sales-excel/data.txt"},
        ],
    }


class NotFound(RuntimeError):
    status = 404


class Forbidden(RuntimeError):
    status = 403


class Transport:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
        self.resources = {}

    def request(self, method, url, body=None, *, audience, headers=None):
        self.calls.append((method, url, copy.deepcopy(body), audience, dict(headers or {})))
        if self.responses:
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return copy.deepcopy(result)
        if method == "GET":
            if url not in self.resources:
                raise NotFound()
            return copy.deepcopy(self.resources[url])
        if method == "PUT":
            self.resources[url] = copy.deepcopy(body)
        return {}


class DefinitionsTests(unittest.TestCase):
    def test_native_acl_and_real_split_audit(self):
        plan = build_definitions(configuration())
        self.assertEqual(API_VERSION, "2026-08-01-preview")
        self.assertEqual(len(plan["partitions"]), 2)
        for part in plan["partitions"]:
            resources = part["resources"]
            ds = resources["datasource"]
            self.assertEqual(ds["type"], "adlsgen2")
            self.assertEqual(ds["indexerPermissionOptions"], ["userIds", "groupIds", "rbacScope"])
            self.assertEqual(ds["credentials"]["connectionString"], f"ResourceId={STORAGE_ID};")
            self.assertTrue(ds["container"]["query"].startswith("projects/project001/ingestion/"))
            self.assertTrue(ds["container"]["query"].endswith("/"))
            for key in ("index", "audit_index"):
                index = resources[key]
                self.assertEqual(index["permissionFilterOption"], "enabled")
                fields = {f["name"]: f for f in index["fields"]}
                self.assertEqual(fields["metadata_storage_path"]["type"], "Edm.String")
                self.assertTrue(all(field["stored"] is True for field in fields.values()
                                    if field["type"] != "Collection(Edm.Single)"))
                for name, permission in (("UserIds", "userIds"), ("GroupIds", "groupIds"), ("RbacScope", "rbacScope")):
                    self.assertEqual(fields[name]["permissionFilter"], permission)
                    self.assertTrue(fields[name]["filterable"])
                    self.assertFalse(fields[name]["retrievable"])
            split, embedding = resources["skillset"]["skills"]
            self.assertEqual(split["maximumPageLength"], 6000)
            self.assertEqual(split["maximumPagesToTake"], 0)
            self.assertEqual(split["pageOverlapLength"], 0)
            self.assertEqual(split["unit"], "azureOpenAITokens")
            self.assertEqual(split["defaultLanguageCode"], "en")
            self.assertEqual(split["azureOpenAITokenizerParameters"]["encoderModelName"], "cl100k_base")
            self.assertEqual(embedding["dimensions"], 3072)
            self.assertEqual(embedding["inputs"], [{"name": "text", "source": "/document/pages/*"}])
            self.assertNotIn("apiKey", embedding)
            projection = resources["skillset"]["indexProjections"]
            self.assertEqual(projection["parameters"]["projectionMode"], "includeIndexingParentDocuments")
            selector = projection["selectors"][0]
            self.assertEqual(selector["targetIndexName"], resources["index"]["name"])
            self.assertEqual(selector["sourceContext"], "/document/pages/*")
            mappings = {m["name"]: m["source"] for m in selector["mappings"]}
            self.assertEqual(mappings["UserIds"], "/document/metadata_user_ids")
            self.assertEqual(mappings["GroupIds"], "/document/metadata_group_ids")
            self.assertEqual(mappings["RbacScope"], "/document/metadata_rbac_scope")
            self.assertEqual(mappings["source_uri"], "/document/metadata_storage_path")
            self.assertEqual(mappings["metadata_storage_path"], "/document/metadata_storage_path")
            self.assertEqual(mappings["aif48owner"], "/document/aif48owner")
            self.assertNotIn("chunk_id", mappings)
            self.assertNotIn("parent_id", mappings)
            self.assertEqual(resources["indexer"]["targetIndexName"], resources["audit_index"]["name"])
            self.assertEqual(resources["indexer"]["parameters"]["configuration"]["executionEnvironment"], "private")
            self.assertEqual(resources["index"]["semantic"]["configurations"][0]["rankingOrder"],
                             "BoostedRerankerScore")
            self.assertTrue(next(f for f in resources["index"]["fields"] if f["name"] == "chunk_id")["sortable"])
            output = {m["targetFieldName"]: m["sourceFieldName"] for m in resources["indexer"]["outputFieldMappings"]}
            self.assertEqual(output["offsets_utf8"], "/document/split_offsets/*/utf8")
            self.assertEqual(output["lengths_codepoint"], "/document/split_lengths/*/codePoint")
            raw = str(resources)
            for forbidden in ("WebApiSkill", "knowledgeStore", "cache", "/pages/*/text"):
                self.assertNotIn(forbidden, raw)

    def test_paths_names_and_determinism(self):
        config = configuration()
        plan = build_definitions(config)
        self.assertEqual(plan, build_definitions(config))
        names = [r["name"] for p in plan["partitions"] for r in p["resources"].values()]
        self.assertEqual(len(set(names)), len(names))
        self.assertTrue(all(len(n) <= 63 for n in names))
        for path in ("../sales.txt", "ingestion/json/../../sales.txt", "https://elsewhere/data.json"):
            bad = copy.deepcopy(config)
            bad["partitions"][0]["input_path"] = path
            with self.assertRaises(ValueError):
                build_definitions(bad)
        bad = copy.deepcopy(config)
        bad["partitions"][1]["input_path"] = bad["partitions"][0]["input_path"]
        with self.assertRaises(ValueError):
            build_definitions(bad)


class ClientTests(unittest.TestCase):
    def runtime_fixture(self):
        config = configuration()
        content = "abcdef"
        partition = config["partitions"][0]
        partition.update({"source": "json", "site": "retail", "library": "sales-json",
                          "input_sha256": hashlib.sha256(content.encode()).hexdigest(), "expected_chunks": 3})
        metadata = {name: partition[name] for name in ("source", "site", "library", "input_sha256")}
        metadata.update({"dataset": config["dataset"], "version": config["version"],
                         "aif48owner": config["owner"],
                         "source_uri": "https://saleslake.blob.core.windows.net/lake/projects/project001/" + partition["input_path"]})
        metadata["metadata_storage_path"] = metadata["source_uri"]
        audit = {**metadata, "parent_id": "parent", "pages": ["ab", "cd", "ef"], "split_ordinals": [1, 2, 3]}
        for unit in ("utf8", "utf16", "codepoint"):
            audit["offsets_" + unit] = [0, 2, 4]
            audit["lengths_" + unit] = [2, 2, 2]
        chunks = [{**metadata, "parent_id": "parent", "chunk_id": "c" + str(i), "chunk_text": text}
                  for i, text in enumerate(audit["pages"], 1)]
        status = {"status": "running", "lastResult": {"status": "success", "startTime": "start",
                                                     "endTime": "end", "itemsFailed": 0}}
        responses = [status, {"value": [audit], "@odata.count": 1},
                     {"value": chunks, "@odata.count": 3}, status]
        return config, partition, responses, content

    def test_runtime_verification_uses_live_complete_evidence(self):
        config, partition, responses, content = self.runtime_fixture()
        transport = Transport(responses)
        client = SearchClient(config, transport)
        verified = {"verified": True, "chunk_count": 3, "input_sha256": partition["input_sha256"], "chunks": []}
        with patch("sales_demo.search._verify_chunks", return_value=verified) as verifier:
            receipt = client.verify_partition(partition, SimpleNamespace(search_token="user-token"))
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["input_sha256"], partition["input_sha256"])
        self.assertEqual(receipt["index"], client.plan()["partitions"][0]["names"]["index"])
        names = client.plan()["partitions"][0]["names"]
        self.assertEqual(receipt["accessed_indexes"], [names["index"], names["audit_index"]])
        self.assertEqual(verifier.call_args.args[0], content)
        self.assertEqual([c["ordinal"] for c in verifier.call_args.args[1]], [1, 2, 3])
        self.assertEqual(receipt["chunk_hashes"]["c1"], hashlib.sha256(b"ab").hexdigest())
        self.assertTrue(all(call[4]["x-ms-query-source-authorization"] == "user-token"
                            for call in transport.calls if "/docs/search?" in call[1]))

    def test_runtime_real_verifier_with_offline_synthetic_unicode_arrays(self):
        # Synthetic arrays test adapter interoperability, not execution of a cloud TextSplit skill.
        config, partition, responses, _ = self.runtime_fixture()
        text = json.dumps({"records": [
            {"sale_id": f"S-{i:04d}", "description": "blue car café 🚙 " * 30}
            for i in range(65)
        ]}, ensure_ascii=False, indent=2) + "\n"
        cuts = [0, text.index("café", len(text) // 3) + 2,
                text.index("café", len(text) * 2 // 3) + 2, len(text)]
        partition["input_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        audit = responses[1]["value"][0]
        audit["input_sha256"] = partition["input_sha256"]
        audit["pages"] = [text[start:end] for start, end in zip(cuts, cuts[1:])]
        metadata = {key: value for key, value in audit.items()
                    if key in ("dataset", "version", "source", "site", "library", "input_sha256",
                               "source_uri", "metadata_storage_path", "aif48owner", "parent_id")}
        children = []
        for index, (start, end) in enumerate(zip(cuts, cuts[1:])):
            piece = text[start:end]
            for unit, encoding, divisor in (("utf8", "utf-8", 1), ("utf16", "utf-16-le", 2)):
                audit["offsets_" + unit][index] = len(text[:start].encode(encoding)) // divisor
                audit["lengths_" + unit][index] = len(piece.encode(encoding)) // divisor
            audit["offsets_codepoint"][index] = start
            audit["lengths_codepoint"][index] = len(piece)
            children.append({**metadata, "chunk_id": f"c{index + 1}", "chunk_text": piece})
        responses[2]["value"] = children
        cache = Path(__file__).resolve().parents[1] / ".venv" / "tiktoken-cache"
        with patch.dict("os.environ", {"TIKTOKEN_CACHE_DIR": str(cache)}), patch(
            "tiktoken.load.read_file", side_effect=AssertionError("Tokenizer downloads are prohibited in tests")
        ):
            receipt = SearchClient(config, Transport(responses)).verify_partition(
                partition, SimpleNamespace(search_token="user-token"))
        self.assertTrue(receipt["verified"])
        self.assertGreater(receipt["input_tokens"], 9000)
        self.assertTrue(all(chunk["tokens"] <= 6000 for chunk in receipt["chunks"]))
        self.assertEqual(receipt["reconstructed_sha256"], partition["input_sha256"])

    def test_runtime_verification_rejects_wrong_scope_hash_and_changed_ingestion(self):
        config, partition, responses, _ = self.runtime_fixture()
        changed = copy.deepcopy(partition)
        changed["input_sha256"] = "0" * 64
        transport = Transport()
        with self.assertRaises(ValueError):
            SearchClient(config, transport).verify_partition(changed, SimpleNamespace(search_token="user-token"))
        self.assertEqual(transport.calls, [])
        responses[1]["value"][0]["input_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            SearchClient(config, Transport(responses)).verify_partition(partition, SimpleNamespace(search_token="user-token"))
        config, partition, responses, _ = self.runtime_fixture()
        responses[-1] = {"lastResult": {"status": "inProgress", "startTime": "new"}}
        with patch("sales_demo.search._verify_chunks", return_value={"verified": True}):
            with self.assertRaises(TimeoutError):
                SearchClient(config, Transport(responses)).verify_partition(partition, SimpleNamespace(search_token="user-token"))

    def test_runtime_retrieve_adapts_trusted_partitions_and_identity(self):
        config, partition, responses, _ = self.runtime_fixture()
        transport = Transport([{"value": responses[2]["value"][:1]}])
        client = SearchClient(config, transport)
        documents = client.retrieve("question", [partition], SimpleNamespace(search_token="user-token"))
        self.assertEqual(documents[0]["text"], "ab")
        self.assertEqual(documents[0]["index"], client.plan()["partitions"][0]["names"]["index"])

    def test_native_denial_checks_both_indexes_with_restricted_user(self):
        for denied in (
            [{"value": [], "@odata.count": 0}, {"value": [], "@odata.count": 0}],
            [Forbidden(), Forbidden()],
        ):
            config, partition, responses, _ = self.runtime_fixture()
            responses.extend([copy.deepcopy(responses[0]), *denied])
            transport = Transport(responses)
            with patch("sales_demo.search._verify_chunks", return_value={
                "verified": True, "chunk_count": 3, "input_sha256": partition["input_sha256"]
            }):
                self.assertTrue(SearchClient(config, transport).verify_native_denial(
                    SimpleNamespace(search_token="restricted-user"), allowed_partition="json"))
            denied_calls = [call for call in transport.calls if "/docs/search?" in call[1]][-2:]
            self.assertTrue(all(call[4] == {"x-ms-query-source-authorization": "restricted-user"}
                                for call in denied_calls))
            self.assertTrue(any("-audit/" in call[1] for call in denied_calls))
            self.assertTrue(any("-chunks/" in call[1] for call in denied_calls))

    def test_native_denial_never_counts_missing_index_or_visible_document(self):
        for denied in (NotFound(), {"value": [{"chunk_id": "leaked"}], "@odata.count": 1}):
            config, partition, responses, _ = self.runtime_fixture()
            responses.extend([copy.deepcopy(responses[0]), denied])
            with patch("sales_demo.search._verify_chunks", return_value={
                "verified": True, "chunk_count": 3, "input_sha256": partition["input_sha256"]
            }):
                self.assertFalse(SearchClient(config, Transport(responses)).verify_native_denial(
                    SimpleNamespace(search_token="restricted-user"), allowed_partition="json"))

    def test_apply_gates_and_collision(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        self.assertEqual(client.configure(), client.plan())
        self.assertEqual(transport.calls, [])
        with self.assertRaises(ValueError):
            client.run_indexers()
        client.configure(apply=True)
        puts = [c for c in transport.calls if c[0] == "PUT"]
        self.assertEqual(len(puts), 10)
        self.assertTrue(all(c[4] == {"If-None-Match": "*"} for c in puts))
        transport.calls.clear()
        client.configure(apply=True)
        self.assertFalse(any(c[0] == "PUT" for c in transport.calls))
        key = next(iter(transport.resources))
        transport.resources[key]["description"] = "someone else"
        with self.assertRaises(ValueError):
            client.configure(apply=True)

    def test_missing_tokens_rejected_without_reads(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        for token in (None, "", "Bearer abc", "a\r\nb"):
            with self.assertRaises(ValueError):
                client.enumerate_chunks("json", token)
            with self.assertRaises(ValueError):
                client.hybrid("sales", ["json", "excel"], token)
        self.assertEqual(transport.calls, [])

    def test_run_refuses_changed_skillset_before_indexer_execution(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        client.configure(apply=True)
        skill_url = next(url for url in transport.resources if "/skillsets/" in url)
        transport.resources[skill_url]["skills"][0]["maximumPagesToTake"] = 2
        transport.calls.clear()
        with self.assertRaises(ValueError):
            client.run_indexers(["json"], apply=True)
        self.assertFalse(any(call[0] == "POST" for call in transport.calls))

    def test_reset_is_explicit_scoped_and_rejects_active_indexers(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        with self.assertRaises(ValueError):
            client.reset_indexers()
        self.assertEqual(transport.calls, [])
        client.configure(apply=True)
        name = client.plan()["partitions"][0]["names"]["indexer"]
        status_url = client._url(f"indexers/{name}/status")
        transport.resources[status_url] = {"lastResult": {"status": "success"}}
        transport.calls.clear()
        client.reset_indexers(["json"], apply=True)
        posts = [call for call in transport.calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1], client._url(f"indexers/{name}/reset"))
        transport.resources[status_url] = {"lastResult": {"status": "inProgress"}}
        transport.calls.clear()
        with self.assertRaises(RuntimeError):
            client.reset_indexers(["json"], apply=True)
        self.assertFalse(any(call[0] == "POST" for call in transport.calls))

    def test_redacted_credentials_require_etag_reassertion(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        client.configure(apply=True)
        source_url = next(url for url in transport.resources if "/datasources/" in url)
        transport.resources[source_url]["credentials"]["connectionString"] = None
        transport.resources[source_url]["@odata.etag"] = '"v1"'
        transport.calls.clear()
        client.configure(apply=True)
        puts = [call for call in transport.calls if call[0] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual(puts[0][4], {"If-Match": '"v1"'})

    def test_pagination_keeps_native_user_header(self):
        transport = Transport([
            {"value": [{"chunk_id": "a"}], "@odata.count": 2,
             "@search.nextPageParameters": {"skip": 1}},
            {"value": [{"chunk_id": "b"}], "@odata.count": 2},
        ])
        client = SearchClient(configuration(), transport)
        self.assertEqual(len(client.enumerate_chunks("json", "user-token")), 2)
        for call in transport.calls:
            self.assertEqual(call[3], "https://search.azure.com")
            self.assertEqual(call[4], {"x-ms-query-source-authorization": "user-token"})
            self.assertNotIn("Authorization", call[4])
        self.assertEqual(transport.calls[1][2]["skip"], 1)

    def test_safe_next_link_and_raw_audit_evidence(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        name = client.plan()["partitions"][0]["names"]["index"]
        raw_audit = {"parent_id": "parent", "pages": ["unchanged"]}
        transport.responses = [
            {"value": [raw_audit], "@odata.count": 1},
            {"value": [{"chunk_id": "c1"}], "@odata.count": 2,
             "@odata.nextLink": f"https://demo.search.windows.net/indexes/{name}/docs/search?api-version={API_VERSION}&$skip=1"},
            {"value": [{"chunk_id": "c2"}], "@odata.count": 2},
        ]
        evidence = client.service_evidence("json", "user-token")
        self.assertEqual(evidence["audit"], [raw_audit])
        self.assertEqual(len(evidence["chunks"]), 2)
        self.assertTrue(all(c[4]["x-ms-query-source-authorization"] == "user-token" for c in transport.calls))

    def test_canonical_odata_continuation_and_remaining_top(self):
        transport = Transport()
        client = SearchClient(configuration(), transport)
        name = client.plan()["partitions"][0]["names"]["index"]
        transport.responses = [
            {"value": [{"chunk_id": "c1"}], "@odata.count": 2,
             "@odata.nextLink": f"https://demo.search.windows.net/indexes('{name}')/docs/search.post.search?api-version={API_VERSION}",
             "@search.nextPageParameters": {"skip": 1, "top": 999, "orderby": "chunk_id asc"}},
            {"value": [{"chunk_id": "c2"}], "@odata.count": 2},
        ]
        self.assertEqual(len(client.enumerate_chunks("json", "user-token")), 2)
        self.assertEqual(transport.calls[-1][2]["orderby"], "chunk_id asc")
        self.assertEqual(transport.calls[-1][2]["skip"], 1)

    def test_missing_count_or_repeated_pages_never_return_partial_results(self):
        for pages in (
            [{"value": [{"chunk_id": "a"}]}],
            [{"value": [{"chunk_id": "a"}], "@odata.count": 2},
             {"value": [{"chunk_id": "a"}], "@odata.count": 2}],
        ):
            with self.assertRaises(ValueError):
                SearchClient(configuration(), Transport(pages)).enumerate_chunks("json", "user-token")

    def test_rejects_escaping_or_mutating_continuations(self):
        client = SearchClient(configuration(), Transport())
        name = client.plan()["partitions"][0]["names"]["index"]
        urls = [
            "https://evil.example/indexes/other/docs/search?api-version=" + API_VERSION,
            "https://demo.search.windows.net/indexes/other/docs/search?api-version=" + API_VERSION,
            f"https://demo.search.windows.net/indexes/{name}/docs/search?api-version=old",
        ]
        for url in urls:
            transport = Transport([{"value": [{"chunk_id": "a"}], "@odata.count": 1, "@odata.nextLink": url}])
            with self.assertRaises(ValueError):
                SearchClient(configuration(), transport).enumerate_chunks("json", "user-token")
            self.assertEqual(len(transport.calls), 1)
        transport = Transport([{"value": [], "@odata.count": 0,
                                "@search.nextPageParameters": {"filter": "true", "skip": 1}}])
        with self.assertRaises(ValueError):
            SearchClient(configuration(), transport).enumerate_chunks("json", "user-token")

    def test_hybrid_fans_out_and_balances(self):
        transport = Transport([
            {"value": [{"chunk_id": "j1", "chunk_text": "json one"}, {"chunk_id": "j2", "chunk_text": "json two"}]},
            {"value": [{"chunk_id": "e1", "chunk_text": "excel one"}]},
        ])
        result = SearchClient(configuration(), transport).hybrid("compare", ["json", "excel"], "user-token", top=3)
        self.assertEqual([r["chunk_id"] for r in result], ["j1", "e1", "j2"])
        self.assertTrue(all(r["citation"]["index"] for r in result))
        for call in transport.calls:
            self.assertEqual(call[2]["queryType"], "semantic")
            self.assertEqual(call[2]["semanticConfiguration"], "sem")
            self.assertEqual(call[2]["vectorQueries"][0]["kind"], "text")
            self.assertEqual(call[4]["x-ms-query-source-authorization"], "user-token")

    def test_status_failure_and_bounded_wait(self):
        for last in ({"status": "persistentFailure"}, {"status": "success", "itemsFailed": 1},
                     {"status": "success", "warnings": [{"message": "truncated"}]}):
            client = SearchClient(configuration(), Transport([{"lastResult": last}]))
            with self.assertRaises(RuntimeError):
                client.wait(["json"], max_polls=1, poll_seconds=0)
        client = SearchClient(configuration(), Transport([{"lastResult": {"status": "inProgress"}}]))
        with self.assertRaises(TimeoutError):
            client.wait(["json"], max_polls=1, poll_seconds=0)

    def test_correlates_only_real_audit_arrays(self):
        audit = {
            "parent_id": "p", "pages": ["abc", "def"], "split_ordinals": [1, 2],
            "offsets_utf8": [0, 3], "offsets_utf16": [0, 3], "offsets_codepoint": [0, 3],
            "lengths_utf8": [3, 3], "lengths_utf16": [3, 3], "lengths_codepoint": [3, 3],
        }
        children = [{"chunk_id": "c2", "parent_id": "p", "chunk_text": "def"},
                    {"chunk_id": "c1", "parent_id": "p", "chunk_text": "abc"}]
        result = correlate_evidence([audit], children)
        self.assertEqual([c["ordinal"] for c in result], [1, 2])
        self.assertEqual(result[1]["offsets"]["utf8"], 3)
        self.assertEqual(result[1]["offset_utf8"], 3)
        self.assertEqual(result[1]["length_codepoint"], 3)
        broken = copy.deepcopy(audit)
        broken["offsets_utf8"] = []
        with self.assertRaises(ValueError):
            correlate_evidence([broken], children)
        with self.assertRaises(ValueError):
            correlate_evidence([audit], children[:1])


if __name__ == "__main__":
    unittest.main()
