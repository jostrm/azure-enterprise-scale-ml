"""Run only the pure embedded CIDR checker, never source preflight or call Azure."""

import contextlib
import io
import re
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
def test_invalid_ranges_and_overlapping_vnets_fail(monkeypatch, vnet, starts, expected):
    output = check(monkeypatch, vnet, starts)
    assert "FAIL" in output and "Cannot peer" in output and expected in output
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
