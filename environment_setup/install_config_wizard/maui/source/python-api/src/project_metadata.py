"""Pure project-scoped display metadata; callers supply only the selected project's state."""

from __future__ import annotations

import json
import re
from uuid import UUID


UNKNOWN_OWNER = "Unknown"
_OWNER_KEYS = ("owner", "projectowner", "owneremail", "projectowners", "aifprojectowners")


def _display_text(value):
    if isinstance(value, list):
        values = [_display_text(item) for item in value]
        result = ", ".join(dict.fromkeys(item for item in values if item))
        return result if len(result) <= 1024 else ""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if (
        not value or len(value) > 1024 or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or value.casefold() in {"unknown", "none", "null", "n/a", "todo", "tbd"}
        or any(marker in value.casefold() for marker in ("<todo>", "$(", "${", "{{", "}}"))
    ):
        return ""
    return value


def _same_project(state, project_number):
    if not isinstance(state, dict):
        return False
    declared = str(state.get("project_number_000") or state.get("project_number") or "").strip()
    if project_number is None or not declared:
        return True
    selected = str(project_number).strip()
    return declared.isdigit() and selected.isdigit() and int(declared) == int(selected)


def owner_from_project_state(state, project_number=None):
    """Return a concrete owner/group or Unknown; never look up another project or folder."""
    if not _same_project(state, project_number):
        return UNKNOWN_OWNER
    owner = _display_text(state.get("technical_admins_email"))
    if owner:
        return owner
    for field in ("tagsProject", "tags"):
        tags = state.get(field)
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except ValueError:
                continue
        if not isinstance(tags, dict):
            continue
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(key).casefold()): value for key, value in tags.items()
        }
        for key in _OWNER_KEYS:
            owner = _display_text(normalized.get(key))
            if owner:
                return owner
    return UNKNOWN_OWNER


def planned_environments_from_project_state(state, project_number=None):
    """Only explicitly configured, valid dev/test/prod subscription IDs; no fallback or inference."""
    if not _same_project(state, project_number):
        return []
    result = []
    for environment, key in (("dev", "dev_sub_id"), ("stage", "test_sub_id"), ("prod", "prod_sub_id")):
        value = _display_text(state.get(key))
        try:
            identifier = UUID(value)
        except (ValueError, AttributeError):
            continue
        if value.casefold() == str(identifier) and identifier.int:
            result.append(environment)
    return result


def project_state_in_factory_scope(state, scope, orchestrator=""):
    """Use the existing verification scope matcher, without filling missing identity from defaults."""
    from src import scale_set_verification as shared

    if not isinstance(state, dict):
        return False
    route = _display_text(state.get("orchestrator")).casefold()
    if route and (route not in {"ado", "gha"} or (orchestrator and route != orchestrator)):
        return False
    try:
        selected = shared._selected_scope(state, scope)
    except (KeyError, TypeError, ValueError):
        return False
    if selected is None:
        return False
    tenant = _display_text(state.get("tenantId"))
    if tenant and (
        not shared._guid(tenant)
        or shared._guid(tenant) not in {shared._guid(value) for value in scope["tenant_ids"]}
    ):
        return False
    return True


def current_factory_project_snapshot(folder, project_number, path, scope, orchestrator=""):
    """Read only a verified local selection; never hydrate historical scope into current membership."""
    from src import project_verification

    try:
        _, selection = project_verification._saved_selection(folder, str(project_number), path)
        state = json.loads(selection["raw"].decode("utf-8-sig"))
    except (project_verification.VerificationRequestError, OSError, ValueError, TypeError):
        return None
    return state if project_state_in_factory_scope(state, scope, orchestrator) else None
