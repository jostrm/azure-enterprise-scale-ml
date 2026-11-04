"""Offline scoring must not turn partial or ambiguous LLM answers into success."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sales_demo.dataset import generate
from sales_demo.sum_evaluation import load_expected, score_response


class SumEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        publication = generate(cls.root / "data")
        cls.config = {
            "dataset": "car-sales", "version": "v1", "artifacts_root": str(cls.root / "data"),
            "partitions": publication["partitions"],
        }
        cls.oracle = cls.root / "data" / "evaluation" / "expected.json"
        cls.expected = load_expected(cls.config, cls.oracle)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def answer(self):
        groups = ["| Source | First sale ID | Last sale ID | Records | Net subtotal (USD cents) |",
                  "|---|---|---|---:|---:|"]
        totals = ["| Source | Deduplicated record count | Net total (USD cents) | Net total (USD) |",
                  "|---|---:|---:|---:|"]
        for source, part in self.expected["partitions"].items():
            ids = sorted(part["amounts"])
            for start in range(0, len(ids), 20):
                chosen = ids[start:start + 20]
                amount = sum(part["amounts"][key] for key in chosen)
                groups.append(f"| {source} | {chosen[0]} | {chosen[-1]} | {len(chosen)} | {amount:,} |")
            amount = part["total_minor"]
            dollars = f"{amount // 100:,}.{amount % 100:02d}"
            totals.append(f"| {source} | {len(ids)} | {amount:,} | ${dollars} |")
        amount = self.expected["total_minor"]
        dollars = f"{amount // 100:,}.{amount % 100:02d}"
        totals.append(f"| **Combined** | **262** | **{amount:,}** | **${dollars}** |")
        return "\n".join(groups) + "\n\n" + "\n".join(totals)

    def response(self, text=None):
        return {
            "status": "completed", "response_id": "synthetic-offline-test",
            "text": self.answer() if text is None else text,
            "output_types": ["reasoning", "message"], "calculator_used": False,
        }

    def test_full_audit_and_exact_totals_pass(self):
        report = score_response(self.response(), self.expected)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["totals"]["status"], "correct")
        self.assertEqual(report["coverage"]["status"], "complete")
        self.assertEqual(report["coverage"]["unique_rows"], 262)
        self.assertEqual(len(report["groups"]), 14)
        self.assertFalse(report["live_execution_verified"])

    def test_correct_total_mentioned_in_prose_is_not_a_valid_audit(self):
        report = score_response(self.response("Expected is $39,535,932.62. I cannot calculate it."), self.expected)
        self.assertFalse(report["passed"])
        self.assertEqual(report["totals"]["status"], "unverifiable")
        self.assertEqual(report["coverage"]["status"], "unverifiable")

    def test_wrong_group_amount_is_reported_independently_of_correct_totals(self):
        text = self.answer().replace("240,458,278", "240,468,278", 1)
        report = score_response(self.response(text), self.expected)
        self.assertFalse(report["passed"])
        self.assertEqual(report["totals"]["status"], "correct")
        self.assertEqual(report["coverage"]["status"], "complete")
        self.assertEqual(report["groups"][0]["difference_minor"], 10000)

    def test_missing_or_duplicate_group_cannot_pass(self):
        lines = self.answer().splitlines()
        for changed in (lines[:2] + lines[3:], lines[:3] + [lines[2]] + lines[3:]):
            with self.subTest(changed=changed[:4]):
                report = score_response(self.response("\n".join(changed)), self.expected)
                self.assertFalse(report["passed"])
                self.assertEqual(report["coverage"]["status"], "incomplete")

    def test_duplicate_and_contradictory_totals_are_rejected(self):
        last = self.answer().splitlines()[-1]
        for duplicate in (last, last.replace("3,953,593,262", "1")):
            report = score_response(self.response(self.answer() + "\n" + duplicate), self.expected)
            self.assertFalse(report["passed"])
            self.assertIn("duplicate-total:combined", report["failures"])

    def test_wrong_money_count_or_currency_fails(self):
        for old, new in (
            ("$39,535,932.62", "$39,535,932.63"),
            ("**262**", "**261**"),
            ("3,953,593,262", "3,95,3593,262"),
            ("USD cents", "EUR cents"),
            ("$39,535,932.62", "NaN"),
        ):
            with self.subTest(new=new):
                report = score_response(self.response(self.answer().replace(old, new)), self.expected)
                self.assertFalse(report["passed"])

    def test_unknown_source_or_range_and_oversized_group_fail(self):
        lines = self.answer().splitlines()
        for replacement in (
            "| other | SALE-000001 | SALE-000020 | 20 | 240,458,278 |",
            "| json | SALE-000000 | SALE-000020 | 20 | 240,458,278 |",
            "| json | SALE-000020 | SALE-000001 | 20 | 240,458,278 |",
            "| json | SALE-000001 | SALE-000040 | 40 | 535,585,829 |",
            "| json | SALE-000001 | SALE-000020 | true | 240,458,278 |",
        ):
            with self.subTest(row=replacement):
                report = score_response(self.response("\n".join(lines[:2] + [replacement] + lines[3:])), self.expected)
                self.assertFalse(report["passed"])

    def test_missing_metadata_failed_status_and_tools_do_not_pass(self):
        for update in (
            {"status": "incomplete"}, {"status": None}, {"output_types": []},
            {"output_types": ["message", "code_interpreter_call"]}, {"calculator_used": True},
            {"oracle_supplied": True},
        ):
            with self.subTest(update=update):
                report = score_response({**self.response(), **update}, self.expected)
                self.assertFalse(report["passed"])

    def test_raw_responses_output_is_supported_without_hidden_reasoning_text(self):
        raw = {
            "id": "synthetic-raw-response", "status": "completed",
            "output": [
                {"type": "reasoning", "summary": [{"text": "irrelevant"}]},
                {"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": self.answer()},
                ]},
            ],
        }
        self.assertTrue(score_response(raw, self.expected)["passed"])
        raw["output"].insert(0, {"type": "mcp_call", "name": "aggregate_sales", "output": "{}"})
        self.assertFalse(score_response(raw, self.expected)["passed"])

    def test_mcp_errors_fail_even_when_answer_matches(self):
        response = self.response()
        response["output_types"] = ["mcp_call", "message"]
        response["retrieval_calls"] = [{"name": "knowledge_base_retrieve", "error": "failed"}]
        self.assertFalse(score_response(response, self.expected)["passed"])

    def test_malformed_raw_output_cannot_crash_or_pass(self):
        for output in ([None], [{"type": "message", "role": "assistant", "content": [None]}]):
            report = score_response({"status": "completed", "output": output}, self.expected)
            self.assertFalse(report["passed"])
        for update in ({"output_types": ["message", {}]}, {"output": {}}):
            self.assertFalse(score_response({**self.response(), **update}, self.expected)["passed"])

    def test_duplicate_total_is_not_labelled_correct(self):
        text = self.answer()
        report = score_response(self.response(text + "\n" + text.splitlines()[-1]), self.expected)
        self.assertNotEqual(report["totals"]["status"], "correct")

    def test_known_header_variations_and_column_order_are_supported(self):
        text = self.answer().replace("Records | Net subtotal", "Record count | Net subtotal")
        text = text.replace("Deduplicated record count", "Records").replace("Net total (USD)", "USD")
        self.assertTrue(score_response(self.response(text), self.expected)["passed"])
        lines = text.splitlines()
        swapped = []
        for line in lines:
            if line.startswith("|"):
                cells = line.strip("|").split("|")
                cells[0], cells[1] = cells[1], cells[0]
                line = "|" + "|".join(cells) + "|"
            swapped.append(line)
        self.assertTrue(score_response(self.response("\n".join(swapped)), self.expected)["passed"])

    def test_code_fenced_examples_and_unsupported_rows_do_not_count(self):
        report = score_response(self.response("```text\n" + self.answer() + "\n```"), self.expected)
        self.assertFalse(report["passed"])
        report = score_response(self.response(self.answer() + "\n| combined | broken |"), self.expected)
        self.assertFalse(report["passed"])

    def test_recorded_source_binding_must_match_fixture(self):
        response = self.response()
        response["sources"] = [
            {"source": part["id"], "content_sha256": part["input_sha256"]}
            for part in self.config["partitions"]
        ]
        self.assertTrue(score_response(response, self.expected)["passed"])
        response["sources"][0]["content_sha256"] = "0" * 64
        self.assertFalse(score_response(response, self.expected)["passed"])

    def test_oracle_mismatch_and_changed_authoritative_rows_fail(self):
        config = deepcopy(self.config)
        config["partitions"][0]["rows_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            load_expected(config, self.oracle)
        oracle = json.loads(self.oracle.read_text())
        oracle["total_minor"] += 1
        path = self.root / "incorrect-oracle.json"
        path.write_text(json.dumps(oracle), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_expected(self.config, path)

    def test_checker_cli_is_offline_and_refuses_data_or_input_overwrite(self):
        spec = importlib.util.spec_from_file_location("check_sum_entry", Path(__file__).resolve().parents[1] / "check_sum.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        result = self.root / "result.json"
        result.write_text(json.dumps(self.response()), encoding="utf-8")
        config = self.root / "config.json"
        config.write_text("{}", encoding="utf-8")
        args = entry.parser().parse_args([
            "--config", str(config), "--oracle", str(self.oracle),
            "--result", str(result), "--output", str(self.root / "score.json"),
        ])
        with patch.object(entry, "load_config", return_value=self.config):
            self.assertTrue(entry.run(args)["passed"])
            for destination in (result, config, self.oracle, self.root / "data" / "new-score.json"):
                args.output = destination
                with self.subTest(destination=destination), self.assertRaises(ValueError):
                    entry.run(args)
        self.assertFalse(hasattr(entry, "operator"))


if __name__ == "__main__":
    unittest.main()
