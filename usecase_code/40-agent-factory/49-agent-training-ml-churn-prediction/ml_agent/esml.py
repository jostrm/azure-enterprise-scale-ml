"""Training, retraining and batch inference through azure_esml AzureMLRollout receipts.

AzureMLRollout records every cloud write and refuses repeats after an uncertain outcome.
These helpers only sequence its public operations and never resubmit a recorded job.
"""
from __future__ import annotations

from pathlib import Path
import shutil

from .configuration import read_json, write_json

TERMINAL = ("registered", "not_promoted")
FAILED_JOB = ("Failed", "Canceled", "CancelRequested", "NotResponding")
MAX_INFERENCE_ATTEMPTS = 5


def build_project(config: dict, location, name: str, *, cloud: bool = False, backend=None):
    from azure_esml import ESMLProject
    from azure_esml.domain_layer.rollout import project_from_rollout_config

    built = project_from_rollout_config(read_json(location.rollout), location.scenarios, scenario=name,
                                        mode="custom", base_path=location.rollout.parent)
    target = built.target
    if (target.tenant_id.lower() != config["tenant_id"].lower()
            or target.subscription_id.lower() != config["subscription_id"].lower()):
        raise ValueError("The ESML rollout targets a different tenant or subscription than this agent")
    if backend is not None:
        return ESMLProject(built.settings, backend=backend)
    if cloud:
        from azure_esml.base_layer import AzureMLSDKBackend

        return ESMLProject(built.settings, backend=AzureMLSDKBackend.from_cli(target, subscription_bound=True))
    return built


def build_rollout(project, location, name: str):
    from azure_esml.domain_layer.rollout import AzureMLRollout

    return AzureMLRollout(project, location.esml(name))


def training_state(directory: Path) -> dict | None:
    """Summarize the receipts of one training run without contacting Azure."""
    directory = Path(directory)
    completion = directory / "training-completion.json"
    if completion.is_file():
        value = read_json(completion)
        return {"state": "registered", "model_id": value["model_id"], "job": value["job"],
                "experiment_name": value.get("experiment_name")}
    decision = directory / "selection-decision.json"
    if decision.is_file() and (directory / "model-registration-intent.json").is_file():
        value = read_json(decision)
        job = read_json(directory / "completed-job.json") if (directory / "completed-job.json").is_file() else {}
        return {"state": "not_promoted", "decision": value.get("decision"), "reasons": value.get("reasons", []),
                "comparisons": value.get("comparisons", []), "job": job.get("name")}
    if (directory / "submitted-job.json").is_file():
        return {"state": "submitted", "job": read_json(directory / "submitted-job.json").get("name")}
    if (directory / "request.json").is_file():
        return {"state": "prepared"}
    return None


def train(rollout, entry: dict, *, data_date: str, policy: dict, champion_evaluation: dict | None = None,
          timeout_seconds: int = 7200, poll_seconds: int = 30) -> dict:
    """Prepare, register definitions and train once; rerunning resumes from receipts."""
    from ml_model_factory.azureml import ModelSelectionRejected

    run = entry["train_run_id"]
    directory = rollout.output / run
    current = training_state(directory)
    if current and current["state"] in TERMINAL:
        return current
    if not (directory / "request.json").is_file():
        rollout.prepare(model_number=entry["model_number"], mode=entry["mode"], data_date_utc=data_date,
                        run_id=run, data_version=entry["data_version"])
    if not (directory / "registered-definitions.json").is_file():
        rollout.register_definitions(run, component_version=entry["component_version"])
    try:
        rollout.execute_training(run, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds,
                                 selection_policy=policy, no_champion=champion_evaluation is None,
                                 champion_evaluation=champion_evaluation)
    except ModelSelectionRejected:
        pass  # The selection decision receipt records why the champion was kept.
    result = training_state(directory)
    if result is None or result["state"] not in TERMINAL:
        raise RuntimeError("Training finished without a registration or selection receipt")
    return result


def champion_evidence(project, job_name: str, destination: Path) -> dict:
    """Download the champion training job's held-out comparison evidence (read-only)."""
    destination = Path(destination)
    if not list(destination.rglob("comparison.json")):
        project.download_output(job_name, "report", destination)
    reports = list(destination.rglob("comparison.json"))
    if len(reports) != 1:
        raise ValueError("The champion report must contain exactly one comparison.json")
    return read_json(reports[0])


def inference_attempts(entry: dict):
    """Planned scoring folder/run first, then bounded retries with their own receipts and lake paths."""
    yield entry["train_run_id"], entry["inference_run_id"]
    for number in range(2, MAX_INFERENCE_ATTEMPTS + 1):
        yield f"{entry['train_run_id']}-a{number}", f"{entry['inference_run_id']}-a{number}"


