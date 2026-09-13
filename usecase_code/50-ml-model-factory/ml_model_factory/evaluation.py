"""Task-aware quality gates and Responsible AI artifacts; no fabricated dashboards."""

from pathlib import Path

from .config import quality_gate, write_json
from .data import read_frame


def prediction_vector(predictions, expected_rows: int):
    import numpy as np
    import pandas as pd

    if isinstance(predictions, pd.DataFrame):
        if len(predictions.columns) != 1:
            raise ValueError("Model returned multiple columns; configure an explicit prediction adapter")
        predictions = predictions.iloc[:, 0]
    array = np.asarray(predictions)
    if array.shape == (expected_rows, 1):
        array = array[:, 0]
    if array.shape != (expected_rows,):
        raise ValueError(f"Expected {expected_rows} scalar predictions, got shape {array.shape}")
    return array


def _probability_metrics(truth, probabilities, classes, metrics: dict, availability: dict) -> None:
    import numpy as np
    import pandas as pd
    from sklearn.metrics import log_loss, roc_auc_score

    if classes is None:
        raise ValueError("Probability predictions require an explicit classes_ mapping")
    classes = np.asarray(classes)
    if classes.ndim != 1 or not len(classes):
        raise ValueError("Probability classes must be a nonempty scalar vector")
    labels = pd.Index(classes)
    if not labels.is_unique or labels.hasnans:
        raise ValueError("Probability classes must be unique and nonmissing")
    if np.issubdtype(classes.dtype, np.number) and not np.isfinite(classes).all():
        raise ValueError("Probability classes must be finite")
    if isinstance(probabilities, pd.DataFrame):
        columns = probabilities.columns
        if (not columns.is_unique or len(columns) != len(labels)
                or (columns.get_indexer(labels) < 0).any()):
            raise ValueError("predict_proba DataFrame columns must match the model classes exactly")
        probabilities = probabilities.loc[:, labels]
    probabilities = np.asarray(probabilities, dtype=float)
    if probabilities.shape != (len(truth), len(classes)):
        raise ValueError(
            f"Expected predict_proba shape {(len(truth), len(classes))}, got {probabilities.shape}"
        )
    if not np.isfinite(probabilities).all() or (probabilities < 0).any() or (probabilities > 1).any():
        raise ValueError("predict_proba must return finite probabilities between zero and one")
    if not np.allclose(probabilities.sum(axis=1), 1, rtol=1e-5, atol=1e-6):
        raise ValueError("predict_proba rows must sum to one")
    encoded = labels.get_indexer(truth)
    if (encoded < 0).any() or len(classes) < 2:
        reason = ("Test targets contain labels unseen in model classes_" if (encoded < 0).any()
                  else "Probability metrics require at least two model classes")
        for name in ("auc_weighted", "log_loss"):
            availability[name] = {"available": False, "reason": reason}
        return

    # Integer encoding preserves estimator column order, including unsorted/string classes.
    metrics["log_loss"] = float(log_loss(encoded, probabilities, labels=np.arange(len(classes))))
    availability["log_loss"] = {"available": True, "class_order": classes.tolist()}
    if len(np.unique(encoded)) != len(classes):
        availability["auc_weighted"] = {
            "available": False,
            "reason": "AUC requires test observations for every model class (at least two classes)",
        }
        return
    if len(classes) == 2:
        metrics["auc_weighted"] = float(roc_auc_score(encoded, probabilities[:, 1]))
        availability["auc_weighted"] = {
            "available": True, "method": "binary", "positive_class": classes.tolist()[1],
            "class_order": classes.tolist(),
        }
    else:
        metrics["auc_weighted"] = float(roc_auc_score(
            encoded, probabilities, labels=np.arange(len(classes)), multi_class="ovr", average="weighted",
        ))
        availability["auc_weighted"] = {
            "available": True, "method": "ovr_weighted", "class_order": classes.tolist(),
        }


