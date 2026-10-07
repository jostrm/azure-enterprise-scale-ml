"""Use-case catalog: serving pattern x task x technology routes, status and examples.

The folder tree under ``usecase-type`` is navigation; this catalog is the source of
truth for what each leaf implements, which shared engines it reuses, its
prerequisites and its honest limitations. Generated leaf notebooks and README
status sections are derived from it, and tests compare them with checked-in files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


PATTERNS = ("batch", "online", "streaming")
PATTERN_SUMMARY = {
    "batch": "bounded scoring of many requests into stored predictions",
    "online": "request/response scoring through an endpoint",
    "streaming": "continuous or micro-batch scoring of arriving events",
}
TASK_FOLDERS = {
    "classification": "classification",
    "regression": "regression",
    "timeseries-forecasting": "forecasting",
    "computer-vision/multi-class": "image_classification",
    "computer-vision/multi-label": "image_classification_multilabel",
    "computer-vision/object-detection": "image_object_detection",
    "computer-vision/instance-segmentation": "image_instance_segmentation",
}
TASK_FOLDER_BY_TASK = {task: folder for folder, task in TASK_FOLDERS.items()}


@dataclass(frozen=True)
class Technology:
    key: str
    short: str
    mode: str
    title: str
    engine: str


TECHNOLOGIES = (
    Technology("notebook", "custom", "custom", "custom notebook (local shared engine)", "local"),
    Technology("azure-automl/notebook", "automl", "automl", "Azure ML AutoML notebook", "azureml"),
    Technology("azure-automl/azureml-pipeline-with-automl-step", "automl-pipeline", "automl",
               "Azure ML pipeline with an AutoML step", "pipeline"),
    Technology("azureml-pipeline", "custom-pipeline", "custom", "Azure ML pipeline with custom training", "pipeline"),
    Technology("databricks-notebook", "databricks", "custom", "Databricks job with shared notebooks", "databricks"),
    Technology("databricks-azureml-pipeline-step", "databricks-aml-step", "custom",
               "Azure ML pipeline running Databricks steps", "azureml-databricks"),
)
TECHNOLOGY_BY_KEY = {technology.key: technology for technology in TECHNOLOGIES}


def task_family(task: str) -> str:
    if task.startswith("image_"):
        return "vision"
    return "forecasting" if task == "forecasting" else "tabular"


def uses_esml(technology: Technology, task: str) -> bool:
    """Tabular/forecasting pipeline leaves reuse the ESML pipeline factory (medallion IN_2_GOLD)."""
    return technology.engine == "pipeline" and task_family(task) != "vision"


@dataclass(frozen=True)
class UseCase:
    pattern: str
    task_folder: str
    technology: Technology
    supported: bool
    reason: str | None = None

    @property
    def task(self) -> str:
        return TASK_FOLDERS[self.task_folder]

    @property
    def family(self) -> str:
        return task_family(self.task)

    @property
    def mode(self) -> str:
        return self.technology.mode

    @property
    def esml(self) -> bool:
        return uses_esml(self.technology, self.task)

    @property
    def folder(self) -> PurePosixPath:
        return PurePosixPath("usecase-type", self.pattern, self.task_folder, *self.technology.key.split("/"))

    @property
    def run_key(self) -> str:
        """Isolated output folder; batch leaves keep their historical custom/automl folders."""
        return self.technology.short if self.pattern == "batch" else f"{self.pattern}-{self.technology.short}"

    def notebook_name(self, scenario_name: str) -> str:
        return f"{scenario_name}-{self.technology.short}.ipynb"

    @property
    def training(self) -> str:
        engine, mode = self.technology.engine, self.mode
        if engine == "local":
            return ("Local custom training and held-out evaluation with the shared engine; the same scenario renders "
                    "as a quality-gated Azure ML v2 pipeline before registration.")
        if engine == "azureml":
            if self.family == "vision":
                return ("AutoML image training through the factory renderer: a quality-gated pipeline when prepared "
                        "images are lake-bound, otherwise a standalone training job.")
            return "AutoML through the factory renderer's quality-gated Azure ML v2 pipeline (prepare, AutoML, evaluate)."
        if engine == "pipeline":
            if self.esml:
                kind = "IN_2_GOLD_TRAINING_AUTOML" if mode == "automl" else "IN_2_GOLD_TRAINING_MANUAL"
                return (f"ESML pipeline factory `{kind}` (medallion lake, data assets, quality-gated evaluation) "
                        "driven by AzureMLRollout receipts.")
            step = "AutoML image" if mode == "automl" else "custom torchvision"
            return f"Factory Azure ML v2 pipeline with a {step} training step and the vision quality gate."
        if engine == "databricks":
            return "Databricks job task `train-evaluate` running the shared accelerator notebook on an existing cluster."
        return ("Azure ML pipeline whose command steps run the existing Databricks job tasks with managed identity "
                "and pass the evaluated MLflow model URI between steps.")

    @property
    def serving(self) -> str:
        engine, pattern = self.technology.engine, self.pattern
        if engine == "databricks":
            return {
                "batch": "Databricks task `batch-score`: Spark scoring of a Unity Catalog table into a Delta table.",
                "online": "Databricks task `register-serve`: Unity Catalog registration and a Model Serving endpoint.",
                "streaming": "Databricks task `stream-score`: Event Hubs (Kafka) Structured Streaming into Delta.",
            }[pattern]
        if engine == "azureml-databricks":
            return {
                "batch": "The second pipeline step runs the Databricks `batch-score` task.",
                "online": "The second pipeline step runs the Databricks `register-serve` task (Model Serving).",
                "streaming": "The second pipeline step starts the Databricks `stream-score` task.",
            }[pattern]
        local = engine == "local"
        if pattern == "batch":
            if self.esml:
                return ("ESML GOLD_INFERENCE plan published as a pipeline-component batch endpoint, or submitted as a "
                        "pipeline job, writing predictions to the lake.")
            prefix = "Local `score` of unlabeled requests; " if local else ""
            return prefix + "Azure ML batch endpoint (no-code MLflow) or factory scoring pipeline job via `serving-render`."
        if pattern == "online":
            prefix = "Local `online-test` contract check; " if local else ""
            return prefix + "Azure ML managed online endpoint via `serving-render`, `serving-deploy` and `serving-invoke`."
        prefix = "Local JSONL `stream-score` simulation and optional Event Hubs consumer; " if local else ""
        return prefix + "Azure ML scheduled micro-batch job (`stream-job`) reading Event Hubs with lake checkpoints."

    @property
    def prerequisites(self) -> tuple[str, ...]:
        engine, family = self.technology.engine, self.family
        items = ["Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved."]
        if engine in ("local", "azureml", "pipeline"):
            items.append("Install the factory extras `train` (plus `vision` for images, `azure` for Azure ML steps and "
                         "`streaming` for Event Hubs consumers).")
        if engine in ("local", "azureml", "pipeline", "azureml-databricks"):
            items.append("For Azure steps: `user-config/runtime.local.json` naming an existing workspace, compute, "
                         "identity and storage selection.")
        if self.esml:
            items.append("`user-config/esml-rollout.local.json` with a reviewed source binding for this scenario and "
                         "pinned Azure ML environments; the ESML SDK is imported from `esml-v2` or azure-esml-sdk.")
        if family == "vision" and engine in ("local", "azureml", "pipeline"):
            items.append("Image training in Azure needs `gpu_compute`, or `vision.device: cpu` for the small custom example.")
        if family == "vision" and self.mode == "automl":
            items.append("AutoML images need lake-bound prepared images (`runtime.lake` with a datastore) and a pinned "
                         "`automl_vision_environment` for evaluation and scoring.")
            if self.pattern == "streaming":
                items.append("AutoML image streaming needs a pinned `streaming_environment` with the AutoML image runtime "
                             "plus azure-eventhub and azure-identity.")
        if self.esml and self.mode == "automl" and family == "forecasting":
            items.append("ESML AutoML forecast inference needs `inference_history_path` (observed history in the lake) "
                         "in the scenario's reviewed rollout binding.")
        if self.mode == "automl":
            items.append("AutoML models are scored in Azure with an AutoML-compatible environment, not in the local venv.")
        if engine in ("databricks", "azureml-databricks"):
            items.append("An existing Databricks workspace and cluster with the shared notebooks and factory wheel "
                         "imported; Unity Catalog objects and permissions per `user-config/databricks`.")
        if engine == "azureml-databricks":
            items.append("An Azure ML compute identity allowed to run the existing Databricks job (no PAT tokens).")
        if self.pattern == "online":
            items.append("Endpoint quota; deployed endpoints bill while running, so delete or scale them to zero when done.")
        if self.pattern == "streaming":
            items.append("An Event Hubs namespace, hub and consumer group, Data Receiver RBAC for the consumer identity, "
                         "and durable checkpoint storage.")
        return tuple(items)

    @property
    def limitations(self) -> tuple[str, ...]:
        if not self.supported:
            return (self.reason,)
        engine, family = self.technology.engine, self.family
        items = []
        if self.pattern == "streaming" and engine in ("local", "azureml", "pipeline"):
            items.append("Azure ML streaming is scheduled micro-batching: latency follows the schedule interval, not "
                         "continuous event-at-a-time scoring.")
        if self.pattern == "streaming" and family == "vision":
            items.append("Base64 image events must respect Event Hubs message size limits; large images need storage URI "
                         "references and a reviewed adapter.")
        if family == "forecasting" and self.mode == "custom":
            items.append("The custom seasonal-naive baseline only forecasts timestamps inside its fitted horizon window.")
        if family == "forecasting" and self.mode == "automl":
            items.append("AutoML forecasting needs observed history with each scoring request (history.parquet or the "
                         "request's history block).")
        if self.esml and self.pattern == "batch":
            items.append("Pipeline-component batch invocation failed with an unresolved service URI error in the paused "
                         "Dev rollout; submit the same inference plan as a pipeline job if invocation is unavailable.")
        if engine in ("databricks", "azureml-databricks"):
            items.append("Databricks models live in Databricks MLflow/Unity Catalog, not in the Azure ML registry.")
        if self.mode == "automl" and family == "vision":
            items.append("The AutoML image adapter follows Microsoft's documented scoring schema; it has not been executed "
                         "against a real AutoML artifact in this repository.")
        items.append("Templates are not evidence of a completed Kaggle, Azure or Databricks run.")
        return tuple(items)

    @property
    def status(self) -> str:
        if not self.supported:
            return "Not supported for this combination; see the reason and the supported alternative."
        if self.technology.engine == "local":
            return ("Executable notebook templates: local steps run offline after data approval; cloud steps are "
                    "explicit, charged operations behind switches that default to false.")
        return ("Executable notebook templates over shared engines; cloud steps are explicit, charged operations "
                "behind switches that default to false and need the listed prerequisites.")


def _support(pattern: str, technology: Technology, task: str) -> tuple[bool, str | None]:
    if pattern == "streaming" and technology.mode == "automl" and task == "forecasting":
        return False, ("AutoML forecast() needs observed history aligned with every request, which event streams do not "
                       "carry. Use streaming/timeseries-forecasting/notebook (custom seasonal-naive model), or AutoML "
                       "batch/online scoring with explicit history.")
    return True, None


def catalog() -> tuple[UseCase, ...]:
    leaves = []
    for pattern in PATTERNS:
        for folder, task in TASK_FOLDERS.items():
            for technology in TECHNOLOGIES:
                supported, reason = _support(pattern, technology, task)
                leaves.append(UseCase(pattern, folder, technology, supported, reason))
    return tuple(leaves)


def find(pattern: str, task_folder: str, technology: str) -> UseCase:
    for leaf in catalog():
        if (leaf.pattern, leaf.task_folder, leaf.technology.key) == (pattern, task_folder, technology):
            return leaf
    raise ValueError(f"Unknown use case {pattern}/{task_folder}/{technology}")


def scenarios_by_task(scenarios_dir: Path) -> dict[str, list[dict]]:
    from .config import load_json, validate_scenario

    result: dict[str, list[dict]] = {task: [] for task in TASK_FOLDERS.values()}
    for path in sorted(Path(scenarios_dir).glob("*.json")):
        scenario = validate_scenario(load_json(path))
        if scenario["name"] != path.stem:
            raise ValueError(f"Scenario file name must equal its name: {path.name}")
        result[scenario["task"]].append(scenario)
    return result


def describe(leaf: UseCase, scenarios: list[dict] | None = None) -> dict:
    result = {
        "folder": leaf.folder.as_posix(), "pattern": leaf.pattern, "task": leaf.task, "technology": leaf.technology.key,
        "mode": leaf.mode, "supported": leaf.supported, "status": leaf.status, "training": leaf.training,
        "serving": leaf.serving, "prerequisites": list(leaf.prerequisites), "limitations": list(leaf.limitations),
    }
    if scenarios is not None:
        result["notebooks"] = [leaf.notebook_name(item["name"]) for item in scenarios] if leaf.supported else []
    return result


def _list_command(args):
    from .layout import source_root

    root = source_root(args.source)
    scenarios = scenarios_by_task(root / "user-config" / "model" / "scenarios")
    leaves = [leaf for leaf in catalog() if args.pattern in (None, leaf.pattern)
              and args.task_folder in (None, leaf.task_folder) and args.technology in (None, leaf.technology.key)]
    return {"leaves": [describe(leaf, scenarios[leaf.task]) for leaf in leaves],
            "supported": sum(leaf.supported for leaf in leaves), "total": len(leaves)}


def _examples_command(args):
    from .examples import render_all

    result = render_all(args.source, write=args.write)
    if not args.write and result["stale"]:
        raise ValueError("Generated use-case files are stale; rerun with --write and review the diff: "
                         + ", ".join(result["stale"][:20]))
    return result


def add_commands(commands) -> None:
    listing = commands.add_parser("usecases", help="List use-case leaves, routes, status and limitations")
    listing.add_argument("--pattern", choices=PATTERNS)
    listing.add_argument("--task-folder", choices=tuple(TASK_FOLDERS))
    listing.add_argument("--technology", choices=tuple(TECHNOLOGY_BY_KEY))
    listing.add_argument("--source", type=Path, help="Template checkout root (auto-detected inside a checkout)")
    listing.set_defaults(handler=_list_command)
    examples = commands.add_parser("usecase-examples", help="Check (default) or rewrite generated leaf notebooks/READMEs")
    examples.add_argument("--source", type=Path, help="Template checkout root (auto-detected inside a checkout)")
    examples.add_argument("--write", action="store_true", help="Rewrite generated files instead of only checking them")
    examples.set_defaults(handler=_examples_command)