def _start_attempt(base: Path, directory: Path, previous: dict) -> None:
    """Copy only the training receipts that GOLD_INFERENCE planning reads; record the failed attempt."""
    directory.mkdir(parents=True)
    copied = []
    for name in ("request.json", "training-completion.json", "selection-decision.json",
                 "model-registration-intent.json"):
        if (base / name).is_file():
            shutil.copy2(base / name, directory / name)
            copied.append(name)
    write_json(directory / "aif49-attempt.json", {"copied_from": base.name, "files": copied, "previous": previous})


def select_inference_attempt(project, rollout, entry: dict) -> tuple[Path, str]:
    """Return the first new, pending or successful attempt; a failed job moves to a fresh attempt."""
    base = rollout.output / entry["train_run_id"]
    previous = None
    for folder, inference_id in inference_attempts(entry):
        directory = rollout.output / folder
        if directory != base and not directory.exists():
            _start_attempt(base, directory, previous)
            return directory, inference_id
        receipt = directory / "inference-pipeline-job.json"
        if not receipt.is_file():
            return directory, inference_id
        job = read_json(receipt)["name"]
        status = project._backend().get_job(job).get("status")
        if status not in FAILED_JOB:
            return directory, inference_id
        previous = {"folder": folder, "inference_run_id": inference_id, "job": job, "status": status}
    raise ValueError(f"Inference failed in {MAX_INFERENCE_ATTEMPTS} attempts; investigate before retrying")


def infer(project, rollout, entry: dict, *, data_date: str, frame, lake_io, lineage: dict,
          model_id: str | None = None, timeout_seconds: int = 7200, poll_seconds: int = 30) -> dict:
    """Plan GOLD_INFERENCE, upload unlabeled gold rows once, submit once, then read lake predictions."""
    from azure_esml.base_layer.tables import write_table

    directory, inference_id = select_inference_attempt(project, rollout, entry)
    run = directory.name
    submitted = (directory / "inference-pipeline-intent.json").is_file()
    request_path = directory / "inference-request.json"
    if submitted and request_path.is_file():
        planned = read_json(request_path)
    else:
        options = {"model_id": model_id} if model_id else {}
        planned = rollout.prepare_inference(run, inference_date_utc=data_date,
                                            inference_run_id=inference_id, **options)
    if f"/runs/{inference_id}/" not in planned["input"]:
        raise ValueError("The prepared inference plan belongs to a different inference run")
    root = entry["lake"]["use_case_root"]
    input_prefix = lake_io.prefix(planned["input"], allowed_root=root)
    output_prefix = lake_io.prefix(planned["output"], allowed_root=root)
    upload_receipt = directory / "aif49-gold-input.json"
    if not upload_receipt.is_file():
        if "request_id" not in frame or frame["request_id"].duplicated().any() or frame.empty:
            raise ValueError("Gold inference rows need a unique request_id")
        gold = directory / "aif49-gold-input"
        if gold.exists() and any(gold.iterdir()):
            raise ValueError("A previous gold input is incomplete; reconcile the lake path before retrying")
        metadata = write_table(frame, gold, format="parquet")
        write_json(gold / "lineage.json", {**lineage, "medallion_stage": "gold", "purpose": "inference",
                                           "labels_included": False, "output": metadata})
        write_json(upload_receipt, {"status": "upload_requested", "path": planned["input"], "rows": len(frame)})
        files = lake_io.upload_folder(gold, input_prefix)
        write_json(upload_receipt, {"status": "uploaded", "path": planned["input"], "rows": len(frame), "files": files})
    elif read_json(upload_receipt).get("status") != "uploaded":
        raise ValueError("An earlier gold upload has an uncertain outcome; reconcile the lake path first")
    rows = read_json(upload_receipt)["rows"]
    job = rollout.submit_inference(run)
    finished = project.wait_for_completion(job["name"], timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
    predictions, blob = lake_io.read_parquet(output_prefix)
    if len(predictions) != rows or "prediction" not in predictions or predictions["prediction"].isna().any():
        raise ValueError("Inference did not produce one usable prediction per request")
    result = {"job": finished["name"], "status": finished["status"], "model_id": planned["model_id"],
              "model_source": planned.get("model_source", "trained"), "inference_run_id": inference_id,
              "input": planned["input"], "output": planned["output"], "predictions_blob": blob,
              "rows": len(predictions)}
    write_json(directory / "aif49-inference-result.json", result)
    return {**result, "frame": predictions}


def latest_inference(rollout_output: Path, entry: dict) -> dict | None:
    """The most recent successful inference result across the planned attempts, without Azure calls."""
    found = None
    for folder, _ in inference_attempts(entry):
        path = Path(rollout_output) / folder / "aif49-inference-result.json"
        if path.is_file():
            found = read_json(path)
    return found
