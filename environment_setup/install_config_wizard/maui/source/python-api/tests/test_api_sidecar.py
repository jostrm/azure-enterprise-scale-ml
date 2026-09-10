import pytest
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from src import api_sidecar, catalog_worker


def test_sidecar_requires_loopback(monkeypatch):
    monkeypatch.setattr(
        api_sidecar,
        "parse_args",
        lambda: type(
            "Args", (), {"host": "0.0.0.0", "port": 8765, "parent_pid": None}
        )(),
    )
    monkeypatch.setenv("AIFACTORY_API_KEY", "test-only")
    with pytest.raises(SystemExit, match="loopback"):
        api_sidecar.main()


def test_sidecar_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        api_sidecar,
        "parse_args",
        lambda: type(
            "Args", (), {"host": "127.0.0.1", "port": 8765, "parent_pid": None}
        )(),
    )
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="AIFACTORY_API_KEY"):
        api_sidecar.main()


def test_sidecar_starts_uvicorn_on_loopback(monkeypatch):
    called = {}
    monkeypatch.setattr(
        api_sidecar,
        "parse_args",
        lambda: type(
            "Args", (), {"host": "127.0.0.1", "port": 8765, "parent_pid": 42}
        )(),
    )
    monkeypatch.setenv("AIFACTORY_API_KEY", "test-only")
    watched = []
    monkeypatch.setattr(api_sidecar, "watch_parent", watched.append)
    monkeypatch.setattr(
        api_sidecar.uvicorn,
        "run",
        lambda app, **options: called.update(app=app, options=options),
    )
    api_sidecar.main()
    assert called["app"] is api_sidecar.app
    assert called["options"]["host"] == "127.0.0.1"
    assert called["options"]["port"] == 8765
    assert watched == [42]


def test_worker_routes_exact_arguments_and_owns_api_parent_without_http(monkeypatch):
    forwarded = []
    watched = []
    arguments = ["--helper", r"C:\selected source\bootstrap\lib\factory_lifecycle.py",
                 "--protected-manifest", r"C:\selected run\configuration.dpapi", "--expected-hash", "a" * 64]
    monkeypatch.setattr(sys, "argv", ["aifactory-api.exe", "--catalog-worker", "--parent-pid", "42", *arguments])
    monkeypatch.delenv("AIFACTORY_API_KEY", raising=False)
    monkeypatch.setattr(api_sidecar, "watch_parent", watched.append)
    monkeypatch.setattr(catalog_worker, "main", lambda argv: forwarded.append(argv) or 2)
    monkeypatch.setattr(api_sidecar.uvicorn, "run", Mock(side_effect=AssertionError("No worker HTTP server")))
    assert api_sidecar.main() == 2
    assert watched == [42]
    assert forwarded == [arguments]


def test_worker_execution_requires_explicit_parent_before_loading_inputs(monkeypatch):
    worker = Mock(side_effect=AssertionError("Unowned worker cannot execute"))
    monkeypatch.setattr(catalog_worker, "main", worker)
    monkeypatch.setattr(sys, "argv", ["aifactory-api.exe", "--catalog-worker", "--helper", "unused"])
    with pytest.raises(SystemExit) as error:
        api_sidecar.main()
    assert error.value.code == 2
    worker.assert_not_called()


@pytest.mark.parametrize("pid", [0, -1, 2**32])
def test_invalid_parent_is_rejected(pid):
    with pytest.raises(SystemExit, match="valid owning parent"):
        api_sidecar.watch_parent(pid)


def test_current_process_cannot_claim_to_be_its_own_parent():
    with pytest.raises(SystemExit, match="distinct"):
        api_sidecar.watch_parent(os.getpid())


@pytest.mark.skipif(os.name != "nt", reason="Windows parent handles")
def test_parent_handle_is_closed_and_only_owned_process_tree_is_stopped(monkeypatch):
    handle = 2**40
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=handle),
                             WaitForSingleObject=Mock(side_effect=[258, 0]), CloseHandle=Mock())
    targets, exits, commands = [], [], []
    monkeypatch.setattr(api_sidecar, "_parent_kernel", lambda: kernel)
    monkeypatch.setattr(api_sidecar.threading, "Thread",
                        lambda *, target, daemon: SimpleNamespace(start=lambda: targets.append(target)))
    monkeypatch.setattr(api_sidecar.subprocess, "Popen", lambda argv, **kwargs: commands.append(argv))
    monkeypatch.setattr(api_sidecar.os, "_exit", exits.append)
    api_sidecar.watch_parent(42)
    assert kernel.WaitForSingleObject.call_args.args == (handle, 0)
    assert len(targets) == 1
    targets[0]()
    kernel.CloseHandle.assert_called_once_with(handle)
    assert commands[0][1:] == ["/PID", str(os.getpid()), "/T", "/F"]
    assert exits == [0]


@pytest.mark.skipif(os.name != "nt", reason="Windows parent handles")
def test_already_exited_parent_prevents_worker_start(monkeypatch):
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=123),
                             WaitForSingleObject=Mock(return_value=0), CloseHandle=Mock())
    monkeypatch.setattr(api_sidecar, "_parent_kernel", lambda: kernel)
    with pytest.raises(SystemExit, match="parent process is unavailable"):
        api_sidecar.watch_parent(42)
    kernel.CloseHandle.assert_called_once_with(123)
