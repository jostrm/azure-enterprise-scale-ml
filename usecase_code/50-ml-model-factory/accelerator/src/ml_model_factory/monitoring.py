"""Observed data shift and labeled performance degradation, not a forecast of drift."""

from datetime import datetime, timedelta, timezone
import math
from uuid import uuid4

import numpy as np
import pandas as pd

from .config import validate_scenario
from .lake import identifier
from .tags import scope_tags


SCHEMA = "aifactory.monitoring/v1"
STATES = {"healthy", "warning", "drift", "insufficient_data", "not_supported", "stale", "unknown"}


def image_statistics(frame: pd.DataFrame, max_image_bytes: int = 5 * 1024 * 1024) -> pd.DataFrame:
    """Fixed image summaries detect input shifts, not semantic/embedding drift."""
    import base64
    import io
    from PIL import Image

    if "image_base64" not in frame:
        raise ValueError("Image-statistics monitoring requires image_base64 inputs, not remote URLs")
    rows = []
    for value in frame["image_base64"]:
        if not isinstance(value, str) or len(value) > (max_image_bytes * 4 // 3 + 8):
            raise ValueError("Image monitoring input exceeds its byte budget")
        raw = base64.b64decode(value, validate=True)
        if len(raw) > max_image_bytes:
            raise ValueError("Decoded image exceeds its byte budget")
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if width * height > 40000000:
                raise ValueError("Image exceeds the monitoring pixel budget")
            pixels = np.asarray(image.convert("RGB").resize((32, 32)), dtype=float) / 255
            means = pixels.mean(axis=(0, 1))
            rows.append({
                "image_red_mean": means[0], "image_green_mean": means[1], "image_blue_mean": means[2],
                "image_brightness_std": float(pixels.mean(axis=2).std()),
                "image_aspect_ratio": width / height, "image_width": float(width), "image_height": float(height),
            })
    return pd.DataFrame(rows, columns=["image_red_mean", "image_green_mean", "image_blue_mean",
                                     "image_brightness_std", "image_aspect_ratio", "image_width", "image_height"])


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Monitoring timestamps require an explicit UTC offset")
    return parsed


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def thresholds(config: dict, name: str, defaults: tuple[float, float]) -> tuple[float, float]:
    selected = config.get(name, {})
    warning, drift = selected.get("warning", defaults[0]), selected.get("drift", defaults[1])
    if (not isinstance(warning, (float, int)) or not isinstance(drift, (float, int))
            or not math.isfinite(warning) or not math.isfinite(drift) or not 0 < warning <= drift):
        raise ValueError(f"{name} requires finite 0 < warning <= drift thresholds")
    return float(warning), float(drift)


def state(score: float, limits: tuple[float, float]) -> str:
    return "drift" if score >= limits[1] else "warning" if score >= limits[0] else "healthy"


def distribution_score(reference, current, categorical: bool, bins: int = 10):
    """Reference-defined bins/categories avoid fitting the baseline on current data."""
    if categorical:
        reference = reference.map(lambda value: "missing:" if pd.isna(value) else f"value:{value}")
        current = current.map(lambda value: "missing:" if pd.isna(value) else f"value:{value}")
        common = reference.value_counts().head(100).index.tolist()
        categories = [*common, "other:"]
        reference = reference.where(reference.isin(common), "other:")
        current = current.where(current.isin(common), "other:")
        counts = lambda series: series.value_counts().reindex(categories, fill_value=0).to_numpy(dtype=float)
        left, right = counts(reference), counts(current)
        # Jensen-Shannon divergence is bounded [0,1] with log base 2.
        p, q = left / left.sum(), right / right.sum()
        midpoint = (p + q) / 2
        divergence = lambda distribution: float(np.sum(
            distribution[distribution > 0] * np.log2(distribution[distribution > 0] / midpoint[distribution > 0])
        ))
        return (divergence(p) + divergence(q)) / 2, "js_divergence"
    reference = pd.to_numeric(reference, errors="raise")
    current = pd.to_numeric(current, errors="raise")
    if np.isinf(reference.dropna()).any() or np.isinf(current.dropna()).any():
        raise ValueError("Infinite numeric feature values require a data-quality correction")
    valid = reference.dropna().to_numpy(dtype=float)
    if not len(valid):
        return None, "psi"
    edges = np.unique(np.quantile(valid, np.linspace(0, 1, bins + 1)))
    if len(edges) == 1:
        margin = max(abs(edges[0]) * 1e-6, 1e-6)
        boundaries = np.array([-np.inf, edges[0] - margin, edges[0] + margin, np.inf])
    else:
        boundaries = np.concatenate(([-np.inf], edges, [np.inf]))
    counts = lambda series: np.append(np.histogram(series.dropna(), bins=boundaries)[0], series.isna().sum()).astype(float)
    p, q = counts(reference), counts(current)
    # Additive smoothing is fixed and documented; no significance claim is attached.
    p, q = (p + 0.5) / (p.sum() + 0.5 * len(p)), (q + 0.5) / (q.sum() + 0.5 * len(q))
    return float(np.sum((q - p) * np.log(q / p))), "psi"


def data_drift(reference: pd.DataFrame, current: pd.DataFrame, features: list[str],
               categorical: list[str], config: dict) -> dict:
    minimum = config.get("min_samples", 100)
    if not isinstance(minimum, int) or minimum < 20:
        raise ValueError("min_samples must be an integer of at least 20")
    if not features:
        return {"status": "not_supported", "features": [], "reason": "No comparable feature representation configured"}
    if len(features) > 200 or len(set(features)) != len(features):
        raise ValueError("Monitoring requires at most 200 unique feature columns")
    missing = set(features) - set(reference.columns).intersection(current.columns)
    if missing:
        return {"status": "unknown", "features": [], "reason": "Feature schema mismatch", "missing_features": sorted(missing)}
    if min(len(reference), len(current)) < minimum:
        return {"status": "insufficient_data", "features": [], "minimum_samples": minimum}
    results = []
    for name in features:
        score, metric = distribution_score(reference[name], current[name], name in categorical)
        limits = thresholds(config, metric, (0.1, 0.25) if metric == "psi" else (0.1, 0.2))
        missing_delta = abs(float(current[name].isna().mean() - reference[name].isna().mean()))
        missing_limits = thresholds(config, "missing_rate_change", (0.05, 0.15))
        status = state(score, limits) if score is not None else "insufficient_data"
        missing_status = state(missing_delta, missing_limits)
        if missing_status in ("warning", "drift"):
            status = max([status, missing_status], key=lambda value: {"healthy": 0, "insufficient_data": 1, "warning": 2, "drift": 3}[value])
        results.append({
            "feature": name, "metric": metric, "value": score, "status": status,
            "warning_threshold": limits[0], "drift_threshold": limits[1],
            "reference_missing_fraction": float(reference[name].isna().mean()),
            "current_missing_fraction": float(current[name].isna().mean()),
            "missing_fraction_change": missing_delta,
        })
    statuses = {row["status"] for row in results}
    status = next((item for item in ("drift", "warning", "insufficient_data") if item in statuses), "healthy")
    return {"status": status, "features": results, "drifted_features": sum(row["status"] == "drift" for row in results)}


def _ids(frame: pd.DataFrame, column: str):
    if column not in frame or frame[column].isna().any() or frame[column].duplicated().any():
        raise ValueError("Performance observations need unique, nonmissing request IDs")
    if frame[column].map(lambda value: isinstance(value, str) and not value.strip()).any():
        raise ValueError("Performance request IDs must not be blank")


def performance_signal(reference: pd.DataFrame | None, predictions: pd.DataFrame | None,
                       labels: pd.DataFrame | None, task: str, target: str,
                       config: dict, window: dict, now: datetime, model_version: str) -> dict:
    if task.startswith("image_") and task != "image_classification":
        return {"status": "not_supported", "reason": "Vision performance monitoring requires task-specific matched annotations/prediction adapters"}
    if reference is None or predictions is None or labels is None:
        return {"status": "unknown", "reason": "Observed labels and a fixed-model baseline are required; predictions are not labels"}
    id_column = config.get("request_id_column", "request_id")
    _ids(predictions, id_column)
    _ids(labels, id_column)
    _ids(reference, id_column)
    if set(reference[id_column]).intersection(predictions[id_column]):
        raise ValueError("Reference and current observations must be disjoint")
    if "model_version" not in reference or "model_version" not in predictions:
        raise ValueError("Baseline and current predictions must identify the same immutable model_version")
    if not reference["model_version"].map(str).eq(model_version).all() or not predictions["model_version"].map(str).eq(model_version).all():
        raise ValueError("Performance comparison cannot mix model versions")
    if not {"actual", "prediction"}.issubset(reference) or "prediction" not in predictions:
        raise ValueError("Baseline needs actual/prediction and current data needs prediction")
    if target not in labels or "observed_at" not in labels:
        raise ValueError("Feedback needs the target and observed_at; never synthesize observed labels")
    if not set(labels[id_column]).issubset(predictions[id_column]):
        raise ValueError("Observed labels contain request IDs outside the selected inference window")
    observed = labels["observed_at"].map(lambda value: utc(str(value)))
    if observed.isna().any() or (observed > now).any():
        raise ValueError("Observed-label timestamps are missing or in the future")
    selected = predictions[[id_column, "prediction"]].merge(
        labels[[id_column, target]], on=id_column, how="inner", validate="one_to_one",
    )
    if reference[["actual", "prediction"]].isna().any().any() or selected[["prediction", target]].isna().any().any():
        raise ValueError("Performance observations must not contain missing labels or predictions")
    coverage = len(selected) / len(predictions) if len(predictions) else 0.0
    minimum = config.get("min_labeled_samples", 50)
    minimum_coverage = config.get("min_label_coverage", 0.5)
    if not isinstance(minimum, int) or minimum < 20 or not 0 < minimum_coverage <= 1:
        raise ValueError("Invalid labeled-sample/coverage monitoring thresholds")
    if min(len(reference), len(selected)) < minimum or coverage < minimum_coverage:
        return {"status": "insufficient_data", "label_coverage": coverage, "labeled_samples": len(selected),
                "minimum_samples": minimum, "reason": "Too few observed outcomes or insufficient label coverage"}
    if task in ("classification", "image_classification"):
        before = (reference["actual"].to_numpy() != reference["prediction"].to_numpy()).astype(float)
        after = (selected[target].to_numpy() != selected["prediction"].to_numpy()).astype(float)
        metric, normalization = "error_rate_increase", 1.0
        limits = thresholds(config, "performance", (0.05, 0.1))
        performance_metrics = {"reference_accuracy": 1 - float(before.mean()),
                               "current_accuracy": 1 - float(after.mean())}
    else:
        truth = pd.to_numeric(reference["actual"], errors="raise").to_numpy(dtype=float)
        normalization = max(float(np.std(truth)), float(np.mean(np.abs(truth))) * 0.01, 1e-8)
        before = np.abs(truth - pd.to_numeric(reference["prediction"], errors="raise").to_numpy(dtype=float)) / normalization
        after = np.abs(pd.to_numeric(selected[target], errors="raise").to_numpy(dtype=float) -
                       pd.to_numeric(selected["prediction"], errors="raise").to_numpy(dtype=float)) / normalization
        metric = "normalized_mae_increase"
        limits = thresholds(config, "performance", (0.1, 0.25))
        current_truth = pd.to_numeric(selected[target], errors="raise").to_numpy(dtype=float)
        current_error = after * normalization
        reference_error = before * normalization
        variance = float(np.sum((current_truth - current_truth.mean()) ** 2))
        performance_metrics = {
            "reference_mae": float(reference_error.mean()), "current_mae": float(current_error.mean()),
            "reference_rmse": float(np.sqrt((reference_error ** 2).mean())),
            "current_rmse": float(np.sqrt((current_error ** 2).mean())),
            "current_r2": 1 - float(np.sum(current_error ** 2)) / variance if variance > 0 else None,
        }
    if not np.isfinite(before).all() or not np.isfinite(after).all():
        raise ValueError("Performance losses must be finite")
    delta = float(np.mean(after) - np.mean(before))
    rng = np.random.default_rng(42)
    draws = [float(rng.choice(after, len(after)).mean() - rng.choice(before, len(before)).mean()) for _ in range(300)]
    lower, upper = (float(value) for value in np.quantile(draws, [0.025, 0.975]))
    raw_state = state(delta, limits)
    # Degradation is an indicator, not proof of a change in P(y|x). Correlated
    # temporal observations require separate block-bootstrap/domain analysis.
    status = "drift" if raw_state == "drift" and lower > 0 else "warning" if raw_state != "healthy" else "healthy"
    return {
        "status": status, "metric": metric, "value": delta, "reference_loss": float(before.mean()),
        "current_loss": float(after.mean()), "normalization": normalization,
        "confidence_interval_95": [lower, upper], "label_coverage": coverage,
        "labeled_samples": len(selected), "reference_samples": len(reference),
        "minimum_samples": minimum, "minimum_label_coverage": minimum_coverage,
        "warning_threshold": limits[0], "drift_threshold": limits[1],
        "performance_metrics": performance_metrics,
        "interpretation": "Observed labeled performance degradation; not proof of conditional concept drift",
    }


def monitor(scenario: dict, context: dict, reference: pd.DataFrame, current: pd.DataFrame,
            config: dict, *, reference_outcomes=None, predictions=None, labels=None,
            now: datetime | None = None) -> dict:
    validate_scenario(scenario)
    scope = scope_tags(context, require=True)
    config = dict(config)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("Monitoring clock must be timezone-aware UTC")
    model_name = config.get("model_name") or scenario.get("model_name") or scenario["name"]
    identifier(model_name, "model_name")
    version = identifier(config.get("model_version"), "model_version")
    if version.lower() in ("latest", "active", "champion", "production"):
        raise ValueError("Monitor an immutable model version, never a registry alias")
    lake = context.get("lake", {})
    if lake.get("model_version") is not None and str(lake["model_version"]) != version:
        raise ValueError("Monitoring model version differs from the selected inference lake model version")
    if lake.get("use_case") is not None and lake["use_case"] != scenario["name"]:
        raise ValueError("Monitoring scenario differs from the selected lake use case")
    window = config.get("window", {})
    baseline = config.get("reference_window", {})
    start, end = utc(window["start"]), utc(window["end"])
    reference_start, reference_end = utc(baseline["start"]), utc(baseline["end"])
    if not reference_start < reference_end <= start < end <= now:
        raise ValueError("Reference/current windows must be ordered, disjoint, and not in the future")
    ttl = config.get("max_age_hours", 24)
    if not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
        raise ValueError("max_age_hours must be finite and positive")
    expires = end + timedelta(hours=ttl)
    features = config.get("features", [] if scenario["task"].startswith("image_") else scenario["features"])
    if not isinstance(features, list) or any(not isinstance(name, str) for name in features):
        raise ValueError("Monitoring features must be a list of column names")
    if scenario.get("target") in features or "prediction" in features:
        raise ValueError("Data drift features must exclude labels and predictions")
    maximum = config.get("max_rows", 100000)
    if (not isinstance(maximum, int) or maximum < 20 or
            any(frame is not None and len(frame) > maximum for frame in
                (reference, current, reference_outcomes, predictions, labels))):
        raise ValueError("Monitoring input exceeds the configured row budget; select a representative bounded window")
    if predictions is not None:
        request = config.get("request_id_column", "request_id")
        if len(predictions) != len(current):
            raise ValueError("Current features and predictions must describe the same observed window")
        if request in current:
            _ids(current, request)
            if request not in predictions or set(current[request]) != set(predictions[request]):
                raise ValueError("Current feature request IDs differ from prediction request IDs")
    if config.get("image_statistics", False):
        if not scenario["task"].startswith("image_"):
            raise ValueError("image_statistics is only applicable to vision tasks")
        reference, current = image_statistics(reference), image_statistics(current)
        features = reference.columns.tolist()
    data = data_drift(reference, current, features, config.get("categorical_features", scenario.get("categorical_features", [])), config)
    concept = performance_signal(reference_outcomes, predictions, labels, scenario["task"], scenario.get("target", "label"),
                                 config, window, now, version)
    measured = {data["status"], concept["status"]}
    overall = next((name for name in ("drift", "warning", "unknown", "insufficient_data") if name in measured),
                   "healthy" if "healthy" in measured else "not_supported")
    stale = expires < now
    metrics = [
        {"name": "reference_samples", "value": len(reference), "unit": "rows", "status": "stale" if stale else data["status"]},
        {"name": "current_samples", "value": len(current), "unit": "rows", "status": "stale" if stale else data["status"]},
    ]
    for feature in data.get("features", []):
        metrics.append({"name": f"data_drift.{feature['feature']}.{feature['metric']}",
                        "value": feature["value"], "unit": "score", "status": "stale" if stale else feature["status"]})
        metrics.append({"name": f"data_quality.{feature['feature']}.missing_fraction_change",
                        "value": feature["missing_fraction_change"], "unit": "fraction", "status": "stale" if stale else feature["status"]})
    for name in ("value", "reference_loss", "current_loss", "label_coverage", "labeled_samples"):
        if name in concept:
            metrics.append({"name": f"concept_signal.{name}", "value": concept[name],
                            "unit": "score" if name == "value" else "number", "status": "stale" if stale else concept["status"]})
    for name, value in concept.get("performance_metrics", {}).items():
        metrics.append({"name": f"performance.{name}", "value": value, "unit": "score",
                        "status": "stale" if stale else concept["status"]})
    return {
        "schema": SCHEMA, "source": "ml-model-factory", "scope": scope,
        "use_case": scenario["name"],
        "subject": {"kind": "model", "name": model_name, "version": version, "task_type": scenario["task"]},
        "report_id": uuid4().hex, "generated_at": iso(now), "window": {"start": iso(start), "end": iso(end)},
        "reference_window": {"start": iso(reference_start), "end": iso(reference_end)}, "expires_at": iso(expires),
        "summary": {"status": "stale" if stale else overall, "data_drift": "stale" if stale else data["status"],
                    "concept_drift": "stale" if stale else concept["status"]},
        "metrics": metrics, "details": {"data_drift": data, "concept_drift": concept},
        "limitations": [
            "Drift describes observed windows, not a prediction that a model will drift in the future.",
            "Data drift is distribution change; it does not by itself establish a model-quality or concept change.",
            "Concept drift signal is labeled performance degradation, not proof of P(y|x) change.",
            "Bootstrap intervals assume independent observations; temporal/group dependence requires domain-specific analysis.",
            "Delayed or selectively observed labels can bias performance estimates even when the coverage threshold passes.",
            "Thresholds and windows are configurable operational heuristics, not universal statistical guarantees.",
            "Vision requires a fixed feature representation; raw pixels/annotations are not silently reduced to tabular outcomes.",
            "Image statistics, when enabled, measure color/dimension shifts and do not establish semantic image drift.",
            "Window bounds are supplied by the data producer; publish only files selected for those exact event-time windows.",
        ],
    }
