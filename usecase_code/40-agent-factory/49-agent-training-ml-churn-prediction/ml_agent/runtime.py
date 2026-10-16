"""One guarded runtime behind the CLI commands and the agent's client-side tools."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import re
import sys
from types import SimpleNamespace

from . import esml, factory, lake
from .configuration import GUID, paths, read_json
from .plan import record_publication, require
from .usecases import AIR, CHURN, USECASES, expected_names, model_name


class ApprovalRequired(PermissionError):
    """A live operation was requested without the matching approved plan or flags."""


@contextlib.contextmanager
def keep_awake():
    """Keep the workstation from sleeping during bounded Azure waits (Windows only)."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    continuous, system_required = 0x80000000, 0x00000001
    kernel = ctypes.windll.kernel32
    kernel.SetThreadExecutionState(continuous | system_required)
    try:
        yield
    finally:
        kernel.SetThreadExecutionState(continuous)


def redact(value):
    """Remove tenant/subscription/object GUIDs and ARM prefixes before output or tool results."""
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.MachineLearningServices/"
                       r"workspaces/[^/]+/(models|data|components)/([^/]+)/versions/([^/\s]+)",
                       r"azureml:\2:\3", value, flags=re.I)
        return GUID.sub("<redacted-guid>", value)
    return value


def model_version(model_id: str) -> tuple[str, str]:
    match = re.search(r"(?:azureml:|/models/)([^/:]+)(?::|/versions/)(\d+)$", model_id)
    if not match:
        raise ValueError("Expected a registered Azure ML model id with an explicit version")
    return match.group(1), match.group(2)


PROJECT_WRITES = ("register_pipeline", "execute_pipeline", "wait_for_completion", "register_outputs",
                  "register_model")


class _Fenced:
    """Proxy that runs a barrier (durable receipt upload) before selected methods of a shared object."""

    def __init__(self, target, names, barrier):
        self._target, self._names, self._barrier = target, frozenset(names), barrier

    def __getattr__(self, name):
        value = getattr(self._target, name)
        if name not in self._names or not callable(value):
            return value

        def call(*args, **kwargs):
            self._barrier()
            return value(*args, **kwargs)

        return call


