"""Pipelines-only Execute deploys each frozen Bicep step on its own (design B, 2026-11-20).

One combined nested ARM deployment exceeds ARM's 4 MB template limit for a whole project. In the
per-step transport every frozen step is previewed and deployed by the Azure CLI from its own .bicep
file and frozen parameters, like the legacy pipelines; the reviewed-plan guarantees stay.
"""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import (
    fl, ROOT, GROUP, RESOURCE, RESOURCE_BODY, SUB, PlanCloud, scoped_manifest, seal, simple_plan_closure,
)

sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))

VAULT = SUB.join(("/subscriptions/", "/resourceGroups/seed-rg/providers/Microsoft.KeyVault/vaults/kvseed001"))


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    monkeypatch.setattr(fl.subprocess, "run", Mock(side_effect=AssertionError("Real commands forbidden")))
    monkeypatch.setattr(fl, "build_opener", Mock(side_effect=AssertionError("Real HTTP forbidden")))


def options(argv):
    """az options as a dict; a flag without a value maps to True."""
    result, index = {}, 4
    while index < len(argv):
        key = argv[index]
        assert key.startswith("--"), argv
        if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            result[key], index = argv[index + 1], index + 2
        else:
            result[key], index = True, index + 1
    return result


class PerStepCloud(PlanCloud):
    """Answers `az deployment ... what-if|create` like ARM; nested REST deployments are forbidden."""

    def __init__(self, document, templates):
        super().__init__(document, templates)
        self.az = []
        self.states = {}
        self.fail_name = None

    def command(self, argv, cwd=None, data=None, timeout=None):
        assert argv[:2] == ["az", "deployment"] and argv[2] in ("sub", "group"), argv
        assert timeout == fl.AZ_DEPLOYMENT_COMMAND_TIMEOUT_SECONDS
        values = options(argv)
        parameters = json.loads(Path(values["--parameters"][1:]).read_text(encoding="utf-8"))
        template = Path(values["--template-file"])
        assert template.is_file()
        self.az.append({"scope": argv[2], "action": argv[3], "options": values, "parameters": parameters,
                        "template": template})
        if argv[3] == "what-if":
            change = {"resourceId": RESOURCE, "changeType": "Modify", "before": RESOURCE_BODY, "after": RESOURCE_BODY}
            if self.what_if_changed:
                change["resourceId"] = GROUP + "/providers/Unrelated/resource/outside"
            return json.dumps({"status": "Succeeded", "error": None, "changes": [change]})
        assert argv[3] == "create" and values["--no-wait"] is True
        scope = ("/subscriptions/" + values["--subscription"] if argv[2] == "sub"
                 else "/subscriptions/" + values["--subscription"] + "/resourceGroups/" + values["--resource-group"])
        child = (scope + "/providers/Microsoft.Resources/deployments/" + values["--name"]).lower()
        self.states[child] = "Failed" if values["--name"] == self.fail_name else "Succeeded"
        for project in self.document["target"]["project_ids"]:
            body = copy.deepcopy(self.bodies[RESOURCE.lower()])
            body["id"] = RESOURCE + "-" + project
            body["tags"][fl.TAG_KEYS["project_id"]] = project
            self.bodies[body["id"].lower()] = body
        return ""

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if url.startswith(fl.ARM) and "/providers/Microsoft.Resources/deployments/" in url:
            assert method == "GET" and "/whatIf?" not in url, "combined nested REST deployment forbidden: " + url
            child = url.removeprefix(fl.ARM).split("?", 1)[0].lower()
            return 200, {}, {"id": child, "properties": {"provisioningState": self.states[child]}}
        return super().request(method, url, audience, data, headers, allowed)


def per_step(projects=("017",)):
    document, templates = scoped_manifest(projects)
    document["deployment"]["deployment_transport"] = fl.PER_STEP_TRANSPORT
    return seal(document), templates


def child_name(document, step):
    return fl.deployment_endpoint(document, step).rsplit("/", 1)[-1]


def test_manifest_names_the_reviewed_per_step_transport_and_rejects_unknown_ones():
    document, _ = per_step()
    assert fl.validate_manifest(document) == document
    document["deployment"]["deployment_transport"] = "template-specs"
    with pytest.raises(fl.Blocked, match="unsupported-deployment-transport"):
        fl.validate_manifest(seal(document))


def test_per_step_preview_runs_one_az_bicep_what_if_per_step_and_no_rest_preview():
    document, templates = per_step()
    cloud = PerStepCloud(document, templates)
    changes = fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"})
    steps = document["deployment"]["steps"]
    assert [call["action"] for call in cloud.az] == ["what-if"] * len(steps)
    for call, step in zip(cloud.az, steps):
        values = call["options"]
        assert call["scope"] == "sub"
        assert call["template"] == ROOT / step["template"] and call["template"].suffix == ".bicep"
        assert values["--name"] == child_name(document, step)
        assert values["--subscription"] == SUB and values["--location"] == document["target"]["region"]
        assert values["--result-format"] == "FullResourcePayloads" and values["--no-pretty-print"] is True
        assert call["parameters"]["parameters"] == {key: {"value": value} for key, value in step["parameters"].items()}
        assert call["parameters"]["contentVersion"] == "1.0.0.0"
    # One merged row per resource: the reviewed rows keep the combined preview's shape.
    assert changes == [{"resource_id": RESOURCE.lower(), "change_type": "Modify",
                        "before_hash": fl.resource_digest(RESOURCE_BODY), "after_hash": fl.resource_digest(RESOURCE_BODY)}]
    assert not cloud.arm_writes


