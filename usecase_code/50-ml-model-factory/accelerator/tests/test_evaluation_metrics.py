import json

import mlflow.pyfunc
import mlflow.sklearn
import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import load_iris
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, f1_score, log_loss, matthews_corrcoef, mean_absolute_error, mean_squared_error,
    precision_score, r2_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.svm import LinearSVC

from ml_model_factory.evaluation import _model_probabilities, evaluate, metrics_for


def test_label_metrics_do_not_fabricate_probabilities():
    truth = ["no", "yes", "yes", "no", "no"]
    predictions = ["no", "yes", "no", "yes", "no"]
    availability = {}
    metrics = metrics_for("classification", truth, predictions, metric_availability=availability)
    assert metrics == pytest.approx({
        "accuracy": accuracy_score(truth, predictions),
        "f1_weighted": f1_score(truth, predictions, average="weighted"),
        "precision_weighted": precision_score(truth, predictions, average="weighted"),
        "recall_weighted": recall_score(truth, predictions, average="weighted"),
        "matthews_correlation": matthews_corrcoef(truth, predictions),
    })
    for name in ("auc_weighted", "log_loss"):
        assert name not in metrics
        assert availability[name]["available"] is False
        assert "never derived from hard labels" in availability[name]["reason"]


def test_binary_probabilities_preserve_unsorted_positive_class():
    classes = ["zebra", "ant"]
    truth = np.array(["zebra", "ant", "ant", "zebra"])
    probabilities = np.array([[0.9, 0.1], [0.2, 0.8], [0.4, 0.6], [0.3, 0.7]])
    availability = {}
    metrics = metrics_for(
        "classification", truth, truth, probabilities=probabilities, classes=classes,
        metric_availability=availability,
    )
    encoded = [0, 1, 1, 0]
    assert metrics["auc_weighted"] == pytest.approx(roc_auc_score(encoded, probabilities[:, 1]))
    assert metrics["log_loss"] == pytest.approx(log_loss(encoded, probabilities, labels=[0, 1]))
    assert availability["auc_weighted"]["positive_class"] == "ant"
    assert availability["auc_weighted"]["class_order"] == classes


def test_multiclass_probabilities_align_dataframe_columns():
    classes = ["zebra", "ant", "bear"]
    truth = np.array(["bear", "ant", "zebra", "bear", "ant", "zebra"])
    probabilities = np.array([
        [0.1, 0.2, 0.7], [0.6, 0.3, 0.1], [0.5, 0.2, 0.3],
        [0.3, 0.2, 0.5], [0.2, 0.7, 0.1], [0.2, 0.1, 0.7],
    ])
    reordered = pd.DataFrame(probabilities, columns=classes)[["ant", "bear", "zebra"]]
    availability = {}
    metrics = metrics_for(
        "classification", truth, truth, probabilities=reordered, classes=classes,
        metric_availability=availability,
    )
    encoded = [2, 1, 0, 2, 1, 0]
    assert metrics["auc_weighted"] == pytest.approx(
        roc_auc_score(encoded, probabilities, multi_class="ovr", average="weighted", labels=[0, 1, 2])
    )
    assert metrics["log_loss"] == pytest.approx(log_loss(encoded, probabilities, labels=[0, 1, 2]))
    assert availability["auc_weighted"]["method"] == "ovr_weighted"


@pytest.mark.parametrize("probabilities,classes,reason", [
    ([[0.2, 0.8], [0.8, 0.2]], None, "classes_"),
    ([[0.2, 0.8], [0.8, 0.2]], ["a", "a"], "unique"),
    ([[0.2, 0.8], [0.8, 0.2]], ["a", None], "nonmissing"),
    ([[0.2, 0.8], [0.8, 0.2]], [0, np.inf], "finite"),
    ([[0.2, 0.8], [0.8, 0.2]], [["a"], ["b"]], "scalar vector"),
    ([[0.2, 0.8], [0.8, 0.2]], [], "nonempty"),
    ([0, 1], ["a", "b"], "shape"),
    ([[0.2, 0.8, 0], [0.8, 0.2, 0]], ["a", "b"], "shape"),
    ([[np.nan, 0.8], [0.8, 0.2]], ["a", "b"], "finite probabilities"),
    ([[np.inf, 0.8], [0.8, 0.2]], ["a", "b"], "finite probabilities"),
    ([[-0.2, 1.2], [0.8, 0.2]], ["a", "b"], "between zero and one"),
    ([[0.2, 0.2], [0.8, 0.2]], ["a", "b"], "sum to one"),
    (pd.DataFrame([[0.2, 0.8], [0.8, 0.2]], columns=["a", "c"]), ["a", "b"], "columns"),
    (pd.DataFrame([[0.2, 0.8], [0.8, 0.2]], columns=["a", "a"]), ["a", "b"], "columns"),
    (pd.DataFrame([[0.2, 0.8], [0.8, 0.2]], columns=["0", "1"]), [0, 1], "columns"),
])
def test_malformed_probabilities_are_data_errors(probabilities, classes, reason):
    with pytest.raises(ValueError, match=reason):
        metrics_for("classification", ["a", "b"], ["a", "b"], probabilities=probabilities, classes=classes)