def metrics_for(task: str, truth, predictions, *, probabilities=None, classes=None,
                metric_availability: dict | None = None, probability_unavailable_reason: str | None = None) -> dict:
    """Measure scalar-label/error metrics; optional probabilities must come from predict_proba.

    Undefined metrics are omitted, with reasons in the optional availability output.
    MAPE is a fraction (not a percentage); Spearman uses average ranks for ties.
    """
    import numpy as np
    import pandas as pd
    from sklearn.metrics import (
        accuracy_score, f1_score, matthews_corrcoef, mean_absolute_error, mean_squared_error,
        precision_score, r2_score, recall_score,
    )

    if task not in ("classification", "regression", "forecasting"):
        raise ValueError(f"Unsupported metrics task: {task!r}")
    truth = prediction_vector(truth, len(truth))
    predictions = prediction_vector(predictions, len(truth))
    if not len(truth):
        raise ValueError("Evaluation requires at least one observation")
    if pd.isna(truth).any() or pd.isna(predictions).any():
        raise ValueError("Evaluation targets and predictions must not contain missing values")
    for values in (truth, predictions):
        if np.issubdtype(values.dtype, np.number) and not np.isfinite(values).all():
            raise ValueError("Evaluation targets and predictions must be finite")
    availability = metric_availability if metric_availability is not None else {}
    availability.clear()
    metrics = {}
    if task == "classification":
        metrics.update({
            "accuracy": float(accuracy_score(truth, predictions)),
            "f1_weighted": float(f1_score(truth, predictions, average="weighted", zero_division=0)),
            "precision_weighted": float(precision_score(truth, predictions, average="weighted", zero_division=0)),
            "recall_weighted": float(recall_score(truth, predictions, average="weighted", zero_division=0)),
        })
        if len(pd.unique(truth)) > 1 and len(pd.unique(predictions)) > 1:
            metrics["matthews_correlation"] = float(matthews_corrcoef(truth, predictions))
        else:
            availability["matthews_correlation"] = {
                "available": False, "reason": "MCC is undefined for constant targets or predictions",
            }
        if probabilities is None:
            reason = probability_unavailable_reason or (
                "Validated predict_proba output and class mapping were not supplied; "
                "probabilities are never derived from hard labels"
            )
            for name in ("auc_weighted", "log_loss"):
                availability[name] = {"available": False, "reason": reason}
        else:
            _probability_metrics(truth, probabilities, classes, metrics, availability)
    else:
        truth, predictions = np.asarray(truth, dtype=float), np.asarray(predictions, dtype=float)
        if not np.isfinite(truth).all() or not np.isfinite(predictions).all():
            raise ValueError("Evaluation targets and predictions must be finite")
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            metrics["mae"] = float(mean_absolute_error(truth, predictions))
            metrics["rmse"] = float(mean_squared_error(truth, predictions) ** 0.5)
            if len(truth) > 1 and not (truth == truth[0]).all():
                metrics["r2"] = float(r2_score(truth, predictions, force_finite=False))
            else:
                availability["r2"] = {
                    "available": False, "reason": "R2 requires at least two observations and nonconstant targets",
                }
            if len(truth) > 1 and not (truth == truth[0]).all() and not (predictions == predictions[0]).all():
                actual_ranks = pd.Series(truth).rank(method="average").to_numpy()
                predicted_ranks = pd.Series(predictions).rank(method="average").to_numpy()
                metrics["spearman_correlation"] = float(np.corrcoef(actual_ranks, predicted_ranks)[0, 1])
            else:
                availability["spearman_correlation"] = {
                    "available": False,
                    "reason": "Spearman requires at least two observations and nonconstant targets and predictions",
                }
            if (truth == 0).any():
                availability["mape"] = {"available": False, "reason": "MAPE is undefined when any actual target is zero"}
            else:
                metrics["mape"] = float(np.mean(np.abs((truth - predictions) / truth)))
    for name, value in list(metrics.items()):
        if not np.isfinite(value):
            del metrics[name]
            availability[name] = {"available": False, "reason": "Metric calculation produced a nonfinite result"}
        elif name not in availability:
            availability[name] = {"available": True}
    return metrics


def _model_probabilities(model, model_path: Path, inputs):
    """Use a declared native sklearn flavor, never guess probabilities from pyfunc labels."""
    if "sklearn" not in model.metadata.flavors:
        return None, None, "MLflow model has no supported sklearn flavor exposing predict_proba and classes_"
    import mlflow.sklearn

    estimator = mlflow.sklearn.load_model(str(model_path))
    predict_proba = getattr(estimator, "predict_proba", None)
    if not callable(predict_proba):
        return None, None, "Model does not support predict_proba; hard labels are not probabilities"
    classes = getattr(estimator, "classes_", None)
    if classes is None:
        return None, None, "Model does not expose classes_; probability column-to-label mapping is unavailable"
    try:
        probabilities = predict_proba(inputs)
    except NotImplementedError:
        return None, None, "Model predict_proba explicitly reports that probabilities are unsupported"
    if probabilities is None:
        raise ValueError("Model predict_proba returned no probability matrix")
    return probabilities, classes, None


