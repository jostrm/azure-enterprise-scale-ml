from pathlib import Path

import pandas as pd

from azure_esml import ESMLProject, LakeSettings, PipelineRequest, PipelineType
from azure_esml.base_layer.tables import read_table
from azure_esml.domain_layer.runtime import TabularDataSteps
from azure_esml.domain_layer.shareback import SilverShareback
from azure_esml.domain_layer.shared_lake import SharedLake
from ml_model_factory.config import load_json, write_json


ROOT = Path(__file__).resolve().parents[1]


def test_real_project_silver_shareback_selection_to_separate_gold(tmp_path):
    from test_esml_end_to_end import local_commands
    lake = tmp_path / "lake"
    layout = SharedLake("example-factory", "dev")
    catalog = SilverShareback(lake, layout)
    scenario = {"name": "customers", "task": "classification", "target": "y", "features": ["age"],
                "dataset": {"provider": "lake", "kind": "dataset"}}
    for producer, ages in (("003", [23, 31, 45]), ("004", [24, 32, 46])):
        source_key = f"mlops/v1/projects/project{producer}/environments/dev/usecases/customers/dataops/runs/refine-v1/silver"
        source = tmp_path / f"raw-{producer}"
        source.mkdir()
        pd.DataFrame({"age": ages, "y": [0, 1, 1]}).to_csv(source / "data.csv", index=False)
        scope = {"aifactory": layout.aifactory, "environment": "dev", "project": producer}
        steps = TabularDataSteps({"scenario": scenario, "tags": scope,
                                 "request": {"pipeline_type": "IN_2_GOLD", "run_id": "refine-v1", "scope": scope},
                                 "dataset": {"format": "csv"}, "table_format": "delta", "bronze_mode": "raw"})
        bronze = tmp_path / f"bronze-{producer}"
        steps.convert("in2bronze", {"data": source}, bronze)
        steps.convert("bronze2silver", {"data": bronze}, lake / source_key)
        catalog.publish(dataset="customers", producer_project=producer, variation="clean",
                        version="v1", source_key=source_key, table_relative="", owner=f"team-{producer}",
                        allowed_projects=["005"])
    variations = catalog.list_variations("customers", consumer_project="005")
    assert {item["producer_project"] for item in variations} == {"003", "004"}
    for product in variations:
        assert len(list((lake / product["key"]).rglob("*.parquet"))) == 0
    document = load_json(ROOT / "examples" / "app_layer" / "lake_settings.json")
    document.update(project_number=5, project_folder_name="project005")
    document["models"][0].update(model_folder_name="customers", use_case="customers", model_name="customers",
                                 dataset_folder_names=["customers"], features=["age"], label="y",
                                 source={"provider": "lake", "kind": "dataset"})
    project = ESMLProject(LakeSettings.from_dict(document)).with_shared_silver(
        catalog, dataset="customers", producer_project="004", variation="clean", version="v1")
    plan = project.create_pipeline(PipelineType.IN_2_GOLD, PipelineRequest("2026-09-14", "consumer-v1"),
                                   output=tmp_path / "job")
    assert list(plan.document["jobs"]) == ["merge"]
    selected = catalog.resolve("customers", "004", "clean", "v1", consumer_project="005")
    outputs = local_commands(plan, {"raw_customers": str(lake / selected["table_key"])}, tmp_path / "execution")
    gold, _ = read_table(outputs["gold"])
    assert gold["age"].tolist() == [24, 32, 46]
    assert outputs["gold"] != lake / selected["table_key"]
    assert load_json(outputs["gold"] / "lineage.json")["medallion_stage"] == "gold"
    binding = catalog.onboard_reference("customers", "004", "clean", "v1",
                                       consumer_project="005", consumer_version="selected-v1")
    assert sorted(path.name for path in (lake / binding["key"]).iterdir()) == ["_SUCCESS.json", "silver-binding.json"]
    from azure_esml.cli import main
    write_json(tmp_path / "settings.json", {"aifactory": layout.aifactory, "environment": layout.environment})
    write_json(tmp_path / "request.json", {"dataset": "customers", "producer_project": "004", "variation": "clean",
                                          "version": "v1", "consumer_project": "005"})
    assert main(["resolve-silver", "--root", str(lake), "--settings", str(tmp_path / "settings.json"),
                 "--request", str(tmp_path / "request.json"), "--output", str(tmp_path / "resolved.json")]) == 0
    assert load_json(tmp_path / "resolved.json")["table_key"] == selected["table_key"]
