"""Fresh, read-only ARM resource-group evidence for an exact saved scale set."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import subprocess
from datetime import datetime, timezone
from http.client import HTTPException as HTTPTransportError
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src import operations, wizard
from src.factory_scope import current_factory_scope


ARM_ORIGIN = "https://management.azure.com"
MAX_GROUPS = 12
MAX_JSON_BYTES = 1024 * 1024
_GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)


class VerificationRequestError(ValueError):
    """A sanitized local selection error, not an Azure verification result."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _absolute_path(value: str) -> Path:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise VerificationRequestError("Provide an absolute ordinary folder and snapshot path.")
    path = Path(value)
    if (not path.is_absolute() or ".." in value.replace("\\", "/").split("/")
            or value.startswith(("\\\\?\\", "\\\\.\\"))
            or any(":" in part or part != part.rstrip(" .") for part in path.parts[1:])):
        raise VerificationRequestError("Paths must be absolute without traversal or special components.")
    return path


def _ordinary_path(path: Path, *, directory: bool = False) -> None:
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise VerificationRequestError("Symbolic links and reparse points are not allowed.")
        if not (stat.S_ISDIR(info.st_mode) if component != path or directory
                else stat.S_ISREG(info.st_mode)):
            raise VerificationRequestError("The factory must be a directory and snapshot an ordinary file.")


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _saved_selection(folder: str, scale_set_id: str, path: str) -> tuple[Path, dict]:
    if (not isinstance(scale_set_id, str) or len(scale_set_id) > 255
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", scale_set_id)
            or ".." in scale_set_id or scale_set_id.endswith(".")):
        raise VerificationRequestError("scale_set_id must be an exact safe scale-set listing ID.")
    root, snapshot = _absolute_path(folder), _absolute_path(path)
    try:
        _ordinary_path(root, directory=True)
        _ordinary_path(snapshot)
        listed = wizard._list_scalesets(str(root), create_legacy_dir=False).get(scale_set_id)
        if listed is None:
            raise VerificationRequestError("Saved scale set no longer exists; refresh the list.", 404)
        if not _same_path(snapshot, Path(listed)):
            raise VerificationRequestError("Snapshot path does not match the selected scale set.", 409)
        with snapshot.open("rb") as source:
            raw = source.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise VerificationRequestError("Saved scale-set snapshot is too large.")
        saved = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(saved, dict):
            raise VerificationRequestError("Saved scale-set snapshot must contain a JSON object.")
        suffix = saved.get("admin_aifactorySuffixRG")
        if (not isinstance(suffix, str) or not suffix.strip()
                or wizard._scaleset_id_from_suffix(suffix) != scale_set_id):
            raise VerificationRequestError("Snapshot identity does not match the selected scale set.", 409)
        owner = saved.get("_save_folder")
        if owner:
            if not _same_path(_absolute_path(owner), root):
                raise VerificationRequestError("Snapshot belongs to a different factory folder.", 409)
        return root, saved
    except (FileNotFoundError, NotADirectoryError):
        raise VerificationRequestError("Factory folder or saved scale-set snapshot was not found.", 404) from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise VerificationRequestError("Saved scale-set snapshot is unreadable or malformed.") from None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) and "<todo>" not in value.casefold() else ""


def _identity(value) -> str:
    return _text(value).strip("-_").casefold()


def _guid(value) -> str:
    return value.lower() if isinstance(value, str) and _GUID.fullmatch(value) else ""


def _selected_scope(saved: dict, scope: dict) -> dict | None:
    if any(saved.get(key) is not None and not isinstance(saved[key], str) for key in (
        "admin_aifactoryPrefixRG", "admin_aifactorySuffixRG", "admin_location",
        "dev_sub_id", "test_sub_id", "prod_sub_id",
    )):
        return None
    prefix = _identity(saved.get("admin_aifactoryPrefixRG"))
    suffix = _identity(saved.get("admin_aifactorySuffixRG"))
    region = _text(saved.get("admin_location")).casefold()
    raw_subs = [_text(saved.get(key)) for key in ("dev_sub_id", "test_sub_id", "prod_sub_id")]
    subscriptions = {_guid(value) for value in raw_subs if value}
    active_subs = {_guid(value) for value in scope["subscription_ids"]}
    if (not prefix or not suffix or not re.fullmatch(r"[a-z0-9]+", region)
            or region not in scope["monitoring_regions"]
            or not subscriptions or "" in subscriptions or "" in active_subs
            or not subscriptions.issubset(active_subs)):
        return None
    for env, raw in zip(("dev", "stage", "prod"), raw_subs):
        if raw and _guid(raw) != _guid(scope["subscriptions"].get(env)):
            return None
    targets = [
        target for target in scope["monitoring_targets"]
        if _identity(target["prefix"]) == prefix and _identity(target["suffix"]) == suffix
        and _guid(target["subscription_id"]) in subscriptions
        and re.fullmatch(r"[a-z0-9]+", target["region"])
        and re.fullmatch(r"[a-z0-9]+", target["location_suffix"])
    ]
    if not any(target["region"] == region for target in targets):
        return None
    return {"monitoring_targets": targets, "subscription_ids": subscriptions,
            "prefix_rg": prefix, "suffix_rg": suffix}


