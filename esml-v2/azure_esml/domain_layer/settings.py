"""ESML mapping configuration; loading never provisions resources or changes state."""

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
from string import Formatter

from ml_model_factory.config import load_json
from ml_model_factory.lake import identifier, relative_key


ENVIRONMENTS = ("dev", "test", "prod")


@dataclass(frozen=True)
class DatasetSettings:
    name: str
    input_path: str | None = None
    format: str = "parquet"
    required_columns: tuple[str, ...] = ()
    source_stage: str = "in"
    delta_version: int | None = None

    def __post_init__(self):
        identifier(self.name, "dataset")
        if self.format not in ("csv", "parquet", "delta"):
            raise ValueError("Dataset format must be csv, parquet or delta; use a custom component for other formats")
        if self.source_stage not in ("in", "silver"):
            raise ValueError("source_stage must be in or an explicitly bound shared silver")
        if self.source_stage == "silver" and (self.format == "csv" or self.input_path is None):
            raise ValueError("Shared silver requires an explicit analytical-table input_path")
        if self.delta_version is not None and (type(self.delta_version) is not int or self.delta_version < 0):
            raise ValueError("delta_version must pin a nonnegative Delta transaction version")
        if self.input_path is not None:
            if not isinstance(self.input_path, str):
                raise ValueError("Dataset input_path must be a relative path template")
            allowed = {"data_version", "data_date_utc", "date_folder", "run_id", "model_version",
                       "environment", "project_folder", "model_folder", "dataset"}
            for _, name, spec, conversion in Formatter().parse(self.input_path):
                if name is not None and (name not in allowed or spec or conversion):
                    raise ValueError(f"Unsupported input_path placeholder: {name}")
            relative_key(self.input_path.format(**{name: "value" for name in allowed}).rstrip("/"))
        if any(not isinstance(value, str) or not value.strip() for value in self.required_columns):
            raise ValueError("Dataset required_columns must be nonempty strings")


@dataclass(frozen=True)
class ModelSettings:
    number: int
    folder: str
    alias: str
    datasets: tuple[DatasetSettings, ...]
    task: str
    label: str
    features: tuple[str, ...]
    options: dict = field(repr=False)

    @property
    def use_case(self) -> str:
        return self.options.get("use_case", self.folder)

    def scenario(self) -> dict:
        result = {
            "name": self.use_case, "model_name": self.options.get("model_name", self.folder),
            "task": self.task, "target": self.label, "features": list(self.features),
            "dataset": deepcopy(self.options.get("source", {"provider": "lake", "kind": "dataset"})),
        }
        for key in ("categorical_features", "sensitive_features", "split", "forecast", "vision", "custom", "quality", "automl"):
            if key in self.options:
                result[key] = deepcopy(self.options[key])
        if "automl" not in result and self.options.get("ml_metric"):
            result["automl"] = {"primary_metric": self.options["ml_metric"]}
        return result