def test_resource_group_step_previews_in_its_own_group():
    document, templates = per_step()
    step = document["deployment"]["steps"][-1]
    template = templates[step["template"]]
    template["$schema"] = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
    step.update(scope="resource-group", resource_group=GROUP, template_hash=fl.digest(template))
    cloud = PerStepCloud(document, templates)
    fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"}, step_ids=[step["id"]])
    [call] = cloud.az
    assert call["scope"] == "group" and call["options"]["--resource-group"] == "reviewed"
    assert "--location" not in call["options"] and call["options"]["--subscription"] == SUB


def test_whole_project_larger_than_four_megabytes_is_no_longer_blocked():
    document, templates = per_step(("017", "019"))
    for template in templates.values():
        template["variables"] = {"padding": "x" * (1536 * 1024)}
    for step in document["deployment"]["steps"]:
        step["template_hash"] = fl.digest(templates[step["template"]])
    cloud = PerStepCloud(document, templates)
    with pytest.raises(fl.Blocked, match="combined-template-too-large"):
        fl.combined_plan_payload(cloud, document, ROOT)
    assert fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"})


def test_key_vault_reference_stays_a_reference_in_the_parameter_file():
    document, templates = per_step()
    step = document["deployment"]["steps"][0]
    reference = {"reference": {"keyVault": {"id": VAULT}, "secretName": "aif-vm-admin-password"}}
    templates[step["template"]]["parameters"]["adminPassword"] = {"type": "securestring"}
    step["parameters"]["adminPassword"] = reference
    step["template_hash"] = fl.digest(templates[step["template"]])
    document["deployment"]["parameter_transport"] = "arm-keyvault-reference-v1"
    cloud = PerStepCloud(document, templates)
    fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"}, step_ids=[step["id"]])
    assert cloud.az[0]["parameters"]["parameters"]["adminPassword"] == reference


def test_rows_merge_by_resource_with_the_strongest_change_and_the_last_writer_after():
    a, b = GROUP + "/providers/X/y/a", GROUP + "/providers/X/y/b"
    merged = fl.merge_step_what_if_rows([
        [{"resourceId": a, "changeType": "Ignore"},
         {"resourceId": b, "changeType": "Create", "before": None, "after": {"v": 1}}],
        [{"resourceId": a.upper().replace("/SUBSCRIPTIONS/", "/subscriptions/"), "changeType": "Create",
          "before": None, "after": {"v": 2}},
         {"resourceId": b, "changeType": "Modify", "before": {"v": 1}, "after": {"v": 3}, "delta": [{"path": "v"}]}],
        [{"resourceId": b, "changeType": "Ignore"}],
    ])
    by_id = {row["resourceId"].lower(): row for row in merged}
    assert len(merged) == 2
    assert by_id[a.lower()]["changeType"] == "Create" and by_id[a.lower()]["after"] == {"v": 2}
    assert by_id[b.lower()] == {"resourceId": b, "changeType": "Create", "before": None, "after": {"v": 3},
                                "delta": [{"path": "v"}]}
    assert fl.merge_step_what_if_rows([[{"resourceId": a, "changeType": "Ignore"}],
                                       [{"resourceId": a, "changeType": "Ignore"}]]) == [
        {"resourceId": a, "changeType": "Ignore"}]


def test_failed_step_what_if_blocks():
    document, templates = per_step()
    cloud = PerStepCloud(document, templates)
    cloud.command = lambda argv, cwd=None, data=None, timeout=None: json.dumps(
        {"status": "Failed", "error": {"code": "InvalidTemplate"}, "changes": []})
    with pytest.raises(fl.Blocked, match="arm-what-if-failed"):
        fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"})


def run_worker(document, cloud):
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    return fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                    ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())


@pytest.fixture
def offline_worker(monkeypatch):
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)


def test_worker_deploys_each_step_with_az_bicep_create_and_no_nested_put(offline_worker):
    document, templates = per_step(("017", "019"))
    cloud = PerStepCloud(document, templates)
    result = run_worker(document, cloud)
    assert result["status"] == "succeeded", result.get("error_code")
    steps = document["deployment"]["steps"]
    creates = [call for call in cloud.az if call["action"] == "create"]
    # Every preview is re-run before the first write.
    assert [call["action"] for call in cloud.az] == ["what-if"] * len(steps) + ["create"] * len(steps)
    assert [call["options"]["--name"] for call in creates] == [child_name(document, step) for step in steps]
    assert all(call["template"].suffix == ".bicep" for call in creates)
    assert not cloud.arm_writes
    assert [row["step_id"] for row in result["deployments"]] == [step["id"] for step in steps]
    assert [row["id"] for row in result["deployments"]] == [
        fl.deployment_endpoint(document, step).removeprefix(fl.ARM) for step in steps]
    assert "pending_deployment" not in result


