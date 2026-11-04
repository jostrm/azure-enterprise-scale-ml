from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from azure_esml.domain_layer.lake_seed import stage_kaggle_examples
from ml_model_factory.config import write_json, load_json
from ml_model_factory.data import sha256


def test_seed_creates_real_master_in_bronze_silver_and_disjoint_gold(tmp_path):
    sources, scenarios, root = (tmp_path / name for name in ("sources", "scenarios", "lake"))
    source = sources / "sample" / "sample.csv"
    source.parent.mkdir(parents=True)
    pd.DataFrame({"x": list(range(60)), "y": [index % 2 for index in range(60)]}).to_csv(source, index=False)
    declared = {"provider": "kaggle", "kind": "dataset", "slug": "fixture/sample", "version": 1,
                "file": "sample.csv", "license": "CC0"}
    write_json(source.parent / "provenance.json", {**declared, "files": {"sample.csv": sha256(source)}})
    write_json(scenarios / "sample.json", {"name": "sample", "task": "classification", "features": ["x"],
                                         "target": "y", "dataset": declared})
    config = {"schema": "esml.shared-lake-bootstrap/v2", "aifactory": "example", "environment": "dev",
              "project": "001", "storage": {"account_url": "https://examplelake.blob.core.windows.net",
                                            "container": "lake3", "datastore": "lake"},
              "datasets": [{"scenario": "sample", "dataset": "sample", "file": "sample.csv"}]}
    result = stage_kaggle_examples(config, source_root=sources, scenario_root=scenarios, root=root, version="v1")
    assert not result["azure_written"]
    assert result["plan"]["files"] > 10
    sample = result["samples"][0]
    assert (root / sample["project_in"] / "sample.csv").is_file()
    assert sum(sample["split_rows"].values()) == 60
    from azure_esml.base_layer.tables import read_table
    split_ids = [set(read_table(root / sample["gold"] / split)[0]["x"])
                 for split in ("train", "validation", "test")]
    assert (root / sample["gold"] / "train" / "_delta_log").is_dir()
    assert all(not left & right for index, left in enumerate(split_ids) for right in split_ids[index + 1:])
    replay = stage_kaggle_examples(config, source_root=sources, scenario_root=scenarios, root=root, version="v1")
    assert replay["plan"] == result["plan"]
    altered = deepcopy(config)
    altered["datasets"][0]["file"] = "../sample.csv"
    with pytest.raises(ValueError):
        stage_kaggle_examples(altered, source_root=sources, scenario_root=scenarios, root=root, version="v2")


def test_rag_seed_cannot_assert_kaggle_origin_without_pinned_verified_master(tmp_path):
    config = {"schema": "esml.shared-lake-bootstrap/v2", "aifactory": "example", "environment": "dev",
              "project": "001", "storage": {"account_url": "https://examplelake.blob.core.windows.net",
                                            "container": "lake3", "datastore": "lake"},
              "datasets": [], "rag_air_passengers": True}
    with pytest.raises(ValueError, match="verified, pinned"):
        stage_kaggle_examples(config, source_root=tmp_path / "fake-source", scenario_root=tmp_path / "scenarios",
                              root=tmp_path / "lake", version="v1")
