"""The runtime delegates consent to the shared provider-native verifier.

Signed JWT, installed workflow, native task, timeline and approval-history
coverage lives in test_pipeline_approvals.py alongside the provider adapter.
"""

import importlib
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))


def fixture(provider="gha"):
    module = importlib.import_module("pipeline_lifecycle_review")
    if provider == "gha":
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "org/repo", "GITHUB_RUN_ID": "42",
               "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "b" * 40, "GITHUB_REF": "refs/heads/main"}
        repository = "https://github.com/org/repo"
        run = {"id": 42, "run_attempt": 1, "head_sha": "b" * 40, "head_branch": "main",
               "repository": {"full_name": "org/repo"}, "event": "workflow_dispatch", "status": "in_progress"}
    else:
        env = {"TF_BUILD": "True", "BUILD_BUILDID": "42", "BUILD_SOURCEVERSION": "b" * 40,
               "BUILD_SOURCEBRANCH": "refs/heads/main"}
        repository = "https://dev.azure.com/org/project/_git/repo"
        run = {"id": 42, "sourceVersion": "b" * 40, "sourceBranch": "refs/heads/main",
               "repository": {"url": repository}}
    cloud = Mock()
    cloud.state_request.return_value = (200, {}, run)
    reviewer = module.ProtectedJobReview(cloud, {"kind": provider, "repository": repository}, environ=env)
    record = {"operation_id": "11111111-1111-1111-1111-111111111111", "plan_hash": "d" * 64,
              "prepared_at": "2026-11-12T19:00:00+00:00", "plan": {"origin": reviewer.origin({})}}
    return reviewer, record, env, run


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_authoritative_provider_adapter_is_used_without_local_approval_fallback(monkeypatch, provider):
    import pipeline_approvals
    reviewer, record, _, _ = fixture(provider)
    proof = {"provider": provider, "run_id": "42", "plan_hash": record["plan_hash"], "native": True}
    verify = Mock(return_value=proof)
    monkeypatch.setattr(pipeline_approvals, "verify_review", verify)
    assert reviewer.verify(record) == proof
    verify.assert_called_once_with(record, environ=reviewer.environ)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_provider_refusal_is_not_replaced_with_boolean_consent(monkeypatch, provider):
    import pipeline_approvals
    reviewer, record, _, _ = fixture(provider)
    record["approved"] = True
    monkeypatch.setattr(pipeline_approvals, "verify_review",
                        Mock(side_effect=pipeline_approvals.ApprovalError("native-review-required")))
    with pytest.raises(ValueError, match="native-review-required"):
        reviewer.verify(record)


def test_changed_authenticated_origin_blocks_before_consent(monkeypatch):
    import pipeline_approvals
    reviewer, record, env, run = fixture()
    env["GITHUB_RUN_ID"], run["id"] = "43", 43
    verify = Mock()
    monkeypatch.setattr(pipeline_approvals, "verify_review", verify)
    with pytest.raises(ValueError, match="origin-changed"):
        reviewer.verify(record)
    verify.assert_not_called()


def test_rerun_cannot_reuse_previous_attempt_approval(monkeypatch):
    import pipeline_approvals
    reviewer, record, env, run = fixture()
    env["GITHUB_RUN_ATTEMPT"], run["run_attempt"] = "2", 2
    verify = Mock()
    monkeypatch.setattr(pipeline_approvals, "verify_review", verify)
    with pytest.raises(ValueError, match="new-review"):
        reviewer.verify(record)
    verify.assert_not_called()
