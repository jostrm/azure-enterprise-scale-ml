from __future__ import annotations

from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_factory.monitoring import (
    build_report, flatten_metrics, main, monitoring_tags, normalize_scope, read_input,
)


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "monitoring-agent-v1.json"
NOW = datetime(2026, 9, 12, 1, 6, tzinfo=timezone.utc)
OPTIONS = {
    "aifactory": "fixture-factory", "project": "001", "environment": "dev",
    "subject": "fixture-knowledge", "version": "1",
    "window_start": "2026-09-12T01:00:00Z", "window_end": "2026-09-12T01:05:00Z",
    "generated_at": "2026-09-12T01:06:00Z", "now": NOW,
}


class MonitoringTests(unittest.TestCase):
    def report(self, payload=None, source_format="metrics-only", **options):
        return build_report(payload or {}, source_format=source_format, **{**OPTIONS, **options})

    def test_real_export_golden_and_all_three_environments(self):
        payload = {"document_count": 19, "reference_count": 2, "retrieval_verified": True,
                   "tool": {"server_url": "SENSITIVE_ENDPOINT"}, "response_sha256": "SENSITIVE_HASH"}
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for environment in ("dev", "test", "prod"):
            with self.subTest(environment=environment):
                expected["scope"]["environment"] = environment
                report = self.report(payload, "knowledge", environment=environment)
                self.assertEqual(expected, report)
                self.assertNotIn("SENSITIVE", json.dumps(report))
                self.assertEqual("not_supported", report["summary"]["concept_drift"])

    def test_scope_is_explicit_and_stage_is_test(self):
        self.assertEqual("test", normalize_scope("factory", "001", "stage")["environment"])
        for field, value in (("aifactory", ""), ("aifactory", "<factory>"), ("aifactory", "unknown"),
                             ("project", 1), ("project", "1"), ("project", "project001"),
                             ("environment", "stage_prod"), ("environment", "qa"), ("version", "")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.report(**{field: value})

    def test_input_identity_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            self.report({"scope": {"aifactory": "different", "project": "001", "environment": "dev"}})
        with self.assertRaises(ValueError):
            self.report({"subject": {"kind": "agent", "name": "different", "version": "1", "task_type": "agent"}})
        with self.assertRaises(ValueError):
            self.report({"agent": "other", "tool_calls": []}, "invocation")
        with self.assertRaises(ValueError):
            self.report({"name": "fixture-knowledge", "version": "wrong"}, "deployment")

    def test_no_checks_does_not_invent_health_or_metrics(self):
        for payload, source in (({}, "metrics-only"), ({"status": "active", "version": "1"}, "deployment"),
                                ({"status": "completed"}, "invocation")):
            with self.subTest(source=source):
                report = self.report(payload, source)
                self.assertEqual("unknown", report["summary"]["status"])
                self.assertEqual([], report["metrics"])
        report = self.report({"metrics": {"error_count": 0, "sample_count": 14}})
        self.assertEqual("unknown", report["summary"]["status"])
        self.assertTrue(all(item["status"] == "unknown" for item in report["metrics"]))

    def test_each_curated_numeric_metric_is_exposed_without_invented_values(self):
        values = {"usage": {"input_tokens": 123, "output_tokens": 32, "cached_tokens": 7},
                  "latency": {"p50_ms": 47.2, "p95_ms": 84.1}, "error_count": 1,
                  "sample_count": 25, "evaluation": {"score": 0.81, "missing": None}}
        report = self.report({"metrics": values, "units": {"usage.input_tokens": "tokens"}})
        actual = {metric["name"]: metric["value"] for metric in report["metrics"]}
        self.assertEqual(flatten_metrics(values), actual)
        self.assertEqual(list(sorted(actual)), list(actual))
        self.assertEqual("insufficient_data", next(item for item in report["metrics"]
                                                   if item["name"] == "evaluation.missing")["status"])
        self.assertEqual("unknown", report["summary"]["status"])
        self.assertEqual(actual, report["details"]["aggregates"])

    def test_nonfinite_boolean_string_and_numeric_overflow_are_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), True, "34", [], 10**400, 9007199254740992):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.report({"metrics": {"value": value}})
        with self.assertRaises(ValueError):
            self.report({"document_count": float("nan")}, "knowledge")

    def test_bounded_flattening_and_stable_names(self):
        with self.assertRaises(ValueError):
            flatten_metrics({f"metric{i}": i for i in range(129)})
        with self.assertRaises(ValueError):
            flatten_metrics({"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}})
        with self.assertRaises(ValueError):
            flatten_metrics({"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}})
        self.assertEqual({"a.b.c.d.e.f": 1}, flatten_metrics({"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}))
        for name in ("nested.dot", "has space", "user@example.com", "a" * 49):
            with self.subTest(name=name), self.assertRaises(ValueError):
                flatten_metrics({name: 1})
        self.assertEqual(128, len(flatten_metrics({f"metric{i}": i for i in range(128)})))

    def test_sensitive_sentinel_fields_never_leave_existing_results(self):
        sentinel = "DO_NOT_EXPORT_SECRET_SENTINEL"
        report = self.report({
            "agent_count_on_page": 5, "foundry_access": True,
            "network": [{"host": sentinel, "addresses": [sentinel], "error": sentinel,
                         "private": True, "reachable": False}],
            "prompt": sentinel, "response": sentinel, "credentials": sentinel,
            "usage": {"access_token": sentinel}, "status": "healthy",
        }, "preflight")
        self.assertNotIn(sentinel, json.dumps(report))
        self.assertEqual("warning", report["summary"]["status"])
        self.assertEqual({"agent_count_on_page": 5, "network_checked_count": 1,
                          "network_private_count": 1, "network_reachable_count": 0},
                         report["details"]["aggregates"])
        for field in ("prompt", "response", "text", "user_id", "access_token", "client_secret"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.report({"metrics": {field: 987654321}})
        with self.assertRaises(ValueError):
            self.report({"metrics": {"count": 1}, "response": sentinel})

    def test_check_values_require_evidence_and_health_is_not_drift(self):
        for value in (True, False):
            report = self.report({"checks": {"invocation_completed": value}})
            self.assertEqual("healthy" if value else "warning", report["summary"]["status"])
            self.assertEqual("not_supported", report["summary"]["data_drift"])
            self.assertEqual("not_supported", report["summary"]["concept_drift"])
        for checks in ({"invocation_completed": "true"}, {"status": True}):
            with self.assertRaises(ValueError):
                self.report({"checks": checks})

    def test_existing_ingestion_numbers_only(self):
        report = self.report({
            "row_count": 7, "document_count": 4, "evaluation_count": 7,
            "corpus_sha256_verified": True,
            "blob_integrity": {name: {"bytes": value, "md5_base64": "SENTINEL"}
                               for name, value in (("raw", 100), ("knowledge", 50), ("evaluation", 40))},
            "documents": [{"content": "SENTINEL"}], "credentials": "SENTINEL",
        }, "ingestion")
        self.assertEqual(6, len(report["metrics"]))
        self.assertEqual(50, report["details"]["aggregates"]["blob_integrity.knowledge.bytes"])
        self.assertNotIn("SENTINEL", json.dumps(report))

    def test_real_invocation_summary_counts_calls_but_not_text_or_usage(self):
        from agent_factory.cli import summarize_response
        response = SimpleNamespace(
            status="completed", output_text="SENTINEL", id="SENTINEL",
            usage={"input_tokens": 99},
            output=[SimpleNamespace(type="mcp_call", name="knowledge_base_retrieve",
                                    server_label="SENTINEL", error=None)],
        )
        source = summarize_response(response, {"name": "fixture-knowledge", "grounding": True})
        report = self.report(source, "invocation")
        self.assertEqual({"tool_call_count": 1}, report["details"]["aggregates"])
        self.assertEqual("unknown", report["summary"]["status"])
        self.assertNotIn("SENTINEL", json.dumps(report))
        self.assertNotIn("input_tokens", json.dumps(report))

    def test_freshness_uses_window_end_not_regeneration(self):
        report = self.report({"checks": {"invocation_completed": True}},
                             window_start="2026-09-10T01:00:00Z", window_end="2026-09-10T01:05:00Z")
        self.assertEqual("2026-09-11T01:05:00Z", report["expires_at"])
        self.assertEqual("stale", report["summary"]["status"])
        self.assertEqual("stale", self.report(now=NOW + timedelta(days=1))["summary"]["status"])
        self.assertEqual("stale", self.report(now=NOW + timedelta(hours=23, minutes=59))["summary"]["status"])

    def test_future_and_inverted_windows_invalid_ttl_and_naive_times_rejected(self):
        for options in ({"window_start": "2026-09-12T01:05:01Z"},
                        {"window_end": "2026-09-12T01:07:00Z"},
                        {"generated_at": "2026-09-12T01:07:00Z"},
                        {"window_start": "2026-09-12T01:00:00"},
                        {"window_start": "not-a-date"},
                        {"ttl_hours": float("nan")}, {"ttl_hours": 0}, {"ttl_hours": 721},
                        {"ttl_hours": 10**400}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.report(**options)
        report = self.report(window_start="2026-09-12T03:00:00+02:00")
        self.assertEqual("2026-09-12T01:00:00Z", report["window"]["start"])

    def test_compact_tags_and_credential_free_report_links(self):
        report = self.report()
        tags = monitoring_tags(report)
        self.assertEqual("1", tags["mon_schema"])
        self.assertEqual("agent-factory", tags["mon_source"])
        self.assertEqual("001", tags["project"])
        self.assertNotIn("mon_report_uri", tags)
        for uri in ("https://reports123.blob.core.windows.net/reports/agent.json",
                    "azureml://jobs/run-001/outputs/monitoring/paths/report.json"):
            self.assertEqual(uri, monitoring_tags(report, uri)["mon_report_uri"])
        for uri in ("https://reports123.blob.core.windows.net/reports/a.json?sig=SECRET",
                    "https://reports123.blob.core.windows.net/reports/a.json#SECRET",
                    "https://user:password@reports123.blob.core.windows.net/reports/a.json",
                    "https://example.com/report.json", "file:///local/report.json",
                    "azureml://jobs/run/outputs/report/paths/../SECRET",
                    "https://reports123.blob.core.windows.net/reports/%3Fsig%3DSECRET"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                monitoring_tags(report, uri)

    def test_units_cannot_smuggle_content_or_unknown_metrics(self):
        for units in ({"count": "SENSITIVE"}, {"absent": "count"}, ["count"]):
            with self.subTest(units=units), self.assertRaises(ValueError):
                self.report({"metrics": {"count": 1}, "units": units})


class MonitoringFileTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / (".monitoring-test-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.input = self.root / "input.json"
        self.output = self.root / "report.json"
        self.input.write_text('{"metrics":{"sample_count":2},"checks":{"invocation_completed":true}}', encoding="utf-8")
        end = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.args = [
            "--input", str(self.input), "--output", str(self.output), "--source-format", "metrics-only",
            "--aifactory", "test-factory", "--project", "001", "--environment", "stage",
            "--subject", "test-agent", "--version", "3", "--window-start", (end - timedelta(minutes=5)).isoformat(),
            "--window-end", end.isoformat(),
        ]

    def test_standalone_cli_writes_report_and_tags_without_azure(self):
        from agent_factory import cli
        for use_factory_cli in (False, True):
            with self.subTest(use_factory_cli=use_factory_cli), patch("agent_factory.cli.AzureSession") as azure:
                tags_path = self.root / "tags.json"
                args = [*self.args, "--tags-output", str(tags_path)]
                if use_factory_cli:
                    with patch("sys.argv", ["agent_factory", "monitoring-export", *args]):
                        self.assertEqual(0, cli.main())
                else:
                    self.assertEqual(0, main(args))
                azure.assert_not_called()
                report = json.loads(self.output.read_text(encoding="utf-8"))
                self.assertEqual("test", report["scope"]["environment"])
                self.assertEqual("healthy", report["summary"]["status"])
                self.assertEqual("test-factory", json.loads(tags_path.read_text(encoding="utf-8"))["aifactory"])
                self.assertEqual(2, json.loads(self.input.read_text(encoding="utf-8"))["metrics"]["sample_count"])

    def test_invalid_source_cannot_overwrite_report_or_input(self):
        self.output.write_text("EXISTING", encoding="utf-8")
        self.input.write_text('{"metrics":{"count":NaN}}', encoding="utf-8")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(self.args)
        self.assertEqual("EXISTING", self.output.read_text(encoding="utf-8"))
        self.input.write_text('{"metrics":{"count":1}}', encoding="utf-8")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([*self.args, "--output", str(self.input)])
        self.assertEqual('{"metrics":{"count":1}}', self.input.read_text(encoding="utf-8"))

    def test_bounded_file_and_duplicate_keys(self):
        for value in ('{"metrics":{"count":1,"count":2}}', '{"ignored":NaN}', " " * (1024 * 1024 + 1)):
            self.input.write_text(value, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_input(self.input)


if __name__ == "__main__":
    unittest.main()
