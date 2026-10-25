"""Fail-closed client checks for enrolling an added scale set in a single-writer factory.

A single-writer factory's deployment binding and live enrollment cover only the scale sets and projects that were
enrolled, so the Factory API refuses to deploy an added scale set until the reviewed provider-state operation
enroll-scale-set extends them: it covers the scale set's common resource group and the group of every project already
placed on it at prepare time, creates missing groups, assigns the deployment identity's roles on exactly those
groups, writes the enrollment with one compare-and-swap and re-pins the saved binding. The Factory API is
authoritative and re-verifies everything on confirmation; these checks only refuse a review or result that does not
describe exactly that change.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import BlockedError, ConfigError, FailureError
from .run_claims import STATE_REF, _sha, _text, _uuid

OPERATION = "enroll-scale-set"
CAPABILITY = "enroll-scale-set-v1"
OPERATION_MODE = "provider-state-and-arm"
AUDIT_PREFIX = "scale-set-enrollments/"
PHRASE_PREFIX = "ENROLL SCALE SET "
BLOCKED_PREFIX = "Scale-set enrollment blocked: "
BLOB_BLOCKER = "Blob-coordinated factories are not supported yet; nothing was changed."
TOO_OLD = ("Factory API too old for enroll-scale-set: it needs an API supporting the enroll-scale-set routes; "
           "no fallback was attempted.")
# The factory key is the factory prefix without its trailing dash (for example aif-128).
FACTORY_KEY = re.compile(r"[a-z][a-z0-9-]{1,79}")
SUFFIX = re.compile(r"\d{3}")
REQUEST_FIELDS = {"contract_version", "folder", "factory_id", "scale_set_id"}
CONFIRM_FIELDS = {"contract_version", "folder", "confirmation_id", "preview_hash", "confirmation_phrase"}
STATUSES = ("enrolled", "binding-repaired")
ROUTES = ("ado", "gha")


def phrase(factory_key: str, suffix: str) -> str:
    return f"{PHRASE_PREFIX}{factory_key} {suffix}"


def _phrase_ok(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(PHRASE_PREFIX):
        return False
    key, _, suffix = value[len(PHRASE_PREFIX):].rpartition(" ")
    return bool(FACTORY_KEY.fullmatch(key)) and bool(SUFFIX.fullmatch(suffix))


def validate_request(request: Any) -> None:
    if (not isinstance(request, dict) or set(request) != REQUEST_FIELDS
            or type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or not _text(request.get("folder")) or not _uuid(request.get("factory_id"))
            or not _uuid(request.get("scale_set_id"))):
        raise ConfigError("Scale-set enrollment requires contract 1, an exact folder, factory UUID and scale-set UUID.")


def validate_confirm_request(body: Any) -> None:
    if (not isinstance(body, dict) or set(body) != CONFIRM_FIELDS
            or type(body.get("contract_version")) is not int or body["contract_version"] != 1
            or not _text(body.get("folder")) or not _uuid(body.get("confirmation_id"))
            or not _sha(body.get("preview_hash"), 64) or not _phrase_ok(body.get("confirmation_phrase"))):
        raise ConfigError("Scale-set enrollment confirmation requires contract 1, the exact folder, confirmation ID, "
                          "server review fingerprint and ENROLL SCALE SET <factory key> <suffix>.")


def blob_blocked(preview: Any) -> bool:
    """The review refused only because the factory is Blob-coordinated (it has no single-writer enrollment)."""
    return isinstance(preview, dict) and preview.get("blockers") == [BLOB_BLOCKER]


def validate_preview(request: dict[str, Any], preview: Any) -> None:
    def invalid(reason):
        raise ConfigError("Unsafe or incompatible scale-set enrollment review: " + reason + ". Nothing was changed.")

    validate_request(request)
    if (not isinstance(preview, dict) or type(preview.get("contract_version")) is not int
            or preview["contract_version"] != 1 or not isinstance(preview.get("capabilities"), list)
            or CAPABILITY not in preview["capabilities"] or preview.get("operation_mode") != OPERATION_MODE):
        invalid("the API must acknowledge " + CAPABILITY + " in " + OPERATION_MODE + " mode; no fallback is allowed")
    if any(preview.get(key) != request[key] for key in ("folder", "factory_id", "scale_set_id")):
        invalid("the exact folder, factory and scale set were not preserved")
    if not _uuid(preview.get("confirmation_id")) or not _sha(preview.get("preview_hash"), 64):
        invalid("missing exact confirmation identity or server review fingerprint")
    if not _phrase_ok(preview.get("confirmation_phrase")):
        invalid("the server confirmation phrase must be exactly ENROLL SCALE SET <factory key> <suffix>")
    if preview.get("state_ref") != STATE_REF:
        invalid("missing the provider state ref")
    for field in ("warnings", "blockers"):
        if not isinstance(preview.get(field), list) or any(not _text(item) for item in preview[field]):
            invalid("missing exact " + field)
    if type(preview.get("can_execute")) is not bool or preview["can_execute"] == bool(preview["blockers"]):
        invalid("can_execute must be a boolean that agrees with the blockers")
    if not _text(preview.get("expires_at")):
        invalid("missing expiry")
    groups, creations, assignments = (preview.get("resource_group_ids"), preview.get("resource_group_creations"),
                                      preview.get("role_assignments"))
    if (not isinstance(groups, list) or not isinstance(creations, list) or any(not _text(item) for item in groups)
            or len(set(groups)) != len(groups) or any(item != item.lower() for item in groups)
            or any(item not in groups for item in creations)):
        invalid("the resource groups to enroll and create must be exact lowercase IDs")
    if not isinstance(assignments, list) or any(
            not isinstance(item, dict) or item.get("scope") not in groups or not _text(item.get("role_definition_id"))
            or not _text(item.get("assignment_id")) or type(item.get("exists")) is not bool for item in assignments):
        invalid("the role assignments must name exact enrolled resource group scopes")
    pending = bool(creations) or any(not item["exists"] for item in assignments)
    if type(preview.get("azure_writes")) is not bool or preview["azure_writes"] != pending:
        invalid("azure_writes must be true exactly when a resource group or role assignment is created")
    if not preview["can_execute"]:
        # A review blocked before reading the provider (Blob coordination, no binding) has null state fields.
        raise BlockedError("Scale-set enrollment is blocked: " + " ".join(preview["blockers"])
                           + " Nothing was changed.")
    if not _text(preview.get("repository")) or not _sha(preview.get("provider_head"), 40):
        invalid("missing provider repository or reviewed head")
    subscription = preview.get("subscription_id")
    if not _uuid(subscription) or not groups or any(
            not item.startswith(f"/subscriptions/{subscription}/resourcegroups/") for item in groups):
        invalid("the resource groups to enroll must be in the reviewed subscription")
    bindings = preview.get("bindings")
    if (not isinstance(bindings, list) or bindings != sorted(set(bindings))
            or any(binding not in ROUTES for binding in bindings)):
        invalid("bindings must name the re-pinned ado or gha routes")
    revision, hashes = preview.get("enrollment_revision"), preview.get("coordination_hash")
    if (not isinstance(revision, dict) or set(revision) != {"from", "to"}
            or any(type(revision[key]) is not int or revision[key] < 1 for key in revision)
            or revision["to"] - revision["from"] not in (0, 1)):
        invalid("the enrollment revision must rise at most once")
    changes = revision["to"] != revision["from"]
    if (not isinstance(hashes, dict) or set(hashes) != {"from", "to"} or any(not _text(hashes[key]) for key in hashes)
            or (hashes["from"] != hashes["to"]) != changes):
        invalid("the coordination hash must change exactly when the enrollment changes")
    audit, prefix = preview.get("audit_record"), AUDIT_PREFIX + request["factory_id"] + "/"
    if changes:
        if audit != prefix + preview["confirmation_id"] + ".json":
            invalid("missing the exact audit record")
    elif (not bindings or not isinstance(audit, str) or not audit.startswith(prefix) or not audit.endswith(".json")
          or not _uuid(audit[len(prefix):-len(".json")])):
        # A binding-only repair re-pins the saved bindings to the state an earlier reviewed enrollment wrote.
        invalid("a binding repair must name the bindings and this factory's earlier audit record")


def repairs_only(preview: dict[str, Any]) -> bool:
    revision = preview.get("enrollment_revision") or {}
    return revision.get("to") == revision.get("from")


def validate_result(result: Any, preview: dict[str, Any]) -> None:
    created = {item["assignment_id"] for item in preview.get("role_assignments") or [] if not item.get("exists")}
    head = result.get("head") if isinstance(result, dict) else None
    if (not isinstance(result, dict) or type(result.get("contract_version")) is not int
            or result["contract_version"] != 1 or result.get("status") not in STATUSES
            or any(result.get(key) != preview.get(key) for key in (
                "folder", "factory_id", "scale_set_id", "repository", "state_ref", "audit_record",
                "resource_group_ids"))
            or result.get("previous_head") != preview.get("provider_head") or not _sha(head, 40)
            or (head == result["previous_head"]) != (result["status"] == "binding-repaired")
            or not isinstance(result.get("resource_groups_created"), list)
            or any(item not in preview["resource_group_creations"] for item in result["resource_groups_created"])
            or not isinstance(result.get("role_assignments_created"), list)
            or any(item not in created for item in result["role_assignments_created"])
            or result.get("bindings_updated") != preview.get("bindings") or not isinstance(result.get("message"), str)):
        raise FailureError("Scale-set enrollment returned an unexpected result. Read the provider state before any "
                           "further action; nothing was retried.")


def describe(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "Change": "Repair the saved binding only" if repairs_only(preview) else "Enroll the scale set",
        "Factory ID": preview["factory_id"], "Scale set ID": preview["scale_set_id"],
        "Saved folder": preview["folder"], "Provider repository": preview["repository"],
        "State ref": preview["state_ref"], "Reviewed state head": preview["provider_head"],
        "Resource groups enrolled": preview["resource_group_ids"],
        "Resource groups created": preview["resource_group_creations"],
        "Role assignments": preview["role_assignments"], "Azure writes": preview["azure_writes"],
        "Enrollment revision": preview["enrollment_revision"], "Coordination hash": preview["coordination_hash"],
        "Saved bindings re-pinned": preview["bindings"], "Expires": preview["expires_at"],
        "Server review fingerprint": preview["preview_hash"], "Audit record": preview["audit_record"],
        "Confirmation phrase": preview["confirmation_phrase"], "Cautions": preview["warnings"],
    }
