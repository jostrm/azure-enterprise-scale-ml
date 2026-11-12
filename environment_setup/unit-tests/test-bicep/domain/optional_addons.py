"""Shared checks for the optional Foundry add-on launchers the project pipeline runs last (deploy.py apply --apply).

The pipeline apply of an optional add-on never fails the project run on an incomplete configuration: it warns in GitHub
Actions and Azure DevOps and skips without contacting Azure (byor-159 run 43192891708 followed the create-factory
quickstart, which turns the MCP on before its images and app registration exist). validate, plan, apply without
--apply and direct run() callers (the add-aifactory-agent-chat CLI) stay strict.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SKIPPED = "skipped-incomplete-configuration"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
# Pipeline-resolved naming of project001 Dev, as the project pipeline exports it.
PROJECT001_DEV = {
    "project_number_000": "001", "dev_test_prod": "dev", "dev_test_prod_sub_id": SUBSCRIPTION, "tenantId": TENANT,
    "admin_location": "swedencentral", "admin_aifactoryPrefixRG": "acme-1-", "projectPrefix": "esml-",
    "admin_locationSuffix": "sdc", "admin_aifactorySuffixRG": "-001", "projectSuffix": "-rg",
    "deleteAllServicesForProject": "false", "deleteAllForProject": "false",
}


def load_launcher(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_session(*_):
    raise AssertionError("an incomplete configuration must not create an Azure session")


def assert_pipeline_apply_warns_and_skips(module, environ: dict, needle: str, capsys) -> None:
    assert module.main(["apply", "--apply"], environ, no_session) == 0
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert any(line.startswith("::warning ") and needle in line for line in lines), out
    assert any(line.startswith("##vso[task.logissue type=warning]") and needle in line for line in lines), out
    result = json.loads(out[out.index("{\n"):])
    assert result["mode"] == SKIPPED and result["mutations"] is False and needle in result["reason"]
    assert needle in err


def assert_strict_outside_the_pipeline_apply(module, environ: dict, capsys) -> None:
    for argv in (["validate"], ["plan"], ["apply"]):
        assert module.main(argv, environ, no_session) == 1, argv
        out, err = capsys.readouterr()
        assert "::warning" not in out and "##vso[" not in out, argv
        assert "error" in err.lower(), argv
    arguments = SimpleNamespace(command="apply", apply=True, output=None, skip_knowledge=False)
    with pytest.raises(ValueError):
        module.run(arguments, environ, no_session)
