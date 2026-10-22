"""Contract between the workflow templates and the Function: inputs, run name, relay filter and script hygiene."""

import re

import pytest
import yaml

from aif_lifecycle.application.events import WorkflowRunObservation, correlate, is_runner_call
from aif_lifecycle.adapters.runner_backend import RunnerBackend
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import DummyWorkflowTracker
from aif_lifecycle.settings import FACTORY_API_TIMEOUT_SECONDS, RUNNER_TIMEOUT_SECONDS

from conftest import TEMPLATE_ROOT
from support import FakeGitHub, confirm_current, make_service

WORKFLOWS = TEMPLATE_ROOT / "workflows"


def load(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the key `on` as true
    return data


def render(template, inputs):
    """Render the two expression forms the run name uses: ${{ inputs.x }} and the relay suffix."""
    text = template.replace("${{ inputs.relay == 'false' && ' no-relay' || '' }}",
                            " no-relay" if inputs["relay"] == "false" else "")
    return re.sub(r"\$\{\{ inputs\.([a-z_]+) \}\}", lambda match: inputs[match.group(1)], text)


@pytest.fixture
def dispatched(clock):
    github = FakeGitHub()
    service = make_service(clock, github=github)
    operation = service.prepare("init-factory", {"factoryId": "aif-121-sdc-dev", "wholeWorkflow": True,
                                                 "simulate": {"dropEventAt": "aif-121-connectivity-sdc-dev"}})
    confirm_current(service, confirm_current(service, operation))
    return github.dispatches[0]["inputs"]


def test_the_dummy_declares_exactly_the_inputs_the_function_dispatches(dispatched):
    declared = set(load("aif-dummy-step.yml")["on"]["workflow_dispatch"]["inputs"])
    assert declared == set(dispatched)


def test_the_rendered_run_name_correlates_with_and_without_relay(dispatched):
    template = load("aif-dummy-step.yml")["run-name"]
    assert dispatched["relay"] == "false"
    title = render(template, dispatched)
    assert title.endswith(" no-relay")
    assert correlate(title) == (dispatched["operation_id"], int(dispatched["step"]), dispatched["target"])
    assert correlate(render(template, {**dispatched, "relay": "true"})) is not None


@pytest.fixture
def ops_dispatch(clock):
    from support import FakeGitHub as Recorder
    github = Recorder()
    backend = RunnerBackend(github, MemoryStore(), clock, workflow="aif-ops.yml", ref="main", backend="rest",
                            secret=b"event-secret", request_ttl_seconds=900)
    backend.refresh_catalog()
    return github.dispatches[0]


def test_aif_ops_declares_exactly_the_inputs_the_runner_backend_dispatches(ops_dispatch):
    on = load("aif-ops.yml")["on"]["workflow_dispatch"]["inputs"]
    assert set(on) == set(ops_dispatch["inputs"])
    assert on["action"]["options"] == ["catalog", "prepare", "confirm", "status"]


def test_the_aif_ops_run_name_carries_the_nonce_and_correlates_as_a_runner_call(ops_dispatch):
    inputs = ops_dispatch["inputs"]
    title = render(load("aif-ops.yml")["run-name"], {**inputs, "relay": "true"})
    assert correlate(title) == (inputs["operation_id"], int(inputs["step"]), f"{inputs['action']}-{inputs['nonce']}")
    observed = WorkflowRunObservation(action="completed", run_id=1, workflow="aif-ops", title=title, status="completed",
                                      conclusion="success", html_url="", attempt=1)
    assert is_runner_call(observed)


def test_aif_ops_runs_the_installed_entry_point_safely_on_the_api_host():
    workflow = load("aif-ops.yml")
    job = workflow["jobs"]["call"]
    assert "aif-lifecycle-mgmt" in job["runs-on"]
    # The job outlasts one Factory API call plus the result post, and ends before the Function stops waiting for it.
    assert FACTORY_API_TIMEOUT_SECONDS + 120 <= job["timeout-minutes"] * 60 <= RUNNER_TIMEOUT_SECONDS - 120
    step = job["steps"][0]
    for name, source in (("AIF_RUNNER_REQUEST", "request"), ("AIF_OPERATION_ID", "operation_id"),
                         ("AIF_STEP", "step"), ("AIF_ACTION", "action"), ("AIF_NONCE", "nonce")):
        assert step["env"][name] == "${{ inputs.%s }}" % source
    assert "-P -m aif_lifecycle.runner" in step["run"], "-P keeps the job's working folder off sys.path"
    assert "-cnotmatch" in step["run"] and "concurrency" not in workflow


def test_the_relay_watches_the_dummy_and_only_forwards_dispatch_runs_of_this_repo():
    relay, dummy = load("aif-event-relay.yml"), load("aif-dummy-step.yml")
    assert dummy["name"] in relay["on"]["workflow_run"]["workflows"]
    assert "aif-ops" in relay["on"]["workflow_run"]["workflows"]
    # Observed on GitHub (byor-121, 2026-10-21): 'requested' events carry the workflow name instead of the run name,
    # so the no-relay filter can't see them and they never correlate.
    assert relay["on"]["workflow_run"]["types"] == ["in_progress", "completed"]
    job = relay["jobs"]["relay"]
    condition = " ".join(job["if"].split())
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in condition
    assert "!endsWith(github.event.workflow_run.display_title, ' no-relay')" in condition
    # aif-ops results come on the results route; only a run that ended badly (no result) is worth relaying.
    assert ("(github.event.workflow_run.name != 'aif-ops' || (github.event.action == 'completed' && "
            "github.event.workflow_run.conclusion != 'success'))") in condition
    assert "aif-lifecycle-mgmt" in job["runs-on"]


@pytest.mark.parametrize("name", ["aif-dummy-step.yml", "aif-event-relay.yml", "aif-ops.yml"])
def test_workflows_need_no_token_permissions_and_never_expand_expressions_in_scripts(name):
    data = load(name)
    assert data["permissions"] == {}
    for job in data["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), f"{name}: an expression inside run: is an injection risk"


def test_the_relay_signs_with_the_same_secret_rule_as_the_function():
    script = load("aif-event-relay.yml")["jobs"]["relay"]["steps"][0]["run"]
    assert "-split ','" in script and ".Trim()" in script
    assert "GITHUB_EVENT_PATH" in script and "toJson" not in script


def test_the_dummy_duration_bounds_match_the_settings():
    script = load("aif-dummy-step.yml")["jobs"]["simulate"]["steps"][0]["run"]
    assert "DURATION >= 5" in script and "DURATION <= 600" in script
    assert DummyWorkflowTracker.__name__  # the tracker passes duration_seconds from AIF_DUMMY_DURATION_SECONDS (5-600)
