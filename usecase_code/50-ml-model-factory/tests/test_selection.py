from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from ml_model_factory import azureml
from ml_model_factory.cli import main
from ml_model_factory.config import load_json, write_json
from ml_model_factory.selection import (
    EVIDENCE_SCHEMA, POLICY_SCHEMA, TASK_METRICS, build_evidence, canonical_hash, compare, validate_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def policy(metric="accuracy", direction="maximize", delta=0, mode="absolute", task="classification"):
    return {"schema": POLICY_SCHEMA, "on_no_champion": "candidate_if_qualified", "profiles": {
        task: {"metrics": [{"metric": metric, "direction": direction, "min_delta": delta, "delta_mode": mode}]},
    }}


def evidence(value=.9, model="sha256:candidate", metric="accuracy", task="classification"):
    return {
        "schema": EVIDENCE_SCHEMA, "model_id": "sha256:" + canonical_hash(model), "model_manifest_sha256": "c" * 64,
        "scope": {"aifactory": "spider-001", "project": "001", "environment": "dev"},
        "task_type": task, "use_case": "example",
        "evaluation": {"dataset_sha256": "a" * 64, "contract_sha256": "b" * 64,
                       "row_count": 100, "split": "test", "evaluator": "ml-model-factory/v1"},
        "quality_gate": {"passed": True}, "metrics": {metric: value},
    }


@pytest.mark.parametrize("metric,direction,new,old,delta,mode,wins", [
    ("accuracy", "maximize", .90, .88, .02, "absolute", True),
    ("accuracy", "maximize", .89, .88, .02, "absolute", False),
    ("accuracy", "maximize", .9, .9, 0, "absolute", False),
    ("rmse", "minimize", 98, 100, .02, "relative", True),
    ("rmse", "minimize", 99, 100, .02, "relative", False),
    ("rmse", "minimize", 99.98, 100, .02, "absolute", True),
    ("r2", "maximize", -.4, -.5, .2, "relative", True),
    ("log_loss", "minimize", .3, .5, .1, "absolute", True),
])
def test_signed_metric_directions_and_exact_boundaries(metric, direction, new, old, delta, mode, wins):
    task = "regression" if metric in ("rmse", "r2") else "classification"
    result = compare(policy(metric, direction, delta, mode, task), evidence(new, metric=metric, task=task),
                     evidence(old, model="sha256:champion", metric=metric, task=task))
    assert result["promotion_allowed"] is wins
    assert result["decision"] == ("candidate_wins" if wins else "champion_kept")
    assert result["policy_sha256"]


def test_tolerated_regression_is_not_a_weighted_sum():
    rules = policy()
    rules["profiles"]["classification"]["metrics"] += [
        {"metric": "f1_weighted", "direction": "maximize", "min_delta": -.001},
    ]
    candidate, champion = evidence(), evidence(.88, model="sha256:champion")
    candidate["metrics"]["f1_weighted"], champion["metrics"]["f1_weighted"] = .799, .8
    assert compare(rules, candidate, champion)["promotion_allowed"]
    candidate["metrics"]["f1_weighted"] = .798
    assert not compare(rules, candidate, champion)["promotion_allowed"]


def test_ties_and_all_regressions_require_explicit_overrides():
    rules = policy(delta=-.1)
    candidate, champion = evidence(.89), evidence(.9, model="sha256:champion")
    assert compare(rules, candidate, champion)["decision"] == "champion_kept"
    profile = rules["profiles"]["classification"]
    profile["require_any_improvement"] = False
    assert compare(rules, candidate, champion)["promotion_allowed"]
    candidate["metrics"]["accuracy"] = .9
    assert compare(rules, candidate, champion)["decision"] == "champion_kept"
    profile["on_tie"] = "candidate"
    assert compare(rules, candidate, champion)["promotion_allowed"]


@pytest.mark.parametrize("value", [None, True, "0.9", float("nan"), float("inf"), -float("inf"), 1.1, -.1])
def test_missing_and_invalid_selected_metric_is_blocked(value):
    result = compare(policy(), evidence(value), evidence(.8, model="sha256:champion"))
    assert result["decision"] == "blocked"
    assert result["promotion_allowed"] is False


@pytest.mark.parametrize("field,value", [
    ("dataset_sha256", "f" * 64), ("contract_sha256", "e" * 64), ("row_count", 99),
    ("split", "validation"), ("evaluator", "other"), ("row_count", False), ("dataset_sha256", None),
])
def test_benchmark_mismatch_blocks(field, value):
    champion = evidence(.8, model="sha256:champion")
    champion["evaluation"][field] = value
    assert compare(policy(), evidence(), champion)["decision"] == "blocked"


@pytest.mark.parametrize("field,value", [("aifactory", "other"), ("project", "002"), ("environment", "test")])
def test_scope_mismatch_blocks(field, value):
    champion = evidence(.8, model="sha256:champion")
    champion["scope"][field] = value
    assert compare(policy(), evidence(), champion)["decision"] == "blocked"


def test_first_model_is_explicit_and_still_requires_metrics_quality_and_scope():
    assert compare(policy(), evidence(), None)["promotion_allowed"]
    rules = policy()
    rules["on_no_champion"] = "block"
    assert compare(rules, evidence(), None)["decision"] == "blocked"
    for invalid in ({**evidence(), "quality_gate": {"passed": False}}, {**evidence(), "scope": {}},
                    {**evidence(), "model_id": "azureml:model@latest"}, {**evidence(), "quality_gate": None}):
        assert compare(policy(), invalid, None)["decision"] == "blocked"
    assert compare(policy("rmse", "minimize", .02, "relative", "regression"),
                   evidence(0, metric="rmse", task="regression"),
                   evidence(0, model="sha256:champion", metric="rmse", task="regression"))["decision"] == "blocked"


@pytest.mark.parametrize("rule", [
    {"metric": "Matthews_promote_weight2", "direction": "maximize"},
    {"metric": "accuracy", "direction": "minimize"},
    {"metric": "accuracy", "direction": "maximize", "min_delta": True},
    {"metric": "accuracy", "direction": "maximize", "min_delta": float("inf")},
    {"metric": "accuracy", "direction": "maximize", "weight": .5},
    {"metric": "accuracy", "direction": "maximize", "delta_mode": "percent"},
    {"metric": [], "direction": "maximize"},
])
def test_policy_typos_directions_and_invalid_values_rejected(rule):
    rules = policy()
    rules["profiles"]["classification"]["metrics"] = [rule]
    with pytest.raises(ValueError):
        validate_policy(rules)


def test_repository_policy_covers_all_tasks_and_does_not_mutate_inputs():
    rules = load_json(ROOT / "model-selection.json")
    original = deepcopy(rules)
    assert set(validate_policy(rules)["profiles"]) == set(TASK_METRICS)
    for task, profile in rules["profiles"].items():
        candidate, champion = evidence(task=task), evidence(task=task, model="sha256:champion")
        candidate["metrics"], champion["metrics"] = {}, {}
        for rule in profile["metrics"]:
            high, low = (.9, .8) if rule["direction"] == "maximize" else (.8, .9)
            candidate["metrics"][rule["metric"]] = high
            champion["metrics"][rule["metric"]] = low
        assert compare(rules, candidate, champion)["promotion_allowed"], task
    assert rules == original
    assert canonical_hash(rules) == canonical_hash(dict(reversed(list(rules.items()))))


def test_cli_persists_kept_and_blocked_decisions(tmp_path):
    for name, data in (("policy", policy()), ("candidate", evidence(.8)),
                       ("champion", evidence(.9, model="sha256:champion"))):
        write_json(tmp_path / f"{name}.json", data)
    argv = ["compare-models", "--policy", str(tmp_path / "policy.json"), "--candidate",
            str(tmp_path / "candidate.json"), "--champion", str(tmp_path / "champion.json"),
            "--output", str(tmp_path / "decision.json")]
    assert main(argv) == 0
    assert load_json(tmp_path / "decision.json")["decision"] == "champion_kept"
    write_json(tmp_path / "candidate.json", evidence(None))
    assert main(argv) == 2
    assert load_json(tmp_path / "decision.json")["decision"] == "blocked"
    with pytest.raises(SystemExit):
        main(["compare-models", "--policy", "p", "--candidate", "c", "--output", "o"])


def test_evidence_binds_data_model_and_contract_but_not_training_algorithm(tmp_path):
    import pandas as pd
    prepared, model = tmp_path / "prepared", tmp_path / "model"
    (prepared / "test").mkdir(parents=True)
    (prepared / "validation").mkdir()
    model.mkdir()
    pd.DataFrame({"x": [1], "y": [0]}).to_parquet(prepared / "test" / "data.parquet")
    pd.DataFrame({"x": [2], "y": [1]}).to_parquet(prepared / "validation" / "data.parquet")
    write_json(prepared / "manifest.json", {"split_rows": {"test": 1}})
    (model / "MLmodel").write_text("metadata: {}\n")
    (model / "weights.bin").write_bytes(b"first-model")
    scenario = {"name": "example", "task": "regression", "target": "y", "features": ["x"],
                "dataset": {"provider": "kaggle", "kind": "dataset"},
                "custom": {"algorithm": "ridge"}}
    first = build_evidence(scenario, prepared, model, {"rmse": 1.0}, {"passed": True})
    scenario["custom"]["algorithm"] = "random_forest"
    second = build_evidence(scenario, prepared, model, {"rmse": .9}, {"passed": True})
    assert first["evaluation"] == second["evaluation"]
    assert not first["scope"]
    (model / "weights.bin").write_bytes(b"second-model")
    changed_model = build_evidence(scenario, prepared, model, {"rmse": .9}, {"passed": True})
    assert changed_model["model_id"] != first["model_id"]
    assert changed_model["evaluation"] == first["evaluation"]
    pd.DataFrame({"x": [2], "y": [1]}).to_parquet(prepared / "test" / "data.parquet")
    changed_data = build_evidence(scenario, prepared, model, {"rmse": .9}, {"passed": True})
    assert changed_data["evaluation"]["dataset_sha256"] != first["evaluation"]["dataset_sha256"]
    scenario["task"] = "forecasting"
    scenario["forecast"] = {"time_column": "x", "frequency": "D", "horizon": 1}
    forecast = build_evidence(scenario, prepared, model, {"rmse": .9}, {"passed": True})
    pd.DataFrame({"x": [3], "y": [2]}).to_parquet(prepared / "validation" / "data.parquet")
    changed_history = build_evidence(scenario, prepared, model, {"rmse": .9}, {"passed": True})
    assert forecast["evaluation"]["dataset_sha256"] != changed_history["evaluation"]["dataset_sha256"]


def selection_service(tmp_path, mutate=None):
    from test_tags import RUNTIME, SCENARIO, service_fixture
    client = service_fixture(tmp_path)
    original_download = client.jobs.download.side_effect

    def download(**kwargs):
        original_download(**kwargs)
        root = Path(kwargs["download_path"]) / "report"
        candidate = evidence()
        candidate["use_case"] = SCENARIO["name"]
        write_json(root / "metrics.json", candidate["metrics"])
        lineage = load_json(root / "lineage.json")
        lineage["mlmodel_sha256"] = candidate["model_manifest_sha256"]
        write_json(root / "lineage.json", lineage)
        if mutate:
            mutate(candidate)
        write_json(root / "comparison.json", candidate)

    client.jobs.download.side_effect = download
    return client, RUNTIME, SCENARIO


def test_sdk_selection_registration_binds_real_report_and_tags(tmp_path):
    client, runtime, _ = selection_service(tmp_path)
    with patch("ml_model_factory.azureml._client", return_value=client):
        azureml.register("train-job", runtime, "tagged", selection_policy=policy(), no_champion=True,
                         decision_path=tmp_path / "decision.json")
    tags = client.models.create_or_update.call_args.args[0].tags
    assert tags["selection_status"] == "winner"
    assert tags["selection_policy_sha256"] == canonical_hash(policy())
    assert tags["lifecycle_status"] == "candidate"
    assert load_json(tmp_path / "decision.json")["source_run_id"] == "train-job"


@pytest.mark.parametrize("field,value", [
    ("model_manifest_sha256", "z" * 64), ("quality_gate", {"passed": True, "tampered": True}),
    ("metrics", {"accuracy": 1.0}), ("use_case", "other"),
])
def test_tampered_selection_report_never_registers(tmp_path, field, value):
    client, runtime, _ = selection_service(tmp_path, lambda item: item.update({field: value}))
    with patch("ml_model_factory.azureml._client", return_value=client), pytest.raises(ValueError):
        azureml.register("train-job", runtime, "tagged", selection_policy=policy(), no_champion=True)
    client.models.create_or_update.assert_not_called()


def test_sdk_loser_and_unacknowledged_bootstrap_never_register(tmp_path):
    client, runtime, scenario = selection_service(tmp_path)
    champion = evidence(.95, model="sha256:champion")
    champion["use_case"] = scenario["name"]
    with patch("ml_model_factory.azureml._client", return_value=client):
        with pytest.raises(azureml.ModelSelectionRejected) as exc:
            azureml.register("train-job", runtime, "tagged", selection_policy=policy(), champion_evaluation=champion)
        assert exc.value.decision["decision"] == "champion_kept"
        with pytest.raises(ValueError, match="exactly one"):
            azureml.register("train-job", runtime, "tagged", selection_policy=policy())
        with pytest.raises(ValueError, match="Runtime requests model selection"):
            azureml.register("train-job", {**runtime, "model_selection": {"policy": "rules.json"}}, "tagged")
    client.models.create_or_update.assert_not_called()


def test_cli_v2_selection_reuses_gated_definition(tmp_path):
    client, runtime, _ = selection_service(tmp_path)
    write_json(tmp_path / "runtime.json", runtime)
    write_json(tmp_path / "policy.json", policy())
    spec = importlib.util.spec_from_file_location("selection_azureml_cli", ROOT / "scripts" / "azureml_cli.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with patch.object(sys, "argv", ["azureml_cli.py", "--runtime", str(tmp_path / "runtime.json"),
                                   "--register-job", "train-job", "--model-name", "tagged",
                                   "--selection-policy", str(tmp_path / "policy.json"), "--no-champion",
                                   "--selection-output", str(tmp_path / "decision.json")]), \
            patch("ml_model_factory.azureml._client", return_value=client), \
            patch("ml_model_factory.project.azure_cli", return_value={"id": "azureml:tagged:1"}) as create:
        script.main()
    assert create.call_args.args[:3] == ("ml", "model", "create")
    assert load_json(tmp_path / "decision.json")["promotion_allowed"]
