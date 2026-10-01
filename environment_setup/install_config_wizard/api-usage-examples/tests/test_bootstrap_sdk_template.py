"""Offline coverage for the two files copied into a consumer repository."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

from test_create_factory import Client, request

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT.parents[2] / "bootstrap" / "python-sdk"
CLI_SRC = ROOT.parents[1] / "azurefactory-cli" / "src"
SUPPORT = Path("azure-enterprise-scale-ml") / "environment_setup" / "install_config_wizard" / "api-usage-examples" / "python"


def load_starter(root):
    spec = importlib.util.spec_from_file_location("copied_sdk_starter", root / "aifactory_sdk.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_support(root):
    support = root / SUPPORT
    support.mkdir(parents=True)
    for name in ("create_factory.py", "inspect_factory.py"):
        shutil.copyfile(ROOT / "python" / name, support / name)
    return support


@pytest.fixture
def consumer():
    root = ROOT / ".local" / ("pytest-sdk-" + str(uuid4()))
    root.mkdir(parents=True)
    shutil.copyfile(STARTER / "aifactory_sdk.py", root / "aifactory_sdk.py")
    shutil.copyfile(STARTER / "aifactory.request.example.json", root / "aifactory.request.json")
    (root / "elsewhere").mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


def isolated_run(root, *args):
    return subprocess.run(
        [sys.executable, "-I", "-S", str(root / "aifactory_sdk.py"), *args],
        cwd=root / "elsewhere", capture_output=True, text=True, timeout=10,
    )


def filled_sample(root):
    body = json.loads((root / "aifactory.request.json").read_text())
    body["folder"] = request()["folder"]
    scale = body["scale_sets"][0]
    for name in ("tenant_id", "subscription_id", "network"):
        scale[name] = request()["scale_sets"][0][name]
    return body


def test_help_works_from_other_cwd_without_sdk_or_submodule(consumer):
    result = isolated_run(consumer, "--help")
    assert result.returncode == 0, result.stderr
    assert all(option in result.stdout for option in ("--request", "--receipt", "--confirm", "--yes"))
    assert not result.stderr


@pytest.mark.parametrize("argv", [[], ["--unknown"], ["--request", "body.json"]])
def test_invalid_arguments_are_reported_before_dependency_loading(consumer, argv):
    result = isolated_run(consumer, *argv)
    assert result.returncode == 2
    assert "usage:" in result.stderr and "error:" in result.stderr
    assert "Missing" not in result.stderr


@pytest.mark.parametrize("missing", ["create_factory.py", "inspect_factory.py"])
def test_missing_support_file_is_explicit_without_fetching_or_fallback(consumer, missing):
    support = copy_support(consumer)
    (support / missing).unlink()
    result = isolated_run(consumer, "--request", "body.json", "--receipt", "review.json")
    assert result.returncode == 2
    assert "Missing submodule support file:" in result.stderr and missing in result.stderr
    assert "consumer repo root" in result.stderr and not result.stdout


def test_missing_installed_sdk_is_explicit(consumer):
    copy_support(consumer)
    result = isolated_run(consumer, "--request", "body.json", "--receipt", "review.json")
    assert result.returncode == 2 and "Missing Python SDK" in result.stderr
    assert r"pip install -e .\azure-enterprise-scale-ml\environment_setup\azurefactory-cli" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("argv", [
    ["--request", r".\aifactory.request.json", "--receipt", r".\factory.receipt.json"],
    ["--confirm", "--receipt", r".\factory.receipt.json", "--yes"],
])
def test_copied_script_resolves_own_submodule_forwards_arguments_and_restores_path(
        consumer, monkeypatch, capsys, argv):
    support = copy_support(consumer)
    (support / "create_factory.py").write_text(
        "import json\nimport sys\nfrom pathlib import Path\n"
        "from inspect_factory import exactly_one\n"
        "HERE = str(Path(__file__).resolve().parent)\n"
        "assert sys.path[0] == HERE\n"
        "def main(argv):\n"
        "    assert HERE not in sys.path\n"
        "    assert exactly_one([1], 'scope') == 1\n"
        "    print(json.dumps(argv))\n"
        "    return 7\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(CLI_SRC))
    monkeypatch.chdir(consumer / "elsewhere")
    starter = load_starter(consumer)
    before = sys.path[:]
    assert starter.main(argv) == 7
    assert json.loads(capsys.readouterr().out) == argv
    assert sys.path == before


@pytest.mark.parametrize("failure", ["import", "main"])
def test_path_is_restored_when_support_code_raises(consumer, monkeypatch, failure):
    support = copy_support(consumer)
    source = (
        "raise RuntimeError('support import failed')\n" if failure == "import"
        else "def main(argv):\n    raise RuntimeError('support main failed')\n"
    )
    (support / "create_factory.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(CLI_SRC))
    starter = load_starter(consumer)
    before = sys.path[:]
    with pytest.raises(RuntimeError, match="support"):
        starter.main(["--request", "body.json", "--receipt", "review.json"])
    assert sys.path == before


def test_sdk_internal_missing_dependency_is_not_hidden(consumer, monkeypatch):
    copy_support(consumer)
    starter = load_starter(consumer)

    def broken_sdk(name):
        raise ModuleNotFoundError("SDK dependency missing", name="sdk_internal_dependency")

    monkeypatch.setattr(starter.importlib, "import_module", broken_sdk)
    with pytest.raises(ModuleNotFoundError, match="SDK dependency"):
        starter.main(["--request", "body.json", "--receipt", "review.json"])


def test_real_sdk_backed_main_keeps_prepare_and_explicit_confirm_separate(
        consumer, monkeypatch, capsys):
    copy_support(consumer)
    monkeypatch.syspath_prepend(str(CLI_SRC))
    import azurefactory

    client = Client()
    monkeypatch.setattr(azurefactory, "AzureFactoryClient", lambda: client)
    starter = load_starter(consumer)
    body = consumer / "aifactory.request.json"
    body.write_text(json.dumps(request()), encoding="utf-8")
    receipt = consumer / "factory.receipt.json"
    monkeypatch.chdir(consumer / "elsewhere")
    before = sys.path[:]
    assert starter.main(["--request", str(body), "--receipt", str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "configuration-preview"
    assert [call[0] for call in client.calls] == ["prepare"]
    assert starter.main(["--confirm", "--receipt", str(receipt)]) == 2
    assert [call[0] for call in client.calls] == ["prepare"]
    capsys.readouterr()
    assert starter.main(["--confirm", "--receipt", str(receipt), "--yes"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["phase"] == "configuration-saved"
    assert result["deployment_started"] is False and result["publication_started"] is False
    assert [call[0] for call in client.calls] == ["prepare", "confirm", "list"]
    assert sys.path == before


def test_json_sample_matches_raw_request_shape_and_safe_defaults(consumer, monkeypatch):
    raw = json.loads((ROOT / "requests" / "01-create-factory.json").read_text())
    sample = json.loads((consumer / "aifactory.request.json").read_text())
    assert set(sample) == set(raw)
    scale = sample["scale_sets"][0]
    assert len(sample["scale_sets"]) == 1 and set(scale) == set(raw["scale_sets"][0])
    assert set(scale["network"]) == set(raw["scale_sets"][0]["network"])
    assert all("[replace-" in value for value in (
        sample["folder"], scale["tenant_id"], scale["subscription_id"], scale["network"]["vnet_cidr"],
    ))
    assert (sample["factory_key"], sample["target_prefix"], sample["target_region"],
            sample["aifactory_version"]) == ("team-ai", "team-", "swedencentral", "main")
    assert (scale["environment"], scale["suffix"], scale["orchestrator"],
            scale["network"]["max_projects"]) == ("dev", "001", "gha", 3)
    assert "initial_project" not in sample
    assert "api_key" not in json.dumps(sample).lower() and "token" not in json.dumps(sample).lower()
    copy_support(consumer)
    monkeypatch.syspath_prepend(str(CLI_SRC))
    starter = load_starter(consumer)
    import azurefactory

    client = Client()
    monkeypatch.setattr(azurefactory, "AzureFactoryClient", lambda: client)
    sample_path = consumer / "aifactory.request.json"
    assert starter.main(
        ["--request", str(sample_path), "--receipt", str(consumer / "review.json")],
    ) == azurefactory.FailureError.exit_code
    assert not client.calls
    client.preview.update(can_execute=False, blockers=["Offline sample validation only."])
    sample_path.write_text(json.dumps(filled_sample(consumer)), encoding="utf-8")
    assert starter.main(["--request", str(sample_path), "--receipt", str(consumer / "review.json")]) == 3
    assert client.calls == [("prepare", filled_sample(consumer))]
    assert not (consumer / "review.json").exists()


@pytest.mark.skipif(not os.environ.get("AIFACTORY_API_SOURCE"), reason="Optional authoritative model validation")
def test_filled_sample_matches_current_pydantic_contract_and_default_project(consumer, monkeypatch):
    monkeypatch.syspath_prepend(os.environ["AIFACTORY_API_SOURCE"])
    from src.factory_catalog_models import CatalogPrepare

    parsed = CatalogPrepare.model_validate(filled_sample(consumer))
    assert parsed.initial_project.number == "001" and parsed.initial_project.placements is None
