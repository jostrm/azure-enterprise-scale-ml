"""Compile approved source bindings into per-model Azure ML factory artifacts offline."""

import argparse
from copy import deepcopy
from pathlib import Path

from azure_esml import ESMLProject, LakeSettings
from azure_esml.domain_layer.rollout import AzureMLRollout, SCENARIO_NUMBERS, model_from_scenario
from ml_model_factory.config import load_json, write_json


def prepare(config_path: Path, scenarios: Path, output: Path) -> dict:
    config = load_json(config_path)
    if config.get("schema") != "esml.azureml-rollout-config/v1":
        raise ValueError("Expected esml.azureml-rollout-config/v1 configuration")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new rollout output directory; do not overwrite earlier execution receipts")
    models, catalog = [], []
    chosen = config["scenarios"]
    if not isinstance(chosen, dict) or not chosen or set(chosen) - set(SCENARIO_NUMBERS):
        raise ValueError("Choose explicit known scenarios with reviewed source bindings")
    for name, number in SCENARIO_NUMBERS.items():
        scenario = load_json(Path(scenarios) / f"{name}.json")
        row = {"scenario": name, "model_number": number, "model_alias": f"M{number:02d}",
               "task": scenario["task"], "dataset_status": scenario["dataset"].get("status"),
               "selected": name in chosen}
        if name in chosen:
            source = chosen[name]
            if scenario["dataset"].get("status") in ("required-selection", "license-review", "requires-license-review"):
                raise ValueError(f"{name}: resolve the existing dataset selection/license gate first")
            if scenario["task"].startswith("image_"):
                raise ValueError(f"{name}: vision needs its ESML task-specific adapter; no tabular fallback")
            model = model_from_scenario(scenario, input_path=source["input_path"], compute=source["compute"])
            if source["mode"] == "automl":
                model["evaluation_environment"] = config["automl_evaluation_environment"]
                model["inference_environment"] = config["automl_evaluation_environment"]
                model["inference_mode"] = "automl"
            if "environment" in source:
                model["environment"] = source["environment"]
            if source.get("limits"):
                model.setdefault("automl", {})["limits"] = source["limits"]
            models.append(model)
            row.update(mode=source["mode"], compute=source["compute"], status="prepared_not_submitted")
        else:
            row["status"] = "not_selected"
        catalog.append(row)
    settings = {
        "schema": "esml.lake-settings/v2", "aifactory": config["aifactory"],
        "project_number": config["project_number"], "project_folder_name": f"project{config['project_number']:03d}",
        "active_model": models[0]["model_number"], "models": models,
        "runtime": deepcopy(config["runtime"]), "storage": deepcopy(config["storage"]),
        "use_common_datalake_storage": config["use_common_datalake_storage"],
        "storage_targets": deepcopy(config["storage_targets"]),
    }
    project = ESMLProject(LakeSettings.from_dict(settings, base_path=config_path.resolve().parent))
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "lake_settings.local.json", settings)
    write_json(output / "scenario-catalog.json", {"scenarios": catalog, "databricks_in_scope": False})
    rollout = AzureMLRollout(project, output / "runs")
    requests = []
    for name, source in chosen.items():
        request = rollout.prepare(model_number=SCENARIO_NUMBERS[name], mode=source["mode"],
                                  data_date_utc=config["data_date_utc"], run_id=source["run_id"],
                                  data_version=source["data_version"])
        requests.append(request)
    summary = {"schema": "esml.azureml-rollout-preview/v1", "target": config["runtime"],
               "requests": requests, "source_settings": str(output / "lake_settings.local.json"),
               "storage": project.settings.storage, "cloud_submitted": False, "models_registered": False,
               "deployment_strategy": "Explicit pipeline-component batch endpoints after passing training gates",
               "unselected": [row for row in catalog if not row["selected"]]}
    write_json(output / "preview.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import json
    print(json.dumps(prepare(args.config, args.scenarios, args.output), indent=2))


if __name__ == "__main__":
    main()
