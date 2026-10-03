"""The readme documents every catalog profile, CLI command and pipeline."""
from __future__ import annotations

from aifactory_healthmodel import catalog as cat
from aifactory_healthmodel.cli import HANDLERS, LIFECYCLE
from conftest import HEALTHMODEL

README = (HEALTHMODEL / "readme.md").read_text(encoding="utf-8")


def test_every_catalog_profile_is_documented():
    missing = [p["key"] for p in cat.load_catalog()["profiles"] if f"`{p['key']}`" not in README]
    assert missing == []


def test_every_cli_command_is_documented():
    for command in (*LIFECYCLE, *HANDLERS):
        assert f"aif_healthmodel.py {command}" in README, command


def test_pipelines_and_default_alert_policy_are_documented():
    for text in ("infra-project-healthmodel.yaml", "infra-project-healthmodel.yml", "**Sev1**", "**Sev3**", "**Sev2**"):
        assert text in README
