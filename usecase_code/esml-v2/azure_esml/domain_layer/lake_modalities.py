"""Offline, immutable image-label, RAG and conversation releases.

These exports do not activate labeling, retrieval, ACL enforcement or training.
Image exports need an explicit preprocessing adapter before the existing vision
provider can consume them; they are not prepared class folders/AutoML JSONL.
"""

from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from ml_model_factory.config import write_json
from ml_model_factory.lake import identifier, local_key_path
from ml_model_factory.lake_flow import finish, publication, verified_manifest

from .shared_lake import SharedLake


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("source/image sha256 must be a lowercase SHA-256 digest")
    return value


def _records(records, id_field):
    if not isinstance(records, list) or not records or any(not isinstance(r, dict) for r in records):
        raise ValueError("records must be a nonempty list of objects")
    ids = [_text(r.get(id_field), id_field) for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate {id_field}")


def _strings(values, field, *, empty=False):
    if not isinstance(values, list) or (not empty and not values):
        raise ValueError(f"{field} must be an explicit {'possibly empty ' if empty else 'nonempty '}list")
    values = [_text(v, field) for v in values]
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {field}")
    return values


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def _publish(root, key, metadata, jsonl, documents):
    for attempt in range(3):
        try:
            with publication(Path(root), key) as staging:
                for name, rows in jsonl.items():
                    _jsonl(local_key_path(staging, name), rows)
                for name, document in documents.items():
                    write_json(local_key_path(staging, name), document)
                finish(staging, {"key": key, **metadata})
            break
        except PermissionError as error:
            # Windows scanners can briefly hold new directories during atomic rename.
            if getattr(error, "winerror", None) not in (5, 32) or attempt == 2 or local_key_path(root, key).exists():
                raise
            time.sleep(0.05 * (attempt + 1))
    return verified_manifest(local_key_path(root, key))


def _scope(layout, project, use_case):
    return {"aifactory": layout.aifactory, "environment": layout.environment,
            "project": project, "use_case": use_case}


def _review(reviewer):
    if reviewer is not None:
        _text(reviewer, "reviewer")
    return {"status": "approved" if reviewer is not None else "requires_review",
            "reviewer": reviewer, "training_eligible": reviewer is not None,
            "basis": "Caller-supplied review attestation; no automated safety certification."}


def _model(value):
    value = _text(value, "model")
    match = re.fullmatch(r"(?:azureml:)?[A-Za-z0-9][A-Za-z0-9._/-]*:([A-Za-z0-9][A-Za-z0-9._-]*)", value)
    if not match:
        match = re.fullmatch(r"azureml://[A-Za-z0-9._/-]+/versions/([A-Za-z0-9][A-Za-z0-9._-]*)", value)
    if not match or match[1].lower() in {"latest", "active", "default", "champion", "production", "unversioned"}:
        raise ValueError("model must be pinned as name:version or an Azure ML /versions/version URI")
    return value


def _unit(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Coordinates must be finite normalized numbers in [0, 1]")
    return value


def _image_path(landing, name):
    parts = _text(name, "image").split("/")
    if any(part in ("", ".", "..") or re.search(r'[\x00-\x1f\\:*?"<>|]', part)
           or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
           or part.endswith((" ", ".")) for part in parts):
        raise ValueError("Image must be a safe relative landing filepath")
    path = landing.joinpath(*parts)
    if (not path.resolve().is_relative_to(landing.resolve())
            or any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                   for p in (path, *path.parents))):
        raise ValueError("Image paths may not escape landing or traverse links")
    return path


def _polygon(points):
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("A polygon needs at least three vertices")
    if any(not isinstance(p, list) or len(p) != 2 for p in points):
        raise ValueError("Polygon vertices must be [x, y] pairs")
    points = [tuple(_unit(v) for v in p) for p in points]
    if points[0] == points[-1]:
        points.pop()
    if len(set(points)) != len(points) or len(points) < 3:
        raise ValueError("Polygon vertices must be distinct")
    edges = list(zip(points, points[1:] + points[:1]))
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    if abs(area) <= 1e-12:
        raise ValueError("Polygon must be nondegenerate")

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges[i + 1:], i + 1):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            bounds_overlap = (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
                              and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])))
            if bounds_overlap and cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0:
                raise ValueError("Polygon must not self-intersect")
    return [list(p) for p in points]


