import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import catalog_runtime as runtime
from src.catalog_frozen_plan import FrozenPlanner
from src.catalog_storage import CatalogError
from src.ticket_connectors import TicketError


COMMIT = "a" * 40
HELPER = (
    "# AIFACTORY_LIFECYCLE_CONTRACT=1\n"
    "def execute(): pass\n"
    "def unprotect(): pass\n"
    "def validate_manifest(): pass\n"
    "def manifest_digest(): pass\n"
)


@pytest.mark.parametrize("requested", [None, "1.25"])
def test_resolution_uses_public_version_contract(tmp_path, monkeypatch, requested):
    root = tmp_path / "aifactory"
    calls = []

    def published(value, cli, source_root, **kwargs):
        calls.append((value, source_root, kwargs))
        return {"requested_version": "125", "branch": "release/v1.25", "resolved_ref": COMMIT,
                "source_root": str(source_root)}

    monkeypatch.setattr(runtime.release_version, "published_source", published)
    monkeypatch.setattr(runtime.release_version, "saved_version", lambda folder: "125")
    cli = SimpleNamespace(read=lambda tool, args, raw:
                          HELPER if args[-1].endswith(runtime.HELPER) else "variables:\n  location: swedencentral\n")
    selected = runtime.CatalogRuntime(cli=cli)._resolve(root, requested)
    assert calls == [(requested, tmp_path / "azure-enterprise-scale-ml",
                      {"saved": "125" if requested is None else None,
                       "required_paths": {runtime.HELPER: runtime.CONTRACT}})]
    assert selected["resolved_ref"] == COMMIT
    assert selected["template_variables"] == {"location": "swedencentral"}
    assert selected["helper_sha256"] == hashlib.sha256(HELPER.encode()).hexdigest()


def test_publication_failure_has_actionable_no_fallback_message(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise TicketError("Missing publication", 409)

    monkeypatch.setattr(runtime.release_version, "published_source", missing)
    with pytest.raises(CatalogError, match="Fetch/install.*no fallback"):
        runtime.CatalogRuntime()._resolve(tmp_path / "aifactory", "125")


def test_snapshot_creation_uses_public_adapter_and_rechecks_reused_source(tmp_path, monkeypatch):
    creations, commands = [], []
    repository, run = tmp_path / "cache", tmp_path / "run"

    def materialize(source_root, commit, destination, *, git):
        creations.append((source_root, commit, destination, git))
        helper = destination / Path(runtime.HELPER)
        helper.parent.mkdir(parents=True)
        helper.write_text(HELPER, encoding="utf-8")
        return str(destination)

    def command(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(stdout=COMMIT if "rev-parse" in argv else "")

    monkeypatch.setattr(runtime.release_version, "materialize_source", materialize)
    monkeypatch.setattr(runtime.subprocess, "run", command)
    service = runtime.CatalogRuntime(cli=SimpleNamespace(tools=lambda: {"git": "chosen-git"}))
    selected = {"repository": str(repository), "resolved_ref": COMMIT,
                "helper_sha256": hashlib.sha256(HELPER.encode()).hexdigest()}
    helper, execution = service._materialize(tmp_path / "aifactory", selected, run)
    assert service._materialize(tmp_path / "aifactory", selected, run) == (helper, execution)
    assert creations == [(repository, COMMIT, run / "source", "chosen-git")]
    assert len(commands) == 4
    assert all("core.fsmonitor=false" in argv and any(arg.startswith("core.hooksPath=") for arg in argv)
               for argv in commands)
    assert not execution.exists()
    helper.write_text(HELPER + "# changed\n", encoding="utf-8")
    with pytest.raises(CatalogError, match="does not match"):
        service._materialize(tmp_path / "aifactory", selected, run)


@pytest.mark.parametrize("installed_cache", [False, True])
def test_preparation_reads_installed_source_without_materializing(tmp_path, installed_cache):
    root = tmp_path / "aifactory"
    repository = tmp_path / "published"
    source = root / "config-wizard" / "catalog-sources" / COMMIT / "source" if installed_cache else repository
    text = HELPER + "Cloud = object\nBlocked = ValueError\ndef verify_source(): pass\ndef capabilities(): pass\n"
    helper = source / Path(runtime.HELPER)
    helper.parent.mkdir(parents=True)
    helper.write_text(text, encoding="utf-8")
    planner = FrozenPlanner(SimpleNamespace(materialize=lambda *args: pytest.fail("No checkout before confirmation")))
    version = {"repository": str(repository), "resolved_ref": COMMIT,
               "helper_sha256": hashlib.sha256(text.encode()).hexdigest()}
    module, selected_source = planner.module(root, version)
    assert selected_source == source
    assert callable(module.verify_source)
    if not installed_cache:
        assert not root.exists()


def test_preparation_without_installed_source_explains_prerequisite(tmp_path):
    planner = FrozenPlanner(SimpleNamespace(materialize=lambda *args: pytest.fail("No checkout before confirmation")))
    with pytest.raises(CatalogError, match="Install a clean checkout"):
        planner.module(tmp_path / "aifactory", {"resolved_ref": COMMIT, "repository": str(tmp_path / "missing")})
    assert not (tmp_path / "aifactory").exists()
