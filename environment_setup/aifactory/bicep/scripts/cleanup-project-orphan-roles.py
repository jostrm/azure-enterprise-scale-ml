#!/usr/bin/env python3
"""Remove proven project-owned orphan assignments, never unnamed/live principals."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit


GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
RG_NAME = re.compile(r"[\w().-]{1,90}")
Az = Callable[..., subprocess.CompletedProcess[str]]


def warning(message: str) -> None:
    print(f"WARNING: {message}")


def env_value(name: str, default: str = "") -> str:
    value = os.environ.get(f"ORPHAN_{name}", "").strip()
    if re.fullmatch(r"\$\([A-Za-z_]\w*\)", value):
        value = ""
    return value or default


@dataclass(frozen=True)
class Config:
    subscription: str
    project_number: str
    project_rg: str
    common_rg: str

    @classmethod
    def from_env(cls) -> Config:
        subscription = env_value("SUBSCRIPTION_ID")
        number = env_value("PROJECT_NUMBER")
        location = env_value("LOCATION_SUFFIX")
        environment = env_value("ENV")
        if not GUID.fullmatch(subscription) or not re.fullmatch(r"\d{3}", number):
            raise ValueError("Cleanup requires a subscription GUID and a three-digit project number.")
        if not location or environment not in ("dev", "test", "prod"):
            raise ValueError("Cleanup requires a location suffix and dev/test/prod environment.")
        prefix, suffix = env_value("RG_PREFIX"), env_value("RG_SUFFIX")
        project_rg = (
            f"{prefix}{env_value('PROJECT_PREFIX')}project{number}-{location}-"
            f"{environment}{suffix}{env_value('PROJECT_SUFFIX')}"
        )
        # Match the RBAC Bicep commonResourceGroup expression. The BYO VNet RG
        # resolved by 00_resolve_network_env_placeholders is a separate scope.
        common_rg = env_value(
            "COMMON_RG", f"{prefix}{env_value('COMMON_NAME', 'esml-common')}-{location}-{environment}{suffix}"
        )
        for name in (project_rg, common_rg):
            if not RG_NAME.fullmatch(name) or name.endswith("."):
                raise ValueError(f"Invalid cleanup resource group: {name!r}")
        return cls(subscription, number, project_rg, common_rg)

    def scope(self, rg: str) -> str:
        return f"/subscriptions/{self.subscription}/resourceGroups/{rg}"

    def owns_identity_name(self, name: object) -> bool:
        return isinstance(name, str) and name.lower().startswith((
            f"mi-prj{self.project_number}-", f"mi-aca-prj{self.project_number}-",
        ))

    def owns_service_principal_name(self, name: object) -> bool:
        return isinstance(name, str) and re.search(
            rf"(?:^|[-_ ])(?:prj|project){self.project_number}(?:$|[-_ ])", name, re.I,
        ) is not None

    def owns_identity_resource(self, resource_id: object) -> bool:
        if not isinstance(resource_id, str):
            return False
        prefix = f"{self.scope(self.project_rg)}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        if not resource_id.lower().startswith(prefix.lower()):
            return False
        name = resource_id[len(prefix):]
        return "/" not in name and self.owns_identity_name(name)


def json_result(result: subprocess.CompletedProcess[str], purpose: str) -> object:
    if result.returncode:
        warning(f"{purpose} failed; preserving affected assignments. {result.stderr.strip()}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        warning(f"{purpose} returned invalid JSON; preserving affected assignments.")
        return None


def error_code(result: subprocess.CompletedProcess[str]) -> str | None:
    if not result.returncode:
        return None
    # az rest wraps the Graph error JSON in CLI text (for example, ERROR: Not Found(...)).
    text = result.stderr + "\n" + result.stdout
    start = text.find("{")
    if start < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def graph_not_found(result: subprocess.CompletedProcess[str]) -> bool:
    return error_code(result) in (
        "Request_ResourceNotFound", "Directory_ObjectNotFound",
    )


def recorded_project_identities(config: Config, az: Az) -> dict[str, str | None]:
    # Both mi.bicep and get-managed-identity-info.bicep record identity IDs with names.
    # Historical outputs survive identity deletion/recreation, unlike a live identity list.
    result = az(
        "deployment", "group", "list", "--subscription", config.subscription,
        "--resource-group", config.project_rg,
        "--query", "[].{deploymentName:name,"
        "principalId:not_null(properties.outputs.principalId.value,properties.outputs.managedIdentityPrincipalId.value),"
        "resourceId:not_null(properties.outputs.resourceId.value,properties.outputs.managedIdentityId.value),"
        "name:not_null(properties.outputs.name.value,properties.outputs.managedIdentityName.value),"
        "spAndMiArray:properties.outputs.spAndMiArray.value}",
        "--output", "json", "--only-show-errors",
    )
    records = json_result(result, "Reading current-project identity deployment history")
    if not isinstance(records, list):
        warning("No usable project identity history; unproven managed-identity assignments will be preserved.")
        return {}
    principals: dict[str, str | None] = {}
    sp_deployments = {f"{prefix}-spAndMI2Array-{config.project_rg}"[:64].lower() for prefix in ("08", "08b")}
    for record in records:
        if not isinstance(record, dict):
            continue
        principal = record.get("principalId")
        if (
            isinstance(principal, str) and GUID.fullmatch(principal)
            and config.owns_identity_resource(record.get("resourceId"))
            and config.owns_identity_name(record.get("name"))
            and record["resourceId"].rsplit("/", 1)[-1].lower() == record["name"].lower()
        ):
            principals[principal.lower()] = record["resourceId"]
        # These exact project-scoped modules record the optional SP alongside the project MI.
        # An absent SP produces an MI-only array; never read a secret or infer an ID from null.
        sp_and_mi = record.get("spAndMiArray")
        if (
            str(record.get("deploymentName", "")).lower() in sp_deployments
            and isinstance(sp_and_mi, list) and 0 < len(sp_and_mi) <= 2
            and all(isinstance(value, str) and GUID.fullmatch(value) for value in sp_and_mi)
        ):
            for value in sp_and_mi:
                principals.setdefault(value.lower(), None)
    return principals


def valid_assignment(config: Config, assignment: object) -> bool:
    if not isinstance(assignment, dict):
        return False
    scope, assignment_id, principal = (assignment.get(key) for key in ("scope", "id", "principalId"))
    if not all(isinstance(value, str) for value in (scope, assignment_id, principal)):
        return False
    if not GUID.fullmatch(principal):
        return False
    if any(char in scope for char in ("?", "#", "\\", "%")) or any(
        part in (".", "..") for part in scope.split("/")
    ):
        return False
    # Validate both the reported scope AND the full deletion ID; exclude inherited/sibling scopes.
    roots = (config.scope(config.project_rg).lower(), config.scope(config.common_rg).lower())
    if not any(scope.lower() == root or scope.lower().startswith(root + "/") for root in roots):
        return False
    expected = scope.rstrip("/") + "/providers/Microsoft.Authorization/roleAssignments/"
    return (
        assignment_id.lower().startswith(expected.lower())
        and GUID.fullmatch(assignment_id[len(expected):]) is not None
    )


def project_rg_group(config: Config, assignments: Iterable[dict]) -> set[str]:
    # One group may hold several roles. Identify it by principal ID at the exact RG
    # scope, never by display name, inherited access, or assignments on child resources.
    project_scope = config.scope(config.project_rg).lower()
    groups = {
        assignment["principalId"].lower()
        for assignment in assignments
        if assignment["scope"].lower() == project_scope
        and str(assignment.get("principalType", "")).lower() == "group"
    }
    if len(groups) != 1:
        warning(
            f"Expected one distinct Entra group directly on project RG {config.project_rg}; "
            f"found {len(groups)}. Group assignments will be preserved."
        )
        return set()
    print(f"Project RG Entra group principal ID: {next(iter(groups))}")
    return groups


def same_assignment(left: dict, right: dict) -> bool:
    return all(
        str(left.get(key, "")).lower() == str(right.get(key, "")).lower()
        for key in ("id", "scope", "principalId", "principalType", "roleDefinitionId", "delegatedManagedIdentityResourceId")
    ) and all(left.get(key) == right.get(key) for key in ("condition", "conditionVersion"))


def assignment_unchanged(config: Config, assignment: dict, az: Az) -> bool:
    result = az(
        "rest", "--subscription", config.subscription, "--method", "get",
        "--url", f"https://management.azure.com{assignment['id']}?api-version=2022-04-01",
        "--only-show-errors",
    )
    raw = json_result(result, f"Re-reading assignment {assignment['id']}")
    properties = raw.get("properties") if isinstance(raw, dict) else None
    current = {**properties, "id": raw.get("id")} if isinstance(properties, dict) else None
    return valid_assignment(config, current) and same_assignment(current, assignment)


def identity_is_orphan(config: Config, resource_id: str, principal: str, az: Az) -> bool:
    result = az(
        "rest", "--subscription", config.subscription, "--method", "get",
        "--url", f"https://management.azure.com{resource_id}?api-version=2024-11-30",
        "--only-show-errors",
    )
    if result.returncode:
        return error_code(result) in ("ResourceNotFound", "ResourceGroupNotFound")
    resource = json_result(result, f"Checking managed identity {resource_id}")
    properties = resource.get("properties") if isinstance(resource, dict) else None
    current_principal = properties.get("principalId") if isinstance(properties, dict) else None
    return (
        str(resource.get("id", "")).lower() == resource_id.lower()
        and isinstance(current_principal, str) and GUID.fullmatch(current_principal) is not None
        and current_principal.lower() != principal.lower()
    ) if isinstance(resource, dict) else False


def cleanup(config: Config, az: Az) -> int:
    print(f"Orphan cleanup for project {config.project_number}: {config.project_rg}, {config.common_rg}")
    assignments: dict[str, dict] = {}
    project_exists = False
    for rg in dict.fromkeys((config.project_rg, config.common_rg)):
        result = az(
            "group", "exists", "--subscription", config.subscription, "--name", rg,
            "--output", "json", "--only-show-errors",
        )
        exists = json_result(result, f"Checking resource group {rg}")
        if exists is False:
            print(f"Resource group {rg} does not exist; skipping this group.")
            continue
        if exists is not True:
            warning("Resource group existence is inconclusive; no assignments will be deleted.")
            return 0
        project_exists |= rg == config.project_rg
        # ARM returns raw principal IDs without Graph display-name enrichment and includes
        # resource-level assignments. Follow every page before any deletion is attempted.
        path = f"{config.scope(rg)}/providers/Microsoft.Authorization/roleAssignments"
        url = f"https://management.azure.com{path}?api-version=2022-04-01"
        seen_pages: set[str] = set()
        while url:
            parsed = urlsplit(url)
            if (
                url in seen_pages or parsed.scheme != "https"
                or parsed.netloc != "management.azure.com" or parsed.path.lower() != path.lower()
            ):
                warning("Invalid assignment continuation URL; no assignments will be deleted.")
                return 0
            seen_pages.add(url)
            result = az(
                "rest", "--subscription", config.subscription,
                "--method", "get", "--url", url, "--only-show-errors",
            )
            payload = json_result(result, f"Listing assignments in {rg}")
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                warning("Assignment enumeration is incomplete; no assignments will be deleted.")
                return 0
            for raw in payload["value"]:
                properties = raw.get("properties") if isinstance(raw, dict) else None
                record = {**properties, "id": raw.get("id")} if isinstance(properties, dict) else None
                if valid_assignment(config, record):
                    key = record["id"].lower()
                    if key in assignments and not same_assignment(assignments[key], record):
                        warning("Assignment changed during enumeration; no assignments will be deleted.")
                        return 0
                    assignments[key] = record
                else:
                    warning("Ignoring malformed assignment or assignment outside project/common scopes.")
            url = payload.get("nextLink", "")
            if not isinstance(url, str):
                warning("Malformed assignment continuation; no assignments will be deleted.")
                return 0

    project_groups = project_rg_group(config, assignments.values())
    recorded_principals: dict[str, str | None] = {}
    if project_exists and assignments:
        recorded_principals = recorded_project_identities(config, az)
    project_scope = config.scope(config.project_rg).lower()
    project_assignees = {
        assignment["principalId"].lower() for assignment in assignments.values()
        if assignment["scope"].lower() == project_scope
        or assignment["scope"].lower().startswith(project_scope + "/")
    }
    live_principals: set[str] = set()

    deleted = 0
    for assignment in assignments.values():
        principal = assignment["principalId"]
        if principal.lower() in live_principals:
            print(f"Preserving principal {principal}: already observed live during this run.")
            continue
        result = az(
            "rest", "--subscription", config.subscription, "--method", "get",
            "--url", f"https://graph.microsoft.com/v1.0/directoryObjects/{principal}",
            "--only-show-errors",
        )
        if not result.returncode:
            live_principals.add(principal.lower())
            print(f"Preserving live principal {principal}.")
            continue
        if not graph_not_found(result):
            warning(f"Deletion not proven for {principal}; preserving assignment (Graph lookup failed).")
            continue

        owned = principal.lower() in project_groups or principal.lower() in recorded_principals
        identity_resource = recorded_principals.get(principal.lower())
        if not owned:
            # Deleted directory metadata must match the exact principal; names never prove orphan status.
            result = az(
                "rest", "--subscription", config.subscription, "--method", "get",
                "--url", f"https://graph.microsoft.com/v1.0/directory/deletedItems/{principal}",
                "--only-show-errors",
            )
            record = json_result(result, f"Reading deleted-principal ownership for {principal}")
            if isinstance(record, dict):
                alternatives = record.get("alternativeNames")
                is_deleted_sp = (
                    str(record.get("id", "")).lower() == principal.lower()
                    and record.get("@odata.type") == "#microsoft.graph.servicePrincipal"
                )
                if is_deleted_sp and config.owns_identity_name(record.get("displayName")) and isinstance(alternatives, list):
                    identity_resource = next(
                        (value for value in alternatives if config.owns_identity_resource(value)), None,
                    )
                    owned = identity_resource is not None
                elif is_deleted_sp and record.get("servicePrincipalType") == "Application":
                    owned = (
                        principal.lower() in project_assignees
                        and config.owns_service_principal_name(record.get("displayName"))
                    )
        if not owned:
            warning(f"Cannot prove {principal} belongs to project {config.project_number}; preserving assignment.")
            continue

        if identity_resource and not identity_is_orphan(config, identity_resource, principal, az):
            warning(f"Managed identity {principal} is live or ARM lookup is inconclusive; preserving assignment.")
            continue
        if not assignment_unchanged(config, assignment, az):
            warning(f"Assignment changed or could not be re-read: {assignment['id']}; preserving it.")
            continue
        # Independent, typed lookup immediately before deletion protects shared live groups.
        collection = "groups" if principal.lower() in project_groups else "servicePrincipals"
        result = az(
            "rest", "--subscription", config.subscription, "--method", "get",
            "--url", f"https://graph.microsoft.com/v1.0/{collection}/{principal}",
            "--only-show-errors",
        )
        if not graph_not_found(result):
            if not result.returncode:
                live_principals.add(principal.lower())
            warning(f"Final orphan check did not confirm deletion of {principal}; preserving assignment.")
            continue
        print(f"Deleting confirmed project-{config.project_number} orphan: {assignment['id']}")
        result = az(
            "role", "assignment", "delete", "--subscription", config.subscription,
            "--ids", assignment["id"], "--only-show-errors",
        )
        if result.returncode:
            warning(f"Failed to delete assignment {assignment['id']}: {result.stderr.strip()}")
        else:
            deleted += 1
    print(f"Project-{config.project_number} orphan cleanup completed; deleted {deleted} assignment(s).")
    return deleted


def main() -> None:
    try:
        config = Config.from_env()
    except ValueError as error:
        raise SystemExit(f"Invalid orphan cleanup configuration; no assignments deleted: {error}") from error
    executable = shutil.which("az")
    if not executable:
        raise SystemExit("Azure CLI is required for project orphan cleanup.")
    command = [executable]
    if os.name == "nt" and Path(executable).suffix.lower() in (".cmd", ".bat"):
        # Bypass cmd.exe so continuation URLs containing '&' remain one literal argument.
        cli_python = Path(executable).parent.parent / "python.exe"
        if not cli_python.is_file():
            raise SystemExit("Cannot locate the Windows Azure CLI Python runtime; no assignments deleted.")
        command = [str(cli_python), "-IBm", "azure.cli"]

    def az(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*command, *args], capture_output=True, text=True, check=False)

    cleanup(config, az)


if __name__ == "__main__":
    main()
