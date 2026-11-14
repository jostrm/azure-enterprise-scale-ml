"""Native provider approval evidence; no network, real RSA signatures."""
import base64
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_approvals as approvals

NOW = 1_794_500_000
COMMIT = "b" * 40
OPERATION = "11111111-1111-4111-8111-111111111111"
HASH = "c" * 64
TASK = "22222222-2222-4222-8222-222222222222"
REPOSITORY = "33333333-3333-4333-8333-333333333333"
PLAN = "44444444-4444-4444-8444-444444444444"
TIMELINE = "55555555-5555-4555-8555-555555555555"
EXECUTE = "66666666-6666-4666-8666-666666666666"
STAGE = "77777777-7777-4777-8777-777777777777"


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def record(provider):
    return {"operation_id": OPERATION, "plan_hash": HASH, "prepared_at": stamp(NOW - 120),
            "plan": {"origin": {"provider": provider, "repository": "acme/factory" if provider == "gha"
                                else "https://dev.azure.com/acme/project/_git/factory",
                                "run_id": "7", "attempt": 1, "commit": COMMIT, "ref": "refs/heads/main"}}}


def environ(provider):
    if provider == "gha":
        return {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "acme/factory", "GITHUB_RUN_ID": "7",
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": COMMIT, "GITHUB_REF": "refs/heads/main",
                "GITHUB_JOB": "execute"}
    return {"TF_BUILD": "True", "BUILD_BUILDID": "7", "BUILD_SOURCEVERSION": COMMIT,
            "BUILD_SOURCEBRANCH": "refs/heads/main", "SYSTEM_JOBATTEMPT": "1",
            "SYSTEM_STAGEATTEMPT": "1", "SYSTEM_JOBID": EXECUTE, "SYSTEM_STAGEID": STAGE,
            "SYSTEM_PLANID": PLAN, "SYSTEM_TIMELINEID": TIMELINE, "SYSTEM_DEFINITIONID": "9"}


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("relationship", ["continuation_of", "recovery_of"])
def test_continuation_needs_a_new_exact_native_review_not_parent_evidence(provider, key, relationship):
    child = record(provider)
    child["operation_id"] = "88888888-8888-4888-8888-888888888888"
    child["plan_hash"] = "d" * 64
    child["plan"][relationship] = {"operation_id": OPERATION, "plan_hash": HASH}
    child["plan"]["origin"]["run_id"] = "8"
    native, environment = Provider(provider), environ(provider)
    with pytest.raises(approvals.ApprovalError, match="current-job-mismatch"):
        approvals.verify_review(child, transport=native, oidc=OIDC(key),
                           environ=environment, clock=lambda: NOW)
    environment["GITHUB_RUN_ID" if provider == "gha" else "BUILD_BUILDID"] = "8"
    native.run["id"] = 8
    if provider == "gha":
        for job in native.jobs:
            job["run_id"] = 8
        token = OIDC(key)
        token.claims.update(run_id="8", aud=approvals.audience(child))
        def signed(aud):
            assert aud == approvals.audience(child)
            raw = (encode(json.dumps(token.header).encode()) + "." + encode(json.dumps(token.claims).encode())).encode()
            return raw.decode() + "." + encode(key.sign(raw, padding.PKCS1v15(), hashes.SHA256()))
        token.token = signed
    else:
        token = None
    with pytest.raises(approvals.ApprovalError, match="exact-prepared-operation-jobs|native-server-review-job"):
        approvals.verify_review(child, transport=native, oidc=token,
                           environ=environment, clock=lambda: NOW)
    if provider == "gha":
        native.jobs[1]["name"] = f"Execute reviewed {child['operation_id']} / {child['plan_hash']}"
    else:
        next(row for row in native.records if row["id"] == "review-job")["name"] = (
            f"Review {child['operation_id']} / {child['plan_hash']}")
    proof = approvals.verify_review(child, transport=native, oidc=token, environ=environment, clock=lambda: NOW)
    assert proof["operation_id"] == child["operation_id"]
    assert proof["plan_hash"] == child["plan_hash"] and proof["run_id"] == "8"


def encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live approval call forbidden"))


