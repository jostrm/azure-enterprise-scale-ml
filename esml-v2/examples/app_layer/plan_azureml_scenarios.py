"""Compile approved source bindings into per-model Azure ML factory artifacts offline."""

import argparse
from pathlib import Path

from azure_esml import ESMLProject, LakeSettings
from azure_esml.domain_layer.rollout import AzureMLRollout, SCENARIO_NUMBERS, settings_from_rollout_config
from ml_model_factory.config import load_json, write_json


def prepare(config_path: Path, scenarios: Path, output: Path) -> dict:
    config = load_json(config_path)
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new rollout output directory; do not overwrite earlier execution receipts")
    # The package compiles and gates bindings; this AppLayer script only writes the reviewed preview.
    settings, catalog = settings_from_rollout_config(config, scenarios)
    chosen = config["scenarios"]
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
