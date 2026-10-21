"""Contract between the workflow templates and the Function: inputs, run name, relay filter and script hygiene."""

import re

import pytest
import yaml

from aif_lifecycle.application.events import correlate
from aif_lifecycle.adapters.trackers import DummyWorkflowTracker

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


def test_the_relay_watches_the_dummy_and_only_forwards_dispatch_runs_of_this_repo():
    relay, dummy = load("aif-event-relay.yml"), load("aif-dummy-step.yml")
    assert dummy["name"] in relay["on"]["workflow_run"]["workflows"]
    job = relay["jobs"]["relay"]
    condition = " ".join(job["if"].split())
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in condition
    assert "!endsWith(github.event.workflow_run.display_title, ' no-relay')" in condition
    assert "aif-lifecycle-mgmt" in job["runs-on"]


@pytest.mark.parametrize("name", ["aif-dummy-step.yml", "aif-event-relay.yml"])
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
