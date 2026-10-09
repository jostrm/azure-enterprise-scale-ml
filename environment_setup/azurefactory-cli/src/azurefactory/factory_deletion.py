"""Fail-closed checks for the named, whole-factory deletion review."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from .errors import ConfigError, FailureError

PURPOSE = "delete-aifactory-confirm"
CAPABILITY = "delete-aifactory-v1"
RETENTION_CONTRACT = "ordered-project-pipelines-v1"
REQUEST_FIELDS = {"contract_version", "folder", "factory_id", "expected_revision", "version_ref"}


def _text(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _uuid(value: Any) -> bool:
    try:
        parsed = UUID(value)
        return bool(parsed.int) and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_request(request: Any) -> None:
    if (not isinstance(request, dict) or set(request) - REQUEST_FIELDS
            or type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or not _text(request.get("folder")) or not _uuid(request.get("factory_id"))
            or not _hash(request.get("expected_revision"))
            or ("version_ref" in request and not _text(request["version_ref"]))):
        raise ConfigError("Factory deletion requires contract 1, an exact folder and factory UUID, "
                          "a current revision fingerprint, and no narrowed or additional scope.")


def validate_deletion_preview(request: dict[str, Any], preview: Any) -> None:
    from .review import validate_preview

    def invalid(reason):
        raise ConfigError("Unsafe or incompatible factory deletion preview: " + reason + ".")

    validate_request(request)
    if (not isinstance(preview, dict) or type(preview.get("contract_version")) is not int
            or preview["contract_version"] != 1 or not isinstance(preview.get("capabilities"), list)
            or CAPABILITY not in preview["capabilities"]):
        invalid("the API must acknowledge delete-aifactory-v1; no fallback is allowed")
    validate_preview(preview)
    if (preview.get("operation_mode") != "runtime"
            or preview.get("action") != "delete-factory"
            or preview.get("folder") != request["folder"]
            or preview.get("factory_id") != request["factory_id"]
            or preview.get("scale_set_id") is not None or preview.get("project_id") is not None
            or preview.get("deletion_options") is not None
            or preview.get("source_revision") != request["expected_revision"]):
        invalid("the exact whole factory and saved revision were not preserved")
    if not _uuid(preview.get("confirmation_id")) or not _hash(preview.get("preview_hash")):
        invalid("missing exact confirmation identity or server preview fingerprint")
    if (preview.get("deletion_scope") != "whole-factory"
            or preview.get("preserve_entra_groups") is not True
            or preview.get("retain_saved_configuration") is not False):
        invalid("the backend did not prove whole-factory scope, Entra preservation and saved configuration handling")
    policy = preview.get("deletion_retention_policy")
    if (not isinstance(policy, dict) or policy.get("mode") != "preserve-reusable-infrastructure"
            or policy.get("required_execution_contract") != RETENTION_CONTRACT
            or policy.get("execution_scope") != "whole-resource-groups"
            or policy.get("selective_retention_supported") is not False
            or not isinstance(policy.get("limitations"), list) or not policy["limitations"]
            or any(not _text(item) for item in policy["limitations"])):
        invalid("the API must explicitly acknowledge its whole-group retention policy and limitations")
    plan = preview.get("deletion_plan")
    if (not isinstance(plan, dict) or plan.get("contract") != RETENTION_CONTRACT
            or plan.get("retention_policy") != policy):
        invalid("retention policy differs from the server execution plan")
    factory = preview.get("target")
    if (not isinstance(factory, dict) or factory.get("id") != request["factory_id"]
            or not _text(factory.get("key")) or not isinstance(factory.get("scale_sets"), list)
            or not factory["scale_sets"]):
        invalid("missing the exact factory and all its scale sets")
    phrase = preview.get("confirmation_phrase")
    if not _text(phrase) or phrase != "DELETE " + factory["key"]:
        invalid("the server confirmation phrase does not identify the reviewed factory")
    version = preview.get("source_version")
    if (not isinstance(version, dict)
            or any(not _text(version.get(field)) for field in ("requested_version", "branch", "resolved_ref"))
            or ("version_ref" in request and version.get("aifactory_version") != request["version_ref"])):
        invalid("missing or changed backend source version")
    for field in ("effects", "warnings", "retained_resources"):
        if not isinstance(preview.get(field), list) or any(not _text(item) for item in preview[field]):
            invalid("missing exact effects, warnings or retained resource manifest")
    scales = {}
    for scale in factory["scale_sets"]:
        if (not isinstance(scale, dict) or any(not _uuid(scale.get(field)) for field in
                                             ("id", "tenant_id", "subscription_id"))
                or scale.get("environment") not in ("dev", "stage", "prod") or scale["id"] in scales):
            invalid("invalid or duplicate scale-set identity")
        scales[scale["id"]] = scale
    targets = preview.get("deletion_targets")
    if not isinstance(targets, list) or not targets:
        invalid("empty deletion manifest")
    groups, deleted, retained, covered = set(), set(), set(), set()
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("scale_set_id"), str):
            invalid("invalid deletion target")
        scale = scales.get(target["scale_set_id"])
        if (scale is None or target.get("factory_id") != request["factory_id"]
                or target.get("project_id") is not None
                or any(target.get(field) != scale[field] for field in
                       ("environment", "subscription_id", "tenant_id"))):
            invalid("a deletion target broadened or changed its factory, scale set, subscription or tenant")
        name = target.get("resource_group")
        if (not _text(name) or not re.fullmatch(r"[\w().-]{1,90}", name)
                or name.endswith(".") or target.get("name") != name):
            invalid("invalid resource-group name")
        group = f"/subscriptions/{scale['subscription_id']}/resourceGroups/{name}"
        if target.get("resource_id") != group or group.lower() in groups:
            invalid("resource-group identity changed or appeared more than once")
        groups.add(group.lower())
        covered.add(scale["id"])
        members = {}
        for field in ("delete", "retain"):
            entries = target.get(field)
            if not isinstance(entries, list) or (field == "delete" and not entries):
                invalid("missing or empty resource manifest")
            members[field] = set()
            for entry in entries:
                if (not _text(entry) or "\\" in entry or "?" in entry or "#" in entry
                        or any(part in (".", "..", "") for part in entry.split("/")[1:])
                        or not (entry.lower() == group.lower() or
                                entry.lower().startswith(group.lower() + "/providers/"))
                        or entry.lower() in members[field]):
                    invalid("duplicate resource or resource outside its exact reviewed group")
                members[field].add(entry.lower())
        if (members["delete"] & members["retain"]
                or (group.lower() in members["delete"] and members["retain"])):
            invalid("deleted and retained resources contradict each other")
        if group.lower() not in members["delete"] or members["retain"]:
            invalid("the acknowledged whole-group runtime cannot execute selective retention")
        deleted.update(members["delete"])
        retained.update(members["retain"])
    if covered != set(scales):
        invalid("the manifest does not cover every scale set of the whole factory")
    for field in ("protected_resources", "retained_resources"):
        entries = plan.get(field)
        if not isinstance(entries, list):
            invalid("missing frozen plan retention manifest")
        seen = set()
        for entry in entries:
            if (not _text(entry) or not re.fullmatch(
                    r"/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[^/?#\\\x00-\x20]+"
                    r"(?:/providers/[^?#\\\x00-\x20]+)?", entry)
                    or any(part in (".", "..", "") for part in entry.split("/")[1:])
                    or entry.lower() in seen):
                invalid("invalid or duplicate frozen retained resource")
            seen.add(entry.lower())
        if retained & seen:
            invalid("duplicate protected and retained resource entries")
        retained.update(seen)
    if any(keep == group or keep.startswith(group + "/") for group in groups for keep in retained):
        invalid("retained infrastructure overlaps a group selected for cascading deletion")
    listed_retained = preview["retained_resources"]
    if (len({item.lower() for item in listed_retained}) != len(listed_retained)
            or {item.lower() for item in listed_retained} != retained):
        invalid("retained resources differ from the exact target manifests")
    inventory = preview.get("inventory")
    if not isinstance(inventory, list) or any(
            not isinstance(item, dict) or not _text(item.get("resource_id")) for item in inventory):
        invalid("missing exact deletion inventory")
    ids = [item["resource_id"].lower() for item in inventory]
    if len(set(ids)) != len(ids) or set(ids) != deleted:
        invalid("deletion inventory is empty, incomplete or broader than the reviewed manifest")


def validate_job(job: Any, *, factory_id: str | None = None, job_id: str | None = None) -> None:
    if (not isinstance(job, dict) or job.get("action") != "delete-factory"
            or not _uuid(job.get("id")) or not _uuid(job.get("factory_id"))
            or (factory_id is not None and job["factory_id"] != factory_id)
            or (job_id is not None and job["id"] != job_id)
            or job.get("scale_set_id") is not None or job.get("project_id") is not None
            or job.get("status") not in ("queued", "running", "succeeded", "failed", "interrupted")):
        raise FailureError("Deletion returned an incompatible job or changed scope. "
                           "Inspect server state; never blindly retry confirmation.")
