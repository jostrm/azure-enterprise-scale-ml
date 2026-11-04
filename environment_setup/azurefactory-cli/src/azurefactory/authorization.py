"""Fail-closed client checks for granting or revoking a factory's deletion permission.

The Factory API is authoritative and re-verifies everything on confirmation; these checks
only refuse a preview or result that does not describe exactly the requested change of
the enrollment's deletion permission (`allow_delete`) in the provider state.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import BlockedError, ConfigError, FailureError
from .run_claims import STATE_REF, _sha, _text, _uuid

PURPOSE = "authorize-deletion-confirm"
OPERATION = "authorize-deletion"
CAPABILITY = "authorize-deletion-v1"
OPERATION_MODE = "provider-state"
AUDIT_PREFIX = "deletion-authorizations/"
MODES = {"allow": ("ALLOW DELETE ", "authorized"), "revoke": ("REVOKE DELETE ", "revoked")}
# The catalog's readable factory key (factory_catalog_models.factory_key).
FACTORY_KEY = re.compile(r"[a-z][a-z0-9-]{1,79}")
REQUEST_FIELDS = {"contract_version", "folder", "factory_id", "mode"}
ROUTES = ("ado", "gha")


def phrase(mode: str, factory_key: str) -> str:
    return MODES[mode][0] + factory_key


def validate_request(request: Any) -> None:
    if (not isinstance(request, dict) or set(request) != REQUEST_FIELDS
            or type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or not _text(request.get("folder")) or not _uuid(request.get("factory_id"))
            or request.get("mode") not in MODES):
        raise ConfigError("Deletion authorization requires contract 1, an exact folder, factory UUID and "
                          "mode allow or revoke.")


def validate_preview(request: dict[str, Any], preview: Any) -> None:
    def invalid(reason):
        raise ConfigError("Unsafe or incompatible deletion authorization review: " + reason
                          + ". Nothing was authorized.")

    validate_request(request)
    if (not isinstance(preview, dict) or type(preview.get("contract_version")) is not int
            or preview["contract_version"] != 1 or not isinstance(preview.get("capabilities"), list)
            or CAPABILITY not in preview["capabilities"] or preview.get("operation_mode") != OPERATION_MODE):
        invalid("the API must acknowledge " + CAPABILITY + "; no fallback is allowed")
    if preview.get("azure_writes") is not False:
        invalid("a deletion permission change must not change Azure")
    if (preview.get("folder") != request["folder"] or preview.get("factory_id") != request["factory_id"]
            or preview.get("mode") != request["mode"]):
        invalid("the exact folder, factory and mode were not preserved")
    if not _uuid(preview.get("confirmation_id")) or not _sha(preview.get("preview_hash"), 64):
        invalid("missing exact confirmation identity or server review fingerprint")
    expected = MODES[request["mode"]][0]
    stated = preview.get("confirmation_phrase")
    if (not isinstance(stated, str) or not stated.startswith(expected)
            or not FACTORY_KEY.fullmatch(stated[len(expected):])):
        invalid("the server confirmation phrase must be exactly " + expected.strip() + " <factory key>")
    if preview.get("state_ref") != STATE_REF:
        invalid("missing the provider state ref")
    for field in ("warnings", "blockers"):
        if not isinstance(preview.get(field), list) or any(not _text(item) for item in preview[field]):
            invalid("missing exact " + field)
    if type(preview.get("can_execute")) is not bool or preview["can_execute"] == bool(preview["blockers"]):
        invalid("can_execute must be a boolean that agrees with the blockers")
    if not _text(preview.get("expires_at")):
        invalid("missing expiry")
    if not preview["can_execute"]:
        # A review blocked before reading the provider (Blob coordination, no binding) has null state fields.
        raise BlockedError("Deletion authorization is blocked: " + " ".join(preview["blockers"])
                           + " Nothing was authorized.")
    if not _text(preview.get("repository")) or not _sha(preview.get("provider_head"), 40):
        invalid("missing provider repository or reviewed head")
    scopes, bindings = preview.get("scopes"), preview.get("bindings")
    if not isinstance(scopes, list) or any(not _text(scope) for scope in scopes) or len(set(scopes)) != len(scopes):
        invalid("missing the exact resource group scopes")
    if (not isinstance(bindings, list) or bindings != sorted(set(bindings))
            or any(binding not in ROUTES for binding in bindings)):
        invalid("bindings must name the re-pinned ado or gha routes")
    revision, hashes = preview.get("enrollment_revision"), preview.get("coordination_hash")
    if (not isinstance(revision, dict) or set(revision) != {"from", "to"}
            or any(type(revision[key]) is not int or revision[key] < 1 for key in revision)
            or revision["to"] != revision["from"] + (1 if scopes else 0)):
        invalid("the enrollment revision must rise exactly once when scopes change")
    if (not isinstance(hashes, dict) or set(hashes) != {"from", "to"} or any(not _text(hashes[key]) for key in hashes)
            or (hashes["from"] != hashes["to"]) != bool(scopes)):
        invalid("the coordination hash must change exactly when scopes change")
    audit = preview.get("audit_record")
    if scopes:
        if audit != AUDIT_PREFIX + request["factory_id"] + "/" + preview["confirmation_id"] + ".json":
            invalid("missing the exact audit record")
    else:
        # A binding-only repair re-pins the saved bindings to the state an earlier reviewed
        # authorization already wrote, under that authorization's own audit record.
        prefix = AUDIT_PREFIX + request["factory_id"] + "/"
        if (not bindings or not isinstance(audit, str) or not audit.startswith(prefix) or not audit.endswith(".json")
                or not _uuid(audit[len(prefix):-len(".json")])):
            invalid("a binding repair must name the bindings and this factory's earlier audit record")


def repairs_only(preview: dict[str, Any]) -> bool:
    return not preview["scopes"]


def validate_authorization(result: Any, receipt: dict[str, Any]) -> None:
    preview = receipt["preview"]
    head = result.get("head") if isinstance(result, dict) else None
    if (not isinstance(result, dict) or type(result.get("contract_version")) is not int
            or result["contract_version"] != 1 or preview.get("mode") not in MODES
            or result.get("status") != MODES[preview["mode"]][1]
            or result.get("folder") != receipt["folder"] or result.get("factory_id") != preview["factory_id"]
            or result.get("repository") != preview["repository"] or result.get("state_ref") != preview["state_ref"]
            or result.get("previous_head") != preview["provider_head"] or not _sha(head, 40)
            or (head == preview["provider_head"]) != repairs_only(preview)
            or result.get("audit_record") != preview["audit_record"]
            or result.get("bindings_updated") != preview["bindings"] or not isinstance(result.get("message"), str)):
        raise FailureError("Deletion authorization returned an unexpected result. Read the provider state "
                           "before any further action; nothing was retried.")


def describe(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "Change": ("Repair the saved binding only" if repairs_only(preview) else
                   "Grant deletion permission" if preview["mode"] == "allow" else "Revoke deletion permission"),
        "Factory ID": preview["factory_id"], "Saved folder": preview["folder"],
        "Provider repository": preview["repository"], "State ref": preview["state_ref"],
        "Reviewed state head": preview["provider_head"], "Resource group scopes": preview["scopes"],
        "Enrollment revision": preview["enrollment_revision"], "Coordination hash": preview["coordination_hash"],
        "Saved bindings re-pinned": preview["bindings"], "Expires": preview["expires_at"],
        "Server review fingerprint": preview["preview_hash"], "Audit record": preview["audit_record"],
        "Confirmation phrase": preview["confirmation_phrase"], "Cautions": preview["warnings"],
    }
