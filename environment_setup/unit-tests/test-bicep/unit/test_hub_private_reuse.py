"""Second-factory private hub reuse never invents or reopens a public route."""

import copy

import pytest

from unit.test_registered_prerequisites import (
    FoundationRuntime, foundation, foundation_args, foundation_execute,
    no_live, provision_foundation, workspace,
)


class PrivateRuntime(FoundationRuntime):
    def __init__(self):
        super().__init__()
        self.reject_heads = False
        self.heads = 0

    def blob(self, method, *args, **kwargs):
        if method == "HEAD":
            self.heads += 1
            if self.reject_heads:
                raise foundation.enrollment.EnrollmentError("remote-request-failed-403")
        return super().blob(method, *args, **kwargs)


def private_account(workspace):
    runtime = PrivateRuntime()
    initial = provision_foundation(workspace, runtime)
    account = initial["coordination"]["account_id"]
    properties = runtime.resources[account]["properties"]
    properties["publicNetworkAccess"] = "Disabled"
    properties["networkAcls"]["ipRules"] = []
    runtime.heads = 0
    return runtime, account


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_blank_ip_reuses_verified_private_account_without_arm_or_network_writes(workspace, blank):
    runtime, account = private_account(workspace)
    before = copy.deepcopy(runtime.resources)
    writes = copy.deepcopy(runtime.writes)
    args = foundation_args(workspace)
    args["bootstrap_public_ipv4"] = blank
    plan = foundation.prepare(**args, runtime=runtime)
    assert plan["can_execute"] and not plan["effects"]
    assert plan["inputs"]["bootstrap_public_ipv4"] is None
    assert plan["bootstrap_network_access"]["rule"] is None
    assert plan["bootstrap_network_access"]["removal_authorized"] is False
    assert plan["private_reuse_access"]["verified"] is True
    assert plan["private_reuse_access"]["authentication"] == "Entra-OAuth-only"
    assert plan["private_reuse_access"]["provider_runner_attested"] is False
    result = foundation_execute(plan, workspace, runtime)
    assert result["status"] == "succeeded"
    assert result["private_reuse_access"]["verified"] is True
    assert runtime.heads >= 3
    assert runtime.resources == before and runtime.writes == writes
    assert runtime.resources[account]["properties"]["publicNetworkAccess"] == "Disabled"


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_blank_ip_cannot_create_new_storage_or_guess_an_approved_address(workspace, blank):
    runtime = PrivateRuntime()
    args = foundation_args(workspace)
    args["bootstrap_public_ipv4"] = blank
    with pytest.raises(foundation.FoundationError, match="approved-bootstrap-public-ipv4-required"):
        foundation.prepare(**args, runtime=runtime)
    assert not runtime.resources and not runtime.writes and not runtime.blobs


def test_blank_ip_cannot_adopt_an_existing_public_account(workspace):
    runtime = PrivateRuntime()
    provision_foundation(workspace, runtime)
    before = copy.deepcopy(runtime.resources)
    args = foundation_args(workspace)
    args["bootstrap_public_ipv4"] = ""
    with pytest.raises(foundation.FoundationError, match="approved-bootstrap-public-ipv4-required"):
        foundation.prepare(**args, runtime=runtime)
    assert runtime.resources == before


def test_blank_ip_private_reuse_needs_actual_authenticated_data_plane_access(workspace):
    runtime, _ = private_account(workspace)
    runtime.reject_heads = True
    before = copy.deepcopy(runtime.resources)
    args = foundation_args(workspace)
    args["bootstrap_public_ipv4"] = ""
    plan = foundation.prepare(**args, runtime=runtime)
    assert not plan["can_execute"] and not plan["private_reuse_access"]["verified"]
    assert any("authenticated-execution-path-required" in blocker for blocker in plan["blockers"])
    assert runtime.heads == 1 and runtime.resources == before


def test_private_access_revoked_after_review_prevents_execution(workspace):
    runtime, _ = private_account(workspace)
    args = foundation_args(workspace)
    args["bootstrap_public_ipv4"] = ""
    plan = foundation.prepare(**args, runtime=runtime)
    writes = copy.deepcopy(runtime.writes)
    events = copy.deepcopy(runtime.events)
    runtime.reject_heads = True
    with pytest.raises(foundation.FoundationError, match="foundation-live-state-or-plan-changed"):
        foundation_execute(plan, workspace, runtime)
    assert runtime.writes == writes and runtime.events == events