def publish_image_annotations(root, layout: SharedLake, *, project, use_case, dataset,
                              source_version, annotation_version, records: list[dict], task: str,
                              class_names: list[str] | None = None, reviewer: str | None = None) -> dict:
    """Records: record_id, image (relative to master landing), sha256, label/labels/objects.

    Detection objects have label + box=[x,y,width,height]; segmentation objects
    have label + polygon=[[x,y],...]. Optional width/height must match decoded bytes.
    Approved releases require an explicit reviewed class_names taxonomy. Labels
    are supplied, never inferred. Invalid releases emit reference-only quarantine.
    Releases live OUTSIDE master datasets so source manifests remain immutable.
    Payload: exports/annotations.jsonl; taxonomy/review manifests at release root.
    """
    base = layout.use_case(project, use_case)
    master_key = layout.master(dataset, source_version)
    key = layout.annotations(dataset, annotation_version)
    aliases = {"multilabel": "image_classification_multilabel", "detection": "image_object_detection",
               "segmentation": "image_instance_segmentation"}
    try:
        task = aliases.get(_text(task, "task"), task)
        if task not in {"image_classification", "image_classification_multilabel",
                        "image_object_detection", "image_instance_segmentation"}:
            raise ValueError("Unsupported image task")
        _records(records, "record_id")
        review = _review(reviewer)
        classes = _strings(class_names, "class_names") if class_names is not None else None
        if reviewer is not None and classes is None:
            raise ValueError("Approval requires an explicit reviewed class_names taxonomy")
        source = local_key_path(root, master_key)
        master = verified_manifest(source)
        if master.get("aifactory", layout.aifactory) != layout.aifactory:
            raise ValueError("Master belongs to another AI Factory")
        from PIL import Image
        exported, observed, images = [], set(), set()
        for record in records:
            image = _text(record.get("image"), "image")
            if image in images:
                raise ValueError("Duplicate image reference")
            images.add(image)
            image_key = "landing/" + image
            if image_key not in master["files"]:
                raise ValueError("Image is absent from the immutable master inventory")
            content = _image_path(source / "landing", image).read_bytes()
            digest = sha256(content).hexdigest()
            if digest != _hash(record.get("sha256")) or master["files"].get(image_key) != digest:
                raise ValueError("Image sha256 does not match the immutable master landing")
            with Image.open(BytesIO(content)) as decoded:
                decoded.load()
                width, height = decoded.size
            if any(k in record and (type(record[k]) is not int or record[k] != v)
                   for k, v in (("width", width), ("height", height))):
                raise ValueError("Declared image dimensions do not match actual bytes")
            row = {"record_id": record["record_id"], "image": image, "sha256": digest,
                   "width": width, "height": height}
            if task == "image_classification":
                row["label"] = _text(record.get("label"), "label")
                labels = [row["label"]]
            elif task == "image_classification_multilabel":
                row["labels"] = _strings(record.get("labels"), "labels")
                labels = row["labels"]
            else:
                objects = record.get("objects")
                if not isinstance(objects, list) or not objects or any(not isinstance(o, dict) for o in objects):
                    raise ValueError("Detection/segmentation requires supplied nonempty objects")
                row["objects"], labels = [], []
                for obj in objects:
                    label = _text(obj.get("label"), "object label")
                    shape = {"label": label}
                    if task == "image_object_detection":
                        box = obj.get("box")
                        if not isinstance(box, list) or len(box) != 4:
                            raise ValueError("box must be [x, y, width, height]")
                        x, y, w, h = [_unit(v) for v in box]
                        if w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
                            raise ValueError("Bounding box must have positive area inside the image")
                        shape["box"] = box
                    else:
                        shape["polygon"] = _polygon(obj.get("polygon"))
                    row["objects"].append(shape)
                    labels.append(label)
            observed.update(labels)
            exported.append(row)
        if classes is not None and not observed.issubset(classes):
            raise ValueError("Supplied labels are absent from class_names")
        verified_manifest(source)
    except (ValueError, OSError) as error:
        quarantine = base + f"/quarantine/annotations/{uuid4().hex}"
        _publish(root, quarantine, {"kind": "annotation_rejection", "training_eligible": False}, {},
                 {"issue.json": {"status": "rejected", "source": master_key,
                                 "reason_code": "invalid_annotations", "raw_records_copied": False}})
        raise ValueError(f"Image annotations rejected; quarantine: {quarantine}") from error
    review.update({"task": task, "adapter_required": True, "training_started": False})
    return _publish(root, key, {**_scope(layout, project, use_case), "kind": "image_annotations",
                    "task": task, "format": "jsonl", "source": master_key,
                    "source_manifest_sha256": sha256((source / "_SUCCESS.json").read_bytes()).hexdigest(),
                    "review": review, "record_count": len(exported)},
                    {"exports/annotations.jsonl": exported},
                    {"taxonomy.json": {"classes": classes if classes is not None else sorted(observed),
                                       "reviewed": reviewer is not None}, "review-manifest.json": review})


