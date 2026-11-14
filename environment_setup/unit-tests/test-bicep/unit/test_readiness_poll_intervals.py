"""Offline contract: readiness polls look often, and their total patience is not shortened.

Five loops already poll a real condition (capability host state, APIM SKU update state, Application Gateway
backend health) but slept 20 or 30 seconds between looks, so a run noticed readiness up to that much too late.
Each loop now looks every 5 or 10 seconds, and its attempts times its interval is at least the old budget, so
a slow resource gets the same time as before.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
SETTINGS = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
ADO_PROJECT = SETTINGS / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
GHA_PROJECT = SETTINGS / "github-actions/infra-project-phase.yml"
ADO_GATEWAY = SETTINGS / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-2-ai-gateway.yaml"
GHA_GATEWAY = SETTINGS / "github-actions/infra-ai-gateway.yml"
SCALESET = ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh"
CAPHOST_STEP = "69-wait-account-caphost-succeeded"


def ado_caphost_wait() -> str:
    steps = yaml.safe_load(ADO_PROJECT.read_text(encoding="utf-8"))["steps"]
    return next(s for s in steps if s.get("displayName") == CAPHOST_STEP)["inputs"]["inlineScript"]


def gha_caphost_wait() -> str:
    steps = yaml.safe_load(GHA_PROJECT.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]
    return next(s for s in steps if s.get("name") == CAPHOST_STEP)["run"]


def apim_sku_wait(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    loops = re.findall(r"for attempt in \{1\.\.\d+\}; do.*?\n\s*done", text, flags=re.DOTALL)
    assert len(loops) == 1, f"expected one APIM SKU wait loop in {path.name}"
    assert "properties.provisioningState" in loops[0]
    return loops[0]


def app_gateway_health_wait() -> str:
    text = SCALESET.read_text(encoding="utf-8")
    body = text[text.index("aif_deploy_simple_application_gateway() {"):]
    return body[:body.index("\n}\n")]


def budget(loop: str) -> tuple[int, int]:
    """(attempts, seconds between looks) of a `max_attempts=N` or `{1..N}` loop with one sleep length."""
    attempts = re.search(r"max_attempts=(\d+)|for attempt in \{1\.\.(\d+)\}", loop)
    sleeps = set(re.findall(r"\bsleep (\d+)\b", loop))
    assert attempts and len(sleeps) == 1, (attempts, sleeps)
    return int(attempts.group(1) or attempts.group(2)), int(sleeps.pop())


@pytest.mark.parametrize("name,loop,max_interval,old_budget_seconds", [
    ("ADO account capability host", ado_caphost_wait, 5, 60 * 20),
    ("GHA account capability host", gha_caphost_wait, 5, 45 * 20),
    ("ADO APIM SKU update", lambda: apim_sku_wait(ADO_GATEWAY), 10, 180 * 30),
    ("GHA APIM SKU update", lambda: apim_sku_wait(GHA_GATEWAY), 10, 180 * 30),
    ("Simple-mode Application Gateway health", app_gateway_health_wait, 10, 20 * 30),
])
def test_readiness_poll_looks_often_and_keeps_its_old_budget(name, loop, max_interval, old_budget_seconds):
    attempts, interval = budget(loop())
    assert interval <= max_interval, f"{name}: looks only every {interval}s"
    assert attempts * interval >= old_budget_seconds, f"{name}: gives up after {attempts * interval}s, before {old_budget_seconds}s"


def test_apim_sku_wait_is_the_same_in_both_twins():
    assert budget(apim_sku_wait(ADO_GATEWAY)) == budget(apim_sku_wait(GHA_GATEWAY))
