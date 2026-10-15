"""Offline creation of missing ADO JSON configuration from existing YAML."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIBRARY = ROOT / "bootstrap/lib/aifactory_scaleset_config.py"
LAUNCHER = ROOT / "bootstrap/ADO-update-aifactory-and-run-project.sh"
DEFAULT_REGIONS = ["francecentral", "denmarkeast", "italynorth", "norwayeast", "germanywestcentral"]


@pytest.fixture
def config():
    spec = importlib.util.spec_from_file_location("ado_json_initialization_config", LIBRARY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_json_preserves_customer_yaml_without_template_identity(config, tmp_path):
    source = tmp_path / "variables.yaml"
    source.write_text(
        'variables:\n'
        '  azureDevOpsTenantId: "customer.example"\n'
        '  project_number_000: "012"\n'
        '  admin_location: "swedencentral"\n'
        '  tenantId: "$(deploymentTenant)"\n'
        '  enableAISearch: "false"\n'
        '  tagsProject: \'{"message":"keep # and : punctuation"}\'\n'
        '  quoted: \'O\'\'Brien\' # comment\n'
        '  blank: ""\n'
        '  unquotedBlank: # intentionally empty\n'
        '  old_custom_key: "preserved"\n',
        encoding="utf-8",
    )
    target = tmp_path / "aifactory/variables.json"
    assert config.initialize_json_from_ado_yaml(source, target)
    values = json.loads(target.read_text(encoding="utf-8"))["dev"]
    assert values == {
        "azureDevOpsTenantId": "customer.example", "project_number_000": "012",
        "admin_location": "swedencentral", "tenantId": "$(deploymentTenant)",
        "enableAISearch": "false", "tagsProject": {"message": "keep # and : punctuation"},
        "quoted": "O'Brien", "blank": "", "unquotedBlank": "", "old_custom_key": "preserved",
    }
    assert source.read_text(encoding="utf-8").startswith("variables:\n")


@pytest.mark.parametrize("setting,expected", [
    ("'[]'", []), ('""', ""), ("", ""),
    ("'" + json.dumps(DEFAULT_REGIONS) + "'", DEFAULT_REGIONS),
])
def test_region_arrays_and_explicit_disabling_survive_creation(config, tmp_path, setting, expected):
    source = tmp_path / "variables.yaml"
    source.write_text(f"variables:\n  aiSearchFallbackLocationArrayDev: {setting}\n", encoding="utf-8")
    target = tmp_path / "variables.json"
    config.initialize_json_from_ado_yaml(source, target)
    assert json.loads(target.read_text())["dev"]["aiSearchFallbackLocationArrayDev"] == expected


@pytest.mark.parametrize("existing", ['{"dev":{"keep":"exact"}}\n', "not-json\n", ""])
def test_existing_json_is_never_overwritten_or_reformatted(config, tmp_path, existing):
    target = tmp_path / "variables.json"
    target.write_text(existing, encoding="utf-8")
    assert not config.initialize_json_from_ado_yaml(tmp_path / "missing.yaml", target)
    assert target.read_text(encoding="utf-8") == existing


@pytest.mark.parametrize("content", [
    "", "variables:\n", "other:\n  key: value\n",
    'variables:\n  key: first\n  key: second\n',
    'variables:\n  key: "unclosed\n',
    "variables:\n  key: |\n    multiline\n",
    "variables:\n  key:\n    nested: value\n",
    "variables:\n- group: secret-group\n",
    "variables:\n\t key: value\n",
    "variables:\n  aiSearchFallbackLocationArrayDev: '[broken]'\n",
])
def test_invalid_or_unsupported_yaml_fails_before_creating_json(config, tmp_path, content):
    source = tmp_path / "variables.yaml"
    source.write_text(content, encoding="utf-8")
    target = tmp_path / "variables.json"
    with pytest.raises(ValueError):
        config.initialize_json_from_ado_yaml(source, target)
    assert not target.exists()


def test_real_ado_template_is_readable_and_missing_fields_get_refreshed_defaults(config, tmp_path):
    source = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml"
    target = tmp_path / "variables.json"
    config.initialize_json_from_ado_yaml(source, target)
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["dev"]["aiSearchFallbackLocationArrayDev"] == DEFAULT_REGIONS
    assert document["dev"]["aiSearchFallbackLocationArrayStageProd"] == DEFAULT_REGIONS
    assert document["dev"]["project_number_000"] == "001"


def test_missing_yaml_fails_without_creating_json(config, tmp_path):
    target = tmp_path / "variables.json"
    with pytest.raises(FileNotFoundError):
        config.initialize_json_from_ado_yaml(tmp_path / "missing.yaml", target)
    assert not target.exists()


def test_bom_crlf_and_header_comments_are_preserved_as_values(config, tmp_path):
    source = tmp_path / "variables.yaml"
    source.write_bytes(b'\xef\xbb\xbfvariables: # active configuration\r\n  project_number_000: "012"\r\n')
    target = tmp_path / "variables.json"
    config.initialize_json_from_ado_yaml(source, target)
    assert json.loads(target.read_text()) == {"dev": {"project_number_000": "012"}}


@pytest.mark.parametrize("setting,expected", [(None, DEFAULT_REGIONS), ("'[]'", []), ('""', "")])
def test_created_json_flows_through_actual_template_merge_and_ado_override(config, tmp_path, setting, expected):
    source = tmp_path / "variables.yaml"
    source.write_text(
        'variables:\n  project_number_000: "012"\n  azureDevOpsTenantId: "customer.example"\n'
        + (f"  aiSearchFallbackLocationArrayDev: {setting}\n" if setting is not None else ""),
        encoding="utf-8",
    )
    active = tmp_path / "active.json"
    config.initialize_json_from_ado_yaml(source, active)
    output = tmp_path / "merged.json"
    marker = '  "${PYTHON[@]}" - "$CONFIG_TEMPLATE_FILE" "$state_dir/variables.json" "$CONFIG_FILE" <<\'PY\'\n'
    merge = LAUNCHER.read_text(encoding="utf-8").split(marker, 1)[1].split("\nPY\n", 1)[0]
    result = subprocess.run(
        [sys.executable, "-", str(ROOT / "environment_setup/aifactory/variables.json"), str(active), str(output)],
        input=merge, cwd=tmp_path, text=True, capture_output=True, timeout=30,
        env={**os.environ, "PYTHONPATH": str(LIBRARY.parent)},
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(output.read_text())
    assert document["dev"]["project_number_000"] == "012"
    assert document["dev"]["azureDevOpsTenantId"] == "customer.example"
    assert document["dev"]["aiSearchFallbackLocationArrayDev"] == expected
    assert document["dev"]["aiSearchFallbackLocationArrayStageProd"] == DEFAULT_REGIONS
    override_path = ROOT / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("ado_created_json_override", override_path)
    overrides = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overrides)
    serialized, _ = overrides.selected_values(document, "dev")
    assert serialized["project_number_000"] == "012"
    assert serialized["aiSearchFallbackLocationArrayDev"] == (
        expected if isinstance(expected, str) else json.dumps(expected, separators=(",", ":")))


@pytest.mark.parametrize("json_enabled,project_only,existing,created", [
    ("true", "false", False, True), ("false", "false", False, False),
    ("true", "true", False, False), ("true", "false", True, False),
])
@pytest.mark.parametrize("helper_layout", ["local", "submodule", "stale-local"])
def test_actual_launcher_initialization_runs_before_tenant_lookup(
        tmp_path, json_enabled, project_only, existing, created, helper_layout):
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash required")
    text = LAUNCHER.read_text(encoding="utf-8")
    start = text.index("ensure_json_configuration() {")
    end = text.index("\nensure_json_configuration\n", start) + len("\nensure_json_configuration\n")
    assert end < text.index('ado_tenant="${ADO_TENANT:-}"')
    root = tmp_path / "consumer"
    (root / "lib").mkdir(parents=True)
    library = root / ("lib" if helper_layout == "local" else "azure-enterprise-scale-ml/bootstrap/lib")
    library.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LIBRARY, library / "aifactory_scaleset_config.py")
    if helper_layout == "stale-local":
        (root / "lib/aifactory_scaleset_config.py").write_text("# Older installed helper.\n", encoding="utf-8")
    source = root / "variables.yaml"
    source.write_text('variables:\n  azureDevOpsTenantId: "customer.example"\n  project_number_000: "012"\n',
                      encoding="utf-8")
    target = root / "aifactory/variables.json"
    if existing:
        target.parent.mkdir()
        target.write_text('{"dev":{"keep":"unchanged"}}\n', encoding="utf-8")
    script = (
        'set -euo pipefail\n'
        'PYTHON=("$TEST_PYTHON")\nSCRIPT_DIR="$TEST_ROOT"\nREPO_ROOT="$TEST_ROOT"\n'
        'CONFIG_FILE=aifactory/variables.json\nVARIABLES_FILE=variables.yaml\n'
        'use_json_override="$JSON_ENABLED"\nproject_only="$PROJECT_ONLY"\n'
        'aif_info() { printf "%s\\n" "$*"; }\naif_success() { printf "%s\\n" "$*"; }\n'
        'aif_error() { printf "%s\\n" "$*" >&2; }\n'
        'git() { exit 91; }\naz() { exit 92; }\n'
        + text[start:end]
    )
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-c", script], cwd=root, capture_output=True,
        text=True, timeout=30,
        env={**os.environ, "TEST_PYTHON": Path(sys.executable).as_posix(),
             "TEST_ROOT": root.as_posix(), "JSON_ENABLED": json_enabled, "PROJECT_ONLY": project_only},
    )
    assert result.returncode == 0, result.stderr
    assert target.exists() == (created or existing)
    if created:
        assert json.loads(target.read_text())["dev"]["azureDevOpsTenantId"] == "customer.example"
    if existing:
        assert target.read_text() == '{"dev":{"keep":"unchanged"}}\n'