@dataclass(frozen=True)
class LakeSettings:
    aifactory: str
    project: str
    project_folder: str
    active_model: int
    models: tuple[ModelSettings, ...]
    storage: dict = field(repr=False)
    runtime: dict = field(repr=False)
    base_path: Path = field(repr=False)

    @classmethod
    def load(cls, path: str | Path, *, overrides: dict | None = None):
        path = Path(path).resolve()
        document = load_json(path)
        for key, value in (overrides or {}).items():
            if key in ("storage", "runtime"):
                document[key] = {**document.get(key, {}), **deepcopy(value)}
            else:
                document[key] = deepcopy(value)
        return cls.from_dict(document, base_path=path.parent)

    @classmethod
    def from_dict(cls, document: dict, *, base_path: Path | None = None):
        if not isinstance(document, dict):
            raise ValueError("lake_settings must be an object")
        if document.get("schema", "esml.lake-settings/v2") != "esml.lake-settings/v2":
            raise ValueError("Unsupported lake_settings schema")
        number = document.get("project_number")
        if isinstance(number, str) and re.fullmatch(r"\d{3}", number):
            number = int(number)
        if type(number) is not int or not 1 <= number <= 999:
            raise ValueError("project_number must be an integer from 1 to 999")
        project = f"{number:03d}"
        folder = document.get("project_folder_name", f"project{project}")
        if folder != f"project{project}":
            raise ValueError("project_folder_name must agree with project_number")
        factory = identifier(document.get("aifactory"), "aifactory")
        storage, runtime = document.get("storage"), document.get("runtime")
        if not isinstance(storage, dict) or not isinstance(runtime, dict):
            raise ValueError("Explicit storage and runtime mappings are required; legacy mapping alone is not connectivity")
        identifier(storage.get("datastore"), "datastore")
        if storage.get("input_area", "landing") not in ("landing", "in"):
            raise ValueError("storage.input_area must be landing or in")
        prefix = relative_key(storage.get("prefix", "mlops/v1"))
        if prefix == "projects" or prefix.startswith("projects/"):
            raise ValueError("New outputs require a versioned namespace, not the legacy projects root")
        if runtime.get("environment_name") not in ENVIRONMENTS:
            raise ValueError("runtime.environment_name must be dev, test or prod")
        from azure_esml.base_layer.contracts import WorkspaceTarget
        WorkspaceTarget(**{key: runtime.get(key) for key in (
            "tenant_id", "subscription_id", "resource_group", "workspace_name",
        )})
        identifier(runtime.get("compute"), "compute")
        environment = runtime.get("environment")
        if not isinstance(environment, str) or not re.fullmatch(r"azureml:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", environment):
            raise ValueError("runtime.environment must pin an existing Azure ML environment name and version")
        if environment.rsplit(":", 1)[1].lower() in ("latest", "active"):
            raise ValueError("runtime.environment must be an immutable version")
        models = []
        entries = document.get("models")
        if not isinstance(entries, list) or not entries:
            raise ValueError("lake_settings.models must be a nonempty list")
        for entry in entries:
            if not isinstance(entry, dict) or type(entry.get("model_number")) is not int or entry["model_number"] < 1:
                raise ValueError("Every model needs a positive model_number")
            model_folder = identifier(entry.get("model_folder_name"), "model_folder")
            alias = identifier(entry.get("model_short_alias", f"M{entry['model_number']}"), "model_alias")
            use_case = identifier(entry.get("use_case", model_folder), "use_case")
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", use_case):
                raise ValueError("use_case must be a lowercase lake identifier of 2-63 characters")
            names = entry.get("dataset_folder_names", [])
            if (not isinstance(names, list) or any(not isinstance(name, str) for name in names)
                    or len(names) != len(set(names))):
                raise ValueError("dataset_folder_names must contain unique folder names")
            options = entry.get("datasets", {})
            if (not isinstance(options, dict) or set(options) - set(names)
                    or any(not isinstance(option, dict) for option in options.values())):
                raise ValueError("datasets overrides must refer to configured dataset_folder_names")
            for override in options.values():
                columns = override.get("required_columns", [])
                if not isinstance(columns, list):
                    raise ValueError("Dataset required_columns must be a list")
            source = entry.get("source", {"provider": "lake", "kind": "dataset"})
            if not isinstance(source, dict) or source.get("provider") not in ("lake", "kaggle"):
                raise ValueError("source must explicitly describe mapped lake or Kaggle data")
            for key in ("merge", "split", "custom", "automl", "quality"):
                if key in entry and not isinstance(entry[key], dict):
                    raise ValueError(f"Model {key} must be a JSON object")
            datasets = tuple(DatasetSettings(
                name=name, input_path=options.get(name, {}).get("input_path"),
                format=options.get(name, {}).get("format", entry.get("input_format", "parquet")),
                required_columns=tuple(options.get(name, {}).get("required_columns", [])),
                source_stage=options.get(name, {}).get("source_stage", "in"),
                delta_version=options.get(name, {}).get("delta_version"),
            ) for name in names)
            if not datasets and not entry.get("discover_datasets"):
                raise ValueError("Configure dataset_folder_names or explicitly enable discover_datasets")
            task = entry.get("ml_type")
            if task not in ("classification", "regression", "forecasting"):
                raise ValueError("Built-in ESML tabular pipelines support classification, regression and forecasting")
            label = entry.get("label")
            features = entry.get("features", [])
            if not isinstance(label, str) or not label.strip():
                raise ValueError("Every model needs an explicit label")
            if (not isinstance(features, list) or any(not isinstance(value, str) or not value for value in features)
                    or len(features) != len(set(features)) or label in features):
                raise ValueError("features must be unique column names excluding the label")
            for flag in ("discover_datasets", "bronze"):
                if flag in entry and type(entry[flag]) is not bool:
                    raise ValueError(f"{flag} must be a JSON boolean")
            for format_key in ("table_format", "aml_table_format"):
                if entry.get(format_key, "delta") not in ("delta", "parquet"):
                    raise ValueError(f"{format_key} must be delta or parquet; no silent format fallback")
            if entry.get("bronze_mode", "raw") not in ("raw", "normalized"):
                raise ValueError("bronze_mode must be raw or explicitly normalized for legacy compatibility")
            models.append(ModelSettings(entry["model_number"], model_folder, alias, datasets, task,
                                        label, tuple(features), deepcopy(entry)))
        for values in ([model.number for model in models], [model.folder for model in models],
                       [model.alias.casefold() for model in models], [model.use_case for model in models]):
            if len(values) != len(set(values)):
                raise ValueError("Model numbers, folders, aliases and use cases must be unique")
        active = document.get("active_model")
        if type(active) is not int or active not in [model.number for model in models]:
            raise ValueError("active_model must select a configured model_number")
        return cls(factory, project, folder, active, tuple(models), deepcopy(storage), deepcopy(runtime),
                   Path(base_path or Path.cwd()).resolve())

    def model(self, number: int | None = None) -> ModelSettings:
        selected = self.active_model if number is None else number
        if type(selected) is not int:
            raise ValueError("Select a model by its integer model_number")
        for model in self.models:
            if model.number == selected:
                return model
        raise ValueError(f"Model {selected!r} is not configured in this project")

    @property
    def scope(self) -> dict[str, str]:
        return {"aifactory": self.aifactory, "project": self.project,
                "environment": self.runtime["environment_name"]}
