"""Stage verified Kaggle examples for a reviewed, separate Azure publication."""

from pathlib import Path
from copy import deepcopy
import shutil
import tempfile

from ml_model_factory.config import load_json, write_json
from ml_model_factory.lake import identifier, local_key_path
from ml_model_factory.lake_flow import finish, publication, verified_manifest

from .shared_lake import SharedLake
from .lake_publication import publication_plan


def stage_kaggle_examples(config: dict, *, source_root: Path, scenario_root: Path,
                         root: Path, version: str) -> dict:
    from .lake_ingestion import SharedLakeIngestion
    from .runtime import TabularDataSteps
    from ml_model_factory.storage_selection import resolve_storage_selection
    config = resolve_storage_selection(config)

    if config.get("schema") != "esml.shared-lake-bootstrap/v2":
        raise ValueError("Use a shared-lake-bootstrap/v2 configuration")
    identifier(version, "version")
    layout = SharedLake(config["aifactory"], config["environment"], config.get("prefix", "mlops/v1"))
    project = config["project"]
    layout.project(project, "validation", version)
    root, source_root, scenario_root = Path(root).resolve(), Path(source_root).resolve(), Path(scenario_root).resolve()
    if root == source_root or root.is_relative_to(source_root) or source_root.is_relative_to(root):
        raise ValueError("Staging lake and downloaded Kaggle source must be separate")
    loader = SharedLakeIngestion(root, layout)
    table_format = config.get("table_format", "delta")
    aml_table_format = config.get("aml_table_format", table_format)
    if table_format not in ("delta", "parquet") or aml_table_format not in ("delta", "parquet"):
        raise ValueError("Select delta or parquet explicitly; a missing Delta engine is not a silent fallback")
    keys, samples = [], []
    blueprint_key = f"{layout.prefix}/_system/blueprints/{version}"
    blueprint_dir = local_key_path(root, blueprint_key)
    if blueprint_dir.exists():
        verified_manifest(blueprint_dir)
        if load_json(blueprint_dir / "design.json") != layout.blueprint():
            raise ValueError("Blueprint version changed; choose a new version")
    else:
        with publication(root, blueprint_key) as staging:
            write_json(staging / "design.json", layout.blueprint())
            finish(staging, {"kind": "shared-lake-blueprint", "aifactory": layout.aifactory})
    keys.append(blueprint_key)
    for entry in config["datasets"]:
        scenario_name, dataset = identifier(entry["scenario"], "scenario"), identifier(entry["dataset"], "dataset")
        filename = Path(entry["file"])
        if filename.name != str(filename) or filename.name in ("", ".", ".."):
            raise ValueError("Seed dataset file must be a single filename")
        scenario = load_json(scenario_root / (scenario_name + ".json"))
        source = source_root / scenario_name / filename
        provenance = load_json(source.parent / "provenance.json")
        if any(provenance.get(field) != scenario["dataset"].get(field) for field in ("provider", "kind", "slug", "version")):
            raise ValueError("Kaggle provenance differs from the chosen scenario")
        loader.ingest(dataset, version, source, provenance=provenance)
        keys.append(layout.master(dataset, version))
        loader.publish_silver(dataset, version, version, required_columns=scenario["features"] + [scenario["target"]],
                              owner="kaggle-sample-bootstrap", allowed_projects=(project,), table_format=table_format)
        keys.append(layout.product(dataset, version))
        loader.onboard(project, dataset, version, source_version=version, source_kind="master")
        input_key = layout.project(project, dataset, version)
        keys.append(input_key)
        use_case = layout.use_case(project, scenario_name)
        refined_key = f"{use_case}/dataops/runs/{version}"
        refined = local_key_path(root, refined_key)
        step = TabularDataSteps({
            "scenario": scenario, "tags": {"aifactory": layout.aifactory, "project": project, "environment": layout.environment},
            "request": {"pipeline_type": "IN_2_GOLD_TRAINING_MANUAL", "run_id": version},
            "table_format": table_format, "aml_table_format": aml_table_format,
            "bronze_mode": "raw", "require_gold": True,
            "dataset": {"format": filename.suffix.lstrip("."), "required_columns": scenario["features"] + [scenario["target"]]},
        })
        if refined.exists():
            if verified_manifest(refined).get("table_format") != table_format:
                raise ValueError("Refined publication format changed; choose a new version")
        else:
            with publication(root, refined_key) as staging:
                step.convert("in2bronze", {"data": local_key_path(root, input_key + "/in")}, staging / "bronze")
                step.convert("bronze2silver", {"data": staging / "bronze"}, staging / "silver")
                step.merge({"data": staging / "silver"}, staging / "gold")
                finish(staging, {"kind": "sample-dataops", "source": input_key, "table_format": table_format,
                                 "execution": "local-real-transforms"})
        keys.append(refined_key)
        snapshot_key = f"{use_case}/training/snapshots/{version}"
        snapshot = local_key_path(root, snapshot_key)
        if snapshot.exists():
            verified_manifest(snapshot)
            binding = load_json(snapshot / "source-binding.json")
            if (binding.get("scenario") != scenario or binding.get("table_format") != table_format
                    or binding.get("aml_table_format") != aml_table_format):
                raise ValueError("Gold preparation configuration changed; choose a new snapshot version")
        else:
            with publication(root, snapshot_key) as staging:
                step.split({"gold": refined / "gold"}, staging / "compatibility" / "parquet",
                           train=staging / "gold" / "train", validation=staging / "gold" / "validation",
                           test=staging / "gold" / "test")
                write_json(staging / "source-binding.json", {
                    "source": input_key, "refined": refined_key, "scenario": scenario,
                    "table_format": table_format, "aml_table_format": aml_table_format,
                    "purpose": "Kaggle teaching data; not a production model-quality claim",
                })
                finish(staging, {"kind": "training-snapshot", "scenario": scenario_name})
        keys.append(snapshot_key)
        samples.append({"scenario": scenario_name, "dataset": dataset, "project_in": input_key + "/in",
                        "gold": snapshot_key + "/gold", "table_format": table_format,
                        "gold_compatibility": snapshot_key + "/compatibility/parquet",
                        "split_rows": load_json(snapshot / "compatibility" / "parquet" / "manifest.json")["split_rows"]})
    image = config.get("image_dataset")
    if image:
        name, dataset = identifier(image["scenario"], "scenario"), identifier(image["dataset"], "dataset")
        limit = image.get("limit", 24)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Image seed limit must be 1-100 explicitly selected examples")
        source = source_root / name
        provenance = load_json(source / "provenance.json")
        selected = sorted((source / "annotations").glob("*.xml"))[:limit]
        if len(selected) != limit:
            raise ValueError("Not enough paired Kaggle images/annotations for the requested sample")
        import xml.etree.ElementTree as ET
        from ml_model_factory.data import sha256
        with tempfile.TemporaryDirectory(prefix="esml-image-seed-") as temporary:
            subset = Path(temporary)
            for annotation in selected:
                filename = ET.parse(annotation).getroot().findtext("filename")
                if not filename or Path(filename).name != filename:
                    raise ValueError("Kaggle annotation contains an invalid image filename")
                for path, folder in ((annotation, "annotations"), (source / "images" / filename, "images")):
                    relative = folder + "/" + path.name
                    if provenance["files"].get(relative) != sha256(path):
                        raise ValueError("Image or annotation differs from Kaggle provenance")
                    (subset / folder).mkdir(exist_ok=True)
                    shutil.copy2(path, subset / relative)
            loader.ingest(dataset, version, subset, provenance=provenance)
        loader.onboard(project, dataset, version, source_version=version, source_kind="master")
        keys += [layout.master(dataset, version), layout.project(project, dataset, version)]
        from ml_model_factory.vision import prepare_vision
        scenario = load_json(scenario_root / (name + ".json"))
        snapshot_key = layout.use_case(project, name) + f"/training/snapshots/{version}"
        snapshot = local_key_path(root, snapshot_key)
        scenario["vision"]["image_base_uri"] = (
            f"azureml://datastores/{config['storage']['datastore']}/paths/{snapshot_key}/gold"
        )
        if snapshot.exists():
            verified_manifest(snapshot)
            if load_json(snapshot / "source-binding.json").get("scenario") != scenario:
                raise ValueError("Image preparation configuration changed; choose a new snapshot version")
        else:
            with publication(root, snapshot_key) as staging:
                prepare_vision(scenario, local_key_path(root, layout.project(project, dataset, version) + "/in"),
                               staging / "gold")
                write_json(staging / "source-binding.json", {
                    "source": layout.master(dataset, version), "scenario": scenario,
                    "labels": "Unchanged Kaggle Pascal VOC boxes; bounded teaching subset, not production validation",
                })
                finish(staging, {"kind": "image-training-snapshot", "scenario": name})
        keys.append(snapshot_key)
        from .lake_modalities import publish_image_annotations
        records = []
        taxonomy = set()
        for annotation in selected:
            node = ET.parse(annotation).getroot()
            filename = node.findtext("filename")
            width, height = int(node.findtext("size/width")), int(node.findtext("size/height"))
            objects = []
            for obj in node.findall("object"):
                label = obj.findtext("name")
                taxonomy.add(label)
                xmin, ymin, xmax, ymax = [float(obj.findtext("bndbox/" + key)) for key in ("xmin", "ymin", "xmax", "ymax")]
                objects.append({"label": label, "box": [xmin / width, ymin / height,
                                                        (xmax - xmin) / width, (ymax - ymin) / height]})
            records.append({"record_id": annotation.stem, "image": "images/" + filename,
                            "sha256": provenance["files"]["images/" + filename],
                            "width": width, "height": height, "objects": objects})
        label_key = layout.annotations(dataset, version)
        if local_key_path(root, label_key).exists():
            verified_manifest(local_key_path(root, label_key))
        else:
            publish_image_annotations(root, layout, project=project, use_case=name, dataset=dataset,
                                      source_version=version, annotation_version=version, records=records,
                                      task="image_object_detection", class_names=sorted(taxonomy))
        keys.append(label_key)
        samples.append({"scenario": name, "dataset": dataset, "images": limit,
                        "annotations": "Original Pascal VOC labels, unchanged",
                        "gold": snapshot_key + "/gold",
                        "project_in": layout.project(project, dataset, version) + "/in"})
    if config.get("rag_air_passengers", False):
        import hashlib
        import pandas as pd
        from .lake_modalities import publish_rag_snapshot
        from ml_model_factory.data import sha256
        source_key = layout.master("air-passengers", version)
        master_root = local_key_path(root, source_key)
        if not (master_root / "_SUCCESS.json").is_file():
            raise ValueError("RAG seed requires a verified, pinned AirPassengers master release")
        master = verified_manifest(master_root)
        origin = master.get("signature", {}).get("provenance", {})
        if (master.get("download_provenance_verified") is not True
                or origin.get("provider") != "kaggle" or origin.get("slug") != "rakannimer/air-passengers"):
            raise ValueError("RAG seed master lacks verified AirPassengers Kaggle provenance")
        source = master_root / "landing" / "AirPassengers.csv"
        if origin.get("files", {}).get("AirPassengers.csv") != sha256(source):
            raise ValueError("RAG seed source differs from pinned Kaggle bytes")
        frame = pd.read_csv(source)
        if "Month" not in frame or "#Passengers" not in frame:
            raise ValueError("Expected the verified AirPassengers Kaggle schema for the text projection")
        documents = []
        for year, rows in frame.groupby(frame["Month"].str[:4], sort=True):
            text = f"AirPassengers teaching dataset, year {year}.\n" + "\n".join(
                f"In {row['Month']}, international airline passengers were {row['#Passengers']} thousand."
                for _, row in rows.iterrows()
            )
            documents.append({
                "document_id": "air-passengers-" + year, "text": text,
                "source_uri": f"https://www.kaggle.com/datasets/rakannimer/air-passengers#year-{year}",
                "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source_version": version + "-derived-text", "acl": [f"project{project}"],
            })
        rag_key = layout.use_case(project, "air-passengers") + f"/rag/corpora/air-passengers/versions/{version}"
        derivation = {"master": source_key, "master_manifest_sha256": sha256(master_root / "_SUCCESS.json"),
                      "derivation": "air-passengers-annual-text/v1", "license": origin["license"]}
        if local_key_path(root, rag_key).exists():
            previous = verified_manifest(local_key_path(root, rag_key))
            if previous.get("provenance") != derivation:
                raise ValueError("RAG release has different derivation provenance; create a new release version")
        else:
            publish_rag_snapshot(root, layout, project, "air-passengers", "air-passengers", version,
                                 documents, chunker={"chunk_characters": 600, "overlap": 60},
                                 provenance=derivation)
        keys.append(rag_key)
        samples.append({"scenario": "rag-air-passengers", "documents": len(documents),
                        "data_origin": "Deterministic text projection of verified Kaggle table; not original prose",
                        "index_status": "not_built", "acl_enforced": False})
    plan = publication_plan(root, keys, account_url=config["storage"]["account_url"], container=config["storage"]["container"])
    result = {"schema": "esml.shared-lake-seed/v2", "state": "staged", "version": version,
              "samples": samples, "publications": keys, "azure_written": False, "plan": plan}
    write_json(root / "seed-result.json", result)
    write_json(root / "publication-plan.json", plan)
    return result


