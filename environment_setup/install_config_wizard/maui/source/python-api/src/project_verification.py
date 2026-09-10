"""Fresh authenticated ARM evidence for the observed RGs of one saved project."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import operations, scale_set_verification as shared, wizard
from src.factory_scope import current_factory_scope

VerificationRequestError = shared.VerificationRequestError


def _number(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,255}", value):
        return ""
    return value.lstrip("0") or "0"


def _source_signature(root: Path, saved: dict) -> tuple:
    source, _ = wizard._startup_import_candidate(str(root), saved)
    paths = {root / "config-wizard" / "factory_state.json", root / "variables.json"}
    if source:
        paths.add(Path(source))
    signatures = []
    for path in sorted(paths):
        if path.exists():
            shared._ordinary_path(path)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            signatures.append((str(path), digest.digest()))
        else:
            signatures.append((str(path), None))
    return tuple(signatures)


def _saved_selection(folder: str, project_number: str, path: str) -> tuple[Path, dict]:
    number = _number(project_number)
    if not number:
        raise VerificationRequestError("project_number must be a numeric saved-project listing ID.")
    root, snapshot = shared._absolute_path(folder), shared._absolute_path(path)
    try:
        shared._ordinary_path(root, directory=True)
        shared._ordinary_path(snapshot)
        listed = wizard._list_project_snapshots(str(root), create_legacy_dir=False)
        matches = [(key, value) for key, value in listed.items() if _number(key) == number]
        if not matches:
            raise VerificationRequestError("Saved project no longer exists; refresh the list.", 404)
        matching_paths = [key for key, value in matches if shared._same_path(snapshot, Path(value))]
        if len(matching_paths) != 1:
            raise VerificationRequestError("Snapshot path does not match the selected project.", 409)
        with snapshot.open("rb") as stream:
            raw = stream.read(shared.MAX_JSON_BYTES + 1)
        if len(raw) > shared.MAX_JSON_BYTES:
            raise VerificationRequestError("Saved project snapshot is too large.")
        saved = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(saved, dict):
            raise VerificationRequestError("Saved project snapshot must contain a JSON object.")
        if _number(saved.get("project_number_000")) != number:
            raise VerificationRequestError("Snapshot identity does not match the selected project.", 409)
        local = root / "config-wizard" / f"project-{matching_paths[0]}" / "project_state.json"
        owner = saved.get("_save_folder")
        if not shared._same_path(snapshot, local) and not owner:
            raise VerificationRequestError("Legacy snapshot must identify its factory folder.", 409)
        if owner and not shared._same_path(shared._absolute_path(owner), root):
            raise VerificationRequestError("Snapshot belongs to a different factory folder.", 409)
        before = _source_signature(root, saved)
        effective = wizard._load_project_state(str(snapshot), str(root))
        if _number(effective.get("project_number_000")) != number:
            raise VerificationRequestError("Hydrated identity does not match the selected project.", 409)
        if _source_signature(root, saved) != before:
            raise VerificationRequestError("Current project configuration changed while loading.", 409)
        return root, {"raw": raw, "effective": effective, "sources": before}
    except (FileNotFoundError, NotADirectoryError):
        raise VerificationRequestError("Factory folder or saved project snapshot was not found.", 404) from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise VerificationRequestError("Saved project configuration is unreadable or malformed.") from None


def _reference(reference: dict) -> tuple[str, str, str] | None:
    parsed = shared._resource_id(reference.get("id"))
    if parsed is None:
        return None
    _, subscription, name = parsed
    if any(reference.get(key) and shared._guid(reference[key]) != subscription
           for key in ("subscription_id", "subscriptionId")):
        return None
    if reference.get("name") and (
        shared._group_name(reference["name"]).casefold() != name.casefold()
    ):
        return None
    return parsed


def _references(environment: dict) -> list | None:
    refs = environment.get("resource_group_refs")
    if refs is not None and not isinstance(refs, list):
        return None
    if refs:
        return refs
    name = shared._group_name(environment.get("resource_group"))
    names = environment.get("resource_groups") or []
    if not isinstance(names, list):
        return None
    # Old overviews expose only one subscription: never combine it with an
    # array of group names whose subscriptions are no longer knowable.
    if any(not isinstance(item, str) or item.casefold() != name.casefold() for item in names):
        return None
    if not name:
        return []
    subscription = shared._guid(environment.get("subscription_id"))
    if not subscription:
        return None
    return [{"id": f"/subscriptions/{subscription}/resourceGroups/{name}",
             "name": name, "subscription_id": subscription,
             "tenant_id": environment.get("tenant_id", "")}]


def _region(reference: dict, environment: dict, groups: list, resource_id: str) -> str:
    locations = {
        shared._text(reference.get(key)).casefold() for key in ("location", "region")
        if reference.get(key)
    }
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Invalid resource-group metadata.")
        if str(group.get("id", "")).casefold() == resource_id.casefold():
            if _reference(group) is None:
                raise ValueError("Inconsistent resource-group metadata.")
            locations.add(shared._text(group.get("location")).casefold())
    if not locations:
        regions = environment.get("regions") or []
        if not isinstance(regions, list):
            raise ValueError("Invalid environment regions.")
        locations.update(shared._text(region).casefold() for region in regions)
        if environment.get("region"):
            locations.add(shared._text(environment["region"]).casefold())
    if len(locations) != 1 or not next(iter(locations)):
        raise ValueError("Resource-group region is missing or ambiguous.")
    return next(iter(locations))


def _candidates(overview: dict, selected: dict, number: str, scope: dict) -> tuple[list, dict]:
    tenants = {shared._guid(sub): shared._guid(tenant)
               for sub, tenant in scope["subscription_tenants"].items()}
    if any(not shared._guid(tenant) for tenant in scope["tenant_ids"]):
        raise ValueError("Invalid factory tenant.")
    groups = overview.get("resource_inventory", {}).get("resource_groups", [])
    if not isinstance(groups, list):
        raise ValueError("Invalid group inventory.")
    candidates = {}
    projects = overview["projects"]
    if not isinstance(projects, list):
        raise ValueError("Invalid project inventory.")
    for project in projects:
        if not isinstance(project, dict):
            raise ValueError("Invalid project metadata.")
        if _number(project.get("project_number")) != number:
            continue
        environments = project["environments"]
        if not isinstance(environments, list):
            raise ValueError("Invalid project environments.")
        for environment in environments:
            if not isinstance(environment, dict):
                raise ValueError("Invalid project environment.")
            env = environment["environment"]
            if env not in ("dev", "stage", "prod"):
                raise ValueError("Invalid project environment.")
            references = _references(environment)
            if references is None:
                raise ValueError("Missing or inconsistent resource-group references.")
            for reference in references:
                parsed = _reference(reference) if isinstance(reference, dict) else None
                if parsed is None:
                    raise ValueError("Invalid resource-group reference.")
                resource_id, subscription, name = parsed
                identity = operations.parse_resource_group_name(name)
                if (identity["is_common"] or _number(identity["project_number"]) != number
                        or identity["environment"] != env
                        or subscription not in selected["subscription_ids"]):
                    continue
                targets = [target for target in selected["monitoring_targets"]
                           if target["environment"] == env
                           and shared._guid(target["subscription_id"]) == subscription]
                if not targets or not operations.AzureInventoryProvider._is_relevant_group(
                    name, {"monitoring_targets": targets}, subscription,
                ):
                    continue
                region = _region(reference, environment, groups, resource_id)
                targets = [target for target in targets if target["region"] == region]
                if not targets or not operations.AzureInventoryProvider._is_relevant_group(
                    name, {"monitoring_targets": targets}, subscription,
                ):
                    continue
                raw_tenant = reference.get("tenant_id") or reference.get("tenantId")
                if raw_tenant:
                    tenant = shared._guid(raw_tenant)
                    if (not tenant or tenants.get(subscription, tenant) != tenant
                            or any(reference.get(key) and shared._guid(reference[key]) != tenant
                                   for key in ("tenant_id", "tenantId"))):
                        raise ValueError("Inconsistent resource-group tenant.")
                    tenants[subscription] = tenant
                candidates.setdefault(resource_id.casefold(), (resource_id, subscription))
    return list(candidates.values()), tenants


def verify_resource_groups(
    aifactory_folder: str, project_number: str, path: str, *,
    service=None, runner=None, opener=None,
) -> dict:
    """Check only exact observed project RGs using fresh authenticated ARM GETs."""
    root, saved = _saved_selection(aifactory_folder, project_number, path)

    def result(message: str, checks=None) -> dict:
        return {"project_number": project_number,
                "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "message": message, "checks": checks or []}

    try:
        scope = current_factory_scope(root)
        selected = shared._selected_scope(saved["effective"], scope)
    except (OSError, ValueError, TypeError, KeyError):
        return result("Current factory scope is unreadable or invalid; no resource groups were checked.")
    if selected is None:
        return result("Saved project is outside or missing the active factory scope; no resource groups were checked.")
    try:
        overview = (service or operations.OperationsService()).overview(
            str(root), include_azure=True, force_refresh=False,
        )
        if not shared._inventory_matches(overview["factory"], root, scope, selected):
            return result("Inventory does not match the current factory scope; refresh before verifying.")
        if _saved_selection(str(root), project_number, path)[1] != saved:
            return result("Saved project changed while loading inventory; refresh before verifying.")
        candidates, tenants = _candidates(overview, selected, _number(project_number), scope)
    except (operations.AzureCollectionError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return result("Scoped Azure inventory or observed resource-group identity is unavailable or inconsistent; no resource groups were checked.")
    if not candidates:
        return result("No observed resource groups match this saved project.")
    if len(candidates) > shared.MAX_GROUPS:
        return result(f"More than {shared.MAX_GROUPS} project resource groups matched; verification was not attempted.")
    checks = shared._verify_candidates(candidates, tenants, runner=runner, opener=opener)
    try:
        unchanged = (current_factory_scope(root) == scope
                     and _saved_selection(str(root), project_number, path)[1] == saved)
    except (OSError, ValueError, TypeError, KeyError):
        unchanged = False
    if not unchanged:
        for check in checks:
            check.update(verified=False, message="Configuration changed during verification; refresh the saved-project list.")
        return result("Configuration changed during verification. No current-project access is inferred.", checks)
    verified = sum(check["verified"] for check in checks)
    return result(f"{verified} of {len(checks)} project resource groups verified with authenticated ARM HTTP 200.", checks)
