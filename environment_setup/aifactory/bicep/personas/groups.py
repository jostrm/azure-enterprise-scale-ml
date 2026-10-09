"""Explicit Entra-admin bootstrap; normal pipelines only call resolve_seeded_groups.

Preview is the default. ``discover --execute`` publishes existing groups, never
creates them; ``create --execute`` also creates missing groups. Neither operation
changes membership, renames groups, assigns Entra roles, or deletes anything.
Use a serialized authorized-admin run: Graph display names are not unique and Key
Vault secret set has no compare-and-swap. Read/recheck guards detect conflicts but
cannot make concurrent independent directory administrators atomic.

Names: aif--{factory}--{environment}--persona200/201 (shared across scalesets), and
aif--{factory}--{scaleset}--{environment}--{project}--persona210..216.
Double-hyphen boundaries are unambiguous: validated slugs cannot contain "--".
Secret names are group-{display_name}; values are bound JSON, not bare GUIDs.
An explicit manifest.groups GUID adopts only a group with the canonical name.
Historical names must first be reviewed and renamed by an Entra administrator;
this tool intentionally cannot silently alias a historical name into a new scope.

Admin prerequisites: Graph Group.Read.All for discovery; Group.ReadWrite.All
and appropriate delegated directory rights for creation; seeding-vault secret
get (including deleted-secret checks) and set for publication. Authenticate with
``az login --tenant <manifest tenant_id>`` first. Runtime needs only secret get.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlencode, urlsplit
from uuid import UUID


MANIFEST_SCHEMA = "aifactory.persona-access/v1"
RECORD_SCHEMA = "aifactory.persona-group/v1"
COMMON_PERSONAS = ("persona200", "persona201")
PROJECT_PERSONAS = tuple(f"persona{number}" for number in range(210, 217))
GRAPH_GROUPS = "https://graph.microsoft.com/v1.0/groups"
GRAPH_SELECT = "id,displayName,securityEnabled,mailEnabled,groupTypes,isAssignableToRole,deletedDateTime"
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_PLACEHOLDERS = {"todo", "tbd", "changeme", "placeholder", "replace-me", "your-factory",
                 "your-scaleset", "your-vault", "your-resource-group", "undefined", "null"}
_KNOWN_CODES = (
    "SecretNotFound", "SecretDisabled", "SecretBeingDeleted", "ObjectIsDeletedButRecoverable",
    "Request_ResourceNotFound", "ResourceNotFound", "VaultNotFound", "Forbidden",
    "Unauthorized", "AuthorizationFailed", "Authorization_RequestDenied",
    "InsufficientPrivileges", "AccessDenied", "ErrorAccessDenied",
)


class GroupsError(ValueError):
    """A safe operator-facing error; never embeds CLI output or secret values."""


class AzureCLIError(GroupsError):
    def __init__(self, code):
        self.code = code
        super().__init__("Azure CLI request failed")


_CLI_ERRORS = (GroupsError, RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError)


def _error_code(error):
    for attribute in ("error_code", "code"):
        code = getattr(error, attribute, None)
        if code in _KNOWN_CODES:
            return code
    # Inspect the actual error code, never a phrase/code quoted inside its
    # message; inaccessible vaults/subscriptions are not missing secrets.
    text = str(error)
    try:
        document = json.loads(text)
        details = document.get("error", document) if isinstance(document, dict) else {}
        code = details.get("code") if isinstance(details, dict) else None
        if code in _KNOWN_CODES:
            return code
    except (TypeError, ValueError):
        pass
    match = re.search(r"(?:^|\s)ERROR:\s*\(([A-Za-z_]+)\)", text)
    if match is None:
        match = re.match(r"^\s*\(([A-Za-z_]+)\)", text)
    if match and match[1] in _KNOWN_CODES:
        return match[1]
    return "Unknown"


def cli(*args):
    executable = shutil.which("az")
    if not executable:
        raise GroupsError("Install Azure CLI and authenticate with the manifest tenant.")
    command = [executable]
    if Path(executable).suffix.lower() in (".cmd", ".bat"):
        runtime = Path(executable).parent.parent / "python.exe"
        if not runtime.is_file():
            raise GroupsError("Azure CLI Python runtime is missing; repair Azure CLI.")
        command = [str(runtime), "-X", "utf8", "-IBm", "azure.cli"]
    try:
        result = subprocess.run(
            [*command, *args, "--output", "json", "--only-show-errors"],
            text=True, encoding="utf-8", capture_output=True, timeout=180,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise GroupsError("Azure CLI transport failed; check installation, login and connectivity.") from None
    if result.returncode:
        raise AzureCLIError(_error_code(RuntimeError(result.stderr))) from None
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except (TypeError, ValueError):
        raise GroupsError("Azure CLI returned invalid JSON.") from None


def _guid(value, field):
    if (not isinstance(value, str) or not _GUID.fullmatch(value)
            or UUID(value).int in (0, (1 << 128) - 1)):
        raise GroupsError(f"{field} must be a nonzero GUID, not a placeholder.")
    return str(UUID(value))


def _slug(value, field):
    if (not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?", value)
            or "--" in value or value in _PLACEHOLDERS):
        raise GroupsError(f"{field} must be a concrete lowercase slug of 1-24 characters.")
    return value


def validate_identity_manifest(manifest):
    """Validate only identity/seeding fields; independent of provisioning policy."""
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise GroupsError(f"Manifest schema must be {MANIFEST_SCHEMA}.")
    result = deepcopy(manifest)
    result["tenant_id"] = _guid(result.get("tenant_id"), "tenant_id")
    for field in ("factory", "scaleset"):
        result[field] = _slug(result.get(field), field)
    if result.get("environment") not in ("dev", "test", "prod"):
        raise GroupsError("environment must be dev, test or prod.")
    if not isinstance(result.get("project"), str) or not re.fullmatch(r"project[0-9]{3}", result["project"]):
        raise GroupsError("project must be projectNNN (three digits).")
    seed = result.get("seeding")
    if not isinstance(seed, dict):
        raise GroupsError("seeding must specify subscription_id, resource_group and vault_name.")
    seed["subscription_id"] = _guid(seed.get("subscription_id"), "seeding.subscription_id")
    for field, pattern in (
        ("resource_group", r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}"),
        ("vault_name", r"[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]"),
    ):
        value = seed.get(field)
        if (not isinstance(value, str) or not re.fullmatch(pattern, value)
                or value.lower() in _PLACEHOLDERS or value.endswith(".")
                or (field == "vault_name" and "--" in value)):
            raise GroupsError(f"Invalid concrete seeding.{field}.")
    groups = result.get("groups", {})
    if not isinstance(groups, dict) or set(groups) - set(COMMON_PERSONAS + PROJECT_PERSONAS):
        raise GroupsError("groups must map known persona IDs to explicitly reviewed GUIDs.")
    result["groups"] = {persona: _guid(value, f"groups.{persona}") for persona, value in groups.items()}
    if len(set(result["groups"].values())) != len(result["groups"]):
        raise GroupsError("Each persona must have a unique group object ID.")
    return result


def group_specs(manifest, scope="project"):
    """Return persona -> {name, seed_key, binding}; project includes shared core."""
    manifest = validate_identity_manifest(manifest)
    if scope not in ("common", "project"):
        raise GroupsError("scope must be common or project.")
    specs = {}
    personas = COMMON_PERSONAS + (PROJECT_PERSONAS if scope == "project" else ())
    for persona in personas:
        binding = {field: manifest[field] for field in ("tenant_id", "factory", "environment")}
        parts = [manifest["factory"]]
        if persona in PROJECT_PERSONAS:
            binding.update({field: manifest[field] for field in ("scaleset", "project")})
            parts.append(manifest["scaleset"])
        parts.append(manifest["environment"])
        if persona in PROJECT_PERSONAS:
            parts.append(manifest["project"])
        name = "--".join(["aif", *parts, persona])
        seed_key = f"group-{name}"
        if len(name) > 120 or len(seed_key) > 127:
            raise GroupsError("Derived group or secret name exceeds its supported length.")
        specs[persona] = {"name": name, "seed_key": seed_key, "binding": binding}
    return specs


def _record(spec, persona, object_id):
    return {"schema": RECORD_SCHEMA, **spec["binding"], "persona": persona,
            "object_id": _guid(object_id, "group object_id"), "display_name": spec["name"]}


def _validate_record(value, spec, persona):
    if not isinstance(value, dict):
        raise GroupsError(f"Invalid seeding record for {persona}; expected a bound JSON envelope.")
    object_id = _guid(value.get("object_id"), f"{persona} object_id")
    if value != _record(spec, persona, object_id):
        raise GroupsError(f"Seeding record schema/name/binding mismatch for {persona}; refusing to reuse or replace it.")
    return object_id


def _seed_args(manifest, spec):
    return ("--vault-name", manifest["seeding"]["vault_name"], "--name", spec["seed_key"],
            "--subscription", manifest["seeding"]["subscription_id"])


def _read_seed(manifest, spec, persona, run, *, allow_missing=False):
    try:
        secret = run("keyvault", "secret", "show", *_seed_args(manifest, spec))
    except _CLI_ERRORS as error:
        if _error_code(error) == "SecretNotFound":
            if allow_missing:
                return None
            raise GroupsError(f"Missing seeding record for {persona}; ask the Entra administrator to run discover/create --execute.") from None
        raise GroupsError(f"Cannot read seeding record for {persona}; verify tenant/subscription, vault secret GET authorization and enabled state.") from None
    if not isinstance(secret, dict) or not isinstance(secret.get("attributes"), dict):
        raise GroupsError(f"Malformed secret response for {persona}.")
    if secret["attributes"].get("enabled") is not True or secret.get("deletedDate") is not None:
        raise GroupsError(f"Seeding record for {persona} is disabled/deleted; administrator review is required.")
    try:
        record = json.loads(secret["value"])
    except (KeyError, TypeError, ValueError):
        raise GroupsError(f"Invalid JSON seeding record for {persona}; bare GUIDs are not accepted.") from None
    _validate_record(record, spec, persona)
    return record


def _assert_not_deleted(manifest, spec, persona, run):
    try:
        run("keyvault", "secret", "show-deleted", *_seed_args(manifest, spec))
    except _CLI_ERRORS as error:
        if _error_code(error) == "SecretNotFound":
            return
        raise GroupsError(f"Cannot check deleted seeding record for {persona}; verify vault secret GET authorization.") from None
    raise GroupsError(f"Seeding record for {persona} is soft-deleted; recover and review it separately, never overwrite it.")


def resolve_seeded_groups(manifest, scope, cli):
    """Runtime resolver: only explicitly subscription-scoped Key Vault secret GETs."""
    manifest = validate_identity_manifest(manifest)
    result = {}
    for persona, spec in group_specs(manifest, scope).items():
        record = _read_seed(manifest, spec, persona, cli)
        object_id = record["object_id"]
        if object_id in result.values():
            raise GroupsError("Seeding records reuse one group object ID for multiple personas.")
        result[persona] = object_id
    return result


def _verify_account(manifest, run):
    seed_subscription = manifest["seeding"]["subscription_id"]
    for args, expected_subscription in (
        (("account", "show"), None),
        (("account", "show", "--subscription", seed_subscription), seed_subscription),
    ):
        try:
            account = run(*args)
        except _CLI_ERRORS:
            raise GroupsError("Cannot read Azure account; az login --tenant <manifest tenant_id> and verify the seeding subscription.") from None
        if not isinstance(account, dict) or str(account.get("tenantId", "")).lower() != manifest["tenant_id"]:
            raise GroupsError("Wrong Azure tenant; az login --tenant <manifest tenant_id> before Graph access.")
        if expected_subscription and str(account.get("id", "")).lower() != expected_subscription:
            raise GroupsError("Wrong seeding subscription returned by az account show.")
        if account.get("state") != "Enabled":
            raise GroupsError("Azure subscription is not enabled.")


def _graph(run, method, url, *, body=None):
    args = ("rest", "--method", method, "--url", url)
    if body is not None:
        args += ("--body", json.dumps(body, separators=(",", ":")))
    try:
        return run(*args)
    except _CLI_ERRORS:
        requirement = ("Group.ReadWrite.All and appropriate delegated directory rights"
                       if method == "post" else "Group.Read.All")
        raise GroupsError(f"Graph {method.upper()} failed; verify the manifest tenant, {requirement}, and that the group exists and is not deleted.") from None


def _validate_group(group, spec, *, expected_id=None):
    if not isinstance(group, dict):
        raise GroupsError("Graph returned an invalid group response.")
    object_id = _guid(group.get("id"), "Graph group ID")
    if expected_id and object_id != expected_id:
        raise GroupsError("Graph returned a different group ID than requested.")
    if group.get("displayName") != spec["name"]:
        raise GroupsError("Adopted/seeded group has a noncanonical name; review and rename historical groups to the expected display name separately.")
    role_assignable = group.get("isAssignableToRole")
    if (group.get("securityEnabled") is not True or group.get("mailEnabled") is not False
            or group.get("groupTypes") != [] or (role_assignable is not None and role_assignable is not False)
            or group.get("deletedDateTime") is not None):
        raise GroupsError("Group must be active, security-enabled, non-mail, assigned membership, and not Entra role-assignable.")
    return object_id


def _find_group(spec, run):
    query = urlencode({"$filter": f"displayName eq '{spec['name']}'", "$select": GRAPH_SELECT})
    url = f"{GRAPH_GROUPS}?{query}"
    seen, groups = set(), []
    while url:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "graph.microsoft.com"
                or parts.path != "/v1.0/groups" or parts.fragment or url in seen or len(seen) >= 1000):
            raise GroupsError("Graph returned an unsafe or cyclic pagination link.")
        seen.add(url)
        page = _graph(run, "get", url)
        if not isinstance(page, dict) or not isinstance(page.get("value"), list):
            raise GroupsError("Graph returned an invalid groups page.")
        groups.extend(page["value"])
        url = page.get("@odata.nextLink")
        if url is not None and not isinstance(url, str):
            raise GroupsError("Graph returned an invalid pagination link.")
    if len(groups) > 1:
        raise GroupsError(f"Duplicate exact display name {spec['name']}; an Entra administrator must resolve the ambiguity.")
    if groups:
        return _validate_group(groups[0], spec)
    return None


def _get_group(spec, object_id, run):
    group = _graph(run, "get", f"{GRAPH_GROUPS}/{object_id}?{urlencode({'$select': GRAPH_SELECT})}")
    return _validate_group(group, spec, expected_id=object_id)


def _read_admin_seed(manifest, spec, persona, run):
    record = _read_seed(manifest, spec, persona, run, allow_missing=True)
    if record is None:
        _assert_not_deleted(manifest, spec, persona, run)
    return record


def _check_unique(ids):
    values = [value for value in ids.values() if value is not None]
    if len(values) != len(set(values)):
        raise GroupsError("Each persona must resolve to a unique group object ID.")


def reconcile_groups(manifest, operation="discover", *, scope="project", execute=False, cli=cli):
    """Plan or execute a separately authorized directory bootstrap."""
    if operation not in ("discover", "create") or type(execute) is not bool:
        raise GroupsError("operation must be discover/create and execute must be boolean.")
    manifest = validate_identity_manifest(manifest)
    specs = group_specs(manifest, scope)
    _verify_account(manifest, cli)
    ids, records, changes, blockers = {}, {}, [], []
    # Validate every seed and directory identity before the first write.
    for persona, spec in specs.items():
        record = _read_admin_seed(manifest, spec, persona, cli)
        records[persona] = record
        adopted_id = manifest["groups"].get(persona)
        seeded_id = record["object_id"] if record else None
        if adopted_id and seeded_id and adopted_id != seeded_id:
            raise GroupsError(f"Explicit group adoption conflicts with the immutable seed for {persona}.")
        exact_id = _find_group(spec, cli)
        object_id = seeded_id or adopted_id or exact_id
        if object_id:
            _get_group(spec, object_id, cli)
            if exact_id != object_id:
                raise GroupsError(f"Group ID/name lookup disagrees for {persona}; resolve duplicates or directory replication before retrying.")
        ids[persona] = object_id
        if not object_id:
            if operation == "discover":
                blockers.append(f"Missing group {spec['name']}; authorize an Entra administrator to run create --execute.")
            else:
                changes.append({"action": "create-group", "persona": persona, "display_name": spec["name"]})
        if record is None and (object_id or operation == "create"):
            changes.append({"action": "publish-seed", "persona": persona, "seed_key": spec["seed_key"],
                            "object_id": object_id})
    _check_unique(ids)
    result = {"state": "preview", "operation": operation, "scope": scope,
              "groups": ids, "changes": changes, "blockers": blockers}
    if not execute or blockers:
        return result
    for persona, spec in specs.items():
        if ids[persona]:
            continue
        # Recheck just before creation, then detect duplicate names after creation.
        object_id = _find_group(spec, cli)
        if object_id is None:
            created = _graph(cli, "post", GRAPH_GROUPS, body={
                "displayName": spec["name"],
                "description": f"AI Factory {persona}; assigned human security group",
                "mailEnabled": False, "securityEnabled": True, "groupTypes": [],
                "mailNickname": "aif-" + hashlib.sha256(spec["name"].encode("utf-8")).hexdigest()[:40],
            })
            object_id = _validate_group(created, spec)
        ids[persona] = object_id
        if _find_group(spec, cli) != object_id:
            raise GroupsError(f"Created group for {persona} is not uniquely resolvable yet; wait for replication and rerun discover. No automatic deletion.")
    _check_unique(ids)
    # Check all directory identities and all destination secrets again before
    # publication; an administrator must serialize writers across the vault.
    for persona, spec in specs.items():
        if _find_group(spec, cli) != ids[persona]:
            raise GroupsError(f"Directory identity changed for {persona}; refusing publication.")
        _get_group(spec, ids[persona], cli)
        existing = _read_admin_seed(manifest, spec, persona, cli)
        desired = _record(spec, persona, ids[persona])
        if existing is not None and existing != desired:
            raise GroupsError(f"Seeding record conflict for {persona}; group ID/binding changes are forbidden.")
        if records[persona] is not None and existing is None:
            raise GroupsError(f"Seeding record disappeared for {persona}; refusing to recreate it.")
        records[persona] = existing
    for persona, spec in specs.items():
        desired = _record(spec, persona, ids[persona])
        existing = _read_admin_seed(manifest, spec, persona, cli)
        if existing is not None:
            if existing != desired:
                raise GroupsError(f"Seeding record conflict for {persona}; refusing overwrite.")
            continue
        if records[persona] is not None:
            raise GroupsError(f"Seeding record disappeared for {persona}; refusing to recreate it.")
        try:
            cli("keyvault", "secret", "set", *_seed_args(manifest, spec),
                "--value", json.dumps(desired, sort_keys=True, separators=(",", ":")))
        except _CLI_ERRORS:
            raise GroupsError(f"Cannot publish {persona}; verify seeding vault secret SET authorization. Already completed changes are retained for a safe rerun.") from None
        if _read_seed(manifest, spec, persona, cli) != desired:
            raise GroupsError(f"Published seeding record verification failed for {persona}.")
    result["state"] = "executed"
    for change in changes:
        if change["action"] == "publish-seed":
            change["object_id"] = ids[change["persona"]]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--operation", required=True, choices=("discover", "create"))
    parser.add_argument("--scope", choices=("common", "project"), default="project")
    parser.add_argument("--execute", action="store_true", help="Authorize writes; absent means read-only preview.")
    args = parser.parse_args(argv)
    try:
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise GroupsError("Cannot read manifest JSON; check the file path and JSON syntax.") from None
        result = reconcile_groups(manifest, args.operation, scope=args.scope, execute=args.execute, cli=cli)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if result["blockers"] else 0
    except GroupsError as error:
        print(f"Persona groups: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
