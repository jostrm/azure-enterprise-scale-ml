import json

import pytest

from aif_lifecycle.domain import errors
from aif_lifecycle.problem import PROBLEM_MEDIA_TYPE, problem_document


@pytest.mark.parametrize("error, status, code", [
    (errors.ValidationFailed("bad"), 400, "validation-failed"),
    (errors.InvalidId("bad id"), 400, "invalid-id"),
    (errors.InvalidSignature("no"), 401, "invalid-signature"),
    (errors.ProtectedTarget("host"), 403, "protected-target"),
    (errors.UnknownId("missing"), 404, "unknown-id"),
    (errors.OperationNotFound("missing"), 404, "operation-not-found"),
    (errors.AlreadyExists("dup"), 409, "already-exists"),
    (errors.InProgress("busy"), 409, "in-progress"),
    (errors.RevisionMismatch("stale"), 409, "revision-mismatch"),
    (errors.InvalidState("not now"), 409, "invalid-state"),
    (errors.ScopeNotSupported("envs"), 409, "scope-not-supported"),
    (errors.ReviewBlocked("blocked"), 409, "review-blocked"),
    (errors.ConfirmationExpired("late"), 410, "confirmation-expired"),
    (errors.UpstreamError("bad gateway"), 502, "upstream-error"),
    (errors.UpstreamUnavailable("down"), 503, "upstream-unavailable"),
    (errors.UpstreamTimeout("slow"), 504, "upstream-timeout"),
])
def test_each_error_has_a_stable_code_and_status(error, status, code):
    assert (error.status, error.code) == (status, code)


def test_problem_document_follows_rfc_9457_with_code_and_correlation_id():
    document = problem_document(errors.AlreadyExists("Scale set aif-121-sdc-dev-002 exists."),
                                correlation_id="c-1", instance="/api/v1/lifecycle/add-scaleset/prepare")
    assert PROBLEM_MEDIA_TYPE == "application/problem+json"
    assert document == {
        "type": "urn:aifactory:lifecycle:problem:already-exists",
        "title": "The target already exists",
        "status": 409,
        "detail": "Scale set aif-121-sdc-dev-002 exists.",
        "code": "already-exists",
        "correlationId": "c-1",
        "instance": "/api/v1/lifecycle/add-scaleset/prepare",
    }


def test_unexpected_exceptions_never_leak_details_or_secrets():
    document = problem_document(RuntimeError("Traceback ... key=supersecret"), correlation_id="c-2", instance="/x")
    text = json.dumps(document)
    assert document["status"] == 500 and document["code"] == "internal-error"
    assert "supersecret" not in text and "Traceback" not in text


def test_extra_fields_are_added_but_cannot_override_the_contract():
    error = errors.ScopeNotSupported("multi env", extra={"environments": ["dev", "stage"], "status": 200})
    document = problem_document(error, correlation_id="c-3", instance="/x")
    assert document["environments"] == ["dev", "stage"]
    assert document["status"] == 409
