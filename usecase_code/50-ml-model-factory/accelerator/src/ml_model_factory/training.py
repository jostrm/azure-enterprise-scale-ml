"""Custom estimators, fitted only on the training split."""

from pathlib import Path

from .config import write_json
from .data import read_frame


def tabular_pipeline(scenario: dict):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    categorical = scenario.get("categorical_features", [])
    numeric = [column for column in scenario["features"] if column not in categorical]
    preprocessing = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                              ("scale", StandardScaler())]), numeric),
        ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
                                  ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), categorical),
    ], remainder="drop")
    algorithm = scenario.get("custom", {}).get("algorithm")
    seed = scenario.get("split", {}).get("seed", 42)
    if scenario["task"] == "classification":
        models = {
            "logistic_regression": LogisticRegression(max_iter=1000, random_state=seed),
            "random_forest": RandomForestClassifier(n_estimators=100, random_state=seed, n_jobs=1),
        }
        algorithm = algorithm or "logistic_regression"
    else:
        models = {
            "ridge": Ridge(alpha=1.0),
            "random_forest": RandomForestRegressor(n_estimators=100, random_state=seed, n_jobs=1),
        }
        algorithm = algorithm or "ridge"
    if algorithm not in models:
        raise ValueError(f"Unsupported {scenario['task']} custom algorithm {algorithm!r}; choose {sorted(models)}")
    return Pipeline([("preprocess", preprocessing), ("estimator", models[algorithm])])


def train(scenario: dict, prepared: Path, model_output: Path) -> None:
    import mlflow.sklearn
    from mlflow.models import infer_signature

    if scenario["task"] == "forecasting":
        from .forecasting import train as train_forecast
        return train_forecast(scenario, prepared, model_output)
    if scenario["task"] not in ("classification", "regression"):
        raise ValueError(f"Use the vision training implementation for {scenario['task']}")
    frame = read_frame(Path(prepared) / "train")
    features, target = frame[scenario["features"]], frame[scenario["target"]]
    model = tabular_pipeline(scenario)
    model.fit(features, target)
    sample = features.head(5)
    mlflow.sklearn.save_model(
        model, str(model_output), signature=infer_signature(sample, model.predict(sample)),
        input_example=sample,
    )
    write_json(Path(model_output) / "factory.json", {
        "scenario": scenario, "training_rows": len(frame), "mode": "custom",
    })
    from .tags import build_tags, stamp_model
    stamp_model(model_output, build_tags(scenario))