def _group_name(value) -> str:
    if (isinstance(value, str) and re.fullmatch(r"[\w().-]{1,90}", value)
            and not value.endswith(".")):
        return value
    return ""


def _resource_id(value) -> tuple[str, str, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    if (len(parts) != 5 or parts[0] or parts[1].casefold() != "subscriptions"
            or parts[3].casefold() != "resourcegroups"):
        return None
    subscription, name = _guid(parts[2]), _group_name(parts[4])
    if not subscription or not name:
        return None
    return f"/subscriptions/{subscription}/resourceGroups/{name}", subscription, name


def _candidates(groups: list, selected: dict) -> list[tuple[str, str]] | None:
    candidates = {}
    for group in groups:
        if not isinstance(group, dict):
            return None
        name = _group_name(group.get("name"))
        if not name:
            return None
        if (operations.LocalFactoryDiscovery._PROJECT_RE.search(name)
                or not re.search(r"(^|[-_])(common|shared|hub)([-_]|$)", name, re.I)):
            continue
        raw_id = group.get("id")
        metadata_subs = [group[key] for key in ("subscriptionId", "subscription_id")
                         if group.get(key)]
        if raw_id:
            parsed = _resource_id(raw_id)
        else:
            parsed = _resource_id(
                f"/subscriptions/{metadata_subs[0]}/resourceGroups/{name}"
            ) if metadata_subs else None
        if parsed is None:
            return None
        resource_id, subscription, id_name = parsed
        if (id_name.casefold() != name.casefold()
                or any(_guid(sub) != subscription for sub in metadata_subs)):
            return None
        if subscription not in selected["subscription_ids"]:
            continue
        targets = [target for target in selected["monitoring_targets"]
                   if _guid(target["subscription_id"]) == subscription
                   and target["region"] == _text(group.get("location")).casefold()]
        if not targets or not operations.AzureInventoryProvider._is_relevant_group(
            name, {"monitoring_targets": targets}, subscription
        ):
            continue
        candidates.setdefault(resource_id.casefold(), (resource_id, subscription))
    return list(candidates.values())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _access_token(subscription: str, expected_tenant: str, runner) -> tuple[str | None, str]:
    try:
        prefix = operations._azure_cli_command(operations.resolve_azure_cli())
    except (RuntimeError, OSError):
        return None, "Azure CLI is unavailable; resource access was not checked."
    env = os.environ.copy()
    env.update({
        "AZURE_CORE_LOGIN_EXPERIENCE_V2": "off",
        "AZURE_CORE_ENABLE_BROKER_ON_WINDOWS": "false",
        "AZURE_CORE_LOG_LEVEL": "critical",
        "AZURE_LOGGING_ENABLE_LOG_FILE": "false",
    })
    try:
        result = runner(
            [*prefix, "account", "get-access-token", "--subscription", subscription,
             "--resource", ARM_ORIGIN + "/", "--output", "json", "--only-show-errors"],
            shell=False, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, env=env,
        )
        if result.returncode:
            return None, "Azure access token unavailable. Check Azure sign-in and access to this subscription."
        document = json.loads(result.stdout)
        if (not isinstance(document, dict) or _guid(document.get("subscription")) != subscription
                or (expected_tenant and _guid(document.get("tenant")) != expected_tenant)):
            return None, "Azure token account does not match the selected subscription and tenant."
        token = document.get("accessToken")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/-]{1,32768}=*", token):
            return None, "Azure CLI did not return a usable access token."
        return token, ""
    except subprocess.TimeoutExpired:
        return None, "Azure token request timed out; resource access was not checked."
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None, "Azure access token unavailable; resource access was not checked."


def _status_message(status: int) -> str:
    return {
        401: "Azure rejected authentication (HTTP 401); check Azure sign-in.",
        403: "Azure denied access to this resource group (HTTP 403).",
        404: "Azure resource group was not found (HTTP 404).",
    }.get(status, f"Azure returned HTTP {status}; only HTTP 200 verifies resource access.")