def test_failed_step_stops_the_run_and_names_its_child_deployment(offline_worker):
    document, templates = per_step()
    cloud = PerStepCloud(document, templates)
    failing = document["deployment"]["steps"][1]
    cloud.fail_name = child_name(document, failing)
    result = run_worker(document, cloud)
    assert result["status"] == "reconciliation-required" and result["error_code"] == "arm-deployment-failed"
    assert len([call for call in cloud.az if call["action"] == "create"]) == 2
    assert result["pending_deployment"] == fl.deployment_endpoint(document, failing).removeprefix(fl.ARM)
    assert [row["step_id"] for row in result["deployments"]] == [document["deployment"]["steps"][0]["id"]]


def test_changed_step_preview_blocks_before_any_create(offline_worker):
    document, templates = per_step()
    cloud = PerStepCloud(document, templates)
    cloud.what_if_changed = True
    result = run_worker(document, cloud)
    assert result["error_code"] == "arm-what-if-changed-since-prepare"
    assert not [call for call in cloud.az if call["action"] == "create"] and not cloud.arm_writes


def test_cloud_command_passes_a_longer_timeout_to_the_runner():
    document, _ = per_step()
    runner = Mock(return_value=Mock(returncode=0, stdout="{}", stderr=""))
    cloud = fl.Cloud(document, command_runner=runner, opener=Mock())
    cloud.command(["python", "-V"], timeout=fl.AZ_DEPLOYMENT_COMMAND_TIMEOUT_SECONDS)
    assert runner.call_args.kwargs["timeout"] == fl.AZ_DEPLOYMENT_COMMAND_TIMEOUT_SECONDS
    cloud.command(["python", "-V"])
    assert runner.call_args.kwargs["timeout"] == fl.LOCAL_COMMAND_TIMEOUT_SECONDS


@pytest.mark.parametrize("injected", [True, False])
def test_foundry_phases_deploy_step_by_step_with_their_gates(monkeypatch, injected):
    from .test_native_foundry_lifecycle import FoundryCloud, foundry_document, native_closure

    class AzFoundryCloud(FoundryCloud):
        """Per-step az calls; a phase's reviewed effects land when its last step deploys."""

        def __init__(self, document, templates):
            super().__init__(document, templates)
            self.az = []

        def command(self, argv, cwd=None, data=None, timeout=None):
            assert argv[:2] == ["az", "deployment"] and argv[2] == "sub", argv
            name = options(argv)["--name"]
            step = next(row for row in self.document["deployment"]["steps"] if child_name(self.document, row) == name)
            phase = next((ids for ids in self.expanded if step["id"] in ids), None)
            last = phase is not None and phase[-1] == step["id"]
            self.az.append((argv[3], step["id"]))
            if argv[3] == "what-if":
                return json.dumps({"status": "Succeeded", "changes": [] if not last else [
                    {"resourceId": key, "changeType": "NoChange" if key in self.bodies else "Create",
                     "before": copy.deepcopy(self.bodies.get(key)), "after": copy.deepcopy(self.planned[key])}
                    for key in self.expanded[phase]]})
            if last:
                self.request("PUT", fl.deployment_endpoint(self.document, step) + "?api-version=2022-09-01",
                             fl.ARM, data={"step_ids": list(phase)})
            return ""

    document = foundry_document()
    if not injected:
        document["deployment"]["steps"][-1]["parameters"]["disableAgentNetworkInjection"] = True
    fl.plan_foundry_lifecycle(document)
    document["deployment"]["deployment_transport"] = fl.PER_STEP_TRANSPORT
    templates = {}
    for step in document["deployment"]["steps"]:
        template = {"$schema": "subscriptionDeploymentTemplate.json",
                    "parameters": {key: {} for key in step["parameters"]}, "resources": []}
        templates[step["template"]] = template
        step["template_hash"] = fl.digest(template)
    cloud = AzFoundryCloud(document, templates)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", native_closure)
    document["deployment"]["changes"] = fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"})
    fl.freeze_foundry_lifecycle(cloud, document, ROOT)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                      ROOT, document["run_id"], document["manifest_hash"], cloud, Mock())
    assert result["status"] == "succeeded", result.get("error_code")
    phases = document["deployment"]["foundry_lifecycle"]["phases"]
    assert cloud.executed == [tuple(phase["step_ids"]) for phase in phases]
    steps = [step["id"] for step in document["deployment"]["steps"]]
    assert [step for action, step in cloud.az if action == "create"] == steps
    assert [row["step_id"] for row in result["deployments"]] == steps
    assert not [event for event in cloud.events if event[0] == "POST"]
    assert result["foundry_readiness"]["completed_gates"] == (
        ["account-identity", "configured-agent-network-ready"] if injected else ["account-identity"])
    assert fl.verify_worker_receipt(locks, document) == result
