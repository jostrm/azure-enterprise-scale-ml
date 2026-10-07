"""Offline reviewed deployment/update contract; no Azure calls."""

import copy
import importlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))

from unit.test_registered_prerequisites import (  # noqa: E402
    FoundationRuntime, HUB_RG, TENANT, EXTERNAL, foundation, no_live, provision_foundation, workspace,
)


def core():
    return importlib.import_module("all_factories_dashboard")


class Runtime(FoundationRuntime):
    def arm(self, method, identifier, api, **kwargs):
        if method == "PUT" and "/providers/microsoft.resources/deployments/" in identifier:
            assert foundation.lock_blob(HUB_RG) in self.leases
            assert not self.read_only
            self.writes.append(("arm", method, identifier, copy.deepcopy(kwargs.get("data"))))
            parameters = kwargs["data"]["properties"]["parameters"]
            desired = {
                "location": parameters["location"]["value"],
                "tags": {"hidden-title": "All AI Factories", "aifactory.dashboard": "all-ai-factories-v1",
                         "aifactory.scope": "connectivity-hub"},
                "properties": {"metadata": {"allAiFactories": {
                    "hubResourceGroupId": HUB_RG,
                    "selectedSubscriptionIds": parameters["selectedSubscriptionIds"]["value"],
                    "sourcePayloadSha256": parameters["sourcePayloadSha256"]["value"],
                    "numericAggregationSupported": False,
                }}},
            }
            resource_id = HUB_RG + "/providers/microsoft.portal/dashboards/all-ai-factories"
            self.resources[resource_id] = {"id": resource_id, **copy.deepcopy(desired)}
            self.resources[identifier] = {"id": identifier, "properties": {
                "provisioningState": "Succeeded",
                "outputs": {"desiredDashboard": {"type": "Object", "value": desired},
                            "dashboardId": {"type": "String", "value": resource_id}},
            }}
            return 200, {}, self.resources[identifier]
        return super().arm(method, identifier, api, **kwargs)


def ready(workspace):
    runtime = Runtime()
    provision_foundation(workspace, runtime, HUB_RG)
    runtime.writes.clear()
    return runtime


def prepare(runtime, **extra):
    return core().prepare(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB_RG,
                          location="swedencentral", selected_subscription_ids=[EXTERNAL],
                          runtime=runtime, compiler=lambda _: {"resources": []}, **extra)


def execute(plan, runtime, folder):
    return core().execute(plan, state_dir=folder, expected_plan_hash=plan["plan_hash"],
                          runtime=runtime, compiler=lambda _: {"resources": []}, sleep=lambda _: None)


