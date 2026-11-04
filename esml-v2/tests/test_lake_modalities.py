"""Local synthetic fixtures test publication contracts, not external services."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from uuid import uuid4

from PIL import Image
import pytest

from azure_esml.domain_layer import lake_modalities
from azure_esml.domain_layer.lake_modalities import (
    publish_fine_tuning_snapshot, publish_image_annotations, publish_rag_snapshot, stream_paths,
)
from azure_esml.domain_layer.shared_lake import SharedLake
from ml_model_factory.lake import local_key_path
from ml_model_factory.lake_flow import finish, verified_manifest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def lake():
    root = ROOT / (".mt-" + uuid4().hex[:12])
    root.mkdir()
    try:
        yield root, SharedLake("test-factory", "dev")
    finally:
        shutil.rmtree(root)


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def master_image(root, layout, name="sample.png"):
    key = layout.master("images", "source-v1")
    source = local_key_path(root, key)
    (source / "landing" / "images").mkdir(parents=True)
    path = source / "landing" / "images" / name
    Image.new("RGB", (20, 10), (17, 50, 100)).save(path)
    digest = sha256(path.read_bytes()).hexdigest()
    finish(source, {"kind": "master", "aifactory": layout.aifactory, "provenance": "synthetic-test-only"})
    return {"record_id": "image-1", "image": "images/" + name, "sha256": digest}


def image_release(root, layout, record, task, **kwargs):
    return publish_image_annotations(
        root, layout, project="001", use_case="inspection", dataset="images",
        source_version="source-v1", annotation_version="labels-v1", records=[record], task=task, **kwargs)


@pytest.mark.parametrize(("task", "annotation"), [
    ("image_classification", {"label": "object"}),
    ("image_classification_multilabel", {"labels": ["object", "round"]}),
    ("image_object_detection", {"objects": [{"label": "object", "box": [0.1, 0.2, 0.5, 0.6]}]}),
    ("image_instance_segmentation", {"objects": [{"label": "object", "polygon": [[0, 0], [1, 0], [0.5, 1]]}]}),
])
def test_image_shapes_have_actual_dimensions_and_immutable_separate_release(lake, task, annotation):
    root, layout = lake
    record = master_image(root, layout)
    master = local_key_path(root, layout.master("images", "source-v1"))
    before = verified_manifest(master)
    result = image_release(root, layout, {**record, **annotation}, task)
    target = local_key_path(root, result["key"])
    assert result["format"] == "jsonl"
    assert result["review"]["status"] == "requires_review"
    assert not result["review"]["training_eligible"]
    assert result["review"]["adapter_required"]
    assert "/annotations/images/versions/labels-v1" in result["key"]
    assert not target.is_relative_to(master)
    row = rows(target / "exports" / "annotations.jsonl")[0]
    assert (row["width"], row["height"]) == (20, 10)
    assert verified_manifest(master) == before
    with pytest.raises(ValueError, match="Immutable"):
        image_release(root, layout, {**record, **annotation}, task)
    assert verified_manifest(target) == result


def test_annotation_approval_requires_explicit_reviewer_and_taxonomy(lake):
    root, layout = lake
    record = {**master_image(root, layout), "label": "object"}
    with pytest.raises(ValueError):
        image_release(root, layout, record, "image_classification", reviewer="reviewer")
    result = image_release(root, layout, record, "image_classification", reviewer="reviewer", class_names=["object"])
    assert result["review"]["status"] == "approved"
    assert result["review"]["training_eligible"]
    assert result["review"]["training_started"] is False


@pytest.mark.parametrize("name", ["sample image.png", "画像.png"])
def test_image_source_filenames_preserve_spaces_and_unicode(lake, name):
    root, layout = lake
    record = {**master_image(root, layout, name), "label": "object"}
    result = image_release(root, layout, record, "image_classification")
    exported = rows(local_key_path(root, result["key"]) / "exports" / "annotations.jsonl")[0]
    assert exported["image"] == "images/" + name


@pytest.mark.parametrize(("task", "update"), [
    ("image_classification", {}),
    ("image_classification", {"label": ""}),
    ("image_classification", {"label": "object", "sha256": "0" * 64}),
    ("image_classification", {"label": "object", "image": "../sample.png"}),
    ("image_classification", {"label": "object", "image": "C:\\outside.png"}),
    ("image_classification", {"label": "object", "width": 30}),
    ("multilabel", {"labels": []}),
    ("multilabel", {"labels": ["object", "object"]}),
    ("detection", {"objects": [{"label": "object", "box": [0.8, 0, 0.5, 1]}]}),
    ("detection", {"objects": [{"label": "object", "box": [0, 0, 0, 1]}]}),
    ("detection", {"objects": [{"label": "object", "box": [0, 0, True, 1]}]}),
    ("detection", {"objects": [{"label": "object", "box": [0, 0, float("nan"), 1]}]}),
    ("segmentation", {"objects": [{"label": "object", "box": [0, 0, 1, 1]}]}),
    ("segmentation", {"objects": [{"label": "object", "polygon": [[0, 0], [0.5, 0.5], [1, 1]]}]}),
    ("segmentation", {"objects": [{"label": "object", "polygon": [[0, 0], [1, 1], [0, 1], [1, 0]]}]}),
    ("segmentation", {"objects": [{"label": "object", "polygon": [[0, 0], [2, 0], [0, 1]]}]}),
])
def test_invalid_labels_are_quarantined_without_raw_data_or_release(lake, task, update):
    root, layout = lake
    record = {**master_image(root, layout), **update}
    with pytest.raises(ValueError, match="quarantine"):
        image_release(root, layout, record, task)
    issues = list(root.rglob("issue.json"))
    assert len(issues) == 1
    issue = json.loads(issues[0].read_text(encoding="utf-8"))
    assert issue["raw_records_copied"] is False
    assert issue["status"] == "rejected"
    assert not list(root.rglob("annotations.jsonl"))


def test_image_rejects_duplicate_ids_and_unknown_taxonomy(lake):
    root, layout = lake
    record = {**master_image(root, layout), "label": "object"}
    with pytest.raises(ValueError):
        publish_image_annotations(root, layout, project="001", use_case="inspection", dataset="images",
                                  source_version="source-v1", annotation_version="labels-v1",
                                  records=[record, record], task="image_classification")
    with pytest.raises(ValueError):
        image_release(root, layout, record, "image_classification", class_names=["other"])


def test_image_master_tampering_is_detected(lake):
    root, layout = lake
    record = {**master_image(root, layout), "label": "object"}
    source = local_key_path(root, layout.master("images", "source-v1"))
    (source / "landing" / "images" / "sample.png").write_bytes(b"not an image")
    with pytest.raises(ValueError):
        image_release(root, layout, record, "image_classification")


def document(name="document-1", text="A😀BCDEF你好"):
    return {"document_id": name, "text": text, "source_uri": "fixture://synthetic/" + name,
            "source_sha256": sha256(text.encode("utf-8")).hexdigest(), "acl": ["group:readers"]}


def rag_release(root, layout, documents, version="v1", **kwargs):
    return publish_rag_snapshot(root, layout, "001", "search", "manuals", version, documents,
                                chunker={"chunk_characters": 4, "overlap": 1}, **kwargs)


def test_rag_chunks_preserve_unicode_offsets_hashes_acls_and_tombstones(lake):
    root, layout = lake
    live, deleted = document(), document("removed")
    del deleted["text"]
    deleted["deleted"] = True
    result = rag_release(root, layout, [live, deleted])
    target = local_key_path(root, result["key"])
    chunks = rows(target / "chunks" / "chunks.jsonl")
    assert [(c["start"], c["end"]) for c in chunks] == [(0, 4), (3, 7), (6, 9)]
    for chunk in chunks:
        assert chunk["text"] == live["text"][chunk["start"]:chunk["end"]]
        assert chunk["acl"] == live["acl"]
        assert chunk["source_sha256"] == live["source_sha256"]
        assert chunk["document_id"] == live["document_id"]
    assert rows(target / "tombstones.jsonl")[0]["document_id"] == "removed"
    assert result["index"]["status"] == "not_built"
    assert result["index"]["embedding_model"] == "not_selected"
    assert result["index"]["index_sync_required"]
    assert not result["index"]["acl_enforced"]
    assert not result["index"]["embeddings_computed"]
    repeated = rag_release(root, layout, [deleted, live], version="v2", embedding_model="text-embedding:2025-01-01")
    assert rows(local_key_path(root, repeated["key"]) / "chunks" / "chunks.jsonl") == chunks
    assert repeated["index"]["embedding_model"] == "text-embedding:2025-01-01"
    with pytest.raises(ValueError, match="Immutable"):
        rag_release(root, layout, [live, deleted])


def test_rag_all_deleted_and_explicit_empty_acl_are_fail_closed(lake):
    root, layout = lake
    source = {**document(), "text": "", "deleted": True, "acl": []}
    result = rag_release(root, layout, [source])
    target = local_key_path(root, result["key"])
    assert result["document_count"] == result["chunk_count"] == 0
    assert rows(target / "chunks" / "chunks.jsonl") == []
    assert rows(target / "tombstones.jsonl")[0]["acl"] == []


def test_rag_duplicate_document_ids_are_not_silently_overwritten(lake):
    root, layout = lake
    with pytest.raises(ValueError, match="Duplicate document_id"):
        rag_release(root, layout, [document(), document()])


@pytest.mark.parametrize("update", [
    {"acl": None}, {"acl": ["read", "read"]}, {"source_uri": ""},
    {"source_sha256": "0" * 64}, {"deleted": "true"}, {"deleted": True}, {"text": ""},
])
def test_rag_rejects_missing_acl_stale_hash_and_invalid_tombstones(lake, update):
    root, layout = lake
    with pytest.raises(ValueError):
        rag_release(root, layout, [{**document(), **update}])
    assert not list(root.rglob("_SUCCESS.json"))


@pytest.mark.parametrize("chunker", [
    {"chunk_characters": 0, "overlap": 0}, {"chunk_characters": 4, "overlap": 4},
    {"chunk_characters": True, "overlap": 0}, {"chunk_characters": 4, "overlap": -1},
    {"chunk_characters": 4, "overlap": 0, "format": "delta"},
])
def test_rag_rejects_invalid_chunk_contract(lake, chunker):
    root, layout = lake
    with pytest.raises(ValueError):
        publish_rag_snapshot(root, layout, "001", "search", "manuals", "v1", [document()], chunker=chunker)


def conversations():
    return [{"record_id": split, "source_id": "source-" + split, "source_sha256": sha256(split.encode()).hexdigest(),
             "split": split, "license": "CC-BY-4.0", "consent": True,
             "messages": [{"role": "system", "content": "Answer the question."},
                          {"role": "user", "content": "Question for " + split},
                          {"role": "assistant", "content": "Answer for " + split}]}
            for split in ("train", "validation", "test")]


def fine_release(root, layout, records, **kwargs):
    return publish_fine_tuning_snapshot(root, layout, "001", "assistant", "v1", records,
                                        base_model="base-model:2025-01-01", **kwargs)


def test_fine_tuning_exports_only_messages_and_separate_review_provenance(lake):
    root, layout = lake
    result = fine_release(root, layout, conversations())
    target = local_key_path(root, result["key"])
    assert result["format"] == "jsonl"
    assert result["split_counts"] == {"train": 1, "validation": 1, "test": 1}
    assert result["review"]["status"] == "requires_review"
    assert result["review"]["training_eligible"] is False
    assert result["review"]["training_status"] == "not_started"
    for split in result["split_counts"]:
        assert set(rows(target / f"{split}.jsonl")[0]) == {"messages"}
    assert len(rows(target / "records-manifest.jsonl")) == 3
    assert verified_manifest(target) == result
    with pytest.raises(ValueError, match="Immutable"):
        fine_release(root, layout, conversations())


def test_fine_tuning_explicit_review_is_an_attestation_not_a_job(lake):
    root, layout = lake
    result = fine_release(root, layout, conversations(), reviewer="reviewer")
    assert result["review"]["training_eligible"]
    assert result["review"]["training_status"] == "not_started"


def test_multiturn_training_cannot_embed_a_validation_prompt(lake):
    root, layout = lake
    records = conversations()
    records[0]["messages"] = deepcopy(records[1]["messages"]) + [
        {"role": "user", "content": "A distinct extra follow-up"},
        {"role": "assistant", "content": "A distinct follow-up answer"},
    ]
    with pytest.raises(ValueError, match="prompt overlap"):
        fine_release(root, layout, records, reviewer="reviewer")


@pytest.mark.parametrize("invalid", ["duplicate", "prompt_overlap", "source_leak", "source_hash_leak", "duplicate_id",
                                    "split", "missing_split", "consent", "license", "role", "last_user", "empty", "secret", "hash"])
def test_fine_tuning_rejects_leakage_bad_roles_missing_evidence_and_secrets(lake, invalid):
    root, layout = lake
    records = conversations()
    if invalid == "duplicate":
        records[1]["messages"] = deepcopy(records[0]["messages"])
    elif invalid == "prompt_overlap":
        records[1]["messages"][1] = deepcopy(records[0]["messages"][1])
    elif invalid == "source_leak":
        records[1]["source_id"] = records[0]["source_id"]
    elif invalid == "source_hash_leak":
        records[1]["source_sha256"] = records[0]["source_sha256"]
    elif invalid == "duplicate_id":
        records[1]["record_id"] = records[0]["record_id"]
    elif invalid == "split":
        records[0]["split"] = "dev"
    elif invalid == "missing_split":
        records.pop()
    elif invalid == "consent":
        records[0]["consent"] = False
    elif invalid == "license":
        records[0]["license"] = "unknown"
    elif invalid == "role":
        records[0]["messages"][1]["role"] = "tool"
    elif invalid == "last_user":
        records[0]["messages"].pop()
    elif invalid == "empty":
        records[0]["messages"][1]["content"] = ""
    elif invalid == "secret":
        records[0]["messages"][1]["content"] = "password=example-test-secret"
    else:
        del records[0]["source_sha256"]
    with pytest.raises(ValueError):
        fine_release(root, layout, records)
    assert not list(root.rglob("_SUCCESS.json"))


@pytest.mark.parametrize("model", ["unversioned-model", "model:latest", "model@latest", "model:production"])
def test_rag_and_fine_tuning_require_pinned_models(lake, model):
    root, layout = lake
    with pytest.raises(ValueError):
        rag_release(root, layout, [document()], embedding_model=model)
    with pytest.raises(ValueError):
        publish_fine_tuning_snapshot(root, layout, "001", "assistant", "v1", conversations(), base_model=model)


def test_stream_checkpoints_stable_across_runs_models_and_no_delta_claim(lake):
    _, layout = lake
    args = {"project": "001", "use_case": "sensor", "dataset": "events", "version": "v1"}
    before = stream_paths(layout, **args, run_id="run-1", model_version="1")
    after = stream_paths(layout, **args, run_id="run-2", model_version="2")
    assert before["checkpoint"] == after["checkpoint"]
    assert before["inference_gold"] != after["inference_gold"]
    assert before["gold_format"] == "parquet"
    assert before["delta_transaction_log_created"] is False
    assert before["status"] == "contract_only"


def test_publication_retries_only_transient_windows_permission_errors(lake, monkeypatch):
    root, layout = lake
    original = lake_modalities.publication
    calls = []

    def busy_once(*args):
        calls.append(args)
        if len(calls) == 1:
            error = PermissionError("Simulated transient scanner lock")
            error.winerror = 5
            raise error
        return original(*args)

    monkeypatch.setattr(lake_modalities, "publication", busy_once)
    result = rag_release(root, layout, [document()])
    assert 2 <= len(calls) <= 3
    assert verified_manifest(local_key_path(root, result["key"])) == result


def test_permission_denial_is_not_suppressed(lake, monkeypatch):
    root, layout = lake

    def denied(*args):
        raise PermissionError("Denied")

    monkeypatch.setattr(lake_modalities, "publication", denied)
    with pytest.raises(PermissionError, match="Denied"):
        rag_release(root, layout, [document()])