def write_common_runtimes(config: dict, seed: dict, runtime: dict, output: Path) -> list[str]:
    """Generate consumer runtime files; does not create the proposed datastore."""
    from ml_model_factory.tags import assert_scope
    from ml_model_factory.storage_selection import resolve_storage_selection
    config = resolve_storage_selection(config)
    assert_scope({"aifactory": config["aifactory"], "project": config["project"],
                  "environment": config["environment"]}, runtime)
    files = []
    declarations = {item["scenario"]: item for item in config["datasets"]}
    for sample in seed["samples"]:
        if "project_in" not in sample:
            continue
        name = sample["scenario"]
        current = deepcopy(runtime)
        current.pop("input_path", None)
        current["datastore"] = config["storage"]["datastore"]
        for key in ("use_common_datalake_storage", "storage_targets", "common_resource_group"):
            if key in config:
                current[key] = deepcopy(config[key])
        current["input_data"] = f"azureml://datastores/{current['datastore']}/paths/{sample['project_in']}/"
        if name in declarations:
            current["input_data"] += declarations[name]["file"]
        current["lake"] = {
            "aifactory": config["aifactory"], "project": config["project"], "environment": config["environment"],
            "use_case": name, "dataset": sample["dataset"], "data_version": seed["version"],
            "snapshot_id": seed["version"], "run_id": "common-" + seed["version"] + "-" + name,
            "storage": {key: config["storage"][key] for key in ("account_url", "container", "datastore")},
        }
        path = Path(output) / f"{name}.runtime.local.json"
        current = resolve_storage_selection(current)
        if path.exists() and load_json(path) != current:
            raise ValueError(f"Consumer runtime already differs: {path}")
        write_json(path, current)
        files.append(str(path))
    return files
