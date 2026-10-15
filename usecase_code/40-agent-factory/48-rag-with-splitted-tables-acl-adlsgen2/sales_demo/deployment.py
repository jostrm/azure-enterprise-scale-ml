"""Approval-gated, immutable publication; no role grants or shared-resource deletion."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import format_datetime
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .configuration import digest, local_file, readiness, relative_path

STORAGE_API = "2023-11-03"


def publication_plan(config: dict) -> dict:
    root = Path(config["artifacts_root"])
    files, excluded, seen = [], [], set()
    for entry in config["publication"]["files"]:
        path = relative_path(entry["path"])
        if path in seen:
            raise ValueError("Duplicate publication path.")
        seen.add(path)
        if path.startswith("images/"):
            excluded.append(path)
            continue
        if not path.startswith(("ingestion/json/", "ingestion/excel/", "structured/json/",
                                "structured/excel/", "originals/")):
            raise ValueError("Only sales input, authoritative rows and originals may enter the sales lake.")
        master = local_file(root / "master", path).read_bytes()
        project = local_file(root / "project", path).read_bytes()
        if digest(master) != entry["sha256"] or master != project:
            raise ValueError("Master and project publication copies must match the pinned bytes.")
        source = "json" if path.startswith(("ingestion/json/", "structured/json/")) else "excel"
        files.append({
            "path": path, "source": source, "sha256": entry["sha256"],
            "master": config["master_prefix"] + "/" + path,
            "project": config["project_prefix"] + "/" + path,
        })
    if not files:
        raise ValueError("The publication contains no sales files.")
    return {
        "mutations": False, "container": config["container"], "files": files, "excluded": excluded,
        "copy_method": "Upload master once; read pinned master bytes and copy to immutable project paths.",
        "ancestor_policy": "Existing ancestors must already allow traversal; this tool never changes them.",
        "cleanup": "No delete operation is implemented. Shared services and unrelated paths are never removed.",
    }


def broad_data_roles(assignments: list[dict], definitions: dict, principal_ids: set[str]) -> list[dict]:
    read = "microsoft.storage/storageaccounts/blobservices/containers/blobs/read"
    principals = {value.casefold() for value in principal_ids}
    found = []
    for assignment in assignments:
        properties = assignment["properties"]
        if properties["principalId"].casefold() not in principals:
            continue
        role = definitions[properties["roleDefinitionId"]]
        for permission in role.get("permissions", []):
            grants = any(fnmatchcase(read, action.lower()) for action in permission.get("dataActions", []))
            excludes = any(fnmatchcase(read, action.lower()) for action in permission.get("notDataActions", []))
            if grants and not excludes:
                found.append({
                    "principal_id": properties["principalId"], "scope": properties["scope"],
                    "role_definition_id": properties["roleDefinitionId"],
                    "requires_condition_review": bool(properties.get("condition")),
                })
                break
    return found


def missing_private_links(links: list[dict], storage_id: str, foundry_id: str) -> list[dict]:
    approved = {
        (link["properties"]["privateLinkResourceId"].casefold(), link["properties"]["groupId"].casefold())
        for link in links if link["properties"].get("status") == "Approved"
        and link["properties"].get("provisioningState") == "Succeeded"
    }
    required = [(storage_id, "blob"), (storage_id, "dfs"), (foundry_id, "openai_account")]
    return [
        {"privateLinkResourceId": resource, "groupId": group}
        for resource, group in required if (resource.casefold(), group) not in approved
    ]


def role_allows(assignments: list[dict], definitions: dict, principal: str, kind: str, operation: str) -> bool:
    exclusion = "notActions" if kind == "actions" else "notDataActions"
    for assignment in assignments:
        properties = assignment["properties"]
        if properties["principalId"].casefold() != principal.casefold() or properties.get("condition"):
            continue
        for permission in definitions[properties["roleDefinitionId"]].get("permissions", []):
            if (any(fnmatchcase(operation.casefold(), action.casefold()) for action in permission.get(kind, []))
                    and not any(fnmatchcase(operation.casefold(), action.casefold())
                                for action in permission.get(exclusion, []))):
                return True
    return False


def preflight(config: dict, session, factory) -> dict:
    from agent_factory.azure import ARM
    from agent_factory.discovery import discover
    from agent_factory.data import require_private_endpoint

    target = discover(factory, session)
    storage = session.arm("GET", config["storage_resource_id"], api_version="2023-05-01")
    properties = storage["properties"]
    if properties.get("isHnsEnabled") is not True or properties.get("publicNetworkAccess") != "Disabled":
        raise ValueError("The sales lake must have HNS enabled and public network access disabled.")
    container = session.arm(
        "GET", config["storage_resource_id"] + "/blobServices/default/containers/" + config["container"],
        api_version="2023-05-01",
    )
    if container["properties"].get("publicAccess", "None") != "None":
        raise ValueError("Anonymous source access is forbidden.")
    search_id = target.group_id + "/providers/Microsoft.Search/searchServices/" + target.search_name
    search = session.arm("GET", search_id, api_version="2025-05-01")
    if search["properties"].get("publicNetworkAccess") != "Disabled":
        raise ValueError("Use the existing private Search service.")
    deployment = session.arm("GET", target.account_id + "/deployments/" + target.embedding_deployment)
    if deployment["properties"]["model"]["name"] != "text-embedding-3-large":
        raise ValueError("The selected embedding deployment has the wrong model.")
    account = session.arm("GET", target.account_id)
    links = session.pages(ARM + search_id + "/sharedPrivateLinkResources?api-version=2025-05-01")
    missing_links = missing_private_links(links, config["storage_resource_id"], target.account_id)
    embedding_endpoint = account["properties"]["endpoints"]["OpenAI Language Model Instance API"].rstrip("/")
    for endpoint in (target.search_endpoint, embedding_endpoint, target.project_endpoint,
                     f"https://{config['storage_account']}.dfs.core.windows.net",
                     f"https://{config['storage_account']}.blob.core.windows.net"):
        require_private_endpoint(endpoint)
    scope = config["storage_resource_id"] + "/blobServices/default/containers/" + config["container"]
    assignments = session.pages(
        ARM + scope + "/providers/Microsoft.Authorization/roleAssignments"
        "?api-version=2022-04-01&$filter=atScope()"
    )
    definitions = {}
    for assignment in assignments:
        role_id = assignment["properties"]["roleDefinitionId"]
        if role_id not in definitions:
            definitions[role_id] = session.arm("GET", role_id, api_version="2022-04-01")["properties"]
    principals = set(config.get("acl_test_principal_ids", [])) | set(config.get("denied_test_user_ids", []))
    for partition in config["partitions"]:
        principals.update(partition.get("allowed_group_ids", []))
        principals.update(partition.get("allowed_user_ids", []))
    issues = broad_data_roles(assignments, definitions, principals)
    backend = {"query_read": False, "indexer_status_read": False, "principal_id": None}
    if config.get("backend_identity_client_id"):
        identities = session.pages(
            ARM + target.group_id + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities?api-version=2023-01-31"
        )
        selected = [identity for identity in identities
                    if identity["properties"]["clientId"].casefold() == config["backend_identity_client_id"].casefold()]
        if len(selected) != 1:
            raise ValueError("Select one explicit retrieval managed identity in this project's resource group.")
        principal = selected[0]["properties"]["principalId"]
        backend["principal_id"] = principal
        search_roles = session.pages(
            ARM + search_id + "/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01&$filter=atScope()"
        )
        for assignment in search_roles:
            role_id = assignment["properties"]["roleDefinitionId"]
            if role_id not in definitions:
                definitions[role_id] = session.arm("GET", role_id, api_version="2022-04-01")["properties"]
        backend["query_read"] = role_allows(
            search_roles, definitions, principal, "dataActions",
            "Microsoft.Search/searchServices/indexes/documents/read",
        )
        backend["indexer_status_read"] = role_allows(
            search_roles, definitions, principal, "actions",
            "Microsoft.Search/searchServices/indexers/read",
        )
    return {
        "mutations": False, "target": target.to_dict(),
        "search_endpoint": target.search_endpoint, "embedding_endpoint": embedding_endpoint,
        "project_endpoint": target.project_endpoint,
        "search_identity_object_id": search.get("identity", {}).get("principalId"),
        "broad_data_roles": issues,
        "missing_outbound_private_links": missing_links,
        "outbound_private_links_ready": not missing_links,
        "backend_permissions": backend,
        "backend_permissions_ready": backend["query_read"] and backend["indexer_status_read"],
        "acl_test_principals_checked": sorted(principals),
        "acl_test_ready": bool(principals and config.get("denied_test_user_ids")) and not issues,
        "remaining": readiness(config),
        "caveat": "Include every transitive group of each test user. No role/ACL changes are performed.",
    }


class StorageError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"Scoped Storage operation failed (HTTP {status}); no fallback identity was used.")


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Authenticated storage redirects are forbidden.")


class StorageWriter:
    """Operator transport; never used as an end-user calculator source reader."""

    def __init__(self, config: dict, session):
        self.config, self.session = config, session
        self.roots = (config["master_prefix"], config["project_prefix"])
        self.opener = build_opener(ProxyHandler({}), _NoRedirects())

    def request(self, method: str, path: str, *, dfs: bool = True, query=None,
                body: bytes | None = None, headers=None):
        relative_path(path)
        if not any(path == root or path.startswith(root + "/") for root in self.roots):
            raise ValueError("Write/read path escapes the two approved dataset version roots.")
        service = "dfs" if dfs else "blob"
        url = f"https://{self.config['storage_account']}.{service}.core.windows.net/{self.config['container']}/{path}"
        if query:
            url += "?" + urlencode(query)
        from agent_factory.data import require_private_endpoint
        require_private_endpoint(url)
        request_headers = {
            "Authorization": "Bearer " + self.session.token("https://storage.azure.com"),
            "x-ms-version": STORAGE_API,
            "x-ms-date": format_datetime(datetime.now(timezone.utc), usegmt=True),
            **(headers or {}),
        }
        try:
            with self.opener.open(Request(url, data=body, headers=request_headers, method=method), timeout=90) as response:
                return response.read(), response.headers
        except HTTPError as error:
            raise StorageError(error.code) from None

    def directory(self, path: str, groups: list[str], users: list[str]) -> None:
        owner = base64.b64encode(self.config["owner"].encode()).decode()
        try:
            self.request("PUT", path, query={"resource": "directory"}, headers={
                "If-None-Match": "*", "x-ms-permissions": "rwx------", "x-ms-properties": f"aif48owner={owner}",
            })
        except StorageError as error:
            if error.status not in {409, 412}:
                raise
            _, headers = self.request("HEAD", path, query={"action": "getStatus"})
            if f"aif48owner={owner}" not in headers.get("x-ms-properties", "").split(","):
                raise ValueError("Existing directory is not task-owned; refusing permission changes.") from None
        self.permissions(path, groups, users, directory=True)

    def permissions(self, path: str, groups: list[str], users: list[str], *, directory=False):
        rights = "--x" if directory else "r--"
        entries = ["user::rwx" if directory else "user::rw-", "group::---", "other::---",
                   "mask::r-x" if directory else "mask::r--"]
        entries.extend(f"group:{identity}:{rights}" for identity in sorted(set(groups)))
        entries.extend(f"user:{identity}:{rights}" for identity in sorted(set(users)))
        entries.append(
            f"user:{self.config['search_identity_object_id']}:" + ("r-x" if directory else "r--")
        )
        acl = ",".join(entries)
        self.request("PATCH", path, query={"action": "setAccessControl"}, headers={"x-ms-acl": acl})
        _, response = self.request("HEAD", path, query={"action": "getAccessControl"})
        if set(response.get("x-ms-acl", "").split(",")) != set(entries):
            raise ValueError("ADLS did not preserve the requested task-scoped ACL.")

    def put_immutable(self, path: str, raw: bytes, metadata: dict):
        headers = {
            "If-None-Match": "*", "x-ms-blob-type": "BlockBlob", "Content-Type": "application/octet-stream",
            **{"x-ms-meta-" + key: str(value) for key, value in metadata.items()},
        }
        try:
            self.request("PUT", path, dfs=False, body=raw, headers=headers)
        except StorageError as error:
            if error.status not in {409, 412}:
                raise
            saved, response = self.request("GET", path, dfs=False)
            if saved != raw or any(response.get("x-ms-meta-" + k) != str(v) for k, v in metadata.items()):
                raise ValueError("Existing file differs or belongs to another publication; refusing overwrite.") from None

    def read(self, path: str) -> bytes:
        return self.request("GET", path, dfs=False)[0]


def publish(config: dict, store, *, apply: bool = False) -> dict:
    if not apply:
        raise ValueError("Publication requires explicit --apply after reviewing the exact plan.")
    unresolved = readiness(config)
    if unresolved:
        raise ValueError("Publication prerequisites unresolved: " + " ".join(unresolved))
    plan = publication_plan(config)
    policies = {item["id"]: item for item in config["partitions"]}
    groups = sorted({group for p in policies.values() for group in p.get("allowed_group_ids", [])})
    users = sorted({user for p in policies.values() for user in p.get("allowed_user_ids", [])})
    directories = set()
    for root in (config["master_prefix"], config["project_prefix"]):
        directories.add(root)
        for item in plan["files"]:
            parts = item["path"].split("/")[:-1]
            for length in range(1, len(parts) + 1):
                directories.add(root + "/" + "/".join(parts[:length]))
    # Existing ancestors above these immutable version roots are deliberately untouched.
    for directory in sorted(directories, key=lambda value: (value.count("/"), value)):
        store.directory(directory, groups, users)
    root = Path(config["artifacts_root"])
    for item in plan["files"]:
        policy = policies[item["source"]]
        raw = local_file(root / "master", item["path"]).read_bytes()
        metadata = {
            "aif48owner": config["owner"], "dataset": config["dataset"], "version": config["version"],
            "source": item["source"], "site": policy.get("site", "retail"),
            "library": policy.get("library", item["source"]), "input_sha256": digest(raw),
        }
        store.put_immutable(item["master"], raw, metadata)
        store.permissions(item["master"], policy.get("allowed_group_ids", []), policy.get("allowed_user_ids", []))
        copied = store.read(item["master"])
        if digest(copied) != item["sha256"]:
            raise ValueError("Master changed before project copy; publication remains incomplete.")
        store.put_immutable(item["project"], copied, metadata)
        store.permissions(item["project"], policy.get("allowed_group_ids", []), policy.get("allowed_user_ids", []))
        if digest(store.read(item["project"])) != item["sha256"]:
            raise ValueError("Project copy differs from master; publication remains incomplete.")
    return {
        "owner": config["owner"], "dataset": config["dataset"], "version": config["version"],
        "state": "copied-not-indexed", "files": plan["files"], "mutations": True,
        "verified_publication": False,
    }
