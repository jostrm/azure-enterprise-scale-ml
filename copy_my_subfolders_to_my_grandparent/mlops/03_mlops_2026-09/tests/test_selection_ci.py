import contextlib
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import yaml

SPEC = importlib.util.spec_from_file_location("selection_ci", Path(__file__).parents[1] / "scripts" / "ci.py")
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class SelectionTrainingTests(unittest.TestCase):
    def setUp(self):
        from ml_model_factory import azureml

        self.root = Path(__file__).parent / (".selection-ci-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.output = self.root / "output"
        self.runtime = {
            "subscription_id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "resource_group": "fixture-rg", "workspace_name": "fixture-workspace",
            "compute": "fixture-compute", "environment": "azureml:fixture-environment:1",
            "input_data": "azureml://datastores/fixture/paths/input.csv",
            "aifactory": "fixture-factory", "project": "001", "environment_name": "dev",
            "model_selection": {"policy": "policy.json", "champion_evaluation": "champion.json"},
        }
        self.scenario = {
            "name": "selection-test", "task": "classification", "target": "label",
            "features": ["feature"], "quality": {"min_accuracy": 0.5},
            "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/data",
                        "version": 1, "file": "input.csv"},
        }
        self.policy = {
            "schema": "aifactory.model-selection-policy/v1", "on_no_champion": "candidate_if_qualified",
            "profiles": {"classification": {
                "require_any_improvement": True, "on_tie": "keep_champion",
                "metrics": [
                    {"metric": "accuracy", "direction": "maximize", "min_delta": 0.02, "delta_mode": "absolute"},
                    {"metric": "f1_weighted", "direction": "maximize", "min_delta": -0.01, "delta_mode": "absolute"},
                ],
            }},
        }
        self.candidate = {
            "schema": "aifactory.model-evaluation/v1", "model_id": "sha256:" + "c" * 64,
            "scope": {"aifactory": "fixture-factory", "project": "001", "environment": "dev"},
            "use_case": "selection-test", "task_type": "classification",
            "evaluation": {"dataset_sha256": "a" * 64, "contract_sha256": "b" * 64,
                           "row_count": 10, "split": "test", "evaluator": "ml-model-factory/v1"},
            "quality_gate": {"passed": True}, "metrics": {"accuracy": 0.85, "f1_weighted": 0.79},
        }
        self.champion = deepcopy(self.candidate)
        self.champion.update(model_id="sha256:" + "d" * 64, metrics={"accuracy": 0.80, "f1_weighted": 0.80})
        self.write("runtime.json", self.runtime)
        self.write("scenario.json", self.scenario)
        self.write("policy.json", self.policy)
        self.write("champion.json", self.champion)
        self.args = SimpleNamespace(
            scenario=str(self.root / "scenario.json"), runtime=str(self.root / "runtime.json"),
            output=str(self.output), mode="custom", ml_extension_version=ci.ML_EXTENSION_VERSION,
            timeout_seconds=30, poll_seconds=1,
        )
        self.events = []
        self.downloaded = []
        self.report_count = 1
        self.download = Mock(side_effect=self.fake_download)
        self.client = self.enterContext(patch.object(
            azureml, "_client", return_value=SimpleNamespace(jobs=SimpleNamespace(download=self.download))))
        self.register = self.enterContext(patch.object(azureml, "register", side_effect=self.fake_register))
        self.real_run = ci.subprocess.run
        self.transport = self.enterContext(patch.object(ci.subprocess, "run", side_effect=self.fake_transport))
        self.enterContext(patch.object(ci.shutil, "which", return_value="fixture-az"))
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def fake_transport(self, command, **kwargs):
        if command[0] != "fixture-az":
            return self.real_run(command, **kwargs)
        if command[1:3] == ["extension", "show"]:
            return SimpleNamespace(stdout=ci.ML_EXTENSION_VERSION, stderr="")
        if command[1:4] == ["ml", "job", "create"]:
            self.events.append("submit")
            return SimpleNamespace(stdout="submitted-job", stderr="")
        if command[1:4] == ["ml", "job", "show"]:
            self.events.append("completed")
            return SimpleNamespace(stdout='{"status":"Completed"}', stderr="")
        raise AssertionError(f"Unexpected Azure operation: {command}")

    def fake_download(self, *, name, download_path, output_name):
        self.assertEqual(name, "submitted-job")
        self.assertEqual(output_name, "report")
        folder = Path(download_path)
        self.assertEqual(list(folder.iterdir()), [])
        self.downloaded.append(folder)
        self.events.append("download")
        for index in range(self.report_count):
            report = folder / "named-outputs" / ("report" + str(index))
            report.mkdir(parents=True)
            (report / "comparison.json").write_text(json.dumps(self.candidate), encoding="utf-8")

    def fake_register(self, name, runtime, model_name, **selection):
        self.assertEqual(name, "submitted-job")
        self.assertEqual(model_name, "selection-test")
        if "model_selection" in runtime or getattr(self.args, "selection_policy", None):
            self.assertEqual(self.decision()["decision"], "candidate_wins")
            self.assertEqual(self.events[-1], "download")
            self.assertEqual(selection["selection_policy"], self.policy)
            self.assertEqual(selection["no_champion"], self.decision()["provenance"]["no_champion"])
            self.assertEqual(selection["champion_evaluation"], None if selection["no_champion"] else self.champion)
            self.assertEqual(selection["decision_path"], self.output / "registration-selection-decision.json")
        else:
            self.assertEqual(selection, {})
        self.events.append("register")
        return "/models/selection-test/versions/1"

    def decision(self):
        return json.loads((self.output / "selection-decision.json").read_text())

    def status(self):
        return json.loads((self.output / "training-status.json").read_text())

    def assert_blocked(self, message=None):
        with self.assertRaises(ValueError) as caught:
            ci.train(self.args)
        if message:
            self.assertIn(message, str(caught.exception))
        self.register.assert_not_called()
        self.assertFalse((self.output / "registered-model.json").exists())
        self.assertEqual(self.status()["outcome"], "Failed")
        self.assertEqual(self.decision()["decision"], "blocked")
        self.assertIs(self.decision()["promotion_allowed"], False)

    def test_winner_uses_real_rules_and_registers_after_exact_job_report(self):
        ci.train(self.args)
        self.assertEqual(self.events, ["submit", "completed", "download", "register"])
        self.assertEqual(self.decision()["decision"], "candidate_wins")
        comparisons = self.decision()["comparisons"]
        self.assertEqual([row["passed"] for row in comparisons], [True, True])
        self.assertEqual(comparisons[1]["min_delta"], -0.01)
        self.assertEqual(self.status()["registration"], "registered")
        provenance = self.decision()["provenance"]
        self.assertEqual(provenance["pipeline_job"], "submitted-job")
        self.assertEqual(provenance["output_name"], "report")
        self.assertEqual(provenance["policy_sha256"], hashlib.sha256((self.root / "policy.json").read_bytes()).hexdigest())
        self.assertEqual(provenance["candidate_evaluation_sha256"],
                         hashlib.sha256(Path(provenance["candidate_evaluation_path"]).read_bytes()).hexdigest())
        self.assertEqual(json.loads((self.output / "registered-model.json").read_text())["job"], "submitted-job")

    def test_champion_kept_is_success_without_registration_or_stale_receipt(self):
        self.output.mkdir()
        (self.output / "registered-model.json").write_text('{"id":"stale"}')
        self.candidate["metrics"]["accuracy"] = 0.81
        ci.train(self.args)
        self.register.assert_not_called()
        self.assertFalse((self.output / "registered-model.json").exists())
        self.assertEqual(self.status()["outcome"], "Succeeded")
        self.assertEqual(self.status()["registration"], "skipped")
        self.assertEqual(self.decision()["winner_id"], self.champion["model_id"])
        printed = json.loads(self.stdout.getvalue())
        self.assertEqual(printed["decision"], "champion_kept")
        self.assertIs(printed["promotion_allowed"], False)

    def test_bootstrap_requires_explicit_choice_and_quality(self):
        self.runtime["model_selection"] = {"policy": "policy.json", "no_champion": True}
        self.write("runtime.json", self.runtime)
        ci.train(self.args)
        self.assertEqual(self.decision()["decision"], "candidate_wins")
        self.assertIs(self.decision()["provenance"]["no_champion"], True)
        self.assertIsNone(self.decision()["champion_id"])

    def test_bootstrap_policy_can_block_even_explicit_no_champion(self):
        self.runtime["model_selection"] = {"policy": "policy.json", "no_champion": True}
        self.write("runtime.json", self.runtime)
        self.policy["on_no_champion"] = "block"
        self.write("policy.json", self.policy)
        self.assert_blocked("without a champion")

    def test_no_selection_preserves_registration_without_download(self):
        self.runtime.pop("model_selection")
        self.write("runtime.json", self.runtime)
        ci.train(self.args)
        self.download.assert_not_called()
        self.register.assert_called_once()
        self.assertFalse((self.output / "selection-decision.json").exists())
        self.assertEqual(self.status()["decision"], "selection_disabled")

    def test_cli_selection_paths_resolve_beside_runtime_not_current_directory(self):
        self.runtime.pop("model_selection")
        self.write("runtime.json", self.runtime)
        self.args.selection_policy = "policy.json"
        self.args.champion_evaluation = "champion.json"
        ci.train(self.args)
        self.assertEqual(self.decision()["provenance"]["policy_path"], str((self.root / "policy.json").resolve()))

    def test_invalid_or_missing_selection_controls_fail_before_cloud(self):
        invalid = [
            None, [], {}, {"policy": "policy.json"},
            {"policy": "policy.json", "no_champion": False},
            {"policy": "policy.json", "no_champion": "true"},
            {"policy": "policy.json", "no_champion": True, "champion_evaluation": "champion.json"},
            {"policy": "policy.json", "champion_evaluation": "missing.json"},
            {"policy": "policy.json", "champion_evaluation": ""},
            {"policy": "policy.json", "no_champion": True, "candidate_evaluation": "manual.json"},
            {"policy": "missing.json", "no_champion": True},
        ]
        for config in invalid:
            with self.subTest(config=config):
                self.runtime["model_selection"] = config
                self.write("runtime.json", self.runtime)
                with self.assertRaises(ValueError):
                    ci.train(self.args)
        self.transport.assert_not_called()
        self.download.assert_not_called()
        self.register.assert_not_called()

    def test_cli_does_not_inherit_a_missing_explicit_champion_choice(self):
        self.args.selection_policy = "policy.json"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            ci.train(self.args)
        self.args.selection_policy = None
        self.args.no_champion = True
        with self.assertRaisesRegex(ValueError, "requires --selection-policy"):
            ci.train(self.args)
        self.transport.assert_not_called()

    def test_unknown_policy_metric_fails_before_cloud(self):
        self.policy["profiles"]["classification"]["metrics"][0]["metric"] = "acuracy"
        self.write("policy.json", self.policy)
        with self.assertRaisesRegex(ValueError, "metric"):
            ci.train(self.args)
        self.transport.assert_not_called()

    def test_policy_and_champion_files_must_contain_objects(self):
        for filename, value in (("champion.json", None), ("champion.json", []), ("policy.json", [])):
            with self.subTest(filename=filename, value=value):
                self.write(filename, value)
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    ci.train(self.args)
        self.transport.assert_not_called()

    def test_missing_downloaded_report_cannot_use_manual_or_stale_evidence(self):
        self.output.mkdir()
        (self.output / "comparison.json").write_text(json.dumps(self.candidate))
        self.report_count = 0
        self.assert_blocked("exactly one comparison.json")

    def test_multiple_downloaded_reports_are_ambiguous(self):
        self.report_count = 2
        self.assert_blocked("exactly one comparison.json")

    def test_invalid_job_report_json_is_blocked_and_audited(self):
        def invalid_report(**kwargs):
            (Path(kwargs["download_path"]) / "comparison.json").write_text("{invalid")
        self.download.side_effect = invalid_report
        self.assert_blocked()

    def test_download_transport_failure_is_blocked_and_audited(self):
        self.download.side_effect = RuntimeError("report download unavailable")
        self.assert_blocked("report download unavailable")

    def test_scope_mismatch_is_blocked_even_without_a_champion(self):
        self.runtime["model_selection"] = {"policy": "policy.json", "no_champion": True}
        self.write("runtime.json", self.runtime)
        self.candidate["scope"]["environment"] = "prod"
        self.assert_blocked("scope")

    def test_untyped_candidate_fields_are_blocked_with_actionable_artifacts(self):
        original = deepcopy(self.candidate)
        for candidate in (None, [], {**original, "scope": None}, {**original, "source_context": None},
                          {**original, "quality_gate": None}, {**original, "evaluation": None},
                          {**original, "metrics": None}):
            with self.subTest(candidate=candidate):
                self.candidate = candidate
                self.assert_blocked()
                self.assertTrue(self.decision()["reasons"])

    def test_wrong_task_use_case_or_explicit_job_context_is_blocked(self):
        original = deepcopy(self.candidate)
        for change in ({"task_type": "regression"}, {"use_case": "other-case"},
                       {"source_context": {"pipeline_job": "different-job"}},
                       {"source_context": {"pipeline_job_name": "different-job"}}):
            with self.subTest(change=change):
                self.candidate = deepcopy(original)
                self.candidate.update(change)
                self.assert_blocked()

    def test_incompatible_benchmark_and_undefined_metric_block_registration(self):
        original = deepcopy(self.candidate)
        changes = (
            ("dataset_sha256", "e" * 64), ("contract_sha256", "e" * 64),
            ("row_count", 11), ("evaluator", "unsupported/v2"), ("split", "train"),
        )
        for key, value in changes:
            with self.subTest(field=key):
                self.candidate = deepcopy(original)
                self.candidate["evaluation"][key] = value
                self.assert_blocked()
        self.candidate = deepcopy(original)
        del self.candidate["metrics"]["f1_weighted"]
        self.assert_blocked("metric")
        self.candidate = deepcopy(original)
        self.candidate["quality_gate"]["passed"] = False
        self.assert_blocked("quality")

    def test_repeat_downloads_use_fresh_directories(self):
        ci.train(self.args)
        ci.train(self.args)
        self.assertEqual(len(set(self.downloaded)), 2)

    def test_existing_registration_gate_can_still_refuse_the_winner(self):
        self.register.side_effect = ValueError("existing registration lineage gate failed")
        with self.assertRaisesRegex(ValueError, "lineage gate"):
            ci.train(self.args)
        self.assertEqual(self.decision()["decision"], "candidate_wins")
        self.assertFalse((self.output / "registered-model.json").exists())
        self.assertEqual(self.status()["outcome"], "Failed")

    def test_registration_recheck_keeping_champion_is_also_successful(self):
        from ml_model_factory.azureml import ModelSelectionRejected
        from ml_model_factory.selection import compare

        changed = deepcopy(self.candidate)
        changed["metrics"]["accuracy"] = 0.81
        rechecked = compare(self.policy, changed, self.champion)
        self.register.side_effect = ModelSelectionRejected(rechecked)
        ci.train(self.args)
        self.assertEqual(self.status()["outcome"], "Succeeded")
        self.assertEqual(self.status()["registration"], "skipped")
        self.assertEqual(self.decision()["decision"], "champion_kept")
        self.assertEqual(self.decision()["provenance"]["stage"], "registration_recheck")
        self.assertFalse((self.output / "registered-model.json").exists())

    def test_registration_recheck_blocking_winner_cannot_create_receipt(self):
        from ml_model_factory.azureml import ModelSelectionRejected
        from ml_model_factory.selection import compare

        changed = deepcopy(self.candidate)
        changed["evaluation"]["dataset_sha256"] = "f" * 64
        self.register.side_effect = ModelSelectionRejected(compare(self.policy, changed, self.champion))
        with self.assertRaises(ModelSelectionRejected):
            ci.train(self.args)
        self.assertEqual(self.decision()["decision"], "blocked")
        self.assertEqual(self.status()["outcome"], "Failed")
        self.assertFalse((self.output / "registered-model.json").exists())


