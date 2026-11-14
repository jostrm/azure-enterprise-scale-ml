"""Compile bicep/main.bicep and check the contract with the parameter renderer.

Skipped when the Azure CLI with Bicep is not installed on the machine.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache

import pytest

from aifactory_healthmodel import catalog as cat
from aifactory_healthmodel.application.parameters import BICEP_OPTIONS
from conftest import HEALTHMODEL

BICEP = HEALTHMODEL / "bicep"
MONITORING_READER = "43d0d8ad-25c7-4714-9337-8ba259a9fe05"


def _az():
    return shutil.which("az") or shutil.which("az.cmd")


pytestmark = pytest.mark.skipif(_az() is None, reason="Azure CLI with Bicep is required")


@lru_cache(maxsize=4)
def build(path: str) -> tuple[dict, str]:
    result = subprocess.run([_az(), "bicep", "build", "--file", path, "--stdout"],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stderr


def template() -> dict:
    return build(str(BICEP / "main.bicep"))[0]


def resources_of(node: dict):
    items = node.get("resources", [])
    for item in (items.values() if isinstance(items, dict) else items):
        yield item
        if item.get("type") == "Microsoft.Resources/deployments":
            yield from resources_of(item["properties"]["template"])


def test_main_template_compiles_without_warnings():
    _, stderr = build(str(BICEP / "main.bicep"))
    warnings = [line for line in stderr.splitlines()
                if "Warning" in line and "new Bicep release" not in line]
    assert warnings == []


def test_cloudhealth_resources_use_the_catalog_api_version():
    types = {}
    for resource in resources_of(template()):
        if resource["type"].startswith("Microsoft.CloudHealth/"):
            types.setdefault(resource["type"], set()).add(resource["apiVersion"])
    assert set(types) == {
        "Microsoft.CloudHealth/healthmodels",
        "Microsoft.CloudHealth/healthmodels/authenticationsettings",
        "Microsoft.CloudHealth/healthmodels/entities",
        "Microsoft.CloudHealth/healthmodels/relationships",
    }
    assert all(versions == {cat.load_catalog()["apiVersion"]} for versions in types.values())


def test_rendered_parameters_match_template_parameters():
    declared = template()["parameters"]
    produced = {"healthModelName", "location", "modelScope", "rootDisplayName", "readerResourceGroups",
                "entities", "relationships"} | BICEP_OPTIONS
    assert produced <= set(declared)
    required = {name for name, item in declared.items() if "defaultValue" not in item}
    assert required <= {"healthModelName", "location", "rootDisplayName"}


def test_default_alert_policy_alerts_on_root_and_layers_only():
    policy = template()["parameters"]["alertPolicy"]["defaultValue"]
    assert policy == {
        "rootUnhealthySeverity": "Sev1", "rootDegradedSeverity": "Sev3",
        "layerUnhealthySeverity": "Sev2", "layerDegradedSeverity": "",
        "resourceUnhealthySeverity": "", "resourceDegradedSeverity": "",
    }
    assert template()["parameters"]["healthObjective"]["defaultValue"] == 99


def test_model_identity_gets_monitoring_reader_only():
    roles = [r for r in resources_of(template()) if r["type"] == "Microsoft.Authorization/roleAssignments"]
    assert len(roles) == 1
    text = json.dumps(template())
    assert MONITORING_READER in text
    # Contributor/Owner style roles must never be granted by the health model template.
    for forbidden in ("b24988ac-6180-42a0-ab88-20f7382dd24c", "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"):
        assert forbidden not in text


def test_entities_and_relationships_are_batched_loops():
    loops = {r["type"]: r for r in resources_of(template()) if "copy" in r}
    for kind in ("Microsoft.CloudHealth/healthmodels/entities", "Microsoft.CloudHealth/healthmodels/relationships"):
        assert loops[kind]["copy"]["mode"].lower() == "serial"
        assert 1 <= loops[kind]["copy"]["batchSize"] <= 10


def test_minimal_bicepparam_example_builds():
    path = BICEP / "examples" / "minimal.bicepparam"
    result = subprocess.run([_az(), "bicep", "build-params", "--file", str(path), "--stdout"],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    parameters = json.loads(json.loads(result.stdout)["parametersJson"])["parameters"]
    assert parameters["healthModelName"]["value"] == "hm-contoso-prj001-sdc-dev-001"
    assert len(parameters["entities"]["value"]) >= 3


def test_example_parameters_were_rendered_from_the_project_definition():
    import importlib.util
    import re
    path = BICEP / "examples" / "project001-dev.parameters.json"
    text = path.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("render_example", BICEP / "examples" / "render_example.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert json.loads(text) == module.render(), "run: python bicep/examples/render_example.py"
    # Examples are rendered from the anonymized fixture; no real subscription IDs.
    assert set(re.findall(r"/subscriptions/([0-9a-f-]{36})", text)) == {"00000000-0000-0000-0000-0000000000aa"}
