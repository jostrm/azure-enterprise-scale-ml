"""Run only the pure embedded CIDR checker, never source preflight or call Azure."""

import contextlib
import io
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
PREFLIGHT = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "preflight.sh"


def check(monkeypatch, vnet, starts, subnet_overrides=None):
    source = PREFLIGHT.read_text(encoding="utf-8")
    code = source.split('out="$(PF_CIDR="$_cidr_data" "$PYBIN" - <<\'PY\' 2>/dev/null\n', 1)[1].split("\nPY\n", 1)[0]
    subnets = {
        "common": ("172.16.XX.0/26", 28),
        "scoring": ("172.16.XX.64/26", 28),
        "pbi": ("172.16.XX.128/26", 28),
        "bastion": ("172.16.XX.192/26", 26),
        **(subnet_overrides or {}),
    }
    data = [f"ENV|{label}|{octet}" for label, octet in zip(("Dev", "Stage", "Prod"), starts)]
    data += [f"VNET|{vnet}"]
    data += [f"{role}|{cidr}|{minimum}" for role, (cidr, minimum) in subnets.items()]
    monkeypatch.setenv("PF_CIDR", "\n".join(data))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(code, str(PREFLIGHT), "exec"), {})
    return output.getvalue()


@pytest.mark.parametrize("prefix,starts", [
    (18, ("0", "64", "128")), (20, ("0", "16", "32")), (24, ("61", "62", "63")),
    (18, ("0", "", "")),
])
def test_aligned_disjoint_vnets_pass(monkeypatch, prefix, starts):
    assert check(monkeypatch, f"172.16.XX.0/{prefix}", starts) == ""


@pytest.mark.parametrize("vnet,starts,expected", [
    ("172.16.0.0/16", ("61", "62", "63"), "Dev (172.16.0.0/16) overlaps Stage"),
    ("172.16.0.0/18", ("15", "20", "25"), "Dev (172.16.0.0/18) overlaps Stage"),
    ("172.16.XX.0/18", ("61", "62", "63"), "172.16.61.0/18) invalid or not network-aligned"),
    ("172.16.XX.0/16", ("61", "62", "63"), "172.16.61.0/16) invalid or not network-aligned"),
    ("172.16.XX.0/18", ("0", "64", "64"), "Stage (172.16.64.0/18) overlaps Prod"),
    ("172.16.XX.0/20", ("0", "16", "25"), "Prod common_vnet_cidr (172.16.25.0/20)"),
    ("172.16.XX.0/18", ("", "64", "128"), "Dev range must be"),
    ("172.16.XX.0/18", ("0", "256", "128"), "Stage range must be"),
    ("172.16.XX.0/18", ("000", "64", "128"), "invalid or not network-aligned"),
])
def test_invalid_ranges_and_overlapping_vnets_warn(monkeypatch, vnet, starts, expected):
    output = check(monkeypatch, vnet, starts)
    assert "WARN" in output and "FAIL" not in output and "Cannot peer" in output and expected in output
    assert "0/64/128" in output


def test_every_environment_subnet_checked_strictly(monkeypatch):
    output = check(monkeypatch, "172.16.XX.0/18", ("0", "64", "128"),
                   {"bastion": ("172.16.0.192/26", 26)})
    assert "Stage bastion (172.16.0.192/26) is not inside" in output
    assert "Prod bastion (172.16.0.192/26) is not inside" in output
    output = check(monkeypatch, "172.16.XX.0/18", ("0", "64", "128"),
                   {"scoring": ("172.16.XX.65/26", 28)})
    assert output.count("not network-aligned") == 3
    output = check(monkeypatch, "172.16.XX.0/18", ("0", "64", "128"),
                   {"scoring": ("172.16.XX.0/26", 28)})
    assert output.count("CIDR_SUBNET_OVERLAP") == 3