class SelectionWorkflowTests(unittest.TestCase):
    def test_artifacts_do_not_require_registration_receipt_when_champion_is_kept(self):
        root = Path(__file__).parents[1]
        github = yaml.safe_load((root / "github" / "ml-factory.yml").read_text())
        self.assertLessEqual(len(github["on"]["workflow_dispatch"]["inputs"]), 10)
        uploads = [step for step in github["jobs"]["train"]["steps"]
                   if step.get("uses", "").startswith("actions/upload-artifact@")]
        receipt = next(step for step in uploads if step["with"]["name"] == "evaluated-model-registration")
        decision = next(step for step in uploads if step["with"]["name"] == "model-training-outcome")
        self.assertIn("hashFiles('generated/registered-model.json')", receipt["if"])
        self.assertEqual(decision["if"], "always()")
        self.assertIn("selection-decision.json", decision["with"]["path"])
        self.assertNotEqual(decision["with"]["if-no-files-found"], "error")
        ado = yaml.safe_load((root / "ado" / "ml-factory.yml").read_text())
        train = next(stage for stage in ado["stages"] if "${{ if eq(parameters.action, 'train') }}" in stage)
        steps = train["${{ if eq(parameters.action, 'train') }}"][0]["jobs"][0]["steps"]
        publications = {step["artifact"]: step for step in steps if "publish" in step}
        self.assertIn("registrationReceiptPresent", publications["evaluated-model-registration"]["condition"])
        self.assertEqual(publications["model-training-outcome"]["condition"], "always()")
        self.assertEqual(github["jobs"]["deploy"]["if"], "inputs.action == 'deploy'")
        self.assertEqual(github["jobs"]["deploy"]["needs"], "validate")
        self.assertTrue(github["jobs"]["deploy"]["environment"])


if __name__ == "__main__":
    unittest.main()