class OIDC:
    def __init__(self, key):
        self.key = key
        self.claims = {"iss": approvals.ISSUER, "aud": approvals.audience(record("gha")),
                       "sub": "repo:acme/factory:environment:esaf-pipelines-execute",
                       "repository": "acme/factory", "repository_id": "20",
                       "sha": COMMIT, "ref": "refs/heads/main", "run_id": "7", "run_attempt": "1",
                       "workflow_ref": "acme/factory/.github/workflows/pipelines-only-gha.yml@refs/heads/main",
                       "workflow_sha": COMMIT, "environment": "esaf-pipelines-execute",
                       "actor_id": "10", "runner_environment": "self-hosted",
                       "iat": NOW - 2, "nbf": NOW - 2, "exp": NOW + 298, "jti": "native-job-token"}
        self.header = {"alg": "RS256", "kid": "github-key", "typ": "JWT"}
        self.corrupt = False

    def token(self, requested_audience):
        assert requested_audience in (approvals.audience(record("gha")),
                                      approvals.finalizer_audience(record("gha")))
        raw = (encode(json.dumps(self.header).encode()) + "." + encode(json.dumps(self.claims).encode())).encode()
        signature = self.key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
        if self.corrupt:
            signature = bytes([signature[0] ^ 1]) + signature[1:]
        return raw.decode() + "." + encode(signature)

    def jwks(self):
        numbers = self.key.public_key().public_numbers()
        return {"keys": [{"kty": "RSA", "kid": "github-key", "alg": "RS256", "use": "sig",
                          "n": encode(numbers.n.to_bytes(256, "big")),
                          "e": encode(numbers.e.to_bytes(3, "big"))}]}


class Provider:
    def __init__(self, provider):
        self.provider, self.calls = provider, []
        if provider == "gha":
            self.run = {"id": 7, "run_attempt": 1, "head_sha": COMMIT, "event": "workflow_dispatch",
                        "status": "in_progress", "path": ".github/workflows/pipelines-only-gha.yml",
                        "repository": {"id": 20, "full_name": "acme/factory"}, "actor": {"id": 10}}
            self.protection = {"id": 30, "name": "esaf-pipelines-execute", "can_admins_bypass": False,
                               "protection_rules": [{"type": "required_reviewers", "prevent_self_review": True,
                                                     "reviewers": [{"type": "User", "reviewer": {"id": 11}}]}]}
            self.reviews = [{"state": "approved", "user": {"id": 11},
                             "environments": [{"id": 30, "name": "esaf-pipelines-execute"}]}]
            self.jobs = [
                {"id": 40, "run_id": 7, "run_attempt": 1, "head_sha": COMMIT, "name": "prepare",
                 "status": "completed", "conclusion": "success", "started_at": stamp(NOW - 200),
                 "completed_at": stamp(NOW - 100)},
                {"id": 41, "run_id": 7, "run_attempt": 1, "head_sha": COMMIT,
                 "name": f"Execute reviewed {OPERATION} / {HASH}", "status": "in_progress",
                 "started_at": stamp(NOW - 30), "completed_at": None,
                 "labels": ["self-hosted", "linux", "esaf-lifecycle-external"]},
            ]
        else:
            self.run = {"id": 7, "sourceVersion": COMMIT, "sourceBranch": "refs/heads/main",
                        "status": "inProgress", "definition": {"id": 9, "revision": 2},
                        "orchestrationPlan": {"planId": PLAN},
                        "repository": {"id": REPOSITORY, "type": "TfsGit",
                                       "url": record("ado")["plan"]["origin"]["repository"]}}
            self.definition = {"id": 9, "revision": 2,
                               "repository": {"id": REPOSITORY}, "process": {"yamlFilename": "pipelines-only-ado.yml"}}
            self.task_definition = {"id": TASK, "name": "ManualValidation", "serverOwned": True,
                                    "runsOn": ["Server"], "version": {"major": 1, "minor": 0, "patch": 0}}
            self.records = [
                {"id": "prepare-stage", "parentId": None, "type": "Stage", "name": "Prepare", "attempt": 1},
                {"id": "prepare-job", "parentId": "prepare-stage", "type": "Job", "name": "PrepareOperation",
                 "identifier": "PrepareOperation", "attempt": 1, "state": "completed", "result": "succeeded",
                 "startTime": stamp(NOW - 200), "finishTime": stamp(NOW - 100)},
                {"id": "review-stage", "parentId": None, "type": "Stage", "name": "Review", "attempt": 1},
                {"id": "review-job", "parentId": "review-stage", "type": "Job",
                 "name": f"Review {OPERATION} / {HASH}", "identifier": "ReviewPipelinesLifecycle",
                 "attempt": 1, "workerName": None, "state": "completed", "result": "succeeded"},
                {"id": "review-task", "parentId": "review-job", "type": "Task", "name": "ReviewPipelinesLifecycle",
                 "task": {"id": TASK, "name": "ManualValidation", "version": "1.0.0"}, "attempt": 1,
                 "state": "completed", "result": "succeeded", "startTime": stamp(NOW - 90),
                 "finishTime": stamp(NOW - 50)},
                {"id": STAGE, "parentId": None, "type": "Stage", "name": "Execute", "attempt": 1},
                {"id": EXECUTE, "parentId": STAGE, "type": "Job", "name": "ExecuteReviewedOperation",
                 "identifier": "ExecuteReviewedOperation", "attempt": 1, "state": "inProgress",
                 "startTime": stamp(NOW - 30)},
            ]
        self.source = (ROOT / "bootstrap/templates" / f"pipelines-only-{provider}.yml").read_bytes()

    def request(self, method, url, body=None, raw=False):
        self.calls.append(url)
        assert method == "GET" and body is None, "Approval adapter must not mutate providers"
        if "/contents/" in url:
            return 200, {}, {"encoding": "base64", "content": base64.b64encode(self.source).decode()}
        if "/items?" in url:
            return 200, {}, {"content": self.source.decode()}
        if "/environments/" in url:
            return 200, {}, self.protection
        if "/approvals" in url:
            return 200, {}, self.reviews
        if "/jobs?" in url:
            return 200, {}, {"jobs": self.jobs}
        if "/timeline?" in url:
            return 200, {}, {"id": TIMELINE, "records": self.records}
        if "/definitions/" in url:
            return 200, {}, self.definition
        if "/distributedtask/tasks/" in url:
            return 200, {}, {"value": [self.task_definition]}
        return 200, {}, self.run


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_native_exact_review_accepted(provider, key):
    proof = approvals.verify_review(record(provider), transport=Provider(provider),
                                    oidc=OIDC(key), environ=environ(provider), clock=lambda: NOW)
    assert proof["operation_id"] == OPERATION and proof["plan_hash"] == HASH
    assert proof["environment"] == "esaf-pipelines-execute" and proof["provider"] == provider
    assert "token" not in json.dumps(proof).lower()


