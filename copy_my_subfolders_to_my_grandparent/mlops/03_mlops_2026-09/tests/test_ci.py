import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import yaml

SPEC = importlib.util.spec_from_file_location("ci", Path(__file__).parents[1] / "scripts" / "ci.py")
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class PollTests(unittest.TestCase):
    def poll(self, statuses):
        statuses = iter(statuses)
        return ci.wait_for_job("az", ["--workspace-name", "example"], "job", 30, 1,
                               execute=lambda *a, **k: json.dumps({"status": next(statuses)}),
                               sleep=lambda _: None)

    def test_running_then_completed(self):
        self.assertEqual(self.poll(["Queued", "Running", "Completed"])["status"], "Completed")
        self.assertEqual(self.poll(["Succeeded"])["status"], "Succeeded")
        self.assertEqual(ci.status_outcome("Completed"), "Succeeded")

    def test_failure_and_unknown_are_not_success(self):
        for status in ["Failed", "Canceled", "Cancelled", "NotResponding", "", None, "NewStatus", {}]:
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.poll([status])

    def test_timeout_never_succeeds(self):
        ticks = iter([0, 0, 40])
        with self.assertRaises(TimeoutError):
            ci.wait_for_job("az", [], "job", 30, 1,
                            execute=lambda *a, **k: '{"status":"Running"}',
                            clock=lambda: next(ticks), sleep=lambda _: None)

    def test_invalid_timeouts(self):
        for timeout in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                ci.wait_for_job("az", [], "job", timeout, 1)

    def test_malformed_response_fails(self):
        with self.assertRaises(ValueError):
            ci.wait_for_job("az", [], "job", 30, 1, execute=lambda *a, **k: "not JSON")
        with self.assertRaises(ValueError):
            ci.wait_for_job("az", [], "job", 30, 1, execute=lambda *a, **k: "[]")

    def test_target_must_be_explicit(self):
        with self.assertRaises(ValueError):
            ci.target({})
        self.assertEqual(ci.target({
            "subscription_id": "sub", "resource_group": "rg", "workspace_name": "ws",
        }), ["--subscription", "sub", "--resource-group", "rg", "--workspace-name", "ws"])


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".ci-test-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.runtime = self.root / "runtime.json"
        self.runtime.write_text(json.dumps({
            "subscription_id": "sub", "resource_group": "rg", "workspace_name": "ws",
        }), encoding="utf-8")
        self.args = SimpleNamespace(
            scenario="scenario.json", runtime=str(self.runtime), output=str(self.root),
            mode="custom", ml_extension_version="2.38.1", timeout_seconds=30, poll_seconds=1,
        )
        self.receipt = self.root / "registered-model.json"
        self.receipt.write_text('{"id":"stale"}', encoding="utf-8")
        self.cli = self.enterContext(patch.object(ci, "cli", side_effect=self.fake_cli))
        self.run = self.enterContext(patch.object(ci, "run", side_effect=["2.38.1", "job-one"]))
        self.enterContext(patch.object(ci.shutil, "which", return_value="az"))
        self.wait = self.enterContext(patch.object(ci, "wait_for_job", return_value={"status": "Completed"}))
        self.register = self.enterContext(patch.object(ci, "register_evaluated",
                                                      return_value={"id": "/models/example/versions/1"}))

    def fake_cli(self, *args):
        if args[0] == "render":
            bundle = Path(args[args.index("--output") + 1])
            self.assertFalse(bundle.exists())
            bundle.mkdir(parents=True)
            (bundle / "pipeline.yml").write_text("type: pipeline\n", encoding="utf-8")
        return "{}"

    def test_completed_then_verified_registration(self):
        ci.train(self.args)
        self.wait.assert_called_once()
        self.register.assert_called_once()
        self.assertEqual(json.loads(self.receipt.read_text())["id"], "/models/example/versions/1")
        command = self.run.call_args_list[1].args[0]
        job_path = Path(command[command.index("-f") + 1])
        self.assertEqual(job_path.name, "pipeline.yml")
        self.assertTrue(job_path.parent.name.startswith("bundle-"))
        self.assertEqual(self.register.call_args.args[2], job_path.parent)

    def test_repeat_uses_a_fresh_empty_bundle(self):
        ci.train(self.args)
        first = self.register.call_args.args[2]
        self.run.side_effect = ["2.38.1", "job-two"]
        ci.train(self.args)
        second = self.register.call_args.args[2]
        self.assertNotEqual(first, second)
        self.assertTrue((first / "pipeline.yml").exists())
        self.assertTrue((second / "pipeline.yml").exists())

    def lake_runtime(self):
        runtime = json.loads(self.runtime.read_text())
        runtime["lake"] = {
            "project": "001", "environment": "dev", "dataset": "stable-data", "data_version": "1",
            "snapshot_id": "reviewed-snapshot", "run_id": "must-not-reuse", "serving": "batch",
        }
        self.runtime.write_text(json.dumps(runtime), encoding="utf-8")
        scenario = self.root / "scenario.json"
        scenario.write_text('{"name":"test-case"}', encoding="utf-8")
        self.args.scenario = str(scenario)
        return runtime

    def test_lake_reruns_get_unique_runtime_without_rewriting_snapshot(self):
        original = self.lake_runtime()
        ci.train(self.args)
        first = self.register.call_args.args[1]
        self.run.side_effect = ["2.38.1", "job-two"]
        ci.train(self.args)
        second = self.register.call_args.args[1]
        self.assertNotEqual(first["lake"]["run_id"], second["lake"]["run_id"])
        self.assertNotEqual(first["lake"]["run_id"], original["lake"]["run_id"])
        self.assertEqual(first["lake"]["snapshot_id"], original["lake"]["snapshot_id"])
        self.assertEqual(second["lake"]["snapshot_id"], original["lake"]["snapshot_id"])
        self.assertEqual(json.loads(self.runtime.read_text()), original)
        for call in self.cli.call_args_list:
            args = call.args
            persisted = json.loads(Path(args[args.index("--runtime") + 1]).read_text())
            self.assertIn(persisted["lake"]["run_id"], {first["lake"]["run_id"], second["lake"]["run_id"]})

    def test_intentional_lake_run_override_and_no_legacy_override(self):
        self.lake_runtime()
        self.args.lake_run_id = "reviewed-new-execution"
        ci.train(self.args)
        self.assertEqual(self.register.call_args.args[1]["lake"]["run_id"], "reviewed-new-execution")
        with self.assertRaises(ValueError):
            ci.training_runtime({}, self.args.scenario, "not-lake")

    def test_invalid_lake_run_fails_before_cloud_or_runtime_write(self):
        self.lake_runtime()
        self.args.lake_run_id = "../escape"
        with self.assertRaises(ValueError):
            ci.train(self.args)
        self.run.assert_not_called()
        self.assertEqual(list(self.root.glob("bundle-*")), [])

    def test_failed_job_never_registers_or_keeps_stale_receipt(self):
        self.wait.side_effect = RuntimeError("Failed")
        with self.assertRaises(RuntimeError):
            ci.train(self.args)
        self.register.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_failed_quality_gate_cannot_produce_receipt(self):
        self.register.side_effect = ValueError("quality-gate.json did not pass")
        with self.assertRaises(ValueError):
            ci.train(self.args)
        self.assertFalse(self.receipt.exists())

    def test_missing_registration_id_cannot_produce_receipt(self):
        self.register.return_value = {}
        with self.assertRaises(RuntimeError):
            ci.train(self.args)
        self.assertFalse(self.receipt.exists())

    def test_wrong_extension_stops_before_queue(self):
        self.run.side_effect = ["2.99.0"]
        with self.assertRaises(RuntimeError):
            ci.train(self.args)
        self.cli.assert_not_called()
        self.register.assert_not_called()

    def test_bad_timeout_stops_before_queue(self):
        self.args.timeout_seconds = 0
        with self.assertRaises(ValueError):
            ci.train(self.args)
        self.run.assert_not_called()

    def test_offline_validate_uses_no_azure_commands(self):
        with patch.object(ci.sys, "argv", ["ci.py", "validate", "--scenario", "scenario.json"]):
            self.assertEqual(ci.main(), 0)
        self.cli.assert_called_once_with("validate", "--scenario", "scenario.json")
        self.run.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parents[1]
        self.github = yaml.safe_load((self.root / "github" / "ml-factory.yml").read_text())
        self.ado = yaml.safe_load((self.root / "ado" / "ml-factory.yml").read_text())

    def test_reusable_and_manual_only(self):
        self.assertEqual(set(self.github["on"]), {"workflow_call", "workflow_dispatch"})
        self.assertLessEqual(len(self.github["on"]["workflow_dispatch"]["inputs"]), 10)
        self.assertEqual(self.github["permissions"], {"contents": "read"})
        for job in self.github["jobs"].values():
            self.assertEqual(job["runs-on"][:2], ["self-hosted", "Windows"])
        for name in ("train", "deploy"):
            self.assertEqual(self.github["jobs"][name]["permissions"]["id-token"], "write")
            self.assertEqual(self.github["jobs"][name]["needs"], "validate")
        self.assertEqual(self.github["jobs"]["deploy"]["if"], "inputs.action == 'deploy'")
        self.assertTrue(self.github["jobs"]["deploy"]["environment"])

    def test_offline_jobs_have_no_installs_or_login(self):
        for definition in (self.github["jobs"]["validate"], self.ado["stages"][0]):
            text = json.dumps(definition)
            for disallowed in ("azure/login", "AzureCLI@", "bootstrap.py", "pip install", "az ml"):
                self.assertNotIn(disallowed, text)

    def test_generic_parameters_and_pinned_cli(self):
        parameters = {p["name"] for p in self.ado["parameters"]}
        self.assertTrue({"poolName", "agentName", "serviceConnection", "scenario", "runtime"} <= parameters)
        self.assertEqual(ci.ML_EXTENSION_VERSION, "2.38.1")
        self.assertIn("TENANT_ID", self.github["on"]["workflow_call"]["secrets"])
        for path in (self.root / "ado" / "ml-factory.yml", self.root / "github" / "ml-factory.yml"):
            for deployment_name in ("dsvm-cmn-sdc-dev-001", "sc-spider-dev-001", "adf-001-sdc-dev-bltsc-001"):
                self.assertNotIn(deployment_name, path.read_text())