def test_review_is_readonly_explicit_hub_scoped_and_pins_bicep(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    assert not runtime.writes
    assert plan["stage"] == "all-factories-dashboard"
    assert plan["inputs"]["selected_subscription_ids"] == [EXTERNAL]
    assert plan["effects"][0]["id"].startswith(HUB_RG + "/")
    assert "bootstrap/lib/all-factories-dashboard.bicep" in plan["source"]["files"]
    assert plan["numeric_aggregation_supported"] is False
    assert any(command["purpose"] == "reviewed-dashboard-deployment" for command in plan["commands"])
    assert any(command["purpose"] == "durable-operation-evidence" for command in plan["commands"])


def test_create_and_reviewed_update_keep_one_identity_and_verify_receipt(workspace):
    runtime = ready(workspace)
    first = prepare(runtime)
    receipt = execute(first, runtime, workspace[2])
    assert receipt["status"] == "succeeded", receipt
    core().validate_receipt(receipt, first)
    second = prepare(runtime)
    assert second["effects"][0]["id"] == first["effects"][0]["id"]
    again = execute(second, runtime, workspace[2])
    assert again["status"] == "succeeded", again
    assert len([key for key in runtime.resources if "/microsoft.portal/dashboards/" in key]) == 1
    assert not runtime.leases


@pytest.mark.parametrize("selection", [None, [], ["not-a-subscription"], [EXTERNAL, EXTERNAL]])
def test_missing_invalid_and_duplicate_subscriptions_fail_closed(workspace, selection):
    runtime = ready(workspace)
    with pytest.raises((ValueError, TypeError, foundation.enrollment.EnrollmentError)):
        core().prepare(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB_RG,
                       location="swedencentral", selected_subscription_ids=selection, runtime=runtime)
    assert not runtime.writes


def test_factory_owned_group_and_unowned_dashboard_are_not_adopted(workspace):
    runtime = ready(workspace)
    runtime.resources[HUB_RG]["tags"]["aifactory.factory_id"] = TENANT
    with pytest.raises(ValueError, match="factory-owned"):
        prepare(runtime)
    runtime.resources[HUB_RG]["tags"].pop("aifactory.factory_id")
    identifier = HUB_RG + "/providers/microsoft.portal/dashboards/all-ai-factories"
    runtime.resources[identifier] = {"id": identifier, "tags": {}}
    with pytest.raises(ValueError, match="ownership"):
        prepare(runtime)
    assert not runtime.writes


def test_stale_review_prevents_deployment(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    runtime.resources[HUB_RG]["tags"]["concurrent-change"] = "unreviewed"
    with pytest.raises(ValueError, match="changed"):
        execute(plan, runtime, workspace[2])
    assert not runtime.writes


def test_uncertain_write_retains_lease_and_durable_receipt_without_retry(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    original = runtime.arm
    attempts = []

    def fail(method, identifier, api, **kwargs):
        if method == "PUT" and "/microsoft.resources/deployments/" in identifier:
            attempts.append(identifier)
            raise OSError("unknown remote outcome")
        return original(method, identifier, api, **kwargs)

    runtime.arm = fail
    receipt = execute(plan, runtime, workspace[2])
    assert receipt["status"] == "uncertain"
    assert len(attempts) == 1 and runtime.leases
    assert Path(receipt["receipt_path"]).is_file()
    with pytest.raises(ValueError, match="receipt"):
        core().validate_receipt(receipt, plan)


def test_subscription_changes_are_new_reviewed_updates_not_new_dashboards(workspace):
    runtime = ready(workspace)
    first = prepare(runtime)
    assert execute(first, runtime, workspace[2])["status"] == "succeeded"
    second = core().prepare(source_root=ROOT, tenant_id=TENANT, hub_resource_group_id=HUB_RG,
                            location="swedencentral", selected_subscription_ids=[TENANT, EXTERNAL],
                            runtime=runtime, compiler=lambda _: {"resources": []})
    assert second["dashboard_id"] == first["dashboard_id"]
    assert second["plan_hash"] != first["plan_hash"]
    assert execute(second, runtime, workspace[2])["status"] == "succeeded"
    metadata = runtime.resources[first["dashboard_id"]]["properties"]["metadata"]["allAiFactories"]
    assert metadata["selectedSubscriptionIds"] == sorted([TENANT, EXTERNAL])


def test_plan_tampering_and_source_mismatch_fail_before_writes(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    plan["inputs"]["selected_subscription_ids"] = [TENANT]
    with pytest.raises(ValueError, match="hash"):
        execute(plan, runtime, workspace[2])
    with pytest.raises(ValueError, match="source-payload"):
        prepare(runtime, expected_source_hash="0" * 64)
    assert not runtime.writes


def test_scope_changed_during_lease_acquisition_blocks_arm_write(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    original = runtime.blob

    def change(method, blob=None, **kwargs):
        response = original(method, blob, **kwargs)
        if kwargs.get("headers", {}).get("x-ms-lease-action") == "acquire":
            runtime.resources[HUB_RG]["tags"]["unreviewed"] = "changed"
        return response

    runtime.blob = change
    receipt = execute(plan, runtime, workspace[2])
    assert receipt["status"] == "uncertain"
    assert not runtime.writes and runtime.leases


def test_receipt_is_bound_to_exact_scope_selection_and_source(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    receipt = execute(plan, runtime, workspace[2])
    assert receipt["status"] == "succeeded"
    for key, value in (("dashboard_id", "/other"), ("source", {}),
                       ("inputs", {}), ("effects_completed", []),
                       ("verified_dashboard_sha256", "0" * 64),
                       ("verified_dashboard", {})):
        altered = {**receipt, key: value}
        with pytest.raises(ValueError, match="receipt"):
            core().validate_receipt(altered, plan)


@pytest.mark.parametrize("changed", ["missing-outputs", "wrong-id", "wrong-selection", "actual-resource"])
def test_arm_success_alone_cannot_issue_verified_receipt(workspace, changed):
    runtime = ready(workspace)
    plan = prepare(runtime)
    original = runtime.arm

    def corrupt(method, identifier, api, **kwargs):
        result = original(method, identifier, api, **kwargs)
        if method == "PUT" and "/microsoft.resources/deployments/" in identifier:
            outputs = runtime.resources[identifier]["properties"]["outputs"]
            if changed == "missing-outputs":
                outputs.clear()
            elif changed == "wrong-id":
                outputs["dashboardId"]["value"] = "/other"
            elif changed == "wrong-selection":
                outputs["desiredDashboard"]["value"]["properties"]["metadata"]["allAiFactories"][
                    "selectedSubscriptionIds"] = [TENANT]
            else:
                runtime.resources[plan["dashboard_id"]]["location"] = "eastus"
        return result

    runtime.arm = corrupt
    receipt = execute(plan, runtime, workspace[2])
    assert receipt["status"] == "uncertain"
    assert receipt["reconciliation_required"] and runtime.leases
    assert receipt["effects_completed"] == []
    with pytest.raises(ValueError, match="receipt"):
        core().validate_receipt(receipt, plan)


def test_expired_plan_cannot_mutate_even_with_valid_hash(workspace):
    runtime = ready(workspace)
    plan = prepare(runtime)
    plan["expires_at"] = plan["prepared_at"] - 1
    plan["plan_hash"] = core().digest({key: value for key, value in plan.items() if key != "plan_hash"})
    with pytest.raises(ValueError, match="expired"):
        execute(plan, runtime, workspace[2])
    assert not runtime.writes and not runtime.leases