def evaluate(scenario: dict, prepared: Path, model_path: Path, output: Path) -> dict:
    import mlflow.pyfunc
    import numpy as np
    import pandas as pd
    from sklearn.metrics import confusion_matrix

    task = scenario["task"]
    if task not in ("classification", "regression", "forecasting"):
        raise ValueError("Vision evaluation requires the vision-specific evaluator")
    test = read_frame(Path(prepared) / "test")
    model = mlflow.pyfunc.load_model(str(model_path))
    features = list(scenario["features"])
    if task == "forecasting":
        features = list(dict.fromkeys(features + scenario["forecast"].get("series_columns", []) + [scenario["forecast"]["time_column"]]))
    inputs, truth = test.loc[:, features], test[scenario["target"]]
    predictions = prediction_vector(model.predict(inputs), len(test))
    probabilities, classes, probability_reason = (None, None, None)
    if task == "classification":
        probabilities, classes, probability_reason = _model_probabilities(model, model_path, inputs)
    availability = {}
    metrics = metrics_for(
        task, truth, predictions, probabilities=probabilities, classes=classes,
        metric_availability=availability, probability_unavailable_reason=probability_reason,
    )
    report = {
        "scenario": scenario["name"], "task": task, "test_rows": len(test), "metrics": metrics,
        "metric_availability": availability,
        "responsible_ai": {
            "tooling": "MLflow pyfunc, scikit-learn metrics and held-out cohort analysis",
            "azure_dashboard": "Not generated by this evaluator; use supported Azure RAI components separately.",
            "limitations": [
                "Observational cohort differences are not causal conclusions or proof of fairness.",
                "Small cohorts are unstable; assess representativeness before production use.",
                "No counterfactual, clinical-validation, or differential-privacy guarantee is made.",
            ],
        },
        "cohorts": {}, "missing_value_fraction": inputs.isna().mean().to_dict(),
    }
    cohort_columns = list(scenario.get("sensitive_features", []))
    if task == "forecasting":
        cohort_columns = list(dict.fromkeys(cohort_columns + scenario["forecast"].get("series_columns", [])))
    indexed = test.reset_index(drop=True)
    for column in cohort_columns:
        cohorts = {}
        for value, rows in indexed.groupby(column, dropna=False):
            positions = rows.index.to_numpy()
            cohorts[str(value)] = {
                "rows": len(rows), "small_sample_warning": len(rows) < 30,
                **metrics_for(task, truth.iloc[positions], predictions[positions]),
            }
        report["cohorts"][column] = cohorts
    if task == "classification":
        labels = sorted(set(truth.tolist()) | set(predictions.tolist()), key=str)
        report["confusion_matrix"] = {"labels": [str(label) for label in labels],
                                      "matrix": confusion_matrix(truth, predictions, labels=labels).tolist()}
    if task != "forecasting":
        baseline = metrics["accuracy"] if task == "classification" else -metrics["mae"]
        importance = {}
        rng = np.random.default_rng(scenario.get("split", {}).get("seed", 42))
        for column in features:
            perturbed = inputs.copy()
            perturbed[column] = rng.permutation(perturbed[column].to_numpy())
            changed = prediction_vector(model.predict(perturbed), len(test))
            score = metrics_for(task, truth, changed)
            importance[column] = baseline - (score["accuracy"] if task == "classification" else -score["mae"])
        report["responsible_ai"]["permutation_importance"] = importance
        report["responsible_ai"]["limitations"].append(
            "Permutation importance can be misleading for correlated features and is not a causal explanation."
        )
    else:
        report["responsible_ai"]["limitations"].append(
            "Temporal/series error analysis is provided; feature permutation is omitted to preserve time dependence."
        )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"actual": truth.to_numpy(), "prediction": predictions}).to_parquet(output / "predictions.parquet", index=False)
    write_json(output / "metrics.json", metrics)
    write_json(output / "responsible-ai.json", report)
    try:
        quality_gate(metrics, scenario.get("quality", {}))
    except ValueError as exc:
        write_json(output / "quality-gate.json", {"passed": False, "reason": str(exc)})
        raise
    gate = {"passed": True, "limits": scenario.get("quality", {})}
    write_json(output / "quality-gate.json", gate)
    from .selection import build_evidence
    write_json(output / "comparison.json", build_evidence(scenario, Path(prepared), Path(model_path), metrics, gate))
    return report