def publish_rag_snapshot(root, layout: SharedLake, project, use_case, corpus, version,
                         documents: list[dict], *, chunker: dict, embedding_model: str | None = None,
                         provenance: dict | None = None) -> dict:
    """Publish supplied UTF-8 text, never fetch source_uri or build an index.

    Each document requires document_id/source_uri/source_sha256/acl. Live text's
    UTF-8 hash must match source_sha256; binary extraction needs a separate adapter.
    Deleted records carry the previous hash and explicit ACL, with no live text.
    Offsets count Unicode code points, not bytes or tokens; empty ACL denies all.
    """
    key = layout.use_case(project, use_case) + f"/rag/corpora/{identifier(corpus, 'corpus')}/versions/{identifier(version, 'version')}"
    _records(documents, "document_id")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("RAG derivation provenance must be an object")
    if not isinstance(chunker, dict) or set(chunker) != {"chunk_characters", "overlap"}:
        raise ValueError("chunker requires exactly chunk_characters and overlap")
    size, overlap = chunker["chunk_characters"], chunker["overlap"]
    if type(size) is not int or type(overlap) is not int or not 0 <= overlap < size:
        raise ValueError("chunk_characters must be positive; 0 <= overlap < chunk_characters")
    model = _model(embedding_model) if embedding_model is not None else None
    sources, chunks, tombstones = [], [], []
    for document in sorted(documents, key=lambda d: d["document_id"]):
        acl = _strings(document.get("acl"), "acl", empty=True)
        digest = _hash(document.get("source_sha256"))
        source = {"document_id": document["document_id"], "source_uri": _text(document.get("source_uri"), "source_uri"),
                  "source_sha256": digest, "source_version": _text(document.get("source_version", digest), "source_version"),
                  "acl": acl, "deleted": document.get("deleted", False)}
        if type(source["deleted"]) is not bool:
            raise ValueError("deleted must be a boolean")
        if source["deleted"]:
            if document.get("text") not in (None, ""):
                raise ValueError("Deleted documents must not contain live text")
            tombstones.append(source)
        else:
            text = _text(document.get("text"), "text")
            if sha256(text.encode("utf-8")).hexdigest() != digest:
                raise ValueError("source_sha256 must match the supplied UTF-8 text")
            source["text"] = text
            for start in range(0, len(text), size - overlap):
                end = min(start + size, len(text))
                part = text[start:end]
                chunk_id = _digest([source["document_id"], source["source_version"], start, end, sha256(part.encode("utf-8")).hexdigest()])
                chunks.append({**{k: v for k, v in source.items() if k not in ("text", "deleted")},
                               "chunk_id": chunk_id, "start": start, "end": end, "text": part})
                if end == len(text):
                    break
        sources.append(source)
    index = {"status": "not_built", "embedding_model": model or "not_selected",
             "embeddings_computed": False, "index_sync_required": True, "acl_enforced": False,
             "deleted_document_ids": [r["document_id"] for r in tombstones],
             "required_actions": ["Build a version-pinned index, enforcing source ACLs on every retrieval.",
                                  "Delete every tombstoned document and its chunks from previous indexes; verify deletion.",
                                  "Restrict snapshot/index storage access; these ACL fields alone grant no protection."]}
    return _publish(root, key, {**_scope(layout, project, use_case), "kind": "rag_snapshot", "format": "jsonl",
                    "chunker": {**chunker, "algorithm": "unicode-codepoints/v1"}, "index": index,
                    "document_count": len(sources) - len(tombstones), "chunk_count": len(chunks),
                    "provenance": provenance},
                    {"documents.jsonl": sources, "chunks/chunks.jsonl": chunks, "tombstones.jsonl": tombstones},
                    {"index-manifest.json": index})


_SECRET = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|"
                     r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}|\b(?:api[_-]?key|password|secret)\s*[:=]\s*\S+", re.I)