@pytest.mark.parametrize("claim,value", [
    ("run_id", "8"), ("run_attempt", "2"), ("sha", "d" * 40), ("aud", "attacker"),
    ("iss", "https://attacker.invalid"), ("environment", "unprotected"), ("actor_id", "99"),
    ("workflow_sha", "d" * 40), ("exp", NOW - 1), ("iat", NOW + 120),
])
def test_signed_but_wrong_github_job_is_rejected(key, claim, value):
    oidc = OIDC(key)
    oidc.claims[claim] = value
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_review(record("gha"), transport=Provider("gha"), oidc=oidc,
                                environ=environ("gha"), clock=lambda: NOW)


def test_self_asserted_or_corrupt_jwt_is_never_authority(key):
    for mode in ("signature", "alg", "key"):
        oidc = OIDC(key)
        if mode == "signature":
            oidc.corrupt = True
        elif mode == "alg":
            oidc.header["alg"] = "none"
        else:
            oidc.header["kid"] = "attacker-key"
        with pytest.raises(approvals.ApprovalError):
            approvals.verify_review(record("gha"), transport=Provider("gha"), oidc=oidc,
                                    environ=environ("gha"), clock=lambda: NOW)


@pytest.mark.parametrize("mutation", [
    lambda p: p.protection.update(can_admins_bypass=True),
    lambda p: p.protection["protection_rules"][0].update(prevent_self_review=False),
    lambda p: p.reviews[0].update(state="rejected"),
    lambda p: p.reviews[0]["user"].update(id=10),
    lambda p: p.run.update(run_attempt=2),
    lambda p: p.jobs[1].update(name="Other operation"),
    lambda p: p.jobs[1].update(started_at=stamp(NOW - 200)),
    lambda p: p.jobs[0].update(conclusion="failure"),
    lambda p: setattr(p, "source", p.source.replace(b"environment: esaf-pipelines-execute", b"environment: unprotected")),
])
def test_github_unreviewed_or_stale_operation_rejected(key, mutation):
    provider = Provider("gha")
    mutation(provider)
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_review(record("gha"), transport=provider, oidc=OIDC(key),
                                environ=environ("gha"), clock=lambda: NOW)


