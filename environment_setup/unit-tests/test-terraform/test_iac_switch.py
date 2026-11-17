"""The `iac` feature switch (Joakim, 2026-11-16): `bicep` by default, `terraform` by choice.

`iac` and the Terraform state settings are keys of the factory configuration (variables.json `dev`), the one
place they live. The Factory API reads them, installs `infra-common-terraform.yml` instead of `infra-common.yml`
and sets the workflow's TFSTATE_* GitHub variables from the tfstate* keys. These tests pin that contract here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VARIABLES = ROOT / "environment_setup" / "aifactory" / "variables.json"
TERRAFORM = ROOT / "environment_setup" / "aifactory" / "terraform"
WORKFLOW = TERRAFORM / "copy_to_local_settings" / "github-actions" / "infra-common-terraform.yml"
DOCS = ROOT / "documentation" / "gh-io" / "docs" / "iac" / "terraform.md"

# Configuration key -> the GitHub variable infra-common-terraform.yml reads.
STATE_KEYS = {
    "tfstateResourceGroup": "TFSTATE_RESOURCE_GROUP",
    "tfstateStorageAccount": "TFSTATE_STORAGE_ACCOUNT",
    "tfstateContainer": "TFSTATE_CONTAINER",
    "tfstateSubscriptionId": "TFSTATE_SUBSCRIPTION_ID",
}


def _dev() -> dict:
    return json.loads(VARIABLES.read_text(encoding="utf-8-sig"))["dev"]


def test_iac_defaults_to_bicep_in_the_factory_configuration():
    assert _dev()["iac"] == "bicep"


def test_terraform_state_keys_have_their_workflow_defaults():
    dev = _dev()
    assert {key: dev.get(key) for key in STATE_KEYS} == {
        "tfstateResourceGroup": "", "tfstateStorageAccount": "", "tfstateContainer": "tfstate",
        "tfstateSubscriptionId": ""}


def test_every_state_key_maps_to_a_github_variable_the_workflow_reads():
    read = set(re.findall(r"vars\.(TFSTATE_[A-Z_]+)", WORKFLOW.read_text(encoding="utf-8")))
    assert read == set(STATE_KEYS.values())


def test_readme_and_docs_explain_how_to_choose_terraform():
    for path in (TERRAFORM / "readme.md", DOCS):
        text = path.read_text(encoding="utf-8")
        assert '"iac": "terraform"' in text, path
        for key in STATE_KEYS:
            assert key in text, (path, key)
