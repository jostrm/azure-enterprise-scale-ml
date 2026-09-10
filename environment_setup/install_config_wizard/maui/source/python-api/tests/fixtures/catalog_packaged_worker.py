"""Synthetic local-only lifecycle helper for packaged entry/DPAPI smoke tests."""

import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import zlib

from winpty import Backend, PtyProcess
from src.catalog_arm_schema import parameter_schema, validate_values
from src.catalog_secrets import unprotect


def _record(event, **values):
    with (Path(__file__).parent / "worker-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": event, **values}) + "\n")


def capabilities():
    return {"factory_cohort": "physical-lease-cohort-v1"}


def manifest_digest(document):
    value = {key: item for key, item in document.items() if key != "manifest_hash"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_manifest(document):
    assert document["schema"] == 1 and document["manifest_hash"] == manifest_digest(document)
    assert document["source"]["commit"] == "a" * 40
    assert isinstance(document["config"]["credential"], str)
    assert getattr(sys, "frozen", False)
    assert Backend.ConPTY is not None and PtyProcess is not None
    assert (Path(sys._MEIPASS) / "template-files" / "variables.yaml").is_file()
    validate_values(parameter_schema({"value": {"type": "object"}}), {"value": {"nested": [True, 1]}})
    _record("validate", manifest_hash=document["manifest_hash"])


def execute(document, source_root, execution_root, receipt):
    _record("execute")
    execution = Path(execution_root)
    assert not execution.exists()
    assert Path(receipt).parent == execution
    assert Path(source_root).resolve() == Path(__file__).parent.resolve()
    execution.mkdir()
    if document["config"].get("wait"):
        (execution / "ready").write_text("ready", encoding="utf-8")
        while True:
            time.sleep(.1)
    result = {"schema": 1, "status": "succeeded", "manifest_hash": document["manifest_hash"], "frozen": True}
    Path(receipt).write_text(json.dumps(result), encoding="utf-8")
    return result


def execute_cohort(documents, source_root, execution_root, receipt):
    _record("execute_cohort")
    execution = Path(execution_root)
    assert not execution.exists()
    assert Path(receipt).parent == execution
    assert Path(source_root).resolve() == Path(__file__).parent.resolve()
    execution.mkdir()
    result = {"schema": 1, "status": "succeeded", "frozen": getattr(sys, "frozen", False),
              "children": [{"run_id": child["run_id"], "manifest_hash": child["manifest_hash"]}
                           for child in documents]}
    Path(receipt).write_text(json.dumps(result), encoding="utf-8")
    return result
