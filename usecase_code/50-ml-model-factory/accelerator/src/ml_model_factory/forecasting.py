"""A leakage-free seasonal-naive baseline with an explicit forecast horizon."""

from pathlib import Path

import mlflow.pyfunc

from .config import write_json
from .data import read_frame


class SeasonalNaive(mlflow.pyfunc.PythonModel):
    def __init__(self, scenario, histories):
        self.scenario = scenario
        self.histories = histories

    def predict(self, context, model_input, params=None):
        import pandas as pd

        forecast = self.scenario["forecast"]
        time = forecast["time_column"]
        series = forecast.get("series_columns", [])
        period = self.scenario.get("custom", {}).get("seasonal_period", 1)
        offset = pd.tseries.frequencies.to_offset(forecast["frequency"])
        results = []
        for _, row in model_input.iterrows():
            key = tuple(str(row[column]) for column in series)
            if key not in self.histories:
                raise ValueError(f"Unseen series {key}; train or explicitly select a cold-start model")
            history, last = self.histories[key]
            requested = pd.Timestamp(row[time])
            future = pd.date_range(pd.Timestamp(last) + offset, periods=2 * forecast["horizon"], freq=offset)
            matches = future.get_indexer([requested])
            step = int(matches[0])
            if step < 0:
                raise ValueError("Timestamp must be after training and within the validation/test horizon")
            results.append(float(history[-period + step % period]))
        return pd.Series(results, index=model_input.index, name="prediction")


def train(scenario: dict, prepared: Path, model_output: Path) -> None:
    import pandas as pd
    from mlflow.models import infer_signature

    algorithm = scenario.get("custom", {}).get("algorithm", "seasonal_naive")
    if algorithm != "seasonal_naive":
        raise ValueError("Custom forecasting currently implements seasonal_naive; use AutoML for fitted forecasting")
    frame = read_frame(Path(prepared) / "train")
    forecast = scenario["forecast"]
    series, time = forecast.get("series_columns", []), forecast["time_column"]
    period = scenario.get("custom", {}).get("seasonal_period", 1)
    if not isinstance(period, int) or period < 1:
        raise ValueError("seasonal_period must be a positive integer")
    groups = frame.groupby(series, dropna=False) if series else [((), frame)]
    histories = {}
    for key, group in groups:
        group = group.sort_values(time)
        if len(group) < period:
            raise ValueError("Each series needs at least seasonal_period training rows")
        key = key if isinstance(key, tuple) else (key,)
        histories[tuple(str(value) for value in key)] = (
            group[scenario["target"]].tail(period).tolist(), group[time].iloc[-1].isoformat(),
        )
    model = SeasonalNaive(scenario, histories)
    sample = read_frame(Path(prepared) / "validation").loc[:, list(dict.fromkeys(scenario["features"] + series + [time]))].head(5)
    sample[time] = pd.to_datetime(sample[time])
    mlflow.pyfunc.save_model(
        str(model_output), python_model=model,
        signature=infer_signature(sample, model.predict(None, sample)), input_example=sample,
        code_paths=[str(Path(__file__).parent)],
        pip_requirements=["mlflow-skinny>=2.22,<3", "pandas>=2.2,<3", "PyYAML>=6,<7", "pyarrow>=18,<24"],
    )
    write_json(Path(model_output) / "factory.json", {"scenario": scenario, "mode": "custom", "baseline": True})
    from .tags import build_tags, stamp_model
    stamp_model(model_output, build_tags(scenario))
