"""Explicit, auditable candidate/champion rules; no weighted mix of metric units."""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re

from .config import TASKS
from .data import read_frame, sha256
from .tags import scope_tags


POLICY_SCHEMA = "aifactory.model-selection-policy/v1"
EVIDENCE_SCHEMA = "aifactory.model-evaluation/v1"
DECISION_SCHEMA = "aifactory.model-selection/v1"
MAXIMIZE = {"accuracy", "auc_weighted", "f1_weighted", "precision_weighted", "recall_weighted",
            "matthews_correlation", "r2", "spearman_correlation", "map", "map_50", "map_75", "mar_100"}
MINIMIZE = {"log_loss", "rmse", "mae", "mape", "hamming_loss"}
TASK_METRICS = {
    "classification": {"accuracy", "auc_weighted", "f1_weighted", "precision_weighted", "recall_weighted",
                       "matthews_correlation", "log_loss"},
    "regression": {"rmse", "mae", "mape", "r2", "spearman_correlation"},
    "forecasting": {"rmse", "mae", "mape", "r2", "spearman_correlation"},
    "image_classification": {"accuracy", "f1_weighted", "auc_weighted", "log_loss"},
    "image_classification_multilabel": {"accuracy", "f1_weighted", "hamming_loss"},
    "image_object_detection": {"map", "map_50", "map_75", "mar_100"},
    "image_instance_segmentation": {"map", "map_50", "map_75", "mar_100"},
}


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_policy(policy: dict) -> dict:
    if not isinstance(policy, dict) or policy.get("schema") != POLICY_SCHEMA:
        raise ValueError(f"Model selection policy must use schema {POLICY_SCHEMA}")
    unknown = set(policy) - {"schema", "description", "on_no_champion", "profiles"}
    if unknown:
        raise ValueError(f"Unknown model selection fields: {sorted(unknown)}")
    if policy.get("on_no_champion", "block") not in ("block", "candidate_if_qualified"):
        raise ValueError("on_no_champion must be block or candidate_if_qualified")
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict) or not profiles or set(profiles) - TASKS:
        raise ValueError("profiles must select explicit supported task types")
    for task, profile in profiles.items():
        if not isinstance(profile, dict) or set(profile) - {"metrics", "require_any_improvement", "on_tie"}:
            raise ValueError(f"Unknown or malformed {task} profile fields")
        if type(profile.get("require_any_improvement", True)) is not bool:
            raise ValueError("require_any_improvement must be a JSON boolean")
        if profile.get("on_tie", "keep_champion") not in ("keep_champion", "candidate"):
            raise ValueError("on_tie must be keep_champion or candidate")
        rules = profile.get("metrics")
        if not isinstance(rules, list) or not rules:
            raise ValueError(f"{task} needs at least one selected metric rule")
        seen = set()
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) - {"metric", "direction", "min_delta", "delta_mode"}:
                raise ValueError("Metric rules contain unsupported fields")
            metric = rule.get("metric")
            if not isinstance(metric, str) or metric not in TASK_METRICS[task] or metric in seen:
                raise ValueError(f"Unknown, duplicate or wrong-task metric {metric!r}; check spelling and task")
            seen.add(metric)
            expected = "maximize" if metric in MAXIMIZE else "minimize"
            if rule.get("direction") != expected:
                raise ValueError(f"{metric} direction must be {expected}")
            delta = rule.get("min_delta", 0.0)
            if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(delta):
                raise ValueError("min_delta must be a finite signed number")
            if rule.get("delta_mode", "absolute") not in ("absolute", "relative"):
                raise ValueError("delta_mode must be absolute or relative")
    return deepcopy(policy)


