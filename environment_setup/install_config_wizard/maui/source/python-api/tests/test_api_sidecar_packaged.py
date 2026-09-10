"""Run after build with AIFACTORY_PACKAGED_API pointing to the installed-style exe."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest

from src.catalog_protocol import fingerprint
from src.deployment_config import protect


SECRET = "fixture-sensitive-value-92473"


@pytest.fixture
def packaged():
    value = os.environ.get("AIFACTORY_PACKAGED_API")
    if os.name != "nt" or not value:
        pytest.skip("Set AIFACTORY_PACKAGED_API to the built Windows API executable.")
    executable = Path(value).resolve()
    assert executable.is_file()
    return executable


def environment():
    retained = {"SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                "PROGRAMDATA", "TEMP", "TMP"}
    result = {key: value for key, value in os.environ.items() if key.upper() in retained}
    result["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    return result


def worker_arguments(tmp_path, parent_pid, wait=False, cohort=False):
    source = tmp_path / "selected published source"
    source.mkdir()
    helper = source / "factory_lifecycle.py"
    shutil.copyfile(Path(__file__).parent / "fixtures" / "catalog_packaged_worker.py", helper)
    document = {"schema": 1, "source": {"commit": "a" * 40}, "config": {"credential": SECRET, "wait": wait}}
    if cohort:
        document = [{**document, "run_id": run_id, "config": dict(document["config"])}
                    for run_id in ("child-one", "child-two")]
        for child in document:
            child["manifest_hash"] = fingerprint(child)
        document.sort(key=lambda child: child["manifest_hash"], reverse=True)
        expected_hash = fingerprint(sorted(child["manifest_hash"] for child in document))
    else:
        document["manifest_hash"] = fingerprint(document)
        expected_hash = document["manifest_hash"]
    protected = tmp_path / "protected whole manifest.dpapi"
    protected.write_bytes(protect(json.dumps(document).encode()))
    execution = tmp_path / "new isolated execution"
    arguments = ["--catalog-worker", "--parent-pid", str(parent_pid),
                 "--helper", str(helper), "--helper-sha256", hashlib.sha256(helper.read_text(encoding="utf-8").encode()).hexdigest(),
                 "--expected-hash", expected_hash, "--protected-manifest", str(protected),
                 "--source-root", str(source), "--execution-root", str(execution),
                 "--receipt", str(execution / "receipt.json")]
    if cohort:
        arguments.append("--cohort")
    return arguments, execution, document


def test_packaged_help_dispatch_requires_neither_source_tree_nor_python(packaged, tmp_path):
    result = subprocess.run([str(packaged), "--catalog-worker", "--help"], cwd=tmp_path,
                            env=environment(), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "--protected-manifest" in result.stdout and "--execution-root" in result.stdout
    assert "--port" not in result.stdout


def test_packaged_http_host_starts_with_live_parent_and_current_catalog_contract(packaged, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {**environment(), "AIFACTORY_API_KEY": "synthetic-packaging-api-key",
           "AIFACTORY_CATALOG_OWNER": "windows:synthetic-packaging-owner"}
    process = subprocess.Popen([str(packaged), "--port", str(port), "--parent-pid", str(os.getpid())],
                               cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 60
        healthy = False
        while process.poll() is None and time.monotonic() < deadline:
            try:
                with opener.open(base + "/health", timeout=1) as response:
                    healthy = response.status == 200
                    break
            except (URLError, TimeoutError):
                time.sleep(.1)
        assert healthy, "The bundled HTTP host did not become responsive."
        with opener.open(base + "/openapi.json", timeout=10) as response:
            spec = json.load(response)
        assert "/api/v1/factory-catalog/parameters/prepare" in spec["paths"]
        assert "/api/v1/factory-catalog/terminal/input" in spec["paths"]
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)


def test_packaged_dpapi_worker_executes_only_the_hash_bound_helper(packaged, tmp_path):
    arguments, execution, document = worker_arguments(tmp_path, os.getpid())
    result = subprocess.run([str(packaged), *arguments], cwd=tmp_path, env=environment(),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    receipt = json.loads((execution / "receipt.json").read_text(encoding="utf-8"))
    assert receipt == {"schema": 1, "status": "succeeded", "manifest_hash": document["manifest_hash"], "frozen": True}
    assert SECRET not in result.stdout + result.stderr
    assert not (execution / "configuration.json").exists()


def test_packaged_worker_rejects_changed_expected_hash_without_execution(packaged, tmp_path):
    arguments, execution, _ = worker_arguments(tmp_path, os.getpid())
    arguments[arguments.index("--expected-hash") + 1] = "b" * 64
    result = subprocess.run([str(packaged), *arguments], cwd=tmp_path, env=environment(),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert not execution.exists()
    assert SECRET not in result.stdout + result.stderr


def test_packaged_dpapi_cohort_validates_all_children_before_one_dispatch(packaged, tmp_path):
    arguments, execution, documents = worker_arguments(tmp_path, os.getpid(), cohort=True)
    assert not execution.exists()
    protected = Path(arguments[arguments.index("--protected-manifest") + 1])
    assert SECRET.encode() not in protected.read_bytes()
    result = subprocess.run([str(packaged), *arguments], cwd=tmp_path, env=environment(),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    receipt = json.loads((execution / "receipt.json").read_text(encoding="utf-8"))
    assert receipt == {"schema": 1, "status": "succeeded", "frozen": True,
                       "children": [{"run_id": child["run_id"], "manifest_hash": child["manifest_hash"]}
                                    for child in documents]}
    assert json.loads(result.stdout) == receipt
    source = Path(arguments[arguments.index("--source-root") + 1])
    events = [json.loads(line) for line in (source / "worker-events.jsonl").read_text(encoding="utf-8").splitlines()]
    validations = [{"event": "validate", "manifest_hash": child["manifest_hash"]} for child in documents]
    assert events == validations + [{"event": "execute_cohort"}]
    assert SECRET not in result.stdout + result.stderr
    assert not (execution / "configuration.json").exists()


@pytest.mark.parametrize("resign", [False, True], ids=["tampered-child", "resigned-child"])
def test_packaged_dpapi_cohort_rejects_changed_child_before_dispatch(packaged, tmp_path, resign):
    arguments, execution, documents = worker_arguments(tmp_path, os.getpid(), cohort=True)
    documents[0]["config"]["credential"] = SECRET + "-changed"
    if resign:
        documents[0].pop("manifest_hash")
        documents[0]["manifest_hash"] = fingerprint(documents[0])
    protected = Path(arguments[arguments.index("--protected-manifest") + 1])
    protected.write_bytes(protect(json.dumps(documents).encode()))
    result = subprocess.run([str(packaged), *arguments], cwd=tmp_path, env=environment(),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"status": "blocked", "error_code": "reviewed-runtime-input-or-execution-failed"}
    assert not execution.exists()
    source = Path(arguments[arguments.index("--source-root") + 1])
    assert not (source / "worker-events.jsonl").exists()
    assert SECRET not in result.stdout + result.stderr


def test_packaged_worker_exits_when_its_api_parent_dies(packaged, tmp_path):
    parent = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(90)"],
                              cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    worker = None
    try:
        arguments, execution, _ = worker_arguments(tmp_path, parent.pid, wait=True)
        worker = subprocess.Popen([str(packaged), *arguments], cwd=tmp_path, env=environment(),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while not (execution / "ready").exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        assert (execution / "ready").exists(), "Packaged worker never reached the local-only test execution."
        parent.terminate()
        parent.wait(timeout=10)
        worker.wait(timeout=15)
        assert not (execution / "receipt.json").exists()
    finally:
        for process in (worker, parent):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
