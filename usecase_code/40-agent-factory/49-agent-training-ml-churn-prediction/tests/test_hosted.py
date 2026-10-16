"""Hosted (Foundry Playground) mode: packaging, shared receipts, per-user approval and resumable jobs."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid
import zipfile

import pandas as pd

from tests.support import TEMPLATE, consumer

from ml_agent import esml, factory, hosted, hosted_package
from ml_agent.configuration import fingerprint, paths, read_json, write_json
from ml_agent.lake import LakeIO
from ml_agent.plan import PUBLICATIONS
from ml_agent.runtime import MLRuntime
from ml_agent.usecases import AIR, CHURN

DATASTORE = "azureml://datastores/esml_shared_lake/paths/"


def conflict(message: str):
    from azure.core.exceptions import HttpResponseError

    error = HttpResponseError(message=message)
    error.status_code = 409
    return error


class LakeContainer:
    """In-memory ADLS Gen2 (hierarchical namespace) container: ETags, conditional/create-only uploads,
    directory entries listed as blobs, deletes and expiring leases."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.folders: set[str] = set()
        self.leases: dict[str, tuple[str, datetime]] = {}
        self.fail_uploads: set[str] = set()

    def list_blobs(self, name_starts_with="", include=None):
        metadata = include is not None and "metadata" in include
        files = [SimpleNamespace(name=name, etag=self.etags[name], metadata={} if metadata else None)
                 for name in self.blobs]
        folders = [SimpleNamespace(name=name, etag='"folder"', metadata={"hdi_isfolder": "true"} if metadata else None)
                   for name in self.folders]
        return sorted((item for item in files + folders if item.name.startswith(name_starts_with)),
                      key=lambda item: item.name)

    def upload_blob(self, name, data, overwrite=False, etag=None, match_condition=None):
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

        if any(name.endswith(suffix) for suffix in self.fail_uploads):
            raise ConnectionError("simulated transient upload failure")
        if name in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        if etag is not None and self.etags.get(name) != etag:
            raise ResourceModifiedError("condition not met")
        payload = data.read() if hasattr(data, "read") else data
        self.blobs[name] = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.etags[name] = f'"0x{uuid.uuid4().hex[:12].upper()}"'
        parts = name.split("/")
        self.folders.update("/".join(parts[:index]) for index in range(1, len(parts)))
        return {"etag": self.etags[name]}

    def download_blob(self, name):
        return SimpleNamespace(readall=lambda: self.blobs[name])

    def delete_blob(self, name):
        del self.blobs[name]
        del self.etags[name]

    def get_blob_client(self, name):
        container = self

        class Lease:
            def __init__(self):
                self.id = uuid.uuid4().hex

            def renew(self):
                holder = container.leases.get(name)
                if holder is None or holder[0] != self.id:
                    raise conflict("lease lost")
                container.leases[name] = (self.id, datetime.now(timezone.utc) + timedelta(seconds=60))

            def release(self):
                if container.leases.get(name, ("",))[0] == self.id:
                    del container.leases[name]

        class Client:
            def upload_blob(self, data, overwrite=False, etag=None, match_condition=None):
                return container.upload_blob(name, data, overwrite=overwrite, etag=etag, match_condition=match_condition)

            def acquire_lease(self, lease_duration=60):
                holder = container.leases.get(name)
                if holder is not None and holder[1] > datetime.now(timezone.utc):
                    raise conflict("LeaseAlreadyPresent")
                lease = Lease()
                container.leases[name] = (lease.id, datetime.now(timezone.utc) + timedelta(seconds=lease_duration))
                return lease

        return Client()

    def has(self, suffix: str) -> bool:
        return any(name.endswith(suffix) for name in self.blobs)