class CoreContractTests(unittest.TestCase):
    def test_real_offline_validate_and_render_contract(self):
        from ml_model_factory.azureml import render
        import ml_model_factory

        root = Path(__file__).parent / (".core-test-" + uuid4().hex)
        root.mkdir()
        self.addCleanup(shutil.rmtree, root)
        scenario = {
            "name": "ci-contract", "task": "classification", "target": "label",
            "features": ["feature"], "quality": {"min_accuracy": 0.5},
            "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "example/example",
                        "version": 1, "file": "input.csv"},
        }
        runtime = {
            "subscription_id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "resource_group": "example-rg", "workspace_name": "example-workspace",
            "compute": "example-compute",
            "input_data": "azureml://datastores/example/paths/raw.csv",
            "environment": "azureml:approved-environment:1",
        }
        scenario_path, runtime_path = root / "scenario.json", root / "runtime.json"
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).parents[1] / "scripts" / "ci.py"),
             "validate", "--scenario", str(scenario_path), "--runtime", str(runtime_path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
        self.assertTrue(json.loads(completed.stdout)["valid"])
        source = Path(ml_model_factory.__file__).resolve().parents[1]
        bundle = root / "bundle"
        render(scenario, runtime, bundle, source, mode="custom")
        self.assertEqual(yaml.safe_load((bundle / "pipeline.yml").read_text())["type"], "pipeline")
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(manifest["scenario_name"], "ci-contract")
        self.assertTrue(manifest["model_name"])


if __name__ == "__main__":
    unittest.main()