def test_unseen_targets_omit_probability_metrics_with_reason():
    availability = {}
    metrics = metrics_for(
        "classification", ["a", "unseen"], ["a", "b"],
        probabilities=[[0.7, 0.3], [0.2, 0.8]], classes=["a", "b"], metric_availability=availability,
    )
    assert metrics["accuracy"] == 0.5
    for name in ("auc_weighted", "log_loss"):
        assert name not in metrics
        assert "unseen" in availability[name]["reason"]


def test_single_test_class_retains_defined_log_loss_but_not_auc_or_mcc():
    availability = {}
    metrics = metrics_for(
        "classification", ["a", "a"], ["a", "a"], probabilities=[[0.7, 0.3], [0.8, 0.2]],
        classes=["a", "b"], metric_availability=availability,
    )
    assert metrics["log_loss"] == pytest.approx(-np.mean(np.log([0.7, 0.8])))
    assert "auc_weighted" not in metrics
    assert "matthews_correlation" not in metrics
    assert availability["auc_weighted"]["available"] is False
    assert "constant" in availability["matthews_correlation"]["reason"]


def test_missing_multiclass_test_class_omits_auc_not_log_loss():
    availability = {}
    metrics = metrics_for(
        "classification", ["a", "b"], ["a", "b"], probabilities=[[0.7, 0.2, 0.1], [0.2, 0.7, 0.1]],
        classes=["a", "b", "c"], metric_availability=availability,
    )
    assert metrics["log_loss"] == pytest.approx(-np.log(0.7))
    assert "auc_weighted" not in metrics
    assert "every model class" in availability["auc_weighted"]["reason"]


def test_single_model_class_omits_probability_metrics():
    availability = {}
    metrics = metrics_for(
        "classification", ["a", "a"], ["a", "a"], probabilities=[[1], [1]], classes=["a"],
        metric_availability=availability,
    )
    assert metrics["accuracy"] == 1
    for name in ("auc_weighted", "log_loss"):
        assert name not in metrics
        assert "at least two model classes" in availability[name]["reason"]


@pytest.mark.parametrize("task", ["regression", "forecasting"])
def test_regression_metrics_use_average_tie_ranks_and_fractional_mape(task):
    truth = np.array([1, 1, 3, 5, 8])
    predictions = np.array([2, 1, 3, 4, 4])
    availability = {}
    metrics = metrics_for(task, truth, predictions, metric_availability=availability)
    assert metrics == pytest.approx({
        "mae": mean_absolute_error(truth, predictions),
        "rmse": mean_squared_error(truth, predictions) ** 0.5,
        "r2": r2_score(truth, predictions),
        "spearman_correlation": np.corrcoef([1.5, 1.5, 3, 4, 5], [2, 1, 3, 4.5, 4.5])[0, 1],
        "mape": np.mean(np.abs((truth - predictions) / truth)),
    })
    assert all(value["available"] for value in availability.values())


@pytest.mark.parametrize("truth,predictions,omitted", [
    ([0, 1, 2], [0, 2, 1], ["mape"]),
    ([2, 2, 2], [1, 2, 3], ["r2", "spearman_correlation"]),
    ([2, 2, 2], [2, 2, 2], ["r2", "spearman_correlation"]),
    ([1, 2, 3], [2, 2, 2], ["spearman_correlation"]),
    ([1], [2], ["r2", "spearman_correlation"]),
])
def test_undefined_regression_metrics_are_omitted(truth, predictions, omitted):
    availability = {}
    metrics = metrics_for("regression", truth, predictions, metric_availability=availability)
    assert "mae" in metrics and "rmse" in metrics
    for name in omitted:
        assert name not in metrics
        assert availability[name]["available"] is False
        assert availability[name]["reason"]
    json.dumps(metrics, allow_nan=False)