class FakeModel:
    """Scripted Responses API: each step is a list of (tool, arguments) calls or a final answer."""

    def __init__(self):
        self.steps: list = []
        self.requests: list[dict] = []
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, str):
            return SimpleNamespace(output=[{"type": "message", "content": [{"type": "output_text", "text": step}]}],
                                   output_text=step)
        calls = [{"type": "function_call", "call_id": f"call-{len(self.requests)}-{index}", "name": name,
                  "arguments": json.dumps(arguments)} for index, (name, arguments) in enumerate(step)]
        return SimpleNamespace(output=calls, output_text="")

    def tool_results(self) -> list[dict]:
        items = self.requests[-1]["input"]
        return [json.loads(item["output"]) for item in items if item.get("type") == "function_call_output"]


def make_bundle(config: dict, root: Path) -> Path:
    for name, data in hosted_package.package_files(config).items():
        if name.startswith("bundle/"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return root / "bundle"


class HostedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.consumer = consumer(cls.root)
        factory.write_scenario(paths(cls.consumer))
        cls.bundle = make_bundle(cls.consumer, cls.root / "package")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.container = LakeContainer()
        self.now = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
        self.waits: dict[str, int] = {}
        self.submitted: list[str] = []
        self.registered: list[str] = []

    # ---- fakes ------------------------------------------------------------------------------
    def project_factory(self, config):
        location = paths(config)

        def build(name):
            project = esml.build_project(config, location, name)

            def execute(plan):
                kind = "inference" if "GOLD_INFERENCE" in plan.document["experiment_name"] else "training"
                intent = "inference-pipeline-intent.json" if kind == "inference" else "training-submission-intent.json"
                # The barrier made the submission intent durable in the lake before the Azure ML call.
                self.assertTrue(self.container.has(intent), f"{intent} was not uploaded before submission")
                job = f"{kind}-job-{name}"
                self.submitted.append(job)
                return {"name": job, "status": "Running"}

            def wait(job, **_):
                self.waits[job] = self.waits.get(job, 0) + 1
                if self.waits[job] == 1:
                    raise TimeoutError(f"Job {job} exceeded the wait limit; it may still be running")
                if job.startswith("inference"):
                    self.publish_predictions(location, name)
                return {"name": job, "status": "Completed"}

            def register(job, **options):
                self.registered.append(job)
                return "azureml:M49_49_agent_training_ml_churn_prediction:2"

            project.execute_pipeline = MagicMock(side_effect=execute)
            project.wait_for_completion = MagicMock(side_effect=wait)
            project.register_outputs = MagicMock(return_value=[])
            project.register_model = MagicMock(side_effect=register)
            project._backend = MagicMock(return_value=SimpleNamespace(get_job=lambda job: {"status": "Running"}))
            return project

        return build

    def publish_predictions(self, location, name):
        receipts = sorted(location.esml(name).glob("*/inference-request.json"))
        planned = read_json(receipts[-1])
        gold = planned["input"][len(DATASTORE):].rstrip("/") + "/data.parquet"
        requests = pd.read_parquet(io.BytesIO(self.container.blobs[gold]))
        buffer = io.BytesIO()
        pd.DataFrame({"request_id": requests["request_id"],
                      "prediction": (["Yes", "No"] * len(requests))[:len(requests)]}).to_parquet(buffer, index=False)
        self.container.upload_blob(planned["output"][len(DATASTORE):].rstrip("/") + "/predictions.parquet",
                                   buffer.getvalue())

    def session(self, home: Path, model: FakeModel) -> hosted.HostedAgent:
        """A fresh sandbox: empty home folder, same bundle and the shared lake container."""
        config = hosted.hosted_config(self.bundle, home)
        lake_io = LakeIO(config, container_client=self.container)

        def runtime_factory(config, **options):
            return MLRuntime(config, project_factory=self.project_factory(config), lake_io=lake_io,
                             publisher=lambda config, staged: {"written": staged["plan"]["files"], "reused": 0},
                             **options)

        return hosted.HostedAgent(config=config, credential=object(), container=self.container, client=model,
                                  bundle=self.bundle, runtime_factory=runtime_factory,
                                  approvals_clock=lambda: self.now)

    # ---- tests ------------------------------------------------------------------------------
    def test_package_is_reproducible_allowlisted_and_free_of_workstation_paths(self):
        first = hosted_package.build_package(self.consumer, self.root / "out-1")
        second = hosted_package.build_package(self.consumer, self.root / "out-2")
        self.assertEqual(first["sha256"], second["sha256"])
        with zipfile.ZipFile(first["package"]) as archive:
            names = archive.namelist()
            bundled = json.loads(archive.read("bundle/config.json"))
            self.assertEqual(archive.read("main.py"), (TEMPLATE / "hosted_main.py").read_bytes().replace(b"\r\n", b"\n"))
            self.assertIn(b"azure-ai-agentserver-responses==2.1.0", archive.read("requirements.txt"))
        for required in ("ml_agent/hosted.py", "azure_esml/__init__.py", "ml_model_factory/__init__.py",
                         "bundle/reviewed-rollout.json", "bundle/champion/training-completion.json",
                         f"bundle/ml-factory/user-config/model/scenarios/{CHURN}.json",
                         "bundle/ml-factory/user-config/model/model-selection.json"):
            self.assertIn(required, names)
        self.assertFalse([name for name in names if "__pycache__" in name or name.endswith(".pyc")
                          or ".venv" in name or name.startswith("tests/")])
        bundled_text = json.dumps(bundled)
        self.assertNotIn(json.dumps(str(self.root))[1:-1], bundled_text)
        self.assertNotIn(str(self.root), bundled_text)
        self.assertEqual(bundled["shared_lake"], self.consumer["shared_lake"])

    def test_hosted_plans_bind_independently_of_the_sandbox_home(self):
        one = hosted.hosted_config(self.bundle, self.root / "home-a")
        two = hosted.hosted_config(self.bundle, self.root / "home-b")
        self.assertEqual(fingerprint(one), fingerprint(two))
        self.assertTrue(one["state_root"].startswith(str(self.root / "home-a")))
        changed = json.loads(json.dumps(two))
        changed["model_deployment"] = "other-model"
        self.assertNotEqual(fingerprint(one), fingerprint(changed))
        self.assertNotEqual(fingerprint(self.consumer), fingerprint(one))

    def test_blob_state_keeps_and_retries_failed_updates_detects_conflicts_and_leases_exclusively(self):
        first, second = self.root / "sync-a", self.root / "sync-b"
        write_json(first / "state" / "plans" / "plan.json", {"plan": 1})
        write_json(first / "esml" / "run" / "training" / "manifest.json", {"m": 1})
        write_json(first / "esml" / "run" / "training" / "code" / "big.json", {"skip": 1})
        write_json(first / "state" / "lake-staging" / "v1" / "file.json", {"skip": 1})
        roots = {"state": first / "state", "esml/x": first / "esml"}
        state = hosted.BlobState(self.container, "root/agent-state", roots, journal=first / "journal.json")
        self.assertEqual(state.push(), 2)
        self.assertEqual(state.push(), 0)
        write_json(first / "esml" / "run" / "training" / "manifest.json", {"m": 2})
        self.container.fail_uploads = {"manifest.json"}
        with self.assertRaises(ConnectionError):
            state.push()
        self.container.fail_uploads = set()
        restarted = hosted.BlobState(self.container, "root/agent-state", roots, journal=first / "journal.json")
        restarted.pull()  # the journaled local update is kept, not replaced by the older remote copy
        self.assertEqual(read_json(first / "esml" / "run" / "training" / "manifest.json"), {"m": 2})
        self.assertEqual(restarted.push(), 1)
        mirror = hosted.BlobState(self.container, "root/agent-state", {"state": second / "state",
                                                                       "esml/x": second / "esml"})
        self.assertEqual(mirror.pull(), 2)
        self.assertEqual(read_json(second / "esml" / "run" / "training" / "manifest.json"), {"m": 2})
        self.assertFalse((second / "esml" / "run" / "training" / "code").exists())
        write_json(second / "state" / "plans" / "plan.json", {"plan": "other session"})
        mirror.push()
        write_json(first / "state" / "plans" / "plan.json", {"plan": "stale session"})
        with self.assertRaises(hosted.StateConflict):
            restarted.push()
        self.assertEqual(json.loads(self.container.blobs["root/agent-state/state/plans/plan.json"]),
                         {"plan": "other session"})
        with restarted.lock():
            with self.assertRaises(hosted.Busy):
                with mirror.lock():
                    pass
        with mirror.lock():
            name = "root/agent-state/lock"
            self.container.leases[name] = (self.container.leases[name][0], datetime.now(timezone.utc))
            with restarted.lock():  # the expired lease is taken over; the old holder cannot release it
                pass
            with self.assertRaises(hosted.StateConflict):
                mirror.barrier()  # the old holder can no longer start an Azure write
            self.assertTrue(mirror.lost.is_set())
        self.assertNotIn("root/agent-state/lock", self.container.leases)

    def test_journal_recognizes_an_upload_that_landed_before_a_crash(self):
        root = self.root / "crash"
        write_json(root / "state" / "receipt.json", {"status": "uploaded"})
        state = hosted.BlobState(self.container, "crash/agent-state", {"state": root / "state"},
                                 journal=root / "journal.json")
        state.push()
        write_json(root / "state" / "receipt.json", {"status": "uploaded", "rows": 50})
        data = (root / "state" / "receipt.json").read_bytes()
        old = self.container.etags["crash/agent-state/state/receipt.json"]
        write_json(root / "journal.json", {"dirty": {"state/receipt.json": {
            "base": old, "digest": hosted._sha256(data)}}})
        self.container.upload_blob("crash/agent-state/state/receipt.json", data, overwrite=True)  # it landed
        restarted = hosted.BlobState(self.container, "crash/agent-state", {"state": root / "state"},
                                     journal=root / "journal.json")
        restarted.pull()
        self.assertEqual(restarted.dirty, {})
        self.assertEqual(restarted.push(), 0)

    def test_pending_inference_reports_only_the_latest_unfinished_attempt(self):
        entry = {"train_run_id": "train-1", "inference_run_id": "inf-1"}
        output = self.root / "attempts"
        write_json(output / "train-1" / "inference-pipeline-job.json", {"name": "job-failed"})
        write_json(output / "train-1-a2" / "inference-pipeline-job.json", {"name": "job-ok"})
        write_json(output / "train-1-a2" / "aif49-inference-result.json", {"rows": 1})
        self.assertIsNone(esml.pending_inference(output, entry))
        write_json(output / "train-1-a3" / "inference-pipeline-job.json", {"name": "job-running"})
        self.assertEqual(esml.pending_inference(output, entry)["job"], "job-running")

    def test_only_the_same_users_own_message_approves_and_writes_expire(self):
        model = FakeModel()
        agent = self.session(self.root / "approve-home", model)
        model.steps = [[("plan_run", {"usecases": [CHURN], "fresh_data": True})], "Reply approve <code> to run it."]
        agent.turn("Plan a churn run from scratch", user="alice", conversation_id="c1")
        planned = model.tool_results()[0]["result"]
        code = planned["approval_code"]
        self.assertEqual((list(planned["usecases"]), planned["not_in_plan"]), ([CHURN], [AIR]))
        self.assertFalse([line for line in planned["azure_writes"] if "M05" in line])
        model.steps = ["Not approved."]
        agent.turn("please approve it", user="alice")
        model.steps = ["Not approved."]
        agent.turn(f"approve {code}", user="bob")
        self.assertIn("no pending plan", model.requests[-1]["instructions"])
        model.steps = ["Not approved."]
        agent.turn("approve 000000000000", user="alice")
        self.assertIn("does not match", model.requests[-1]["instructions"])
        self.assertEqual(agent.approvals.active(hosted.caller("alice")), (None, False))
        model.steps = ["Approved."]
        agent.turn(f"approve {code}", user="alice", conversation_id="c2")
        self.assertIn(f"approved plan {code}", model.requests[-1]["instructions"])
        self.assertTrue(agent.approvals.active(hosted.caller("alice"))[1])
        plan, writable = agent.approvals.active(hosted.caller("bob"))
        self.assertIsNotNone(plan)
        self.assertFalse(writable)
        model.steps = [[("start_training", {"usecase": CHURN})], "Not yours."]
        agent.turn("Train churn", user="bob")
        self.assertIn("approved by this user", model.tool_results()[0]["error"])
        self.assertIn("does not allow writes for this user", model.requests[-1]["instructions"])
        model.steps = [[("start_retraining", {"usecase": AIR})], "Not in the plan."]
        agent.turn("Retrain air-passengers too", user="alice", conversation_id="c3")
        self.assertIn(f"plan {code} is active until", model.requests[-1]["instructions"])
        self.assertIn(f"covers: {CHURN}.", model.requests[-1]["instructions"])
        self.assertIn("needs plan_run and the user's approval of the new code", model.requests[-1]["instructions"])
        self.assertIn("does not cover air-passengers", model.tool_results()[0]["error"])
        model.steps = ["Already approved."]
        agent.turn(f"approve {code}", user="alice")
        self.assertIn("already approved and active", model.requests[-1]["instructions"])
        self.now += timedelta(hours=13)
        self.assertFalse(agent.approvals.active(hosted.caller("alice"))[1])
        model.steps = ["Expired."]
        agent.turn(f"approve {code}", user="alice")
        self.assertIn("no pending plan", model.requests[-1]["instructions"])
        model.steps = [[("plan_run", {"usecases": [AIR], "fresh_data": False})], "Approve it."]
        agent.turn("Plan again", user="alice")
        stale = model.tool_results()[0]["result"]["approval_code"]
        self.now += timedelta(minutes=31)
        model.steps = ["Expired."]
        agent.turn(f"approve {stale}", user="alice")
        self.assertIn("expired", model.requests[-1]["instructions"])
        model.steps = [[("plan_run", {"usecases": [], "fresh_data": False})],
                       [("plan_run", {"usecases": ["titanic"], "fresh_data": False})], "Invalid."]
        agent.turn("Plan nothing", user="alice")
        self.assertTrue(all(not result["ok"] for result in model.tool_results()))

    def test_playground_turns_create_train_and_score_m49_without_duplicate_jobs(self):
        from azure_esml.domain_layer.rollout import AzureMLRollout

        calls = {"definitions": 0, "execute": 0}
        execute_training = AzureMLRollout.execute_training

        def definitions(rollout, run_id, *, component_version):
            calls["definitions"] += 1
            self.assertTrue((rollout.output / run_id / "training" / "code").is_dir())
            return write_json(rollout.output / run_id / "registered-definitions.json", {"version": component_version})

        def crash_once(rollout, run_id, **options):
            calls["execute"] += 1
            if calls["execute"] == 1:
                raise ConnectionError("sandbox lost before the training submission")
            return execute_training(rollout, run_id, **options)

        model = FakeModel()
        with patch.object(AzureMLRollout, "register_definitions", autospec=True, side_effect=definitions), \
                patch.object(AzureMLRollout, "execute_training", autospec=True, side_effect=crash_once):
            agent = self.session(self.root / "home-1", model)
            prefix = agent.state.prefix
            self.container.upload_blob(prefix + f"state/{PUBLICATIONS}", json.dumps({"versions": ["aif49-synth-v1"]}))
            model.steps = [[("start_training", {"usecase": CHURN})], "Approval is required."]
            agent.turn("Train churn", user="alice")
            self.assertIn("approved by this user", model.tool_results()[0]["error"])
            model.steps = [[("plan_run", {"usecases": [CHURN], "fresh_data": True})], "Please approve."]
            agent.turn("Create the churn use case from scratch", user="alice")
            planned = model.tool_results()[0]["result"]
            self.assertEqual(planned["usecases"][CHURN]["data_version"], "aif49-synth-v2")
            model.steps = [[("create_usecase_from_template", {"usecase": CHURN})],
                           [("start_training", {"usecase": CHURN})], "Training was interrupted."]
            agent.turn(f"approve {planned['approval_code']}", user="alice")
            created, failed = model.tool_results()
            self.assertEqual(created["result"]["data_version"], "aif49-synth-v2")
            self.assertIn("sandbox lost", failed["error"])
            self.assertTrue(self.container.has("registered-definitions.json"))

            # Fresh sandboxes start empty: the first regenerates the unsubmitted plan's code (keeping the
            # definitions receipt), the next ones resume the recorded jobs.
            shutil.rmtree(self.root / "home-1")
            agent = self.session(self.root / "home-2", model)
            model.steps = [[("start_training", {"usecase": CHURN})], [("get_usecase_status", {"usecase": CHURN})],
                           "Training is running."]
            agent.turn("Try the training again", user="alice")
            training, live = model.tool_results()
            self.assertEqual((training["result"]["state"], training["result"]["job"]),
                             ("running", f"training-job-{CHURN}"))
            self.assertEqual(live["result"]["azure_ml_job"], {"name": f"training-job-{CHURN}", "status": "Running"})
            self.assertIn("still running", live["result"]["next_action"])

            agent = self.session(self.root / "home-3", model)
            model.steps = [[("start_training", {"usecase": CHURN})], [("run_batch_inference", {"usecase": CHURN})],
                           "Scoring is running."]
            agent.turn("Is training done? Then score the customers.", user="alice")
            trained, scoring = model.tool_results()
            self.assertEqual(trained["result"]["state"], "registered")
            self.assertIn("call run_batch_inference", trained["result"]["next_action"])
            self.assertEqual((scoring["result"]["state"], scoring["result"]["job"]),
                             ("running", f"inference-job-{CHURN}"))

            agent = self.session(self.root / "home-4", model)
            model.steps = [[("run_batch_inference", {"usecase": CHURN})], [("get_usecase_status", {"usecase": CHURN})],
                           "Done."]
            agent.turn("Check the scoring", user="alice")
            scored, status = model.tool_results()
        self.assertEqual(scored["result"]["scored"], 50)
        self.assertEqual(scored["result"]["predicted_churn"], 25)
        self.assertEqual(status["result"]["training"]["state"], "registered")
        self.assertIsNone(status["result"]["pending_inference"])
        self.assertEqual(calls["definitions"], 1)
        self.assertEqual(self.submitted, [f"training-job-{CHURN}", f"inference-job-{CHURN}"])
        self.assertEqual(self.registered, [f"training-job-{CHURN}"])
        self.assertEqual(self.container.leases, {})
        synced = [name for name in self.container.blobs if name.startswith(prefix)]
        self.assertFalse([name for name in synced if "/code/" in name or "/lake-staging/" in name])
        self.assertTrue(any(name.endswith("/hosted-approvals/approved.json") for name in synced))
        approved = json.loads(self.container.blobs[next(name for name in synced if name.endswith("approved.json"))])
        self.assertNotIn("alice", json.dumps(approved))
        for request in model.requests:
            self.assertTrue({tool["name"] for tool in request["tools"]} >= {"plan_run", "get_approval_status"})
            self.assertIs(request["store"], False)


if __name__ == "__main__":
    unittest.main()
