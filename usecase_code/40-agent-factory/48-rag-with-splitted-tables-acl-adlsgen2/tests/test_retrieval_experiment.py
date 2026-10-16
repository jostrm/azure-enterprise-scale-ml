"""Offline contracts for an explicitly approved synthetic project-corpus experiment."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sales_demo.dataset import generate
from sales_demo.retrieval_experiment import (
    Experiment, build_documents, definitions, instructions, require_approval, verify_indexed_documents,
    whole_table_documents,
)


class RetrievalExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.publication = generate(cls.root / "data")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def config(self):
        return {
            "dataset": "car-sales", "version": "v1", "owner": "aif48-project001-dev",
            "artifacts_root": str(self.root / "data"), "publication": deepcopy(self.publication),
            "partitions": deepcopy(self.publication["partitions"]),
            "project_prefix": "mlops/v1/projects/project001/environments/dev/usecases/car-sales/rag/corpora/car-sales/versions/v1",
            "storage_account": "demostorage", "container": "lake3",
            "storage_resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/demostorage",
            "search_endpoint": "https://demo.search.windows.net",
            "embedding_endpoint": "https://models.openai.azure.com",
            "embedding_deployment": "text-embedding-3-large",
            "model_deployment": "gpt-5.1",
        }

    def test_whole_rows_cover_all_sources_without_text_split_or_totals(self):
        config = self.config()
        documents = build_documents(config)
        self.assertEqual(set(documents), {"json", "excel"})
        for partition in config["partitions"]:
            chunks = documents[partition["id"]]
            self.assertEqual(len(chunks), 3)
            records = [row for chunk in chunks for row in json.loads(chunk["content"])["records"]]
            self.assertEqual(len(records), partition["row_count"])
            self.assertEqual(len({row["sale_id"] for row in records}), len(records))
            self.assertTrue(all(chunk["input_tokens"] < 6000 for chunk in chunks))
            self.assertTrue(all("total_minor" not in chunk["content"] for chunk in chunks))

    def test_changed_rows_fail_before_any_model_or_cloud_request(self):
        config = self.config()
        config["partitions"][0]["rows_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            build_documents(config)

    def test_two_sources_one_knowledge_base_no_local_function_tool(self):
        config = self.config()
        plan = definitions(config, build_documents(config))
        self.assertEqual(len(plan["indexes"]), 2)
        self.assertEqual(len(plan["sources"]), 2)
        self.assertEqual(len(plan["base"]["knowledgeSources"]), 2)
        self.assertEqual(plan["base"]["outputMode"], "extractiveData")
        self.assertEqual(plan["base"]["retrievalReasoningEffort"], {"kind": "minimal"})
        self.assertNotIn("Text.SplitSkill", json.dumps(plan))
        self.assertNotIn("aggregate_sales", instructions())
        self.assertTrue(all(index["permissionFilterOption"] == "disabled" for index in plan["indexes"]))
        self.assertTrue(all("-experiment-" in index["name"] for index in plan["indexes"]))

    def test_synthetic_project_corpus_requires_explicit_approval(self):
        with self.assertRaises(ValueError):
            require_approval(self.config())
        config = self.config()
        config["retrieval_experiment"] = {
            "synthetic_project_corpus_approved": True,
            "authorization": "project-managed-identity",
        }
        require_approval(config)
        config["retrieval_experiment"]["authorization"] = "personal-user"
        with self.assertRaises(ValueError):
            require_approval(config)

    def test_real_document_readback_must_match_exact_expected_text(self):
        documents = build_documents(self.config())["json"]
        verify_indexed_documents(documents, deepcopy(documents))
        for change in ("missing", "altered", "extra"):
            actual = deepcopy(documents)
            if change == "missing":
                actual.pop()
            elif change == "altered":
                actual[0]["content"] += " altered"
            else:
                actual.append({**actual[0], "id": "unexpected"})
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_indexed_documents(documents, actual)

    def test_partial_upload_can_resume_only_missing_exact_documents(self):
        documents = build_documents(self.config())["json"]
        self.assertEqual(verify_indexed_documents(documents, documents[:1], complete=False), documents[1:])
        changed = deepcopy(documents[:1])
        changed[0]["content"] += "changed"
        with self.assertRaises(ValueError):
            verify_indexed_documents(documents, changed, complete=False)

    def test_configure_routes_by_partition_not_truncated_resource_name(self):
        config = self.config()
        config["owner"] = "a" * 45
        config["retrieval_experiment"] = {
            "synthetic_project_corpus_approved": True, "authorization": "project-managed-identity"}
        experiment = Experiment(config, Mock(), object(), self.root / "long-name")
        payloads = []
        def request(method, url, body, **kwargs):
            payloads.append(body["value"])
            return {"value": [{"key": document["id"], "status": True} for document in body["value"]]}
        experiment.session.request.side_effect = request
        reads = [[], experiment.documents["json"], [], experiment.documents["excel"]]
        with patch.object(experiment, "_private"), patch.object(experiment, "_ensure"), \
                patch.object(experiment, "_read_index", side_effect=reads), \
                patch.object(experiment, "_embedding", return_value=[0.1] * 3072):
            experiment.configure(apply=True, allow_paid=True)
        self.assertEqual({item["source"] for item in payloads[0]}, {"json"})
        self.assertEqual({item["source"] for item in payloads[1]}, {"excel"})

    def test_verify_checks_owned_sources_and_base_before_using_them(self):
        experiment = Experiment(self.config(), Mock(), object(), self.root / "verify")
        with patch.object(experiment, "_private"), patch.object(
            experiment, "_read_index", side_effect=[experiment.documents["json"], experiment.documents["excel"]]
        ), patch("sales_demo.retrieval_experiment.check_resource") as check:
            experiment.verify()
        self.assertEqual(check.call_count, 5)
        self.assertTrue(any("/knowledgesources/" in call.args[1] for call in check.call_args_list))
        self.assertTrue(any("/knowledgebases/" in call.args[1] for call in check.call_args_list))

    def test_inference_and_writes_require_approval_before_network(self):
        experiment = Experiment(self.config(), Mock(), object(), self.root / "state")
        for operation in (experiment.configure, experiment.deploy,
                          lambda: experiment.ask({}, "question"), lambda: experiment.retrieval_probe("question")):
            with self.assertRaises(ValueError):
                operation()
        experiment.session.request.assert_not_called()
        experiment.session.arm.assert_not_called()

    def test_knowledge_probe_uses_both_sources_and_no_permission_bypass_headers(self):
        config = self.config()
        config["retrieval_experiment"] = {
            "synthetic_project_corpus_approved": True, "authorization": "project-managed-identity"}
        session = Mock()
        experiment = Experiment(config, session, object(), self.root / "probe-state")
        session.request.return_value = {
            "activity": [{"type": "searchIndex", "knowledgeSourceName": source["name"], "id": index}
                         for index, source in enumerate(experiment.plan["sources"])],
            "references": [{"docKey": "json", "activitySource": 0}, {"docKey": "excel", "activitySource": 1}],
        }
        with patch.object(experiment, "verify"):
            experiment.retrieval_probe("Facts from JSON and Excel", allow_paid=True)
        body = session.request.call_args.args[2]
        self.assertEqual(len(body["knowledgeSourceParams"]), 2)
        self.assertTrue(all(source["alwaysQuerySource"] for source in body["knowledgeSourceParams"]))
        self.assertNotIn("headers", session.request.call_args.kwargs)

    def test_both_source_activity_without_both_references_is_not_evidence(self):
        config = self.config()
        config["retrieval_experiment"] = {
            "synthetic_project_corpus_approved": True, "authorization": "project-managed-identity"}
        session = Mock()
        experiment = Experiment(config, session, object(), self.root / "one-source-probe")
        session.request.return_value = {
            "activity": [{"type": "searchIndex", "knowledgeSourceName": source["name"], "id": index}
                         for index, source in enumerate(experiment.plan["sources"])],
            "references": [{"docKey": "json", "activitySource": 0}],
        }
        with patch.object(experiment, "verify"), self.assertRaises(RuntimeError):
            experiment.retrieval_probe("question", allow_paid=True)

    def test_native_whole_table_preserves_every_source_byte_and_needs_no_operator_upload(self):
        config = self.config()
        config["retrieval_experiment"] = {"ingestion": "native-whole-table"}
        documents = whole_table_documents(config)
        for part in config["partitions"]:
            actual = documents[part["id"]][0]
            expected = (Path(config["artifacts_root"]) / "master" / part["input_path"]).read_bytes()
            self.assertEqual(actual["content"].encode(), expected)
        plan = definitions(config, documents)
        self.assertEqual(plan["ingestion"], "native-whole-table")
        self.assertTrue(all(index["vectorSearch"]["vectorizers"] == [] for index in plan["indexes"]))
        self.assertGreaterEqual(plan["base"]["retrieveDefaults"]["maxOutputSizeInTokens"], 30000)

    def test_native_configuration_uses_two_scoped_indexers_and_never_pushes_documents(self):
        config = self.config()
        config["retrieval_experiment"] = {
            "ingestion": "native-whole-table", "synthetic_project_corpus_approved": True,
            "authorization": "project-managed-identity",
        }
        session = Mock()
        session.request.return_value = {"lastResult": {"status": "success", "itemsFailed": 0}}
        experiment = Experiment(config, session, object(), self.root / "native-config")
        with patch.object(experiment, "_private"), patch.object(experiment, "_ensure") as ensure, \
                patch.object(experiment, "_read_index",
                             side_effect=[experiment.documents["json"], experiment.documents["excel"]]):
            result = experiment.configure(apply=True, allow_paid=True)
        indexers = [call.args[1] for call in ensure.call_args_list if call.args[0] == "indexers"]
        sources = [call.args[1] for call in ensure.call_args_list if call.args[0] == "datasources"]
        self.assertEqual(len(indexers), 2)
        self.assertTrue(all("skillsetName" not in indexer for indexer in indexers))
        self.assertTrue(all(indexer["parameters"]["configuration"]["executionEnvironment"] == "private"
                            for indexer in indexers))
        self.assertTrue(all(source["container"]["query"].startswith(config["project_prefix"] + "/ingestion/")
                            for source in sources))
        self.assertTrue(all(call.args[0] == "GET" for call in session.request.call_args_list))
        self.assertEqual(result["whole_tables"], 2)
        self.assertFalse(result["text_split"])
        self.assertFalse(result["embeddings"])

    def test_empty_retrieval_cannot_count_as_a_successful_probe(self):
        config = self.config()
        config["retrieval_experiment"] = {
            "synthetic_project_corpus_approved": True, "authorization": "project-managed-identity"}
        session = Mock()
        session.request.return_value = {"activity": [], "references": []}
        experiment = Experiment(config, session, object(), self.root / "empty-probe")
        with patch.object(experiment, "verify"), self.assertRaises(RuntimeError):
            experiment.retrieval_probe("question", allow_paid=True)

    def test_failed_embedding_is_not_cached(self):
        config = self.config()
        session = Mock()
        session.request.return_value = {"data": [{"embedding": [1.0]}]}
        state = self.root / "bad-embedding"
        experiment = Experiment(config, session, object(), state)
        with self.assertRaises(ValueError):
            experiment._embedding(experiment.documents["json"][0])
        self.assertFalse(state.exists())

    def test_cli_has_no_implicit_mutation_or_paid_calls(self):
        spec = importlib.util.spec_from_file_location(
            "retrieval_only_entry", Path(__file__).resolve().parents[1] / "retrieval_only.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        for command in ("configure", "deploy"):
            with self.assertRaisesRegex(ValueError, "--apply"):
                entry.run(entry.parser().parse_args([command, "--config", "not-read.json"]))
        for command in ("configure", "probe", "ask"):
            with self.assertRaisesRegex(ValueError, "--allow-paid"):
                entry.run(entry.parser().parse_args([command, "--config", "not-read.json", "--apply"]))


if __name__ == "__main__":
    unittest.main()