def publish_fine_tuning_snapshot(root, layout: SharedLake, project, use_case, snapshot_id,
                                 records: list[dict], *, base_model: str, reviewer: str | None = None) -> dict:
    """Export messages-only train/validation/test; never submit a fine-tuning job.

    Records require record_id/messages/split/source_id/source_sha256/license and
    consent=True. Provenance and review are caller attestations, not verified
    external rights. Limited secret-pattern rejection is not comprehensive DLP.
    Source groups, conversations and user prompts may not overlap across splits.
    """
    key = layout.use_case(project, use_case) + f"/fine-tuning/snapshots/{identifier(snapshot_id, 'snapshot_id')}"
    _records(records, "record_id")
    model, review = _model(base_model), _review(reviewer)
    splits = {name: [] for name in ("train", "validation", "test")}
    provenance, groups, source_hashes, conversations, prompts = [], {}, {}, set(), {}
    for record in records:
        split = record.get("split")
        if not isinstance(split, str) or split not in splits:
            raise ValueError("split must be train, validation or test")
        source = _text(record.get("source_id"), "source_id")
        digest = _hash(record.get("source_sha256"))
        license_id = _text(record.get("license"), "license")
        if license_id.lower() in {"unknown", "unspecified", "latest"} or record.get("consent") is not True:
            raise ValueError("Explicit license provenance and consent=True are required")
        messages = record.get("messages")
        if not isinstance(messages, list) or len(messages) < 2 or any(not isinstance(m, dict) for m in messages):
            raise ValueError("messages must contain a user/assistant conversation")
        clean, expected = [], "user"
        for position, message in enumerate(messages):
            role, content = message.get("role"), _text(message.get("content"), "message content")
            if set(message) != {"role", "content"}:
                raise ValueError("Only role and content are supported in messages")
            if role == "system" and position == 0:
                pass
            elif role == expected:
                expected = "assistant" if expected == "user" else "user"
            else:
                raise ValueError("Messages must alternate user/assistant, with optional initial system")
            if _SECRET.search(content):
                raise ValueError("Possible raw secret; redact and review before publishing")
            clean.append({"role": role, "content": content})
        if clean[-1]["role"] != "assistant":
            raise ValueError("Conversation must end with assistant")
        conversation = _digest([{"role": m["role"], "content": " ".join(m["content"].split())} for m in clean])
        prompt = _digest([" ".join(m["content"].split()) for m in clean if m["role"] == "user"])
        individual_prompts = {_digest(" ".join(m["content"].split())) for m in clean if m["role"] == "user"}
        if conversation in conversations:
            raise ValueError("Duplicate conversation")
        if source in groups and groups[source] != split:
            raise ValueError("Source group leakage across splits")
        if digest in source_hashes and source_hashes[digest] != split:
            raise ValueError("Source content leakage across splits")
        if any(item in prompts and prompts[item] != split for item in individual_prompts):
            raise ValueError("User prompt overlap across splits")
        conversations.add(conversation)
        source_hashes[digest] = split
        groups[source] = split
        prompts.update({item: split for item in individual_prompts})
        splits[split].append({"messages": clean})
        provenance.append({"record_id": record["record_id"], "split": split, "line": len(splits[split]),
                           "source_id": source, "source_sha256": digest, "license": license_id, "consent": True,
                           "conversation_sha256": conversation, "prompt_sha256": prompt})
    if any(not rows for rows in splits.values()):
        raise ValueError("All three train/validation/test splits must be nonempty")
    review.update({"secret_scan": "limited_patterns_not_comprehensive_DLP", "training_status": "not_started"})
    return _publish(root, key, {**_scope(layout, project, use_case), "kind": "fine_tuning_snapshot",
                    "base_model": model, "format": "jsonl", "review": review,
                    "split_counts": {name: len(rows) for name, rows in splits.items()}},
                    {**{f"{name}.jsonl": rows for name, rows in splits.items()}, "records-manifest.jsonl": provenance},
                    {"review-manifest.json": review})


def stream_paths(layout: SharedLake, *, project, use_case, dataset, version, run_id, model_version) -> dict:
    """Address contract only: checkpoints survive model/run changes; no stream runs."""
    areas = layout.areas(project=project, use_case=use_case, dataset=dataset, version=version,
                         run_id=run_id, snapshot_id="stream", model_version=model_version, serving="streaming")
    return {**{name: areas[name] for name in ("stream_events", "checkpoint", "input", "inference_gold", "output", "stream_deadletter")},
            "gold_format": "parquet", "delta_transaction_log_created": False, "status": "contract_only"}
