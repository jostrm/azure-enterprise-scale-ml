from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HEALTHMODEL = Path(__file__).resolve().parents[1]
REPO = HEALTHMODEL.parent
sys.path.insert(0, str(HEALTHMODEL / "src"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VARIABLES_YAML = (
    REPO / "environment_setup/aifactory/bicep/copy_to_local_settings/"
    "azure-devops/esml-yaml-pipelines/variables/variables.yaml"
)


@pytest.fixture(scope="session")
def metric_definitions() -> dict:
    return json.loads((FIXTURES / "metric-definitions.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def test_env_resources() -> list[dict]:
    return json.loads((FIXTURES / "test-env-resources.json").read_text(encoding="utf-8"))