class MLRuntime:
    """Guarded operations. `credential` replaces the Azure CLI (hosted agent identity); `wait_seconds`
    bounds each Azure wait so a hosted turn returns `running` and a later call resumes from receipts.
    `barrier` (hosted) makes the receipts durable before every Azure ML or lake mutation and wait."""

    def __init__(self, config: dict, *, plan: dict | None = None, apply: bool = False, allow_paid: bool = False,
                 project_factory=None, lake_io=None, publisher=None, credential=None, wait_seconds: int | None = None,
                 hosted: bool = False, barrier=None):
        self.config = config
        self.location = paths(config)
        self.plan = plan
        self.apply = apply is True
        self.allow_paid = allow_paid is True
        self.hosted = hosted is True
        self._credential = credential
        self._barrier = barrier
        if wait_seconds is not None and (type(wait_seconds) is not int or not 5 <= wait_seconds <= 7200):
            raise ValueError("wait_seconds must be 5-7200")
        self._wait = ({"timeout_seconds": wait_seconds, "poll_seconds": min(10, wait_seconds)} if wait_seconds
                      else {"timeout_seconds": 7200, "poll_seconds": 30})
        self._project_factory = project_factory
        self._lake_io = lake_io if lake_io is None or barrier is None else _Fenced(lake_io, ("upload_folder",), barrier)
        if publisher is not None:
            self._publisher = publisher
        elif credential is not None:
            self._publisher = lambda config, staged: lake.publish(config, staged, credential_factory=self._identity)
        else:
            self._publisher = lake.publish
        if barrier is not None:
            self._publisher = _Fenced(SimpleNamespace(call=self._publisher), ("call",), barrier).call
        self.trace: list[dict] = []

    def _identity(self, _config: dict):
        return self._credential

    # ---- guards -------------------------------------------------------------------------
    def _entry(self, name: str, operation: str, *, paid: bool = True) -> dict:
        if self.plan is None:
            raise ApprovalRequired("No approved plan is loaded; run `plan`, get approval, then pass "
                                   "--approved-plan and --plan-sha256.")
        entry = require(self.plan, name, operation)
        if not self.apply:
            raise ApprovalRequired(f"{operation} writes to Azure; rerun with --apply after approval.")
        if paid and not self.allow_paid:
            raise ApprovalRequired(f"{operation} incurs charges; rerun with --allow-paid after approval.")
        return entry

    def _project(self, name: str):
        if self._project_factory is not None:
            project = self._project_factory(name)
        else:
            project = esml.build_project(self.config, self.location, name, cloud=True, credential=self._credential)
        if self._barrier is not None:
            # Each runtime builds its own project, so its write methods are fenced in place.
            fenced = _Fenced(project, PROJECT_WRITES, self._barrier)
            for method in PROJECT_WRITES:
                if callable(getattr(project, method, None)):
                    setattr(project, method, getattr(fenced, method))
        return project

    @property
    def lake_io(self):
        if self._lake_io is None:
            io = (lake.LakeIO(self.config, credential_factory=self._identity) if self._credential is not None
                  else lake.LakeIO(self.config))
            self._lake_io = io if self._barrier is None else _Fenced(io, ("upload_folder",), self._barrier)
        return self._lake_io

    def _record(self, operation: str, name: str, result: dict) -> dict:
        safe = redact(result)
        self.trace.append({"operation": operation, "usecase": name, "result": safe})
        return safe

    # ---- read-only tools ----------------------------------------------------------------
    def list_usecases(self) -> dict:
        return {"usecases": [{"name": name, "model": model_name(name), "task": item["task"],
                              "operation": item["operation"], "synthetic_data": item["synthetic"]}
                             for name, item in USECASES.items()]}

    def status(self, name: str) -> dict:
        if name not in USECASES:
            raise ValueError(f"Unknown use case {name!r}")
        result = {"usecase": name, "model": model_name(name), "names": expected_names(name),
                  "approved_plan": self.plan is not None}
        if self.plan is not None:
            entry = self.plan["usecases"][name]
            directory = self.location.esml(name) / entry["train_run_id"]
            result.update(train_run_id=entry["train_run_id"], data_version=entry["data_version"],
                          training=esml.training_state(directory),
                          inference=esml.latest_inference(self.location.esml(name), entry),
                          pending_inference=esml.pending_inference(self.location.esml(name), entry))
        return self._record("status", name, result)

    def predictions_summary(self, name: str) -> dict:
        if self.plan is None:
            raise ApprovalRequired("No approved plan is loaded.")
        entry = self.plan["usecases"][name]
        latest = esml.latest_inference(self.location.esml(name), entry)
        summary = (lake.load_record(self.location, f"{name}-{latest['inference_run_id']}-summary.json")
                   if latest and latest.get("inference_run_id") else None)
        if summary is None:
            raise ValueError(f"No completed inference for {name} in the approved plan")
        return self._record("predictions_summary", name, summary)

    # ---- live tools ---------------------------------------------------------------------
    def _prepare(self, plan: dict) -> tuple[dict, dict]:
        if self.hosted:
            # The hosted package bundles the reviewed M49 scenario; notebooks belong to the orange checkout.
            result = {"scenario": {"status": "bundled"}, "rollout": factory.write_rollout(self.config, self.location, plan),
                      "notebook": {"notebook": None, "status": "not-rendered-in-hosted-agent"},
                      "data": factory.synthesize(self.location)}
        else:
            result = {
                "scenario": factory.write_scenario(self.location),
                "rollout": factory.write_rollout(self.config, self.location, plan),
                "notebook": factory.render_notebook(self.location),
                "data": factory.synthesize(self.location),
            }
        staged = lake.stage(self.config, self.location, plan["usecases"][CHURN]["data_version"])
        result["staged"] = {"root": staged["root"], "publications": staged["publications"],
                            "files": staged["plan"]["files"], "bytes": staged["plan"]["bytes"]}
        return result, staged

    def prepare_local(self, plan: dict) -> dict:
        """Write the M49 project copy and stage synthetic lake data locally; no Azure writes."""
        return self._prepare(plan)[0]

    def create_usecase(self, name: str) -> dict:
        if name != CHURN:
            raise ValueError("Only the M49 churn use case is created from the template; air-passengers exists.")
        entry = self._entry(name, "create-usecase", paid=False)
        local, staged = self._prepare(self.plan)
        receipt = self._publisher(self.config, staged)
        record_publication(self.location.state, entry["data_version"])
        result = {**local, "publication": receipt, "data_version": entry["data_version"],
                  "lake": entry["lake"], "model": entry["model_name"]}
        lake.record(self.location, f"{name}-create-{entry['data_version']}.json", redact(result))
        return self._record("create_usecase", name, {
            "model": entry["model_name"], "data_version": entry["data_version"], "lake": entry["lake"],
            "scenario": local["scenario"]["status"], "notebook": local["notebook"]["notebook"],
            "rows": local["data"].get("rows"), "publication": {key: receipt.get(key) for key in ("written", "reused")}})

    def _running(self, operation: str, name: str, run_dir, error: TimeoutError, **extra) -> dict:
        """A bounded hosted wait ended before Azure ML finished; receipts make the next call resume."""
        if not self.hosted:
            raise error
        state = esml.training_state(run_dir) or {}
        return self._record(operation, name, {"state": "running", "job": extra.pop("job", None) or state.get("job"),
                                              "message": "Azure ML is still running; check again in a few minutes.",
                                              **extra})

    def train(self, name: str) -> dict:
        if name != CHURN:
            raise ValueError("start_training creates the first M49 model; use start_retraining for air-passengers.")
        entry = self._entry(name, "train")
        project = self._project(name)
        rollout = esml.build_rollout(project, self.location, name)
        try:
            with keep_awake():
                result = esml.train(rollout, entry, data_date=self.plan["data_date_utc"],
                                    policy=read_json(self.location.selection_policy), barrier=self._barrier,
                                    **self._wait)
        except TimeoutError as error:
            return self._running("train", name, rollout.output / entry["train_run_id"], error,
                                 model=entry["model_name"], run_id=entry["train_run_id"])
        return self._record("train", name, {**result, "model": entry["model_name"], "run_id": entry["train_run_id"]})

    def retrain(self, name: str) -> dict:
        if name != AIR:
            raise ValueError("start_retraining only retrains the existing air-passengers model.")
        entry = self._entry(name, "retrain")
        project = self._project(name)
        rollout = esml.build_rollout(project, self.location, name)
        receipts = read_json(self.config["usecases"][AIR]["champion_receipts"] + "/training-completion.json")
        if model_version(receipts["model_id"]) != model_version(entry["champion_model_id"]):
            raise ValueError("Champion receipts do not belong to the configured champion model")
        evidence = esml.champion_evidence(project, receipts["job"],
                                          self.location.work(name) / "champion-report" / receipts["job"])
        try:
            with keep_awake():
                result = esml.train(rollout, entry, data_date=self.plan["data_date_utc"],
                                    policy=read_json(self.location.selection_policy), champion_evaluation=evidence,
                                    barrier=self._barrier, **self._wait)
        except TimeoutError as error:
            return self._running("retrain", name, rollout.output / entry["train_run_id"], error,
                                 champion=entry["champion_model_id"], run_id=entry["train_run_id"])
        return self._record("retrain", name, {**result, "champion": entry["champion_model_id"],
                                              "run_id": entry["train_run_id"]})

    def _requests(self, name: str, entry: dict):
        """Deterministic unlabeled requests; reused unchanged when an inference attempt is retried."""
        import pandas as pd

        work = self.location.work(name) / entry["inference_run_id"]
        existing = work / "requests" / "requests.parquet"
        if name == CHURN:
            description = f"ml_model_factory.synthetic telco-churn requests (seed {entry['inference_seed']}); no labels"
            if not existing.is_file():
                factory.requests(self.location, work / "requests", rows=entry["inference_rows"],
                                 seed=entry["inference_seed"])
            return pd.read_parquet(existing), description
        from ml_model_factory.config import validate_scenario
        from ml_model_factory.data import prepare
        from ml_model_factory.inference import sample_requests

        description = "held-out test months from the approved air-passengers lake version; labels kept separate"
        if not existing.is_file():
            scenario = validate_scenario(read_json(self.location.scenarios / f"{AIR}.json"))
            source = self.lake_io.download_one(entry["input_path"], work / "source", suffix=".csv")
            if not (work / "prepared").exists():
                prepare(scenario, source, work / "prepared")
            sample_requests(scenario, work / "prepared", work / "requests", rows=entry["inference_rows"],
                            split="test")
        return pd.read_parquet(existing), description

    def infer(self, name: str) -> dict:
        entry = self._entry(name, "infer")
        state = esml.training_state(self.location.esml(name) / entry["train_run_id"])
        if state is None or state["state"] not in esml.TERMINAL:
            raise ValueError(f"Train {name} in the approved plan before scoring it.")
        model_id = None
        if state["state"] == "not_promoted":
            if name != AIR or state.get("decision") != "champion_kept":
                raise ValueError("The candidate was not promoted and no retained champion applies.")
            model_id = entry["champion_model_id"]
        project = self._project(name)
        rollout = esml.build_rollout(project, self.location, name)
        frame, source = self._requests(name, entry)
        lineage = {"scope": {"aifactory": self.config["aifactory"], "project": f"{self.config['project_number']:03d}",
                             "environment": self.config["environment"]},
                   "model_id": model_id or state["model_id"], "source": source}
        try:
            with keep_awake():
                result = esml.infer(project, rollout, entry, data_date=self.plan["data_date_utc"], frame=frame,
                                    lake_io=self.lake_io, lineage=lineage, model_id=model_id, **self._wait)
        except TimeoutError as error:
            pending = esml.pending_inference(rollout.output, entry) or {}
            return self._running("infer", name, rollout.output / entry["train_run_id"], error,
                                 job=pending.get("job"), inference_run_id=pending.get("inference_run_id"))
        predictions = result.pop("frame")
        summary = {**result, "usecase": name}
        if name == CHURN:
            churners = predictions[predictions["prediction"].astype(str) == "Yes"]
            summary.update(predicted_churn=int(len(churners)), scored=int(len(predictions)),
                           churn_request_ids=churners["request_id"].astype(str).head(20).tolist())
        else:
            joined = frame.merge(predictions, on="request_id")
            summary["forecasts"] = [{"month": str(row["Month"])[:10], "passengers": round(float(row["prediction"]), 1)}
                                    for _, row in joined.sort_values("Month").iterrows()]
        lake.record(self.location, f"{name}-{result['inference_run_id']}-summary.json", redact(summary))
        return self._record("infer", name, deepcopy(summary))
