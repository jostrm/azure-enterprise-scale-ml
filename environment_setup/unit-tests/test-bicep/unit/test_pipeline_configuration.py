"""API-free configuration is a schema-2 draft, never deployment authorization."""

import importlib
import json
import socket
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
configuration = importlib.import_module("pipeline_configuration")
inputs = importlib.import_module("pipeline_inputs")
TENANT = "44444444-4444-4444-8444-444444444444"
SUB = "55555555-5555-4555-8555-555555555555"


def spec(provider="gha"):
    return {"factory": "acme-ai", "prefix": "acme-", "region": "swedencentral", "region_short": "sdc",
            "tenant": TENANT, "subscription": SUB, "provider": provider, "environment": "dev",
            "scale_set": "001", "project": "007", "cidr": "10.140.0.0/18", "max_projects": 7,
            "version": "main", "network_mode": "private"}


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_starter_creates_valid_initial_config_without_api(tmp_path, monkeypatch, provider):
    def reject(*args, **kwargs):
        raise AssertionError("Configuration generation must not call the Factory API")
    monkeypatch.setattr(socket, "create_connection", reject)
    document = configuration.initial_document(ROOT, spec(provider))
    inputs.validate_register(document)
    configuration.write_new_root(tmp_path, "azurefactory", document)
    result = inputs.resolve_request(tmp_path, {
        "schema": 1, "scenario": 1, "provider": provider, "factory": "acme-ai", "environment": "dev",
        "scale_set": "001", "project": "007", "source_ref": "refs/heads/main", "source_commit": "a" * 40})
    assert result["document"] == document
    assert result["factory"]["status"] == "draft"
    assert not result["document"]["bindings"]
    values = result["variables"][result["projects"][0]["id"]]["dev"]
    assert values["project_number_000"] == "007"
    assert values["tenantId"] == TENANT
    assert values["enablePublicGenAIAccess"] == "false"
    assert values["allowPublicAccessWhenBehindVnet"] == "false"
    assert "aifactory_version" not in document["configurations"][result["factory"]["id"]]["factory"]
    assert not (tmp_path / "azurefactory" / ".azurefactory").exists()


def test_existing_destination_is_never_overwritten(tmp_path):
    document = configuration.initial_document(ROOT, spec())
    configuration.write_new_root(tmp_path, "azurefactory", document)
    original = (tmp_path / "azurefactory" / "register.json").read_bytes()
    with pytest.raises(inputs.InputError, match="destination"):
        configuration.write_new_root(tmp_path, "azurefactory", document)
    assert (tmp_path / "azurefactory" / "register.json").read_bytes() == original


def test_explicit_settings_cannot_retarget_initial_config():
    values = configuration.initial_document(ROOT, spec())
    factory = values["factories"][0]
    project = factory["projects"][0]
    variables = values["configurations"][factory["id"]]["variables"][project["id"]]
    variables["dev"]["tenantId"] = SUB
    with pytest.raises(inputs.InputError, match="identity"):
        configuration.initial_document(ROOT, spec(), variables=variables)


def test_configuration_outputs_match_register_projections(tmp_path):
    document = configuration.initial_document(ROOT, spec())
    configuration.write_new_root(tmp_path, "azurefactory", document)
    factory = document["factories"][0]
    projected = json.loads((tmp_path / "azurefactory" / "factories" / "acme-ai" / "factory.json").read_text())
    assert projected["id"] == factory["id"]
    assert projected["generation"] == document["generation"]
    scale = factory["scale_sets"][0]
    assert document["configurations"][factory["id"]]["scale_sets"][scale["id"]]["orchestrator"] == "gha"


@pytest.mark.parametrize("field,value", [
    ("project", "7"), ("scale_set", "000"), ("tenant", "invalid"), ("cidr", "10.0.0.1/18"),
    ("version", "124"), ("provider", "api"), ("network_mode", "auto"), ("environment", "all"),
])
def test_invalid_starter_never_writes(tmp_path, field, value):
    with pytest.raises((inputs.InputError, ValueError)):
        configuration.initial_document(ROOT, spec() | {field: value})
    assert not list(tmp_path.iterdir())


def test_add_scale_and_project_generate_new_reviewable_draft_without_changing_original():
    original = configuration.initial_document(ROOT, spec())
    before = json.dumps(original, sort_keys=True)
    added = configuration.add_scale(original, "acme-ai", {
        "environment": "dev", "scale_set": "002", "tenant": TENANT, "subscription": SUB,
        "provider": "gha", "cidr": "10.141.0.0/18", "max_projects": 7})
    drafted = configuration.upsert_project(ROOT, added, "acme-ai", "dev", "002", "008")
    inputs.validate_register(drafted)
    assert json.dumps(original, sort_keys=True) == before
    factory = drafted["factories"][0]
    assert len(factory["scale_sets"]) == 2 and len(factory["projects"]) == 2
    new_project = next(p for p in factory["projects"] if p["number"] == "008")
    assert new_project["storage_suffix"] == "002"
    values = drafted["configurations"][factory["id"]]["variables"][new_project["id"]]
    assert values["dev"]["admin_aifactorySuffixRG"] == "-002"
    assert values["dev"]["project_number_000"] == "008"


def test_project_update_is_explicit_and_preserves_identity_and_other_settings():
    original = configuration.initial_document(ROOT, spec())
    factory = original["factories"][0]
    project = factory["projects"][0]
    import copy
    variables = copy.deepcopy(original["configurations"][factory["id"]]["variables"][project["id"]])
    variables["dev"]["admin_aiSearchTier"] = "standard"
    updated = configuration.upsert_project(ROOT, original, "acme-ai", "dev", "001", "007", variables=variables)
    assert updated["factories"] == original["factories"]
    assert updated["configurations"][factory["id"]]["variables"][project["id"]] == variables
    with pytest.raises(inputs.InputError, match="explicit"):
        configuration.upsert_project(ROOT, original, "acme-ai", "dev", "001", "007")


def test_adding_duplicate_scale_is_not_an_update():
    original = configuration.initial_document(ROOT, spec())
    with pytest.raises(inputs.InputError, match="duplicate"):
        configuration.add_scale(original, "acme-ai", {
            "environment": "dev", "scale_set": "001", "tenant": TENANT, "subscription": SUB,
            "provider": "gha", "cidr": "10.141.0.0/18", "max_projects": 7})


def test_subnet_allocator_only_reads_four_common_subnets(monkeypatch):
    import ipaddress
    expected = [ipaddress.ip_network(f"0.0.0.{i * 64}/26") for i in range(4)]

    class Network:
        version, prefixlen = 4, 0

        def __str__(self):
            return "0.0.0.0/0"

        def subnets(self, new_prefix):
            assert new_prefix == 26
            yield from expected
            raise AssertionError("The allocator must not materialize millions of unused subnet objects")

    monkeypatch.setattr(configuration.aifactory_scaleset_config.ipaddress, "ip_network", lambda *a, **k: Network())
    plan = configuration.aifactory_scaleset_config.subnet_plan("0.0.0.0/0")
    assert plan["common_bastion_subnet_cidr"] == "0.0.0.192/26"