def build_evidence(scenario: dict, prepared: Path, model: Path, metrics: dict, quality_gate: dict) -> dict:
    """Capture comparable held-out data identity; publication/promotion stays separate."""
    from .lake_flow import file_inventory, preparation_contract
    import yaml

    prepared, model = Path(prepared), Path(model)
    model_definition = yaml.safe_load((model / "MLmodel").read_text(encoding="utf-8"))
    tags = model_definition.get("metadata", {}).get("model_factory_tags", {})
    files = file_inventory(prepared / "test")
    if not files:
        raise ValueError("Evaluation comparison requires a nonempty held-out test artifact")
    # Forecast evaluation can use validation observations as known history.
    if scenario["task"] == "forecasting":
        files = {"test/" + key: value for key, value in files.items()} | {
            "validation/" + key: value for key, value in file_inventory(prepared / "validation").items()
        }
    if scenario["task"].startswith("image_"):
        rows = sum(bool(line.strip()) for line in (prepared / "test" / "annotations.jsonl").read_text(encoding="utf-8").splitlines())
    else:
        rows = len(read_frame(prepared / "test"))
    model_files = {key: value for key, value in file_inventory(model).items()
                   if "__pycache__" not in Path(key).parts and not key.endswith(".pyc")}
    return {
        "schema": EVIDENCE_SCHEMA, "model_id": "sha256:" + canonical_hash(model_files),
        "model_manifest_sha256": sha256(model / "MLmodel"),
        "scope": scope_tags(tags), "use_case": scenario["name"], "task_type": scenario["task"],
        "evaluation": {
            "dataset_sha256": canonical_hash(files), "contract_sha256": canonical_hash(preparation_contract(scenario)),
            "row_count": rows, "split": "test", "evaluator": "ml-model-factory/v1",
        },
        "quality_gate": deepcopy(quality_gate), "metrics": deepcopy(metrics),
        "limitations": [
            "Compare results from the same held-out data and evaluator; metrics alone do not establish comparability.",
            "Selection is not deployment approval; repeated model selection can overfit a holdout.",
        ],
    }


def _evidence_errors(item: dict, label: str, task: str, selected_metrics: list[str]) -> list[str]:
    errors = []
    if not isinstance(item, dict) or item.get("schema") != EVIDENCE_SCHEMA:
        return [f"{label}: expected {EVIDENCE_SCHEMA} evidence, not an unscoped metrics dictionary"]
    if item.get("task_type") != task:
        errors.append(f"{label}: task type differs from the comparison profile")
    try:
        scope_tags(item.get("scope"), require=True)
    except ValueError:
        errors.append(f"{label}: explicit factory/project/environment identity is missing or invalid")
    if not isinstance(item.get("use_case"), str) or not item["use_case"]:
        errors.append(f"{label}: use-case identity is missing")
    model = item.get("model_id")
    if (not isinstance(model, str) or not model.strip() or any(char in model for char in ("\n", "\r", "?", "@"))
            or re.search(r"(?i)(@latest|[:/](latest|active|champion|production))$", model)):
        errors.append(f"{label}: an immutable model identity is required")
    evaluation = item.get("evaluation", {})
    if not isinstance(evaluation, dict):
        return errors + [f"{label}: missing evaluation provenance"]
    for key in ("dataset_sha256", "contract_sha256"):
        if not isinstance(evaluation.get(key), str) or not re.fullmatch("[a-f0-9]{64}", evaluation[key]):
            errors.append(f"{label}: {key} is missing or invalid")
    if type(evaluation.get("row_count")) is not int or evaluation["row_count"] < 1:
        errors.append(f"{label}: positive evaluation row_count required")
    if evaluation.get("split") != "test" or evaluation.get("evaluator") != "ml-model-factory/v1":
        errors.append(f"{label}: expected held-out test results from the supported evaluator")
    measured = item.get("metrics")
    if not isinstance(measured, dict):
        return errors + [f"{label}: metrics object missing"]
    for metric in selected_metrics:
        value = measured.get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{label}: selected metric {metric} is missing, undefined or non-finite")
        elif ((metric in {"accuracy", "auc_weighted", "f1_weighted", "precision_weighted", "recall_weighted",
                          "map", "map_50", "map_75", "mar_100", "hamming_loss"} and not 0 <= value <= 1)
              or (metric in {"matthews_correlation", "spearman_correlation"} and not -1 <= value <= 1)
              or (metric in {"rmse", "mae", "mape", "log_loss"} and value < 0)
              or (metric == "r2" and value > 1)):
            errors.append(f"{label}: selected metric {metric} is outside its defined range")
    return errors