@pytest.mark.parametrize("task", ["regression", "classification"])
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, None])
@pytest.mark.parametrize("side", ["truth", "predictions"])
def test_nonfinite_inputs_are_rejected(task, bad, side):
    values = {"truth": [0, 1], "predictions": [0, 1]}
    values[side] = [0, bad]
    with pytest.raises(ValueError, match="finite|missing"):
        metrics_for(task, **values)


def test_metric_overflow_is_omitted_instead_of_serializing_infinity():
    availability = {}
    metrics = metrics_for("regression", [1, 2], [1e200, 2e200], metric_availability=availability)
    for name in ("rmse", "r2"):
        assert name not in metrics
        assert availability[name]["available"] is False
        assert "nonfinite" in availability[name]["reason"]
    json.dumps(metrics, allow_nan=False)


def test_metric_vectors_preserve_scalar_shape_contract():
    assert metrics_for("regression", [1, 2], pd.DataFrame({"prediction": [1, 2]}))["mae"] == 0
    with pytest.raises(ValueError, match="multiple columns"):
        metrics_for("regression", [1, 2], pd.DataFrame({"p1": [1, 2], "p2": [1, 2]}))
    with pytest.raises(ValueError, match="scalar predictions"):
        metrics_for("regression", [1, 2], [1])
    with pytest.raises(ValueError, match="at least one observation"):
        metrics_for("classification", [], [])


def _saved_classifier(root, *, multiclass=False, probabilities=True):
    dataset = load_iris(as_frame=True)
    frame = dataset.data.copy()
    frame.columns = ["feature_" + str(index) for index in range(len(frame.columns))]
    target = dataset.target.map({0: "zebra", 1: "ant", 2: "bear"})
    if not multiclass:
        selected = target != "bear"
        frame, target = frame.loc[selected], target.loc[selected]
    train_x, test_x, train_y, test_y = train_test_split(
        frame, target, test_size=0.3, random_state=27, stratify=target,
    )
    estimator = LogisticRegression(max_iter=500) if probabilities else LinearSVC(max_iter=5000)
    estimator.fit(train_x, train_y)
    model_path = root / "model"
    mlflow.sklearn.save_model(estimator, str(model_path), pip_requirements=[])
    prepared = root / "prepared"
    (prepared / "test").mkdir(parents=True)
    test = test_x.copy()
    test["target"] = test_y
    test["cohort"] = np.arange(len(test)) % 2
    test.to_parquet(prepared / "test" / "data.parquet", index=False)
    scenario = {
        "name": "measured_classifier", "task": "classification", "features": list(frame.columns),
        "target": "target", "sensitive_features": ["cohort"], "quality": {"min_accuracy": 0.0},
    }
    return scenario, prepared, model_path, estimator, test_x, test_y


@pytest.mark.parametrize("multiclass", [False, True])
def test_real_sklearn_mlflow_evaluation_records_measured_probabilities_and_evidence(tmp_path, multiclass):
    scenario, prepared, model_path, estimator, inputs, truth = _saved_classifier(tmp_path, multiclass=multiclass)
    assert not (prepared / "manifest.json").exists()
    report = evaluate(scenario, prepared, model_path, tmp_path / "report")
    probabilities = estimator.predict_proba(inputs)
    expected = log_loss(truth, probabilities, labels=estimator.classes_)
    assert report["metrics"]["log_loss"] == pytest.approx(expected)
    if multiclass:
        expected_auc = roc_auc_score(
            truth, probabilities, multi_class="ovr", average="weighted", labels=estimator.classes_,
        )
    else:
        expected_auc = roc_auc_score(truth == estimator.classes_[1], probabilities[:, 1])
    assert report["metrics"]["auc_weighted"] == pytest.approx(expected_auc)
    assert report["metric_availability"]["auc_weighted"]["available"] is True
    assert report["cohorts"]["cohort"]
    assert report["responsible_ai"]["permutation_importance"]
    output = tmp_path / "report"
    assert json.loads((output / "metrics.json").read_text()) == report["metrics"]
    assert json.loads((output / "responsible-ai.json").read_text())["metric_availability"] == report["metric_availability"]
    evidence = json.loads((output / "comparison.json").read_text())
    assert evidence["schema"] == "aifactory.model-evaluation/v1"
    assert evidence["metrics"] == report["metrics"]
    assert evidence["evaluation"]["row_count"] == len(inputs)
    assert json.loads((output / "quality-gate.json").read_text())["passed"] is True


