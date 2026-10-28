"""Time budgets the bootstrap helpers define themselves (2026-10-27: doubled after aif-138 COMMON ran out of time;
2026-10-28: every review window and the network budgets keep a margin of three over their longest observed use).

Each budget is a named module constant so its value is pinned here once and documented in pink
docs/operations/Timeouts-and-limits.md. Budgets that stay unchanged on purpose are pinned too, with the reason.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
sys.path.insert(0, str(LIB))


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_time_budget_tests", LIB / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fl = load("factory_lifecycle")
rp = load("registered_prerequisites")
hlf = load("hub_lock_foundation")
hpt = load("hub_private_transition")
rr = load("registered_repository")
rb = load("runner_bootstrap")
fe = load("factory_enrollment")
prs = load("provider_repository_state")
cnp = load("common_network_preservation")
pd = load("project_deployment")
afd = load("all_factories_dashboard")
rv = load("release_version")
fdp = load("factory_deletion_pipeline")


@pytest.mark.parametrize("module, name, value", [
    # factory_lifecycle: read transport, throttling, local commands and polling deadlines (doubled)
    (fl, "READ_TRANSPORT_ATTEMPTS", 6),
    (fl, "READ_TRANSPORT_RETRY_DELAYS", (0.25, 0.5, 1, 2, 4)),
    (fl, "READ_TRANSPORT_RETRY_WINDOW_SECONDS", 360),
    (fl, "THROTTLED_READ_ATTEMPTS", 16),
    (fl, "REMOTE_SOCKET_TIMEOUT_SECONDS", 120),
    (fl, "SIDE_REQUEST_TIMEOUT_SECONDS", 120),
    (fl, "LOCAL_COMMAND_TIMEOUT_SECONDS", 240),
    (fl, "RECEIPT_REPLACE_ATTEMPTS", 40),
    (fl, "LEAF_DELETE_POLLS", 240),
    (fl, "RESOURCE_GROUP_DELETE_POLLS", 2880),
    (fl, "WHAT_IF_POLLS", 240),
    (fl, "FOUNDRY_READINESS_POLLS", 360),
    (fl, "ARM_DEPLOYMENT_POLLS", 2880),
    (fl, "GITHUB_DISPATCH_DISCOVERY_POLLS", 120),
    # factory_lifecycle: unchanged on purpose
    (fl, "MANIFEST_MAX_LIFETIME_SECONDS", 3 * 3600),   # = pink BOOTSTRAP_FROZEN_SECONDS (three times 60 min, 2026-10-28)
    (fl, "RECEIPT_OBSERVATION_AGE_SECONDS", 3 * 3600),
    (fl, "PROVIDER_RUN_POLLS", 1440),              # x 15 s = 6 h = GitHub's 360-minute job maximum
    (fl, "THROTTLED_READ_DEFAULT_DELAY_SECONDS", 5),
    (fl, "THROTTLED_READ_MAX_DELAY_SECONDS", 60),
    # registered_prerequisites
    (rp, "REVIEW_SECONDS", 1800),
    (rp, "GRAPH_REQUEST_TIMEOUT_SECONDS", 180),
    (rp, "RESOURCE_PROVISIONING_POLLS", 480),
    (rp, "PROVIDER_REGISTRATION_POLLS", 240),
    (rp, "ATOMIC_REPLACE_ATTEMPTS", 40),
    # hub_lock_foundation
    (hlf, "REVIEW_SECONDS", 1800),
    (hlf, "ATOMIC_REPLACE_ATTEMPTS", 40),
    (hlf, "PROVISIONING_POLLS", 240),
    (hlf, "PROVIDER_REGISTRATION_POLLS", 240),
    (hlf, "RBAC_PROPAGATION_ATTEMPTS", 50),
    # hub_private_transition
    (hpt, "REVIEW_SECONDS", 1800),
    (hpt, "ATOMIC_REPLACE_ATTEMPTS", 20),
    (hpt, "DNS_LINK_READINESS_SECONDS", 240),
    (hpt, "PROBE_RUN_COMMAND_MAX_SECONDS", 1200),
    (hpt, "PROBE_POLLS", 300),
    # registered_repository
    (rr, "REVIEW_SECONDS", 1800),
    (rr, "GIT_COMMAND_TIMEOUT_SECONDS", 360),
    (rr, "SOURCE_INVENTORY_TIMEOUT_SECONDS", 120),
    # runner_bootstrap
    (rb, "RESOURCE_PROVISIONING_POLLS", 360),
    (rb, "PREREQUISITES_RUN_COMMAND_SECONDS", 3600),
    (rb, "PREREQUISITES_POLLS", 360),
    # factory_enrollment
    (fe, "COMMAND_TIMEOUT_SECONDS", 240),
    (fe, "REQUEST_TIMEOUT_SECONDS", 180),
    (fe, "TOKEN_MIN_REMAINING_SECONDS", 240),
    (fe, "RBAC_PROPAGATION_ATTEMPTS", 16),
    (fe, "ARM_PROVISIONING_POLLS", 60),
    # the rest
    (prs, "STATE_READ_ATTEMPTS", 6),
    (cnp, "BICEP_BUILD_TIMEOUT_SECONDS", 360),
    (cnp, "NETWORK_DEPLOYMENT_POLLS", 540),
    (pd, "REQUEST_TIMEOUT_SECONDS", 120),
    (pd, "DISPATCH_DISCOVERY_POLLS", 120),
    (afd, "REVIEW_SECONDS", 1800),
    (afd, "BICEP_BUILD_TIMEOUT_SECONDS", 240),
    (rv, "GIT_READ_TIMEOUT_SECONDS", 90),
    (fdp, "PROVIDER_RUN_POLLS", 1440),
    (fdp, "TEARDOWN_REQUEST_MAX_LIFETIME_SECONDS", 3 * 3600),
])
def test_time_budget_values(module, name, value):
    assert getattr(module, name) == value


def test_dns_policy_read_deadline_doubled():
    assert rp._DnsPolicyEvidence.READ_SECONDS == 240


def test_graph_visibility_wait_doubled_to_200_seconds():
    assert sum(rp.GRAPH_VISIBILITY_DELAYS) == 200


def test_every_transport_retry_has_a_delay():
    assert len(fl.READ_TRANSPORT_RETRY_DELAYS) == fl.READ_TRANSPORT_ATTEMPTS - 1


def test_polls_outlast_the_run_commands_they_watch():
    assert hpt.PROBE_POLLS * 4 >= hpt.PROBE_RUN_COMMAND_MAX_SECONDS
    assert rb.PREREQUISITES_POLLS * 10 >= rb.PREREQUISITES_RUN_COMMAND_SECONDS
    # Stay below managed Run Command's 90-minute default (Action Run Command's hard limit).
    assert rb.PREREQUISITES_RUN_COMMAND_SECONDS < 5400 and hpt.PROBE_RUN_COMMAND_MAX_SECONDS < 5400


def test_cached_token_outlives_one_request_but_stays_below_cli_refresh_margin():
    # az/MSAL hands out cached tokens until 5 minutes before expiry.
    assert fe.REQUEST_TIMEOUT_SECONDS < fe.TOKEN_MIN_REMAINING_SECONDS < 300


def test_review_windows_fit_inside_the_native_manifest_cap():
    for module in (rp, hlf, hpt, rr, afd):
        assert module.REVIEW_SECONDS <= fl.MANIFEST_MAX_LIFETIME_SECONDS
    assert fdp.TEARDOWN_REQUEST_MAX_LIFETIME_SECONDS == fl.MANIFEST_MAX_LIFETIME_SECONDS


def test_network_preservation_default_poll_budget():
    import inspect
    assert inspect.signature(cnp.execute_common_network).parameters["max_polls"].default == cnp.NETWORK_DEPLOYMENT_POLLS


@pytest.mark.parametrize("name", [
    "factory_lifecycle", "registered_prerequisites", "hub_lock_foundation", "hub_private_transition",
    "registered_repository", "runner_bootstrap", "factory_enrollment", "common_network_preservation",
    "project_deployment", "all_factories_dashboard", "release_version", "factory_deletion_pipeline",
])
def test_no_inline_time_budget_literals_remain(name):
    """Every timeout, review lifetime and poll count is a named constant (pinned above), never an inline literal."""
    source = (LIB / (name + ".py")).read_text(encoding="utf-8")
    assert not re.findall(r"timeout=\d", source)
    assert not re.findall(r"time\.time\(\) \+ \d", source)
    assert not re.findall(r"range\(\d{2,}", source)
    assert not re.findall(r"attempts=\d{2,}", source)
    assert not re.findall(r'"timeoutInSeconds": \d', source)


PIPELINES = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"


@pytest.mark.parametrize("path, key, values", [
    # GitHub Actions and Azure DevOps (Microsoft-hosted, paid) both stop a job at 360 minutes: doubled, capped at 360.
    ("github-actions/infra-project-phase.yml", "timeout-minutes", [360, 360]),
    ("github-actions/infra-project-healthmodel.yml", "timeout-minutes", [120]),
    ("github-actions/infra-project-dashboards.yml", "timeout-minutes", [120]),
    ("azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-genai.yaml", "timeoutInMinutes",
     [240, 360, 360, 360, 360, 360, 240, 360, 360]),
    ("azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml", "timeoutInMinutes", [360]),
    ("azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/stage-private-azure-mcp.yaml", "timeoutInMinutes", [240]),
    ("azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-healthmodel.yaml", "timeoutInMinutes", [120]),
    ("azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-dashboards.yaml", "timeoutInMinutes", [120]),
    ("azure-devops/esml-yaml-pipelines/aifactory-governance/gov-cross-charging.yaml", "timeoutInMinutes", [120] * 3),
])
def test_pipeline_job_timeouts_doubled_and_capped(path, key, values):
    text = (PIPELINES / path).read_text(encoding="utf-8")
    assert [int(value) for value in re.findall(r"^\s*" + key + r":\s*(\d+)", text, re.M)] == values


def test_project_deletion_budget_doubled():
    for path in ("github-actions/infra-project-phase.yml",
                 "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"):
        assert re.findall(r"AIF_DELETE_TIMEOUT_SECONDS: '(\d+)'", (PIPELINES / path).read_text(encoding="utf-8")) == ["3600"]
    script = (ROOT / "environment_setup/aifactory/bicep/scripts/delete-services-if-disabled.sh").read_text(encoding="utf-8")
    assert '"${AIF_DELETE_TIMEOUT_SECONDS:-3600}"' in script
    deletion = (ROOT / "environment_setup/aifactory/bicep/scripts/project-deletion.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--timeout-seconds", default=3600, type=bounded_seconds(86400))' in deletion


def test_repository_ci_timeouts_doubled():
    verify = (ROOT / ".github/workflows/verify-aifactory-dev.yml").read_text(encoding="utf-8")
    assert re.findall(r"timeout-minutes: (\d+)", verify) == ["60"]
    tests = (ROOT / ".github/workflows/infrastructure-tests.yml").read_text(encoding="utf-8")
    assert re.findall(r"timeout_minutes: (\d+)", tests) == ["60", "100", "60", "60"]
    ado = (ROOT / "environment_setup/unit-tests/test-bicep/azure-pipelines.yml").read_text(encoding="utf-8")
    assert re.findall(r"jobTimeoutMinutes: (\d+)", ado) == ["60", "100", "60", "60"]
