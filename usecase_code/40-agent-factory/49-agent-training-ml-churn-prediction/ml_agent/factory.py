"""The M49 project copy inside the consumer ML factory: scenario, local binding, notebook and data."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path

from .configuration import read_json, write_json
from .usecases import AIR, CHURN, CHURN_LEAF, DATA_FILE, churn_scenario


def scenario_path(location) -> Path:
    return location.scenarios / f"{CHURN}.json"


def notebook_path(location) -> Path:
    return location.ml_root / CHURN_LEAF / f"{CHURN}-custom-pipeline.ipynb"


def load_scenario(location) -> dict:
    from ml_model_factory.config import validate_scenario

    return validate_scenario(read_json(scenario_path(location)))


def write_scenario(location) -> dict:
    """Create the synthetic M49 scenario from the factory churn template; never overwrite edits."""
    from ml_model_factory.config import validate_scenario

    scenario = validate_scenario(churn_scenario(read_json(location.scenarios / "churn.json")))
    path = scenario_path(location)
    if path.exists():
        if read_json(path) != scenario:
            raise ValueError(f"{path.name} differs from the generated M49 scenario; review the consumer edit.")
        return {"scenario": str(path), "status": "unchanged"}
    write_json(path, scenario)
    return {"scenario": str(path), "status": "created"}


def write_rollout(config: dict, location, plan: dict) -> dict:
    """Write the local ESML rollout binding: reviewed M05 binding plus the planned M49 binding."""
    reviewed = read_json(config["reviewed_rollout"])
    churn, air = plan["usecases"][CHURN], plan["usecases"][AIR]
    document = deepcopy(reviewed)
    document["data_date_utc"] = plan["data_date_utc"]
    document["model_numbers"] = {**reviewed.get("model_numbers", {}), CHURN: churn["model_number"]}
    document["scenarios"] = {
        **reviewed["scenarios"],
        CHURN: {"mode": "custom", "compute": churn["compute"], "data_version": churn["data_version"],
                "run_id": churn["train_run_id"], "input_path": churn["lake"]["project_in"]},
        AIR: {**reviewed["scenarios"][AIR], "run_id": air["train_run_id"]},
    }
    write_json(location.rollout, document)
    return {"rollout": str(location.rollout), "scenarios": sorted(document["scenarios"]),
            "model_numbers": document["model_numbers"]}


def render_notebook(location) -> dict:
    """Generate the M49 notebook and README entry with the factory generator, never by hand."""
    from ml_model_factory.examples import render_all

    expected = {f"{CHURN_LEAF}/readme.md", f"{CHURN_LEAF}/{CHURN}-custom-pipeline.ipynb"}
    check = render_all(location.ml_root)
    unexpected = sorted(set(check["stale"]) - expected) + check["unexpected_notebooks"]
    if unexpected:
        raise ValueError("Other generated factory files are stale or edited; run `python -m ml_model_factory "
                         "usecase-examples` and review them first: " + ", ".join(unexpected[:10]))
    if check["stale"]:
        render_all(location.ml_root, write=True)
    return {"notebook": str(notebook_path(location)), "written": check["stale"]}


def synthesize(location) -> dict:
    """Regenerate the deterministic synthetic training file (and provenance) from scratch."""
    from ml_model_factory.synthetic import generate

    return generate(load_scenario(location), location.raw(CHURN))


def requests(location, output: Path, *, rows: int, seed: int) -> dict:
    """Synthetic, unlabeled scoring requests with request_id; never derived from training labels."""
    from ml_model_factory.synthetic import generate_requests

    return generate_requests(load_scenario(location), output, rows=rows, seed=seed)


def offline_demo(location, work: Path, *, rows: int = 50, seed: int = 4901) -> dict:
    """Reproduce M49 from scratch locally: synthesize, prepare, train, evaluate and score. No Azure."""
    from ml_model_factory.data import prepare
    from ml_model_factory.evaluation import evaluate
    from ml_model_factory.inference import score_file
    from ml_model_factory.training import train
    import pandas as pd

    work = Path(work)
    if work.exists() and any(work.iterdir()):
        raise ValueError(f"Offline work folder must be new or empty: {work}")
    # Keep MLflow tracking files with the generated offline artifacts, never in the template.
    os.environ.setdefault("MLFLOW_TRACKING_URI", (work.resolve() / "mlruns").as_uri())
    scenario = load_scenario(location)
    data = synthesize(location)
    prepared, model = work / "prepared", work / "model"
    prepare(scenario, location.raw(CHURN) / DATA_FILE, prepared)
    train(scenario, prepared, model)
    evaluate(scenario, prepared, model, work / "evaluation")
    evaluation = {"metrics": read_json(work / "evaluation" / "metrics.json"),
                  "quality_gate": read_json(work / "evaluation" / "quality-gate.json")}
    request = requests(location, work / "requests", rows=rows, seed=seed)
    score_file(scenario, model, Path(request["requests"]), work / "scored")
    scored = pd.read_parquet(next((work / "scored").rglob("*.parquet")))
    positive = scored[scored["prediction"].astype(str) == "Yes"]
    return {
        "mode": "offline", "azure_written": False, "data": data, "evaluation": evaluation,
        "requests": request["rows"], "predicted_churn": int(len(positive)),
        "predicted_churn_request_ids": positive["request_id"].astype(str).head(10).tolist(),
    }