def _check(resource_id: str, token: str, opener) -> dict:
    _, subscription, name = _resource_id(resource_id)
    url = f"{ARM_ORIGIN}/subscriptions/{subscription}/resourceGroups/{quote(name, safe='()-._')}?api-version=2021-04-01"
    result = {"resource_id": resource_id, "http_status": None, "verified": False, "message": ""}
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    request.add_unredirected_header("Authorization", "Bearer " + token)
    try:
        with opener.open(request, timeout=20) as response:
            status = response.getcode()
            result["http_status"] = status
            if status != 200:
                result["message"] = _status_message(status)
                return result
            content_type = response.headers.get_content_type()
            if (response.geturl() != url or
                    not (content_type == "application/json" or content_type.endswith("+json"))):
                result["message"] = "HTTP 200 did not contain an ARM JSON resource response."
                return result
            body = response.read(MAX_JSON_BYTES + 1)
            if len(body) > MAX_JSON_BYTES:
                result["message"] = "HTTP 200 resource response exceeded the safety limit."
                return result
            document = json.loads(body)
            returned = _resource_id(document.get("id")) if isinstance(document, dict) else None
            if returned is None or returned[0].casefold() != resource_id.casefold():
                result["message"] = "HTTP 200 resource ID did not match the requested resource group."
                return result
            result.update(verified=True, message="Authenticated ARM HTTP 200; resource group ID matched.")
    except HTTPError as error:
        result.update(http_status=error.code, message=_status_message(error.code))
        error.close()
    except (TimeoutError, URLError, OSError, HTTPTransportError):
        result["http_status"] = None
        result["message"] = "Azure resource request timed out or could not connect; access was not verified."
    except (ValueError, TypeError):
        result["message"] = "Azure response was malformed; access was not verified."
    return result


def _inventory_matches(factory: dict, root: Path, scope: dict, selected: dict) -> bool:
    return (
        current_factory_scope(root) == scope
        and _same_path(Path(factory["folder"]), root)
        and set(factory["monitoring_regions"]) == set(scope["monitoring_regions"])
        and {_guid(sub) for sub in factory["subscription_ids"]} ==
            {_guid(sub) for sub in scope["subscription_ids"]}
        and _identity(factory["prefix_rg"]) == selected["prefix_rg"]
        and _identity(factory["suffix_rg"]) == selected["suffix_rg"]
    )


def _verify_candidates(candidates: list[tuple[str, str]], tenants: dict, *,
                       runner=None, opener=None) -> list[dict]:
    runner = runner or subprocess.run
    opener = opener or build_opener(_NoRedirect())
    tokens = {}
    checks = []
    for resource_id, subscription in candidates:
        if subscription not in tokens:
            tokens[subscription] = _access_token(subscription, tenants.get(subscription, ""), runner)
        token, message = tokens[subscription]
        checks.append(_check(resource_id, token, opener) if token else {
            "resource_id": resource_id, "http_status": None, "verified": False, "message": message,
        })
    return checks


def verify_resource_groups(
    aifactory_folder: str, scale_set_id: str, path: str, *,
    service=None, runner=None, opener=None,
) -> dict:
    """Verify observed common RGs, never a Portal URL or cached access status."""
    root, saved = _saved_selection(aifactory_folder, scale_set_id, path)

    def result(message: str, checks=None) -> dict:
        return {"scale_set_id": scale_set_id,
                "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "message": message, "checks": checks or []}

    try:
        scope = current_factory_scope(root)
        selected = _selected_scope(saved, scope)
    except (OSError, ValueError, TypeError, KeyError):
        return result("Current factory scope is unreadable or invalid; no resource groups were checked.")
    if selected is None:
        return result("Saved scale set is outside or missing the active factory scope; no resource groups were checked.")
    try:
        overview = (service or operations.OperationsService()).overview(
            str(root), include_azure=True, force_refresh=False,
        )
        factory = overview["factory"]
        if not _inventory_matches(factory, root, scope, selected):
            return result("Inventory does not match the current factory scope; refresh before verifying.")
        if _saved_selection(str(root), scale_set_id, path)[1] != saved:
            return result("Saved scale set changed while loading inventory; refresh before verifying.")
        candidates = _candidates(overview["common_resource_groups"], selected)
    except (operations.AzureCollectionError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        # Inventory errors can contain CLI output. Return no exception or warning text.
        return result("Scoped Azure inventory is unavailable; no resource groups were checked.")
    if candidates is None:
        return result("Observed resource-group identity is missing or inconsistent; no resource groups were checked.")
    if not candidates:
        return result("No observed common resource groups match this saved scale set.")
    if len(candidates) > MAX_GROUPS:
        return result(f"More than {MAX_GROUPS} common resource groups matched; verification was not attempted.")
    tenants = {_guid(sub): _guid(tenant) for sub, tenant in scope["subscription_tenants"].items()}
    if any(not _guid(tenant) for tenant in scope["tenant_ids"]):
        return result("Current factory tenant identity is invalid; no resource groups were checked.")
    checks = _verify_candidates(candidates, tenants, runner=runner, opener=opener)
    try:
        unchanged = current_factory_scope(root) == scope and _saved_selection(str(root), scale_set_id, path)[1] == saved
    except (OSError, ValueError, TypeError, KeyError):
        unchanged = False
    if not unchanged:
        for check in checks:
            check.update(verified=False, message="Configuration changed during verification; refresh the saved scale-set list.")
        return result("Configuration changed during verification. No current-scale-set access is inferred.", checks)
    verified = sum(check["verified"] for check in checks)
    return result(f"{verified} of {len(checks)} common resource groups verified with authenticated ARM HTTP 200.", checks)
