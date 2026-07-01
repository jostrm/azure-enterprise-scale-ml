"""Base layer: repository paths and config-file parsing.

Single source of truth for where AI Factory settings live, so domain/app
layers and tests never hard-code paths. Keep this module dependency-free
(stdlib only) so unit tests run offline without pip installs.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# test-bicep/base/config.py -> .../unit-tests/test-bicep/base
# parents: 0=base 1=test-bicep 2=unit-tests 3=environment_setup 4=<repo root>
REPO_ROOT = Path(__file__).resolve().parents[4]

CLS = REPO_ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"

GH_ENV_TEMPLATE = CLS / "github-actions/.env.template"
GH_INFRA_COMMON = CLS / "github-actions/infra-common.yml"
GH_INFRA_PROJECT = CLS / "github-actions/infra-project.yml"

ADO_VARIABLES_YAML = (
    CLS / "azure-devops/esml-yaml-pipelines/variables/variables.yaml"
)

GENAI_BICEP_DIR = REPO_ROOT / "environment_setup/aifactory/bicep/esml-genai-1"
COMMON_BICEP_DIR = REPO_ROOT / "environment_setup/aifactory/bicep/esml-common"


def parse_env_template(path: Path = GH_ENV_TEMPLATE) -> dict[str, str]:
    """Parse KEY="value" lines from a .env file, dropping comments."""
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        raw = raw.split("#", 1)[0].strip()
        data[key.strip()] = raw.strip('"').strip("'")
    return data


def parse_yaml_vars(path: Path = ADO_VARIABLES_YAML) -> dict[str, str]:
    """Parse two-space-indented `key: value` entries from variables.yaml."""
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("  ") or line.strip().startswith("#"):
            continue
        match = re.match(r"\s{2}([A-Za-z0-9_]+):\s*(.*)", line)
        if not match:
            continue
        key, raw = match.groups()
        data[key] = raw.split("#", 1)[0].strip().strip('"')
    return data


@lru_cache(maxsize=1)
def env_defaults() -> dict[str, str]:
    return parse_env_template()


@lru_cache(maxsize=1)
def yaml_defaults() -> dict[str, str]:
    return parse_yaml_vars()
