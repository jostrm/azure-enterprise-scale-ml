"""Project-only ADLS ACL provisioning using Azure CLI tokens and standard-library HTTP."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4


DATA_OWNER = "b7e6dc6d-f1e8-4753-8033-0f276bb0955b"
READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"


def cli(*args):
    executable = shutil.which("az")
    if not executable:
        raise FileNotFoundError("Azure CLI must be installed and authenticated")
    command = [executable]
    if Path(executable).suffix.lower() in (".cmd", ".bat"):
        runtime = Path(executable).parent.parent / "python.exe"
        if not runtime.is_file():
            raise FileNotFoundError("Azure CLI Python runtime missing")
        command = [str(runtime), "-X", "utf8", "-IBm", "azure.cli"]
    result = subprocess.run([*command, *args, "-o", "json", "--only-show-errors"],
                            text=True, encoding="utf-8", capture_output=True, timeout=180,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if result.returncode:
        raise RuntimeError(f"Azure CLI {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def validate(config):
    value = deepcopy(config)
    for name in ("tenant_id", "subscription_id"):
        value[name] = str(UUID(value[name]))
    for name, pattern in (
        ("storage_account", r"[a-z0-9]{3,24}"), ("filesystem", r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"),
        ("resource_group", r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}"), ("project", r"project[0-9]{3}"),
    ):
        if not isinstance(value.get(name), str) or not re.fullmatch(pattern, value[name]):
            raise ValueError(f"Invalid {name}")
    if value.get("environment") not in ("dev", "test", "prod"):
        raise ValueError("Explicit environment dev/test/prod is required")
    for name in ("execute", "temporary_data_owner", "legacy_layout"):
        if type(value.get(name, False)) is not bool:
            raise ValueError(f"{name} must be a boolean")
    principals = {}
    for field, kind in (("users", "User"), ("groups", "Group"), ("managed_identities", "ServicePrincipal"),
                        ("readers", "ServicePrincipal")):
        entries = value.get(field, [])
        if not isinstance(entries, list):
            raise ValueError(f"{field} must be an array")
        value[field] = sorted({str(UUID(item)) for item in entries})
        for entry in value[field]:
            if entry in principals:
                raise ValueError("Principal cannot occur in multiple role/type lists")
            principals[entry] = kind
    if not principals:
        raise ValueError("Specify at least one explicit project principal")
    return value, principals


def merge_acl(current, grants, *, directory, defaults):
    entries = {part.rsplit(":", 1)[0]: part.rsplit(":", 1)[1] for part in current.split(",")}
    wanted = dict(entries)
    for kind, principal, permission in grants:
        wanted[f"{kind}:{principal}"] = permission
    desired_mask = list(entries.get("mask:", entries.get("group:", "---")))
    for _, _, permission in grants:
        for index, bit in enumerate(permission):
            if bit != "-":
                desired_mask[index] = bit
    wanted["mask:"] = "".join(desired_mask)
    if defaults and directory:
        for key in ("user:", "group:", "other:"):
            wanted.setdefault("default:" + key, entries.get(key, "---"))
        wanted.setdefault("default:mask:", entries.get("mask:", entries.get("group:", "---")))
        default_mask = list(wanted["default:mask:"])
        for kind, principal, permission in grants:
            wanted[f"default:{kind}:{principal}"] = permission
            for index, bit in enumerate(permission):
                if bit != "-":
                    default_mask[index] = bit
        wanted["default:mask:"] = "".join(default_mask)
    selected = {f"{kind}:{principal}" for kind, principal, _ in grants}
    for prefix in ("", "default:"):
        old_mask, new_mask = entries.get(prefix + "mask:"), wanted.get(prefix + "mask:")
        if old_mask and new_mask and old_mask != new_mask:
            for key, permissions in entries.items():
                local = key.removeprefix(prefix)
                if prefix and not key.startswith(prefix):
                    continue
                if local in selected or local == "user:" or local.startswith(("other:", "mask:")):
                    continue
                if local.startswith(("user:", "group:")) and any(
                    bit != "-" and old_mask[index] == "-" and new_mask[index] != "-"
                    for index, bit in enumerate(permissions)
                ):
                    raise ValueError("ACL mask expansion would expose unrelated existing rights; review that path explicitly")
    if len([key for key in wanted if not key.startswith("default:")]) > 32 or len([key for key in wanted if key.startswith("default:")]) > 32:
        raise ValueError("ADLS ACL entry limit exceeded; use the project group instead of individual members")
    return ",".join(f"{key}:{permission}" for key, permission in sorted(wanted.items()))


class Lake:
    def __init__(self, config):
        self.config = config
        self.token = None

    def request(self, method, path="", query=None, headers=None):
        if self.token is None or int(self.token["expires_on"]) < time.time() + 60:
            self.token = cli("account", "get-access-token", "--subscription", self.config["subscription_id"],
                             "--resource", "https://storage.azure.com/")
            if str(self.token["tenant"]).lower() != self.config["tenant_id"]:
                raise ValueError("Storage token belongs to another tenant")
        url = f"https://{self.config['storage_account']}.dfs.core.windows.net/{self.config['filesystem']}"
        if path:
            url += "/" + quote(path.strip("/"), safe="/")
        elif (query or {}).get("resource") != "filesystem":
            url += "/"
        if query:
            url += "?" + urlencode(query)
        request = Request(url, method=method, headers={
            "Authorization": "Bearer " + self.token["accessToken"],
            "x-ms-version": "2023-11-03", **(headers or {}),
        })
        with urlopen(request, timeout=90) as response:
            content = response.read()
            return dict(response.headers), json.loads(content) if content else None

    def acl(self, path):
        return self.request("HEAD", path, {"action": "getAccessControl"})[0]

    def mkdir(self, path):
        try:
            self.request("PUT", path, {"resource": "directory"}, {"If-None-Match": "*", "Content-Length": "0"})
        except HTTPError as error:
            if error.code != 409:
                raise
            # Do not treat an existing file as a traversable directory.
            headers = self.request("HEAD", path, {"action": "getStatus"})[0]
            if headers.get("x-ms-resource-type") != "directory":
                raise ValueError(f"Existing path is not a directory: {path}") from error

    def paths(self, prefix):
        query = {"resource": "filesystem", "directory": prefix, "recursive": "true", "maxResults": "5000"}
        while True:
            headers, result = self.request("GET", query=query)
            for item in result.get("paths", []):
                yield item["name"], str(item.get("isDirectory", "false")).lower() == "true"
            continuation = headers.get("x-ms-continuation")
            if not continuation:
                break
            query["continuation"] = continuation


def apply(config):
    config, principals = validate(config)
    account = cli("account", "show", "--subscription", config["subscription_id"])
    if str(account["tenantId"]).lower() != config["tenant_id"]:
        raise ValueError("Selected subscription/tenant mismatch")
    storage = cli("storage", "account", "show", "--name", config["storage_account"],
                  "--resource-group", config["resource_group"], "--subscription", config["subscription_id"])
    if not storage.get("isHnsEnabled"):
        raise ValueError("ACLs require an HNS-enabled account; do not substitute project Blob storage")
    root = f"projects/{config['project']}" if config.get("legacy_layout") else f"mlops/v1/projects/{config['project']}"
    leaf = root if config.get("legacy_layout") else f"{root}/environments/{config['environment']}"
    scope = storage["id"] + f"/blobServices/default/containers/{config['filesystem']}"
    result = {
        "schema": "aifactory.project-lake-access/v2", "state": "preview",
        "storage_scope": scope, "project_root": root, "environment_path": leaf,
        "principals": principals, "reader_role": "Reader (ARM metadata, not Storage Blob Data Reader)",
        "acl": "Ancestor traversal only; project directories rwx, files rw-; inherited defaults. Explicit readers r-x/r--.",
        "temporary_executor_data_owner": config.get("temporary_data_owner", False),
        "changes_other_projects": False, "changed_paths": [],
    }
    if not config.get("execute"):
        return result
    temporary_role = None
    lake = Lake(config)
    result["state"] = "applying"
    def save():
        if config.get("receipt_path"):
            path = Path(config["receipt_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    save()
    try:
        if config.get("temporary_data_owner"):
            user = cli("ad", "signed-in-user", "show", "--query", "{id:id,userPrincipalName:userPrincipalName}")
            if user.get("userPrincipalName", "").lower() != account.get("user", {}).get("name", "").lower():
                raise ValueError("Temporary data-owner mode requires the explicitly signed-in user")
            existing = cli("role", "assignment", "list", "--scope", scope, "--include-inherited",
                           "--subscription", config["subscription_id"])
            has_owner = any(item["principalId"] == user["id"] and item["roleDefinitionId"].endswith(DATA_OWNER)
                            and not item.get("condition") for item in existing)
            if not has_owner:
                role = cli("role", "assignment", "create", "--name", str(uuid4()), "--assignee-object-id", user["id"],
                           "--assignee-principal-type", "User", "--role", DATA_OWNER, "--scope", scope,
                           "--subscription", config["subscription_id"])
                temporary_role = role["id"]
                result["temporary_role_id"] = temporary_role
                result["temporary_role_removed"] = False
                save()
        # Fail early if the executor cannot administer the existing root ACL.
        for attempt in range(18):
            try:
                current = lake.acl("")
                lake.request("PATCH", query={"action": "setAccessControl"},
                             headers={"x-ms-acl": current["x-ms-acl"], "If-Match": current["ETag"], "Content-Length": "0"})
                break
            except HTTPError as error:
                if error.code != 403 or temporary_role is None or attempt == 17:
                    raise
                time.sleep(10)
                lake.token = None
        assignments = cli("role", "assignment", "list", "--scope", scope, "--subscription", config["subscription_id"])
        for principal, kind in principals.items():
            if not any(item["principalId"] == principal and item["roleDefinitionId"].endswith(READER)
                       and item["scope"].lower() == scope.lower() for item in assignments):
                cli("role", "assignment", "create", "--assignee-object-id", principal, "--assignee-principal-type", kind,
                    "--role", READER, "--scope", scope, "--subscription", config["subscription_id"])
        segments = leaf.split("/")
        for index in range(1, len(segments) + 1):
            lake.mkdir("/".join(segments[:index]))
        ancestors = [""] + ["/".join(root.split("/")[:index]) for index in range(1, len(root.split("/")))]
        paths = [(path, True, False) for path in ancestors] + [(root, True, True)]
        paths += [(name, directory, True) for name, directory in lake.paths(root)]
        for name, directory, inside in paths:
            grants = []
            for principal, kind in principals.items():
                readonly = principal in config["readers"]
                permission = ("r-x" if directory else "r--") if readonly else ("rwx" if directory else "rw-")
                grants.append(("group" if kind == "Group" else "user", principal, permission if inside else "--x"))
            current = lake.acl(name)
            desired = merge_acl(current["x-ms-acl"], grants, directory=directory, defaults=inside)
            if desired != current["x-ms-acl"]:
                lake.request("PATCH", name, {"action": "setAccessControl"},
                             {"x-ms-acl": desired, "If-Match": current["ETag"], "Content-Length": "0"})
            actual = lake.acl(name)["x-ms-acl"]
            if set(actual.split(",")) != set(desired.split(",")):
                raise ValueError(f"ACL verification failed at {name}")
            result["changed_paths"].append({"path": name or "/", "directory": directory, "project_scope": inside})
        result["state"] = "complete"
    finally:
        if result["state"] != "complete":
            result["state"] = "incomplete"
        try:
            if temporary_role is not None:
                cli("role", "assignment", "delete", "--ids", temporary_role, "--subscription", config["subscription_id"])
                result["temporary_role_removed"] = True
        finally:
            save()
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(apply(json.load(sys.stdin)), indent=2))
    except HTTPError as error:
        print(f"Storage request failed: HTTP {error.code}, code={error.headers.get('x-ms-error-code')}, "
              f"request={error.headers.get('x-ms-request-id')}. No credentials were printed.", file=sys.stderr)
        raise SystemExit(1)
