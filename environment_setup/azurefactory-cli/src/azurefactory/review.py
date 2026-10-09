"""Importable review-receipt helpers for safe prepare/confirm workflows."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from .client import AzureFactoryClient, canonical_json_hash, redact_secrets
from .errors import BlockedError, ConfigError, FailureError

RECEIPT_FORMAT = "azurefactory-review-receipt-v1"
def sanitize_preview(value: Any) -> Any:
    return redact_secrets(value, None)


def sanitize_request(request_body: dict[str, Any], operation: str) -> dict[str, Any]:
    clean = redact_secrets(request_body, None)
    if operation == "parameters":
        templates = []
        for item in request_body.get("templates", []):
            templates.append({
                key: item.get(key)
                for key in ("template", "unset", "resource_group_id", "template_spec_id")
                if key in item
            })
            if "parameters" in item:
                templates[-1]["parameter_names"] = sorted(item.get("parameters", {}))
        clean["templates"] = templates
    return clean


def validate_preview(preview: dict[str, Any]) -> None:
    if not isinstance(preview, dict):
        raise FailureError("Malformed preview: expected JSON object.")
    if preview.get("can_execute") is not True:
        raise BlockedError("Preview cannot execute; resolve blockers before confirming.")
    blockers = preview.get("blockers")
    if not isinstance(blockers, list) or blockers:
        raise BlockedError("Preview has blockers; resolve blockers before confirming.")
    if not preview.get("confirmation_id"):
        raise FailureError("Malformed preview: missing confirmation_id.")
    if parse_expires_at(preview.get("expires_at")) <= datetime.now(timezone.utc):
        raise BlockedError("Preview expired before receipt creation.")


def write_receipt(path: str, *, client: AzureFactoryClient, purpose: str, operation: str,
                  request_body: dict[str, Any], preview: dict[str, Any], **extra) -> dict[str, Any]:
    target = Path(path)
    if not isinstance(request_body, dict) or not isinstance(preview, dict):
        raise ConfigError("Reviewed request and preview must be JSON objects.")
    if preview.get("can_execute") is True:
        validate_preview(preview)
        validate_bindings(request_body, preview, purpose, operation)
    sanitized_preview = sanitize_preview(preview)
    sanitized_request = sanitize_request(request_body, operation)
    receipt = {
        "format": RECEIPT_FORMAT,
        "purpose": purpose,
        "base_url": client.canonical_base_url,
        "folder": request_folder(request_body, purpose),
        "operation": operation,
        "operation_mode": preview.get("operation_mode"),
        "confirmation_id": preview.get("confirmation_id"),
        "can_execute": preview.get("can_execute"),
        "expires_at": preview.get("expires_at"),
        "request": sanitized_request,
        "preview": sanitized_preview,
        "request_hash": canonical_json_hash(sanitized_request),
        "preview_hash": canonical_json_hash(sanitized_preview),
        **extra,
    }
    if receipt["can_execute"] is not True or receipt["preview"].get("blockers"):
        receipt["blocked_reason"] = "Preview cannot be confirmed or started."
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ConfigError(f"Refusing to overwrite existing receipt: {path}") from exc
    return receipt


def load_receipt(path: str, *, client: AzureFactoryClient, purpose: str,
                 operation_mode: str | None = None) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        receipt = json.load(handle)
    if not isinstance(receipt, dict) or receipt.get("format") != RECEIPT_FORMAT:
        raise ConfigError("Receipt format is not supported.")
    if receipt.get("purpose") != purpose:
        raise ConfigError("Receipt purpose does not match this command.")
    if not isinstance(receipt.get("operation"), str) or not receipt.get("operation"):
        raise ConfigError("Receipt operation binding is missing.")
    if not isinstance(receipt.get("folder"), str) or not receipt.get("folder"):
        raise ConfigError("Receipt folder binding is missing.")
    if not isinstance(receipt.get("confirmation_id"), str) or not receipt.get("confirmation_id"):
        raise ConfigError("Receipt confirmation_id binding is missing.")
    if receipt.get("base_url") != client.canonical_base_url:
        raise ConfigError("Receipt was reviewed against a different API URL.")
    if operation_mode and receipt.get("operation_mode") != operation_mode:
        raise ConfigError(f"Receipt operation_mode must be {operation_mode}.")
    if receipt.get("can_execute") is not True or not receipt.get("confirmation_id"):
        raise BlockedError("Receipt preview was blocked or malformed; prepare again after resolving blockers.")
    preview = receipt.get("preview")
    request = receipt.get("request")
    if not isinstance(preview, dict) or not isinstance(request, dict):
        raise ConfigError("Receipt is missing reviewed request/preview details.")
    if receipt.get("preview_hash") != canonical_json_hash(preview):
        raise ConfigError("Receipt preview hash does not match its content.")
    if receipt.get("request_hash") != canonical_json_hash(request):
        raise ConfigError("Receipt request hash does not match its content.")
    if receipt.get("folder") != request_folder(request, purpose):
        raise ConfigError("Receipt folder binding is inconsistent.")
    if receipt.get("confirmation_id") != preview.get("confirmation_id"):
        raise ConfigError("Receipt confirmation_id binding is inconsistent.")
    if receipt.get("expires_at") != preview.get("expires_at"):
        raise ConfigError("Receipt expiry binding is inconsistent.")
    if receipt.get("operation_mode") != preview.get("operation_mode"):
        raise ConfigError("Receipt operation_mode binding is inconsistent.")
    validate_preview(preview)
    validate_bindings(request, preview, purpose, receipt["operation"])
    if purpose == "legacy-start" and receipt.get("contract") != preview.get("deployment_contract"):
        raise ConfigError("Receipt deployment acknowledgement was changed.")
    if parse_expires_at(receipt.get("expires_at")) <= datetime.now(timezone.utc):
        raise BlockedError("Receipt expired; prepare again explicitly.")
    return receipt


def parse_expires_at(value: str | None) -> datetime:
    if not isinstance(value, str) or not value:
        raise ConfigError("Receipt is missing expires_at.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError("Receipt expires_at is not a valid ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise ConfigError("Receipt expires_at must include a timezone.")
    return parsed.astimezone(timezone.utc)


def request_folder(request: dict[str, Any], purpose: str) -> str | None:
    if purpose == "creation-workflow-start":
        scope = request.get("scope")
        return scope.get("folder") if isinstance(scope, dict) else request.get("folder")
    if purpose == "bootstrap-start":
        config = request.get("config")
        return config.get("repo_root") if isinstance(config, dict) else None
    return request.get("folder")


def validate_project_selection(request: dict[str, Any], preview: dict[str, Any]) -> None:
    """Bind automatic requests to concrete reviewed targets, not local selection."""
    action = request.get("action")
    if action not in {"add-project", "add-project-placements"}:
        return
    definition = request.get("project") if action == "add-project" else request
    submitted = definition.get("placements", []) if isinstance(definition, dict) else []
    automatic = [item for item in submitted if isinstance(item, dict)
                 and item.get("scale_set_id") == "latest-successful"]
    if not automatic:
        return

    def require(condition):
        if not condition:
            raise ConfigError("Automatic placement preview lacks consistent resolved target/evidence; prepare again on a supporting API.")

    def identifier(value):
        require(isinstance(value, str))
        parsed = UUID(value)
        require(parsed.int != 0 and str(parsed) == value)
        return value

    try:
        require(type(preview.get("contract_version")) is int and preview["contract_version"] == 1
                and preview.get("operation_mode") == "configuration"
                and "latest-successful-placement-v1" in preview.get("capabilities", []))
        require(not request.get("expected_revision") or preview.get("source_revision") == request["expected_revision"])
        target = preview["target"]
        require(identifier(target["id"]) == request["factory_id"] == preview["factory_id"])
        project_id = identifier(preview["project_id"])
        if action == "add-project-placements":
            require(project_id == request["project_id"])
        projects = [item for item in target["projects"] if item["id"] == project_id]
        require(len(projects) == 1)
        project = projects[0]
        if action == "add-project":
            require(project["number"] == request["project"]["number"])
        selections = preview["resolved_placements"]
        require(isinstance(selections, list) and len(selections) == len(automatic))
        environments = [item["environment"] for item in automatic]
        require(len(set(environments)) == len(environments))
        require(sorted(item["environment"] for item in selections) == sorted(environments))
        resolved = {}
        for selected in selections:
            require(selected["selector"] == "latest-successful"
                    and selected["evidence_kind"] == "recorded-verified-common-deployment"
                    and selected["factory_id"] == target["id"]
                    and selected["environment"] in {"dev", "stage", "prod"}
                    and selected["version_ref"] == target["version_ref"])
            for key in ("scale_set_id", "tenant_id", "subscription_id", "job_id"):
                identifier(selected[key])
            if selected.get("deployment_object_id") is not None:
                identifier(selected["deployment_object_id"])
            require(re.fullmatch(r"[a-f0-9]{40}", selected["source_commit"])
                    and re.fullmatch(r"[a-f0-9]{64}", selected["evidence_hash"]))
            completed = datetime.fromisoformat(selected["completed_at"].replace("Z", "+00:00"))
            require(completed.tzinfo is not None)
            for key in ("writer_id", "auth_namespace"):
                require(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", selected[key]))
            require(selected["orchestrator"] in {"gha", "ado"})
            repository_pattern = (r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
                                  if selected["orchestrator"] == "gha" else
                                  r"https://dev\.azure\.com/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+/_git/[A-Za-z0-9_.%-]+")
            require(re.fullmatch(repository_pattern, selected["repository"]))
            scales = [item for item in target["scale_sets"] if item["id"] == selected["scale_set_id"]]
            require(len(scales) == 1 and all(scales[0][key] == selected[key] for key in
                                            ("environment", "tenant_id", "subscription_id", "orchestrator")))
            resolved[selected["environment"]] = selected["scale_set_id"]
        for placement in submitted:
            expected = (resolved[placement["environment"]] if placement["scale_set_id"] == "latest-successful"
                        else placement["scale_set_id"])
            matches = [item for item in project["placements"] if item["environment"] == placement["environment"]]
            require(len(matches) == 1 and matches[0]["scale_set_id"] == expected)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ConfigError("Automatic placement preview contains missing or malformed resolution evidence.") from None


def validate_settings_selection(request: dict[str, Any], preview: dict[str, Any]) -> None:
    """Require the server to acknowledge the selected scope and configuration mode."""
    if request.get("action") != "configure-settings":
        return
    if (type(preview.get("contract_version")) is not int or preview["contract_version"] != 1
            or preview.get("operation_mode") != "configuration"
            or not isinstance(preview.get("target"), dict)
            or preview["target"].get("id") != request.get("factory_id")
            or not request.get("factory_id")
            or any(key not in preview or preview[key] != request.get(key)
                   for key in ("factory_id", "scale_set_id", "project_id"))
            or not isinstance(preview.get("source_revision"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", preview["source_revision"])
            or request.get("expected_revision") is not None
            and preview["source_revision"] != request["expected_revision"]):
        raise ConfigError("Settings preview must acknowledge the exact scope, revision and configuration-only mode; use a supporting API.")


def validate_bindings(request: dict[str, Any], preview: dict[str, Any], purpose: str, operation: str) -> None:
    if purpose in {"catalog-confirm", "parameters-confirm"}:
        if type(request.get("contract_version")) is not int or request["contract_version"] != 1:
            raise ConfigError("Reviewed catalog request must use contract version 1.")
        if type(preview.get("contract_version")) is not int or preview["contract_version"] != 1:
            raise ConfigError("Preview did not acknowledge catalog contract version 1.")
        expected_mode = "runtime" if operation == "runtime-deploy" else "configuration"
        if preview.get("operation_mode") != expected_mode:
            raise ConfigError("Preview operation mode does not match the requested action.")
        if purpose == "catalog-confirm":
            actions = {
                "factory-create": "create-factory", "factory-clone": "clone",
                "scaleset-add": "create-scale-set", "project-add": "add-project",
                "project-add-placements": "add-project-placements", "runtime-deploy": "deploy",
                "enrollment-binding": "configure-binding",
                "catalog-settings": "configure-settings",
            }
            if operation not in actions or request.get("action") != actions[operation]:
                raise ConfigError("Receipt operation does not match the reviewed catalog action.")
            validate_project_selection(request, preview)
            validate_settings_selection(request, preview)
            if operation == "enrollment-binding":
                if (not isinstance(request.get("binding"), dict) or preview.get("binding") != request["binding"]
                        or not isinstance(preview.get("target"), dict)
                        or preview["target"].get("id") != request.get("factory_id")
                        or not request.get("expected_revision")
                        or preview.get("source_revision") != request["expected_revision"]):
                    raise ConfigError("Binding preview must preserve the exact candidate, factory and catalog revision.")
        elif operation != "parameters":
            raise ConfigError("Parameter receipt operation does not match.")
    elif purpose == "delete-aifactory-confirm":
        from .factory_deletion import validate_deletion_preview

        if operation != "delete-aifactory":
            raise ConfigError("Deletion receipt operation does not match.")
        validate_deletion_preview(request, preview)
    elif purpose == "creation-workflow-start":
        if operation != "creation-workflow" or type(preview.get("contract_version")) is not int or preview["contract_version"] != 1:
            raise ConfigError("Expected a registered creation workflow contract.")
        try:
            for field in ("workflow_id", "confirmation_id"):
                identifier = UUID(preview[field])
                if not identifier.int or str(identifier) != preview[field]:
                    raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ConfigError("Workflow preview must contain exact canonical workflow and confirmation IDs.") from None
        if (not isinstance(preview.get("scope"), dict) or not request_folder(request, purpose)
                or preview["scope"].get("folder") != request_folder(request, purpose)
                or not isinstance(preview.get("stage"), str) or not preview["stage"]
                or not preview.get("source_revision") or not preview.get("input_hash")
                or not isinstance(preview.get("effects"), list) or not preview["effects"]
                or not isinstance(preview.get("review"), dict) or not preview["review"]):
            raise ConfigError("Workflow preview is missing its exact stage, scope, source or effects.")
        if "scope" in request:
            if preview["scope"] != request["scope"] or preview["source_revision"] != request.get("expected_revision"):
                raise ConfigError("Workflow preview changed the requested saved scope or revision.")
        elif preview["workflow_id"] != request.get("workflow_id"):
            raise ConfigError("Workflow preview changed the workflow ID.")
        authorization = preview["review"].get("workflow_authorization")
        if request.get("approval_mode") == "whole-workflow":
            if (not isinstance(authorization, dict) or authorization.get("contract") != "bounded-full-bootstrap-v1"
                    or authorization.get("workflow_id") != preview["workflow_id"]
                    or authorization.get("scope") != preview["scope"]
                    or authorization.get("source_revision") != preview["source_revision"]
                    or not authorization.get("stages") or not authorization.get("target")
                    or not authorization.get("template_fingerprint")
                    or not authorization.get("program_fingerprint")
                    or parse_expires_at(authorization.get("expires_at")) <= datetime.now(timezone.utc)):
                raise ConfigError("API did not return the requested bounded whole-workflow authorization.")
            if authorization.get("authorization_hash") != canonical_json_hash(
                    {key: value for key, value in authorization.items() if key != "authorization_hash"}):
                raise ConfigError("Whole-workflow authorization hash does not match its reviewed content.")
        elif authorization:
            raise ConfigError("API expanded per-stage consent into whole-workflow approval.")
    elif purpose == "bootstrap-start":
        if operation != "bootstrap" or preview.get("flow") != "full-bootstrap":
            raise ConfigError("Expected an explicitly reviewed full-bootstrap flow.")
        if (preview.get("config_format") != "bootstrap-env-v1" or
                preview.get("includes_common") is not True or preview.get("includes_initial_project") is not True):
            raise ConfigError("Bootstrap preview did not acknowledge common infrastructure and the initial project.")
        if not isinstance(request.get("config"), dict) or not isinstance(preview.get("config"), dict):
            raise ConfigError("Bootstrap preview is missing its complete configuration.")
        for field in ("launcher", "orchestrator"):
            if request.get(field) != preview.get(field):
                raise ConfigError(f"Bootstrap preview changed the requested {field}.")
        for field, value in request["config"].items():
            if preview["config"].get(field) != value:
                raise ConfigError(f"Bootstrap preview changed the requested configuration field {field}.")
    elif purpose == "legacy-start":
        if operation != "legacy-project-deployment":
            raise ConfigError("Legacy receipt operation does not match.")
        contract = preview.get("deployment_contract")
        if not isinstance(contract, dict) or contract.get("version") != 2:
            raise ConfigError("Legacy preview must acknowledge deployment contract version 2.")
        if contract.get("draft_id") != request.get("draft_id") or contract.get("patch") is not request.get("patch"):
            raise ConfigError("Legacy receipt request and acknowledgement do not match.")
    else:
        raise ConfigError("Unknown review purpose.")