def compare(policy: dict, candidate: dict, champion: dict | None) -> dict:
    policy = validate_policy(policy)
    task = candidate.get("task_type") if isinstance(candidate, dict) else None
    if task not in policy["profiles"]:
        raise ValueError(f"No selection profile is configured for task {task!r}")
    profile = policy["profiles"][task]
    rules = profile["metrics"]
    result = {
        "schema": DECISION_SCHEMA, "policy_sha256": canonical_hash(policy), "task_type": task,
        "decision": "blocked", "promotion_allowed": False, "winner_id": None,
        "candidate_id": candidate.get("model_id"), "champion_id": champion.get("model_id") if isinstance(champion, dict) else None,
        "candidate_evidence_sha256": None, "champion_evidence_sha256": None,
        "comparisons": [], "reasons": [],
    }
    metrics = [rule["metric"] for rule in rules]
    errors = _evidence_errors(candidate, "candidate", task, metrics)
    gate = candidate.get("quality_gate")
    if not isinstance(gate, dict) or gate.get("passed") is not True:
        errors.append("Candidate did not pass its independent absolute-quality gate")
    if champion is not None:
        errors += _evidence_errors(champion, "champion", task, metrics)
        if not errors:
            for key in ("scope", "use_case", "task_type", "evaluation"):
                if candidate[key] != champion[key]:
                    errors.append(f"Candidate and champion {key} differ; re-evaluate on the same scoped benchmark")
    if errors:
        result["reasons"] = errors
        return result
    result["candidate_evidence_sha256"] = canonical_hash(candidate)
    result["champion_evidence_sha256"] = canonical_hash(champion) if champion is not None else None
    if champion is None:
        if policy.get("on_no_champion", "block") == "candidate_if_qualified":
            result.update(decision="candidate_wins", promotion_allowed=True, winner_id=candidate["model_id"])
            result["reasons"] = ["Explicit no-champion comparison; qualified candidate is the initial winner"]
        else:
            result["reasons"] = ["Policy blocks initial selection without a champion"]
        return result
    if candidate["model_id"] == champion["model_id"]:
        result.update(decision="champion_kept", winner_id=champion["model_id"])
        result["reasons"] = ["Candidate and champion identify the same model"]
        return result
    improvements = []
    all_passed = True
    for rule in rules:
        metric = rule["metric"]
        left, right = Decimal(str(candidate["metrics"][metric])), Decimal(str(champion["metrics"][metric]))
        improvement = left - right if rule["direction"] == "maximize" else right - left
        mode = rule.get("delta_mode", "absolute")
        if mode == "relative":
            if right == 0:
                result["reasons"] = [f"{metric}: relative improvement is undefined for a zero champion score; use absolute"]
                return result
            improvement /= abs(right)
        if not math.isfinite(float(improvement)):
            result["reasons"] = [f"{metric}: improvement cannot be represented as a finite score; use absolute units"]
            return result
        required = Decimal(str(rule.get("min_delta", 0)))
        passed = improvement >= required
        improvements.append(improvement)
        all_passed = all_passed and passed
        result["comparisons"].append({
            "metric": metric, "direction": rule["direction"], "delta_mode": mode,
            "candidate": float(left), "champion": float(right), "improvement": float(improvement),
            "min_delta": float(required), "passed": passed,
        })
    tied = all(value == 0 for value in improvements)
    if not all_passed:
        result["reasons"].append("Candidate did not satisfy every selected metric rule")
    elif tied:
        all_passed = profile.get("on_tie", "keep_champion") == "candidate"
        result["reasons"].append("All selected metrics tie; applying explicit on_tie policy")
    elif profile.get("require_any_improvement", True) and not any(value > 0 for value in improvements):
        all_passed = False
        result["reasons"].append("At least one selected metric must strictly improve")
    if all_passed:
        result.update(decision="candidate_wins", promotion_allowed=True, winner_id=candidate["model_id"])
        result["reasons"].append("Candidate satisfies the configured relative-to-champion rules and absolute quality gate")
    else:
        result.update(decision="champion_kept", winner_id=champion["model_id"])
    return result