@pytest.mark.parametrize("mutation", [
    lambda p: p.run.update(id=8),
    lambda p: p.run.update(sourceVersion="d" * 40),
    lambda p: p.records[4].update(result="failed"),
    lambda p: p.records[4].update(finishTime=stamp(NOW - 130)),
    lambda p: p.records[4].update(attempt=2),
    lambda p: p.records[4].update(previousAttempts=[{"attempt": 1}]),
    lambda p: p.records[4]["task"].update(name="Script"),
    lambda p: p.records[4]["task"].update(id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    lambda p: p.records[3].update(identifier="DifferentJob"),
    lambda p: p.records[3].update(workerName="untrusted-agent"),
    lambda p: p.records[6].update(id="different-job"),
    lambda p: p.task_definition.update(serverOwned=False),
    lambda p: p.task_definition["version"].update(major=0),
    lambda p: setattr(p, "source", p.source.replace(b"allowApproversToApproveTheirOwnRuns: false",
                                                   b"allowApproversToApproveTheirOwnRuns: true")),
])
def test_ado_tampered_failed_old_or_rerun_review_rejected(mutation):
    provider = Provider("ado")
    mutation(provider)
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_review(record("ado"), transport=provider, environ=environ("ado"), clock=lambda: NOW)


def finalizer(provider, key):
    transport, environment_values, oidc = Provider(provider), environ(provider), OIDC(key)
    if provider == "gha":
        transport.jobs[1].update(status="completed", conclusion="success", completed_at=stamp(NOW - 20))
        transport.jobs.append({
            "id": 42, "run_id": 7, "run_attempt": 1, "head_sha": COMMIT,
            "name": f"Finalize reviewed {OPERATION} / {HASH}", "status": "in_progress",
            "started_at": stamp(NOW - 10), "completed_at": None,
            "labels": ["self-hosted", "linux", "esaf-lifecycle-external"]})
        environment_values["GITHUB_JOB"] = "finalize"
        oidc.claims["aud"] = approvals.finalizer_audience(record(provider))
    else:
        final_job, final_stage = "88888888-8888-4888-8888-888888888888", "99999999-9999-4999-8999-999999999999"
        transport.records[6].update(state="completed", result="succeeded", finishTime=stamp(NOW - 20))
        transport.records.extend([
            {"id": final_stage, "parentId": None, "type": "Stage", "name": "Finalize", "attempt": 1},
            {"id": final_job, "parentId": final_stage, "type": "Job", "name": "FinalizeReviewedOperation",
             "identifier": "FinalizeReviewedOperation", "attempt": 1, "state": "inProgress",
             "startTime": stamp(NOW - 10)},
        ])
        environment_values.update(SYSTEM_JOBID=final_job, SYSTEM_STAGEID=final_stage)
    return transport, environment_values, oidc


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_authenticated_same_run_finalizer_attests_terminal_mutator(provider, key):
    transport, environment_values, oidc = finalizer(provider, key)
    proof = approvals.verify_finalizer(record(provider), transport=transport, oidc=oidc,
                                       environ=environment_values, clock=lambda: NOW)
    assert proof["plan_hash"] == HASH and proof["operation_id"] == OPERATION
    assert proof["execution_job_id"] != proof["job_id"]
    assert proof["execution_completed_at"] == stamp(NOW - 20)
    assert "finalizer" in proof["proof_kind"]
    assert transport.run["status"] in ("in_progress", "inProgress"), "No enclosing-run terminal dependency"


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("change", ["active-mutator", "early-finalizer", "rerun", "wrong-operation", "wrong-job"])
def test_finalizer_cannot_attest_an_active_or_different_mutator(provider, key, change):
    transport, env, oidc = finalizer(provider, key)
    if provider == "gha":
        mutator, completion = transport.jobs[1], transport.jobs[2]
        if change == "active-mutator":
            mutator.update(status="in_progress", conclusion=None, completed_at=None)
        elif change == "early-finalizer":
            completion["started_at"] = stamp(NOW - 50)
        elif change == "rerun":
            completion["run_attempt"] = 2
        elif change == "wrong-operation":
            completion["name"] = "Finalize reviewed another operation"
        else:
            env["GITHUB_JOB"] = "execute"
    else:
        mutator, completion = transport.records[6], transport.records[-1]
        if change == "active-mutator":
            mutator.update(state="inProgress", result=None, finishTime=None)
        elif change == "early-finalizer":
            completion["startTime"] = stamp(NOW - 50)
        elif change == "rerun":
            completion["attempt"] = 2
        elif change == "wrong-operation":
            transport.records[3]["name"] = "Review another operation"
        else:
            env["SYSTEM_JOBID"] = EXECUTE
    with pytest.raises(approvals.ApprovalError):
        approvals.verify_finalizer(record(provider), transport=transport, oidc=oidc,
                                    environ=env, clock=lambda: NOW)