def test_real_sklearn_without_predict_proba_omits_probabilities(tmp_path):
    scenario, prepared, model_path, _, _, _ = _saved_classifier(tmp_path, probabilities=False)
    report = evaluate(scenario, prepared, model_path, tmp_path / "report")
    assert "accuracy" in report["metrics"]
    for name in ("auc_weighted", "log_loss"):
        assert name not in report["metrics"]
        assert "does not support predict_proba" in report["metric_availability"][name]["reason"]


class LabelOnlyModel(mlflow.pyfunc.PythonModel):
    def predict(self, context, model_input, params=None):
        return np.where(model_input["x"] > 0, "positive", "negative")


def test_generic_pyfunc_labels_remain_supported_without_fabricated_auc(tmp_path):
    model_path = tmp_path / "model"
    mlflow.pyfunc.save_model(str(model_path), python_model=LabelOnlyModel(), pip_requirements=[])
    prepared = tmp_path / "prepared"
    (prepared / "test").mkdir(parents=True)
    pd.DataFrame({"x": [-2.0, -1.0, 1.0, 2.0], "target": ["negative", "negative", "positive", "positive"]}).to_parquet(
        prepared / "test" / "data.parquet", index=False,
    )
    scenario = {"name": "labels_only", "task": "classification", "features": ["x"], "target": "target"}
    report = evaluate(scenario, prepared, model_path, tmp_path / "report")
    assert report["metrics"]["accuracy"] == 1
    assert "auc_weighted" not in report["metrics"] and "log_loss" not in report["metrics"]
    assert "no supported sklearn flavor" in report["metric_availability"]["auc_weighted"]["reason"]


def test_regression_report_persists_undefined_metric_reasons(tmp_path):
    inputs = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    estimator = DummyRegressor().fit(inputs, [0, 0, 0])
    model_path = tmp_path / "model"
    mlflow.sklearn.save_model(estimator, str(model_path), pip_requirements=[])
    prepared = tmp_path / "prepared"
    (prepared / "test").mkdir(parents=True)
    inputs.assign(target=0).to_parquet(prepared / "test" / "data.parquet", index=False)
    scenario = {"name": "constant_regressor", "task": "regression", "features": ["x"], "target": "target"}
    output = tmp_path / "report"
    report = evaluate(scenario, prepared, model_path, output)
    assert report["metrics"] == {"mae": 0, "rmse": 0}
    persisted = json.loads((output / "responsible-ai.json").read_text())
    for name in ("r2", "mape", "spearman_correlation"):
        assert persisted["metric_availability"][name]["available"] is False
        assert persisted["metric_availability"][name]["reason"]


def test_quality_failure_remains_failure_and_does_not_emit_passing_comparison(tmp_path):
    scenario, prepared, model_path, _, _, _ = _saved_classifier(tmp_path)
    scenario["quality"] = {"min_accuracy": 1.1}
    output = tmp_path / "report"
    with pytest.raises(ValueError):
        evaluate(scenario, prepared, model_path, output)
    assert json.loads((output / "quality-gate.json").read_text())["passed"] is False
    assert not (output / "comparison.json").exists()


class InvalidProbabilityClassifier:
    classes_ = np.array(["a", "b"])

    def __init__(self, failure="data"):
        self.failure = failure

    def predict(self, model_input):
        return np.array(["a"] * len(model_input))

    def predict_proba(self, model_input):
        if self.failure == "unsupported":
            raise NotImplementedError("Probability prediction is unsupported")
        if self.failure == "none":
            return None
        raise ValueError("Invalid input schema for predict_proba")


@pytest.mark.parametrize("failure,reason", [("data", "Invalid input schema"), ("none", "no probability matrix")])
def test_native_probability_prediction_errors_are_not_swallowed(tmp_path, failure, reason):
    model_path = tmp_path / "model"
    mlflow.sklearn.save_model(InvalidProbabilityClassifier(failure), str(model_path), pip_requirements=[])
    model = mlflow.pyfunc.load_model(str(model_path))
    with pytest.raises(ValueError, match=reason):
        _model_probabilities(model, model_path, pd.DataFrame({"x": [1, 2]}))


def test_native_explicitly_unsupported_probabilities_are_omitted(tmp_path):
    model_path = tmp_path / "model"
    mlflow.sklearn.save_model(InvalidProbabilityClassifier("unsupported"), str(model_path), pip_requirements=[])
    model = mlflow.pyfunc.load_model(str(model_path))
    probabilities, classes, reason = _model_probabilities(model, model_path, pd.DataFrame({"x": [1, 2]}))
    assert probabilities is None and classes is None
    assert "unsupported" in reason
