"""Project configuration and local recovery state for interactive publishing."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import runpy
import tempfile

from .foundry_publishing import PreparationRequest
from .m365_publishing import METADATA_FIELDS

ENVIRONMENTS = ("dev", "stage", "test", "prod")
SCOPES = ("Shared", "Tenant")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON property: {key}")
        result[key] = value
    return result


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def _metadata(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - set(METADATA_FIELDS):
        raise ValueError("Publishing metadata contains unsupported fields.")
    if any(not isinstance(item, str) for item in value.values()):
        raise ValueError("Publishing metadata values must be strings.")
    return dict(value)


def _resolved(value) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("Target identifiers must be strings.")
    return "" if value.startswith("$(") and value.endswith(")") else value.strip()


@dataclass(frozen=True)
class ProjectSelection:
    config_path: Path
    environment: str
    request: PreparationRequest
    profile_path: Path
    receipt_path: Path
    metadata: dict
    scope: str

    @property
    def target(self):
        return {
            "subscription_id": self.request.subscription_id,
            "tenant_id": self.request.tenant_id,
            "project_resource_id": self.request.project_resource_id,
            "agent_name": self.request.agent_name,
            "environment": self.environment,
        }


def load_selection(
    config_file: Path, *, environment: str = "dev", agent_name: str | None = None,
    project_resource_id: str | None = None, profile_file: Path | None = None,
    scope: str | None = None, metadata_file: Path | None = None,
) -> ProjectSelection:
    if environment not in ENVIRONMENTS:
        raise ValueError("Environment must be dev, stage, test or prod.")
    environment = "test" if environment == "stage" else environment
    path = Path(config_file).expanduser().resolve(strict=True)
    loader = Path(__file__).resolve().parents[3] / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"
    select = runpy.run_path(str(loader))["selected_values"]
    values, _ = select(read_object(path), environment)
    resource_id = project_resource_id or _resolved(values.get("botFoundryProjectResourceId"))
    agent = agent_name or _resolved(values.get("botFoundryAgentName"))
    if not resource_id or not agent:
        raise ValueError(
            "No complete native publishing target. Configure botFoundryProjectResourceId and "
            "botFoundryAgentName, or supply -ProjectResourceId and -AgentName for this environment."
        )
    parts = resource_id.split("/")
    if len(parts) != 11 or parts[1].lower() != "subscriptions":
        raise ValueError("The publishing target must be a full Foundry project resource id.")
    subscription = parts[2]
    for key in ("dev_test_prod_sub_id", f"{environment}_sub_id"):
        expected = _resolved(values.get(key))
        if expected and expected.lower() != subscription.lower():
            raise ValueError(f"The project subscription conflicts with {key}.")
    # This opt-in is part of the explicit publishing preview, not a configuration-file mutation.
    request = PreparationRequest.from_values(values | {
        "dev_test_prod_sub_id": subscription,
        "botFoundryProjectResourceId": resource_id,
        "botFoundryAgentName": agent,
        "botEnableM365PublicEndpoint": "true",
    })
    if request.skip_reason:
        raise ValueError(f"Publishing is disabled: {request.skip_reason}")
    profile = (Path(profile_file).expanduser().resolve() if profile_file else
               path.parent / ".foundry-publish" / f"{environment}-{agent}.profile.json")
    receipt = profile.with_suffix(".receipt.json")
    initial = ProjectSelection(path, environment, request, profile, receipt, {}, "Shared")
    saved = {}
    saved_scope = "Shared"
    if profile.exists():
        document = read_object(profile)
        if document.get("schema_version") != 1 or document.get("target") != initial.target:
            raise ValueError("Saved publishing profile belongs to a different target or schema.")
        saved = _metadata(document.get("metadata"))
        saved_scope = document.get("scope")
    selected_scope = scope or saved_scope
    if selected_scope not in SCOPES:
        raise ValueError("Publishing scope must be Shared or Tenant.")
    overrides = _metadata(read_object(Path(metadata_file))) if metadata_file else {}
    return ProjectSelection(path, environment, request, profile, receipt, saved | overrides, selected_scope)


def _receipt(selection: ProjectSelection) -> dict | None:
    if not selection.receipt_path.exists():
        return None
    value = read_object(selection.receipt_path)
    if value.get("target") != selection.target:
        raise ValueError("Publishing receipt belongs to a different target.")
    if value.get("state") not in {"applying", "uncertain", "completed"}:
        raise ValueError("Publishing receipt has an unknown state; inspect it before continuing.")
    return value


def _recovery_warning(selection: ProjectSelection, needs_publish: bool) -> str:
    receipt = _receipt(selection)
    if receipt and receipt["state"] in {"applying", "uncertain"} and needs_publish:
        return "A previous publication attempt is unresolved. Inspect its receipt and live publish defaults before retrying."
    return ""


def plan_publication(selection: ProjectSelection, publisher, *, surface: str, retry_uncertain: bool = False) -> dict:
    if surface not in {"Teams", "Copilot"}:
        raise ValueError("Surface must be Teams or Copilot.")
    if not isinstance(retry_uncertain, bool):
        raise ValueError("retry_uncertain must be a boolean.")
    result = deepcopy(publisher.plan(selection.request, selection.metadata, scope=selection.scope))
    result.setdefault("warnings", [])
    result.setdefault("block_reasons", [])
    warning = _recovery_warning(selection, result.get("needs_publish", False))
    if warning:
        result["warnings"].append(warning)
        if not retry_uncertain:
            result["status"] = "blocked"
            result["block_reasons"].append(warning + " An explicit -RetryUncertain and fresh confirmation are required.")
    result.update(
        config_path=str(selection.config_path), environment=selection.environment,
        profile_path=str(selection.profile_path), receipt_path=str(selection.receipt_path),
        scope=selection.scope, surface=surface, retry_uncertain=retry_uncertain,
        access_instructions=(
            f"Publication is shared by Teams and Microsoft 365 Copilot. Open the {surface} agent store. "
            + ("Look under Your agents; channel users still require Foundry RBAC access."
               if selection.scope == "Shared" else
               "After Microsoft 365 admin approval, look under Built by your org.")
            + " Store caching can delay discovery. Publication alone does not verify a conversation."
        ),
    )
    return result


def _atomic_json(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_publication(
    selection: ProjectSelection, publisher, reviewed_plan: dict, *,
    surface: str, retry_uncertain: bool = False,
) -> dict:
    current = plan_publication(selection, publisher, surface=surface, retry_uncertain=retry_uncertain)
    if current["status"] == "blocked" or current.get("missing_fields"):
        raise ValueError("Publication is blocked: " + "; ".join(current["block_reasons"] + current.get("missing_fields", [])))
    if not isinstance(reviewed_plan, dict) or reviewed_plan.get("mode") != "plan":
        raise ValueError("Apply requires a reviewed publication plan.")
    for field in ("target", "publish_body", "active_version", "config_path", "environment",
                  "profile_path", "receipt_path", "scope", "retry_uncertain"):
        if reviewed_plan.get(field) != current.get(field):
            raise ValueError(f"The reviewed {field} changed. Preview and confirm the current publication again.")
    directory = selection.profile_path.parent
    directory.mkdir(parents=True, exist_ok=True)
    if directory == selection.config_path.parent / ".foundry-publish":
        ignore = directory / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8", newline="\n")
    lock = selection.profile_path.with_suffix(".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError(
            f"Another publishing process may be active ({lock}). Do not retry until it finishes. "
            "After a crash, inspect the receipt and confirm no publisher is running before removing this lock."
        ) from error
    os.close(lock_fd)
    receipt = {
        "schema_version": 1, "state": "applying", "target": selection.target,
        "publish_body": current["publish_body"], "scope": selection.scope,
        "active_version": current.get("active_version"),
    }
    try:
        # Another publisher may have finished uncertainly while this process was obtaining the lock.
        warning = _recovery_warning(selection, current.get("needs_publish", False))
        if warning and not retry_uncertain:
            raise ValueError("Publication is blocked: " + warning + " Re-preview with explicit -RetryUncertain before retrying.")
        _atomic_json(selection.profile_path, {
            "schema_version": 1, "target": selection.target, "scope": selection.scope,
            "metadata": {key: value for key, value in current["publish_body"].items()
                         if key in METADATA_FIELDS and key != "appVersion"},
        })
        _atomic_json(selection.receipt_path, receipt)
        try:
            result = publisher.apply(
                selection.request, selection.metadata, scope=selection.scope, reviewed_plan=reviewed_plan,
            )
        except (RuntimeError, ValueError, OSError):
            _atomic_json(selection.receipt_path, receipt | {"state": "uncertain"})
            raise
        state = "completed" if result.get("published") or result.get("status") in {
            "unchanged", "already_published", "pending_admin",
        } else "uncertain"
        _atomic_json(selection.receipt_path, receipt | {"state": state, "result": result})
        return result | {
            "surface": surface, "profile_path": str(selection.profile_path),
            "receipt_path": str(selection.receipt_path),
            "access_instructions": current["access_instructions"],
        }
    finally:
        lock.unlink()