@pytest.mark.parametrize("findings,expected", [
    ([("FAIL", "CIDR_VNET_OVERLAP")], 0),
    ([("WARN", "CIDR_SUBNET_BAD"), ("WARN", "CIDR_VNET_BAD")], 0),
    ([("FAIL", "SEARCH_SKU_UNAVAILABLE")], 1),
    ([("WARN", "SEARCH_QUOTA_UNVALIDATED")], 2),
    ([("FAIL", "CIDR_RANGE_INVALID"), ("FAIL", "RP_NOT_REGISTERED")], 1),
])
def test_cidr_only_warnings_never_trigger_strict_but_nonnetwork_policy_is_unchanged(findings, expected):
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Bash is required for the isolated finding/exit-policy test")
    source = PREFLIGHT.read_text(encoding="utf-8")
    function = "add_finding() {" + source.split("add_finding() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    exits = source[source.index('if [ "$FAIL_COUNT" -gt 0 ]; then'):]
    script = """
set -u
STRICT=true
WARN_ONLY=false
FAIL_COUNT=0
WARN_COUNT=0
CIDR_WARN_COUNT=0
FINDINGS=()
record_report_finding() { printf 'REPORT:%s:%s\\n' "$1" "$2"; }
ci_error() { printf 'ERROR:%s\\n' "$1"; }
ci_warning() { printf 'WARNING:%s\\n' "$1"; }
""" + function + "".join(f"add_finding {severity} {code} 'test finding'\n" for severity, code in findings) + exits
    result = subprocess.run([str(bash), "--noprofile", "--norc", "-c", script],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == expected, result.stdout + result.stderr
    for _, code in findings:
        if code.startswith("CIDR_"):
            assert f"REPORT:WARN:{code}" in result.stdout
            assert f"ERROR:[{code}]" not in result.stdout


def test_bicep_substitutes_same_environment_octet_in_vnet_and_common_subnets():
    main = ROOT / "environment_setup" / "aifactory" / "bicep" / "esml-common" / "main" / "12-networkCommon.bicep"
    source = main.read_text(encoding="utf-8")
    for name in ("common_vnet_cidr", "common_subnet_cidr", "common_subnet_scoring_cidr",
                 "common_pbi_subnet_cidr", "common_bastion_subnet_cidr"):
        assert re.search(rf"var {name}_v = replace\({name},\s*'XX',\s*cidr_range\)", source)
    assert "common_vnet_cidr: common_vnet_cidr_v" in source
    templates = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings"
    ado = (templates / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-common" /
           "infra-aifactory-common.yaml").read_text(encoding="utf-8")
    for environment in ("dev", "test", "prod"):
        assert f"cidr_range: $({environment}_cidr_range)" in ado
    gha = (templates / "github-actions" / "03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    for environment in ("dev", "stage", "prod"):
        assert f'create_or_update_variable "{environment}" "CIDR_RANGE" "${environment.upper()}_CIDR_RANGE"' in gha


@pytest.mark.parametrize("index", [0, 1, 2])
def test_bootstrap_address_diagnostic_branches_warn_without_exiting_or_repairing(index):
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Bash is required for isolated bootstrap address diagnostics")
    source = (ROOT / "bootstrap" / "lib" / "create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    branches = list(re.finditer(
        r"(?m)^([ ]*)if ! aif_validate_(?:cidr|access_hub_cidr|network_plan)\b[\s\S]*?^\1fi", source))
    assert len(branches) == 3
    script = """
set -eu
AIF_DEV_VNET_CIDR=invalid-dev
AIF_ACCESS_HUB_VNET_CIDR=invalid-hub
AIF_VPN_CLIENT_CIDR=invalid-vpn
aif_validate_cidr() { return 1; }
aif_validate_access_hub_cidr() { return 1; }
aif_validate_network_plan() { return 1; }
aif_warn() { printf 'WARNING:%s\\n' "$1"; }
""" + branches[index].group() + """
printf 'VALUES:%s:%s:%s\\n' "$AIF_DEV_VNET_CIDR" "$AIF_ACCESS_HUB_VNET_CIDR" "$AIF_VPN_CLIENT_CIDR"
"""
    result = subprocess.run([str(bash), "--noprofile", "--norc", "-c", script],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARNING:Address planning:" in result.stdout
    assert "VALUES:invalid-dev:invalid-hub:invalid-vpn" in result.stdout
