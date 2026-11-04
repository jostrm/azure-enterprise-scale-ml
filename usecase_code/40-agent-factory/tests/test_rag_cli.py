import importlib.util
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_rag_sources import CONFIG, TARGET, knowledge

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("rag_example", ROOT / "45-rag-agent" / "main.py")
rag = importlib.util.module_from_spec(loader)
loader.loader.exec_module(rag)


class RagCliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sources.json"
        self.path.write_text(json.dumps({"sources": {
            "one": {"agent_name": "test-rag-one", "binding": {}},
            "two": {"agent_name": "test-rag-two", "binding": {}},
        }}), encoding="utf-8")

    def args(self, command, *extra):
        return rag.parser().parse_args([
            command, "--config", str(Path(self.folder.name) / "config.json"),
            "--sources", str(self.path), "--source", "one", *extra,
        ])

    def test_explicit_source_selection_and_distinct_agent_names(self):
        self.assertEqual("test-rag-two", rag.select_source(self.path, "two")["agent_name"])
        with self.assertRaisesRegex(ValueError, "Select one explicit"):
            rag.select_source(self.path, "unknown")
        self.path.write_text('{"sources":{"one":{"agent_name":"same","binding":{}},"two":{"agent_name":"same","binding":{}}}}')
        with self.assertRaisesRegex(ValueError, "own independently"):
            rag.select_source(self.path, "one")
        self.path.write_text('{"sources":{},"sources":{}}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rag.select_source(self.path, "one")

    def test_mutations_and_retry_require_explicit_apply(self):
        for command in ("configure", "approve-link", "materialize", "start", "deploy"):
            with self.subTest(command=command), patch.object(rag, "load_selection") as load:
                with self.assertRaisesRegex(ValueError, "--apply"):
                    rag.run(self.args(command))
                load.assert_not_called()
        for flag in ("--grant-read", "--retry-failed"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                rag.run(self.args("plan", flag))

    def test_source_agent_has_no_azure_inventory_or_public_docs_tools(self):
        source, _ = knowledge()
        spec = rag.source_spec(source, "test-rag-one")
        self.assertTrue(spec["grounding"])
        self.assertNotIn("azure_inventory", spec)
        self.assertNotIn("microsoft_docs", spec)
        self.assertEqual(source.binding_fingerprint, spec["metadata"]["aifactory.rag_binding"])
        self.assertEqual(source.source_key, spec["metadata"]["aifactory.rag_source_key"])

    def test_live_retrieval_drift_stops_ask_before_model_call(self):
        source, _ = knowledge()
        args = self.args("ask", "--input", "Question")
        state = (args.config.parent / ".agent-factory" / TARGET.account_name
                 / TARGET.project_name / "rag" / source.source_key / source.binding_fingerprint)
        state.mkdir(parents=True)
        (state / "deployment.json").write_text(json.dumps({
            "source": source.as_dict(), "agent": {"name": "test-rag-one", "version": "1"},
        }))
        with patch.object(rag, "load_selection", return_value=({}, CONFIG, {})), \
                patch.object(rag, "discover", return_value=TARGET), \
                patch.object(rag.RagSource, "from_binding", return_value=source), \
                patch.object(rag, "validated_documents", return_value=[]), \
                patch.object(rag, "verify_indexed"), \
                patch.object(rag, "verify_retrieval_binding", side_effect=RuntimeError("binding drift")), \
                patch.object(rag, "project_client") as client:
            with self.assertRaisesRegex(RuntimeError, "binding drift"):
                rag.run(args)
            client.assert_not_called()

    def test_existing_copy_run_is_not_started_again(self):
        source, _ = knowledge()
        args = self.args("materialize", "--apply")
        state = (args.config.parent / ".agent-factory" / TARGET.account_name
                 / TARGET.project_name / "rag" / source.source_key / source.binding_fingerprint)
        state.mkdir(parents=True)
        (state / "materialization.json").write_text(json.dumps({
            "binding_fingerprint": source.binding_fingerprint, "factory_name": "adf",
            "factory_id": "/factory", "run_id": "existing-run",
        }))
        session = Mock()
        session.pages.return_value = [{"name": "adf", "type": "Microsoft.DataFactory/factories"}]
        session.arm.return_value = {"status": "InProgress"}
        with patch.object(rag, "load_selection", return_value=({}, CONFIG, {})), \
                patch.object(rag, "discover", return_value=TARGET), \
                patch.object(rag, "AzureSession", return_value=session), \
                patch.object(rag.RagSource, "from_binding", return_value=source), \
                patch.object(rag, "validated_documents", return_value=[]), \
                patch.object(rag, "start_materialization") as start:
            with self.assertRaisesRegex(RuntimeError, "already active"):
                rag.run(args)
            start.assert_not_called()
            session.arm.return_value = {"status": "Failed"}
            with self.assertRaisesRegex(RuntimeError, "Prior materialization failed"):
                rag.run(args)
            start.assert_not_called()
            session.arm.return_value = {"status": "Succeeded"}
            with patch.object(rag, "verify_destination", side_effect=ValueError("SHA mismatch")):
                with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                    rag.run(args)
                start.assert_not_called()
                args.retry_failed = True
                start.return_value = {"status": "running", "run_id": "retry-run"}
                result = rag.run(args)
                self.assertEqual("destination-verification-failed", result["retry_reason"])
                start.assert_called_once()

    @contextmanager
    def materialization_scenario(self):
        source, _ = knowledge()
        args = self.args("materialize", "--apply", "--retry-failed")
        state = (args.config.parent / ".agent-factory" / TARGET.account_name
                 / TARGET.project_name / "rag" / source.source_key / source.binding_fingerprint)
        state.mkdir(parents=True)
        journal = state / "materialization.json"
        saved = {
            "binding_fingerprint": source.binding_fingerprint, "factory_name": "adf",
            "factory_id": "/factory", "run_id": "existing-run",
        }
        journal.write_text(json.dumps(saved), encoding="utf-8")
        session = Mock()
        session.pages.return_value = [{"name": "adf", "type": "Microsoft.DataFactory/factories"}]
        session.arm.return_value = {"status": "Succeeded"}
        with patch.object(rag, "load_selection", return_value=({}, CONFIG, {})), \
                patch.object(rag, "discover", return_value=TARGET), \
                patch.object(rag, "AzureSession", return_value=session), \
                patch.object(rag.RagSource, "from_binding", return_value=source), \
                patch.object(rag, "validated_documents", return_value=[]), \
                patch.object(rag, "verify_destination") as verify, \
                patch.object(rag, "start_materialization", return_value={
                    **saved, "status": "running", "run_id": "retry-run",
                }) as start:
            yield args, source, journal, saved, session, verify, start

    def test_retry_persists_replacement_run_and_next_call_does_not_duplicate_it(self):
        with self.materialization_scenario() as (args, source, journal, _, session, verify, start):
            verify.side_effect = ValueError("SHA mismatch")
            result = rag.run(args)
            start.assert_called_once_with(session, TARGET, source, "adf")
            self.assertEqual("retry-run", result["run_id"])
            self.assertEqual("destination-verification-failed", result["retry_reason"])
            self.assertEqual(result, json.loads(journal.read_text(encoding="utf-8")))
            session.arm.return_value = {"status": "InProgress"}
            with self.assertRaisesRegex(RuntimeError, "already active"):
                rag.run(args)
            self.assertEqual(1, start.call_count)
            self.assertIn("/pipelineruns/retry-run", session.arm.call_args.args[1])

    def test_valid_completed_copy_is_reused_even_with_retry_flag(self):
        with self.materialization_scenario() as (args, _, journal, saved, _, verify, start):
            verify.return_value = {"content_verified": True}
            self.assertEqual(
                {"content_verified": True, "status": "reused", "run_id": "existing-run"},
                rag.run(args),
            )
            start.assert_not_called()
            self.assertEqual(saved, json.loads(journal.read_text(encoding="utf-8")))

    def test_retry_flag_never_restarts_active_copy(self):
        with self.materialization_scenario() as (args, _, journal, saved, session, verify, start):
            for status in ("Queued", "InProgress", "Canceling"):
                session.arm.return_value = {"status": status}
                with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, "already active"):
                    rag.run(args)
            start.assert_not_called()
            verify.assert_not_called()
            self.assertEqual(saved, json.loads(journal.read_text(encoding="utf-8")))

    def test_access_failure_is_not_treated_as_corrupt_destination(self):
        with self.materialization_scenario() as (args, _, journal, saved, _, verify, start):
            verify.side_effect = RuntimeError("Storage read failed: HTTP 403")
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                rag.run(args)
            start.assert_not_called()
            self.assertEqual(saved, json.loads(journal.read_text(encoding="utf-8")))

    def test_failed_restart_preserves_previous_journal(self):
        with self.materialization_scenario() as (args, _, journal, saved, _, verify, start):
            verify.side_effect = ValueError("SHA mismatch")
            start.side_effect = RuntimeError("Materialization prerequisites are not ready")
            with self.assertRaisesRegex(RuntimeError, "prerequisites"):
                rag.run(args)
            self.assertEqual(saved, json.loads(journal.read_text(encoding="utf-8")))

    def test_retry_cannot_cross_binding_or_factory(self):
        with self.materialization_scenario() as (args, _, journal, saved, session, verify, start):
            for field in ("binding_fingerprint", "factory_name"):
                journal.write_text(json.dumps({**saved, field: "different"}), encoding="utf-8")
                with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "another binding or factory"):
                    rag.run(args)
            session.arm.assert_not_called()
            verify.assert_not_called()
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
