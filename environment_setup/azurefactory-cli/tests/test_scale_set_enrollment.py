"""Client checks for enrolling an added scale set in a single-writer factory (enroll-scale-set-v1)."""

from __future__ import annotations

import copy

import pytest

from azurefactory.errors import BlockedError, ConfigError, FailureError
from azurefactory.scale_set_enrollment import (BLOB_BLOCKER, blob_blocked, phrase, validate_confirm_request,
                                               validate_preview, validate_request, validate_result)

FOLDER = r"C:\repos\byor-128\azurefactory"
FACTORY = "11d7fc57-56ee-46d6-919c-3a3d4c8cbb4b"
SCALE = "22222222-2222-4222-8222-222222222222"
CONFIRMATION = "55555555-5555-4555-8555-555555555555"
SUBSCRIPTION = "f0fe8b33-73bf-41e4-9997-e3920d793c06"
COMMON = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/aif-128-esml-common-sdc-dev-002"
PROJECT = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/aif-128-esml-project001-sdc-dev-002-rg"
REQUEST = {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY, "scale_set_id": SCALE}
CONTRIBUTOR = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"


def preview(**changes):
    value = {
        "contract_version": 1, "capabilities": ["enroll-scale-set-v1"], "operation_mode": "provider-state-and-arm",
        "azure_writes": True, "can_execute": True, "folder": FOLDER, "factory_id": FACTORY, "scale_set_id": SCALE,
        "repository": "jostrm/byor-128", "state_ref": "refs/heads/aifactory-state/single-writer-v1",
        "provider_head": "a" * 40, "writer_id": "gha-writer", "auth_namespace": "aif-128",
        "deployment_object_id": "33333333-3333-4333-8333-333333333333", "subscription_id": SUBSCRIPTION,
        "resource_group_ids": [COMMON, PROJECT], "common_dependency_ids": [],
        "resource_group_creations": [COMMON],
        "role_assignments": [{"scope": COMMON, "role_definition_id": CONTRIBUTOR, "assignment_id": "a1", "exists": False},
                             {"scope": PROJECT, "role_definition_id": CONTRIBUTOR, "assignment_id": "a2", "exists": True}],
        "enrollment_revision": {"from": 3, "to": 4}, "coordination_hash": {"from": "h3", "to": "h4"},
        "bindings": ["gha"], "warnings": [], "blockers": [], "confirmation_id": CONFIRMATION,
        "preview_hash": "c" * 64, "confirmation_phrase": "ENROLL SCALE SET aif-128 002",
        "audit_record": f"scale-set-enrollments/{FACTORY}/{CONFIRMATION}.json", "expires_at": "2026-10-25T23:10:00Z",
    }
    value.update(changes)
    return value


def blocked(blockers, **changes):
    return preview(can_execute=False, blockers=blockers, azure_writes=False, repository=None, provider_head=None,
                   writer_id=None, auth_namespace=None, deployment_object_id=None, resource_group_ids=[],
                   resource_group_creations=[], role_assignments=[], enrollment_revision={"from": None, "to": None},
                   coordination_hash={"from": None, "to": None}, bindings=[], **changes)


def result(**changes):
    value = {"contract_version": 1, "status": "enrolled", "folder": FOLDER, "factory_id": FACTORY, "scale_set_id": SCALE,
             "repository": "jostrm/byor-128", "state_ref": "refs/heads/aifactory-state/single-writer-v1",
             "previous_head": "a" * 40, "head": "b" * 40,
             "audit_record": f"scale-set-enrollments/{FACTORY}/{CONFIRMATION}.json",
             "resource_group_ids": [COMMON, PROJECT], "resource_groups_created": [COMMON],
             "role_assignments_created": ["a1"], "bindings_updated": ["gha"], "message": "Enrolled."}
    value.update(changes)
    return value


def test_the_phrase_names_the_factory_key_and_the_scale_set_suffix():
    assert phrase("aif-128", "002") == "ENROLL SCALE SET aif-128 002"


def test_a_closed_request_is_accepted():
    validate_request(REQUEST)


@pytest.mark.parametrize("change", [
    {"extra": 1}, {"contract_version": 2}, {"contract_version": True}, {"folder": ""}, {"factory_id": "nope"},
    {"scale_set_id": "00000000-0000-0000-0000-000000000000"},
])
def test_an_open_or_wrong_request_is_refused_before_any_call(change):
    with pytest.raises(ConfigError, match="Scale-set enrollment requires"):
        validate_request({**REQUEST, **change})


def test_a_confirm_request_needs_the_reviewed_identity_hash_and_phrase():
    body = {"contract_version": 1, "folder": FOLDER, "confirmation_id": CONFIRMATION, "preview_hash": "c" * 64,
            "confirmation_phrase": "ENROLL SCALE SET aif-128 002"}
    validate_confirm_request(body)
    for change in ({"preview_hash": "C" * 64}, {"confirmation_id": "x"}, {"confirmation_phrase": "ENROLL aif-128"},
                   {"extra": True}):
        with pytest.raises(ConfigError):
            validate_confirm_request({**body, **change})


def test_an_executable_review_passes():
    validate_preview(REQUEST, preview())


@pytest.mark.parametrize("change,reason", [
    ({"capabilities": []}, "enroll-scale-set-v1"),
    ({"operation_mode": "provider-state"}, "enroll-scale-set-v1"),
    ({"scale_set_id": "44444444-4444-4444-8444-444444444444"}, "preserved"),
    ({"folder": r"C:\other"}, "preserved"),
    ({"confirmation_phrase": "ENROLL SCALE SET aif-128"}, "confirmation phrase"),
    ({"confirmation_phrase": "ENROLL SCALE SET  002"}, "confirmation phrase"),
    ({"confirmation_phrase": "enroll scale set aif-128 002"}, "confirmation phrase"),
    ({"preview_hash": "x"}, "fingerprint"),
    ({"can_execute": False}, "can_execute"),
    ({"azure_writes": False}, "azure_writes"),
    ({"resource_group_creations": [COMMON.replace("002", "009")]}, "resource groups"),
    ({"resource_group_ids": [COMMON.upper()]}, "resource groups"),
    ({"resource_group_ids": [COMMON, COMMON]}, "resource groups"),
    ({"resource_group_ids": []}, "resource groups"),
    ({"role_assignments": [{"scope": "/subscriptions/x", "role_definition_id": CONTRIBUTOR, "assignment_id": "a",
                            "exists": False}]}, "role assignments"),
    ({"bindings": ["gha", "gha"]}, "bindings"),
    ({"enrollment_revision": {"from": 3, "to": 5}}, "revision"),
    ({"coordination_hash": {"from": "h3", "to": "h3"}}, "coordination hash"),
    ({"audit_record": "scale-set-enrollments/other.json"}, "audit record"),
    ({"state_ref": "refs/heads/main"}, "state ref"),
    ({"provider_head": None}, "provider"),
])
def test_an_unsafe_review_is_refused(change, reason):
    with pytest.raises(ConfigError, match=reason):
        validate_preview(REQUEST, preview(**change))


def test_a_binding_only_repair_keeps_the_revision_and_names_an_earlier_audit_record():
    earlier = f"scale-set-enrollments/{FACTORY}/77777777-7777-4777-8777-777777777777.json"
    repair = preview(enrollment_revision={"from": 4, "to": 4}, coordination_hash={"from": "h4", "to": "h4"},
                     resource_group_creations=[], azure_writes=False, audit_record=earlier,
                     role_assignments=[{"scope": COMMON, "role_definition_id": CONTRIBUTOR, "assignment_id": "a1",
                                        "exists": True}])
    validate_preview(REQUEST, repair)
    with pytest.raises(ConfigError, match="bindings"):
        validate_preview(REQUEST, {**repair, "bindings": []})


def test_a_blocked_review_is_reported_and_never_approvable():
    with pytest.raises(BlockedError, match="Nothing was changed"):
        validate_preview(REQUEST, blocked(["Scale-set enrollment blocked: the binding is stale."]))


def test_the_blob_blocker_is_recognized_exactly():
    review = blocked([BLOB_BLOCKER])
    assert blob_blocked(review)
    assert not blob_blocked(blocked([BLOB_BLOCKER, "Another blocker."]))
    assert not blob_blocked(preview())
    with pytest.raises(BlockedError, match="Blob-coordinated"):
        validate_preview(REQUEST, review)


def test_a_matching_result_passes_and_a_repair_keeps_the_head():
    validate_result(result(), preview())
    validate_result(result(status="binding-repaired", head="a" * 40, resource_groups_created=[],
                           role_assignments_created=[]), preview())


@pytest.mark.parametrize("change", [
    {"status": "authorized"}, {"head": "a" * 40}, {"status": "binding-repaired"}, {"scale_set_id": FACTORY},
    {"audit_record": "scale-set-enrollments/x.json"}, {"resource_group_ids": [COMMON]},
    {"resource_groups_created": [PROJECT]}, {"role_assignments_created": ["a2"]}, {"bindings_updated": []},
    {"previous_head": "b" * 40}, {"message": None},
])
def test_an_unexpected_result_is_a_failure_that_is_never_retried(change):
    with pytest.raises(FailureError, match="nothing was retried"):
        validate_result(result(**change), preview())


def test_checks_do_not_change_their_inputs():
    review = preview()
    before = copy.deepcopy(review)
    validate_preview(REQUEST, review)
    validate_result(result(), review)
    assert review == before
