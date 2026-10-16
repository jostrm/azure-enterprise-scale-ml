"""Bounded, read-only Graph v1 drive delta and explicitly reviewed ACL projection.

Delta is latest state, not an event log. The caller must persist a completed
round and its opaque cursor atomically, and close serving gates on any failure.
No permission grant, source upload, token=latest bootstrap, or POSIX ACL export
is implemented here. Full permission enumeration requires an operator-approved
Sites.FullControl.All scan; seeing a nonempty list does not establish completeness.
"""
from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


GRAPH = "https://graph.microsoft.com"
PREFER = ("hierarchicalsharing, deltashowremovedasdeleted, "
          "deltatraversepermissiongaps, deltashowsharingchanges")
SHARED_CHANGED = "@microsoft.graph.sharedChanged"
MAX_CONTENT_BYTES = 16 * 1024 * 1024
RESYNC_CODES = {"resyncChangesApplyDifferences", "resyncChangesUploadDifferences"}


class GraphSyncError(ValueError):
    """Sanitized, fail-closed source synchronization failure."""


class IncompleteInventory(GraphSyncError):
    """A full source-authoritative inventory or required partition is missing."""


class UnsupportedPermissions(GraphSyncError):
    """A complete returned permission set cannot be represented by the reviewed projection."""


class GraphResponseError(GraphSyncError):
    def __init__(self, status, *, code=None, location=None):
        self.status, self.code, self.location = status, code, location
        super().__init__(f"Graph read failed (HTTP {status}); source serving must remain closed.")


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _identifier(value):
    if (not isinstance(value, str) or not value or len(value) > 512
            or value != value.strip() or value in {".", ".."}
            or re.search(r"[\x00-\x20\x7f/\\?#%]", value)):
        raise GraphSyncError("An explicit stable Graph identifier is required.")
    return value


def _uuid(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        result = str(UUID(value))
        if result != value.lower():
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise GraphSyncError("A canonical Entra UUID is required.") from None


def validate_graph_config(config):
    """Return a defensive normalized copy; no network or grants are performed.

    principal_map values are {'type': 'user'|'group', 'id': '<same UUID>'},
    keyed by 'user:<UUID>' or 'group:<UUID>'. Same-UUID string values are also
    accepted; neither form can change the principal type or identity.
    source_read_scope must be Sites.FullControl.All for permission projection.
    source_authorization is the operator's scope-bound source-read approval text.
    """
    if not isinstance(config, dict):
        raise GraphSyncError("An explicit Graph source configuration is required.")
    result = deepcopy(config)
    result["tenant_id"] = _uuid(result.get("tenant_id"))
    result["drive_id"] = _identifier(result.get("drive_id"))
    result["scope_id"] = _identifier(result.get("scope_id"))
    if result.get("drive_type") not in {"business", "documentLibrary"}:
        raise GraphSyncError("Only a business or documentLibrary drive root is supported.")
    bindings = result.get("bindings")
    if (not isinstance(bindings, list) or len(bindings) != 2
            or any(not isinstance(binding, dict) or set(binding) != {"partition", "item_id"}
                   for binding in bindings)
            or {binding["partition"] for binding in bindings} != {"json", "excel"}):
        raise GraphSyncError("Exactly two explicit json/excel stable item bindings are required.")
    for binding in bindings:
        _identifier(binding["item_id"])
    if len({binding["item_id"] for binding in bindings}) != 2:
        raise GraphSyncError("The required partitions must bind to distinct Graph items.")
    hosts = result.get("download_hosts")
    if (not isinstance(hosts, list) or not hosts
            or any(not isinstance(host, str)
                   or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.sharepoint\.com", host)
                   for host in hosts)):
        raise GraphSyncError("Configure exact tenant SharePoint download hosts, never wildcards.")
    for name, default, maximum in (
        ("max_pages", 1000, 10000), ("max_page_bytes", 4 * 1024 * 1024, MAX_CONTENT_BYTES),
        ("max_round_bytes", 64 * 1024 * 1024, 256 * 1024 * 1024),
        ("max_items", 200000, 1000000), ("max_content_bytes", MAX_CONTENT_BYTES, MAX_CONTENT_BYTES),
    ):
        value = result.get(name, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise GraphSyncError("Graph read budgets must be positive integers within hard limits.")
        result[name] = value
    return result


def _url_parts(url):
    try:
        if (not isinstance(url, str) or len(url) > 32768
                or re.search(r"[\x00-\x20\x7f\\]", url)):
            raise ValueError
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise GraphSyncError("Untrusted continuation or download URL; no credentials were forwarded.") from None


def _graph_url(url, expected_path):
    parsed = _url_parts(url)
    path_matches = parsed.path == expected_path
    if expected_path.endswith("/root/delta"):
        suffix = parsed.path[len(expected_path):] if parsed.path.startswith(expected_path) else ""
        path_matches = path_matches or bool(re.fullmatch(r"\(token='[^/'\r\n]+'\)", suffix))
        if unquote(suffix).casefold() == "(token='latest')":
            raise GraphSyncError("A complete initial inventory is required; latest-token bootstrap is forbidden.")
    if parsed.hostname != "graph.microsoft.com" or not path_matches:
        raise GraphSyncError("Graph continuation escapes the exact approved drive operation.")
    if any(key.lower() in {"token", "$token", "$deltatoken"}
           and value.lower() == "latest" for key, value in parse_qsl(parsed.query)):
        raise GraphSyncError("A complete initial inventory is required; latest-token bootstrap is forbidden.")
    return url


def _permission_scan_token(token, tenant):
    """Check grants on trusted-local OAuth output; Graph validates the token itself."""
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 65536 or len(token.split(".")) != 3:
            raise ValueError
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        scopes = claims.get("scp", "").split()
        roles = claims.get("roles", [])
        if (claims.get("aud") not in {GRAPH, GRAPH + "/", "00000003-0000-0000-c000-000000000000"}
                or _uuid(claims.get("tid")) != tenant
                or not isinstance(roles, list) or "Sites.FullControl.All" not in scopes + roles
                or not math.isfinite(float(claims["exp"])) or float(claims["exp"]) <= time.time() + 30):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise GraphSyncError("The trusted Graph credential lacks a verifiable current permission-scanning grant.") from None


def _download_url(url, hosts):
    if _url_parts(url).hostname not in hosts:
        raise GraphSyncError("Download host is not an explicitly approved tenant SharePoint host.")
    return url


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def _safe_text(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or re.search(r"[\x00-\x1f\x7f]", value)):
        raise GraphSyncError("Malformed Graph item metadata.")
    return value


def compact_item(item, drive_id=None):
    """Allowlist durable metadata: never persist URLs, tokens, or Graph caches."""
    if not isinstance(item, dict):
        raise GraphSyncError("Malformed Graph inventory item.")
    result = {"id": _identifier(item.get("id"))}
    if "deleted" in item:
        if not isinstance(item["deleted"], dict):
            raise GraphSyncError("Malformed Graph tombstone.")
        return {**result, "deleted": {}}
    for field in ("name", "eTag", "cTag"):
        if field in item:
            result[field] = _safe_text(item[field])
    if "size" in item:
        if type(item["size"]) is not int or item["size"] < 0:
            raise GraphSyncError("Malformed Graph item size.")
        result["size"] = item["size"]
    if "parentReference" in item:
        reference = item["parentReference"]
        if not isinstance(reference, dict):
            raise GraphSyncError("Malformed Graph parent reference.")
        parent = {}
        for field in ("id", "driveId"):
            if field in reference:
                parent[field] = _identifier(reference[field])
        if drive_id and parent.get("driveId", drive_id) != drive_id:
            raise GraphSyncError("Graph item belongs to a different drive.")
        result["parentReference"] = parent
    for facet in ("file", "folder", "root", "remoteItem", "package", "malware"):
        if facet not in item:
            continue
        if not isinstance(item[facet], dict):
            raise GraphSyncError("Malformed Graph item facet.")
        result[facet] = {}
        if facet == "file":
            if "mimeType" in item[facet]:
                result[facet]["mimeType"] = _safe_text(item[facet]["mimeType"])
            hashes = item[facet].get("hashes", {})
            if not isinstance(hashes, dict):
                raise GraphSyncError("Malformed Graph content hash metadata.")
            if hashes:
                result[facet]["hashes"] = {
                    key: _safe_text(hashes[key]) for key in ("sha1Hash", "sha256Hash", "quickXorHash")
                    if key in hashes}
    if SHARED_CHANGED in item:
        annotation = item[SHARED_CHANGED]
        if annotation not in (True, False, "True", "False") or type(annotation) not in (bool, str):
            raise GraphSyncError("Malformed Graph sharing-change annotation.")
        result[SHARED_CHANGED] = annotation is True or annotation == "True"
    return result


def _validate_inventory(inventory):
    if not inventory:
        return
    roots = {identity for identity, item in inventory.items() if "root" in item}
    if len(roots) != 1:
        raise IncompleteInventory("A complete inventory must contain exactly one drive root.")
    resolved = set(roots)
    for identity in inventory:
        path = set()
        current = identity
        while current not in resolved:
            if current in path or current not in inventory:
                raise IncompleteInventory("An orphan or hierarchy cycle requires a full source inventory.")
            path.add(current)
            parent = inventory[current].get("parentReference", {}).get("id")
            if (parent not in inventory or "folder" not in inventory[parent]
                    and "root" not in inventory[parent]):
                raise IncompleteInventory("A missing or nonfolder parent requires a full source inventory.")
            current = parent
        resolved.update(path)


def reconcile_inventory(previous, round):
    """Fold last occurrences, cascade deleted folders, then reject hierarchy gaps.

    A child explicitly moved out of a deleted folder survives; descendants absent
    from the delta retain their stable parent linkage. Full resync replaces, not
    merges, the old inventory. Inputs are never mutated.
    """
    if (not isinstance(previous, dict) or not isinstance(round, dict)
            or not isinstance(round.get("items"), list) or type(round.get("full_resync")) is not bool):
        raise GraphSyncError("Malformed Graph round or inventory.")
    current = {} if round["full_resync"] else {
        identity: compact_item(value) for identity, value in previous.items()}
    if any(identity != value["id"] for identity, value in current.items()):
        raise GraphSyncError("Inventory keys must be stable item IDs.")
    for value in current.values():
        value.pop(SHARED_CHANGED, None)
    changes = {}
    for value in round["items"]:
        value = compact_item(value)
        changes[value["id"]] = value
    deleted = {identity for identity, value in changes.items() if "deleted" in value}
    for identity, value in changes.items():
        if identity not in deleted:
            current[identity] = value
    children = {}
    for identity, value in current.items():
        children.setdefault(value.get("parentReference", {}).get("id"), []).append(identity)
    pending = list(deleted)
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in deleted:
                deleted.add(child)
                pending.append(child)
    for identity in deleted:
        current.pop(identity, None)
    _validate_inventory(current)
    return current


def _permission_metadata(value):
    if isinstance(value, dict):
        return {key: _permission_metadata(item) for key, item in value.items()
                if "url" not in key.lower() and key not in {"@odata.context", "shareId"}}
    if isinstance(value, list):
        return sorted((_permission_metadata(item) for item in value), key=_json_bytes)
    return value


def permission_fingerprint(permissions):
    """Hash all returned non-URL permission metadata, independently of list order."""
    if not isinstance(permissions, list) or any(not isinstance(value, dict) for value in permissions):
        raise GraphSyncError("Permissions must be the complete freshly enumerated list.")
    try:
        return _hash(_permission_metadata(permissions))
    except (TypeError, ValueError):
        raise GraphSyncError("Malformed Graph permission metadata.") from None


def _scan_approved(config):
    if (config.get("permission_scan_approved") is not True
            or config.get("source_read_scope") != "Sites.FullControl.All"
            or not isinstance(config.get("source_authorization"), str)
            or not config["source_authorization"].strip()):
        raise GraphSyncError(
            "Full permission enumeration needs explicit scope-bound source authorization, "
            "permission_scan_approved and reviewed Sites.FullControl.All access; no grant is performed.")


def project_permissions(config, permissions):
    config = validate_graph_config(config)
    _scan_approved(config)
    if not isinstance(permissions, list):
        raise GraphSyncError("A complete permission list is required.")
    try:
        return _project_permissions(config, permissions)
    except GraphSyncError:
        raise UnsupportedPermissions("Source permissions require quarantine and explicit review.") from None


def _project_permissions(config, permissions):
    """Project only explicitly mapped Entra user/group read entitlement, never POSIX.

    Every permission must be representable. An empty result, sharing link,
    invitation, expiry, unknown role or principal closes the gate rather than
    silently dropping a grant or substituting a tenant-wide reader.
    """
    config = validate_graph_config(config)
    _scan_approved(config)
    fingerprint = permission_fingerprint(permissions)
    mapping = config.get("principal_map")
    if not isinstance(mapping, dict):
        raise GraphSyncError("A trusted explicit Graph-to-Entra principal_map is required.")
    normalized_mapping = {}
    for key, target in mapping.items():
        if not isinstance(key, str) or ":" not in key:
            raise GraphSyncError("Principal map keys require a user/group type and Entra UUID.")
        kind, identity = key.split(":", 1)
        if isinstance(target, dict):
            if set(target) != {"type", "id"} or target["type"] != kind:
                raise GraphSyncError("A typed principal map must preserve the Entra principal type.")
            target = target["id"]
        if kind not in {"user", "group"} or _uuid(identity) != _uuid(target):
            raise GraphSyncError("Principal remapping or type flattening is not approved.")
        normalized_mapping[(kind, _uuid(identity))] = _uuid(target)
    principals = {"user": set(), "group": set()}
    ids = set()
    allowed_keys = {"id", "roles", "grantedToV2", "grantedToIdentitiesV2", "inheritedFrom",
                    "expirationDateTime", "@odata.type"}
    for permission in permissions:
        if set(permission) - allowed_keys or permission.get("expirationDateTime"):
            raise GraphSyncError("Unsupported link, invitation, expiry or permission facet.")
        identity = _identifier(permission.get("id"))
        if identity in ids:
            raise GraphSyncError("Duplicate permission IDs require a fresh consistent scan.")
        ids.add(identity)
        roles = permission.get("roles")
        if (not isinstance(roles, list) or not roles
                or any(role not in ("read", "write", "owner") for role in roles)):
            raise GraphSyncError("Unsupported Graph permission role.")
        inherited = permission.get("inheritedFrom")
        if inherited is not None and (
            not isinstance(inherited, dict)
            or inherited.get("driveId", config["drive_id"]) != config["drive_id"]
        ):
            raise GraphSyncError("Permission inheritance escapes the configured drive.")
        identities = []
        if "grantedToV2" in permission:
            identities.append(permission["grantedToV2"])
        if "grantedToIdentitiesV2" in permission:
            if not isinstance(permission["grantedToIdentitiesV2"], list):
                raise GraphSyncError("Malformed Graph permission identity list.")
            identities.extend(permission["grantedToIdentitiesV2"])
        if not identities:
            raise GraphSyncError("A permission without a supported V2 identity cannot be projected.")
        for granted in identities:
            if (not isinstance(granted, dict) or set(granted) - {"user", "group", "siteUser", "@odata.type"}
                    or len(set(granted) & {"user", "group"}) != 1):
                raise GraphSyncError("Only explicitly verified Entra user/group principals are supported.")
            kind = "user" if "user" in granted else "group"
            principal = granted[kind]
            if not isinstance(principal, dict):
                raise GraphSyncError("Malformed Graph permission principal.")
            entra_id = _uuid(principal.get("id"))
            if normalized_mapping.get((kind, entra_id)) != entra_id:
                raise GraphSyncError("Graph principal lacks an explicit same-Entra trusted mapping.")
            principals[kind].add(entra_id)
    if not principals["user"] and not principals["group"]:
        raise GraphSyncError("Empty permissions never imply public or default reader access.")
    return {"allowed_user_ids": sorted(principals["user"]),
            "allowed_group_ids": sorted(principals["group"]), "permission_sha256": fingerprint}


def _ancestors(inventory, identity):
    result = []
    while identity in inventory and identity not in result:
        result.append(identity)
        identity = inventory[identity].get("parentReference", {}).get("id")
    return result


def build_change_plan(config, previous, current, previous_permission_hashes=None, permission_hashes=None):
    """Plan stable selected IDs, including descendants affected by parent changes.

    Missing fresh fingerprints conservatively mark security_changed and
    permission_scan_required; absence of sharedChanged is never proof of safety.
    Quarantine describes required serving revocation, not a deletion API.
    """
    config = validate_graph_config(config)
    old_hashes, new_hashes = previous_permission_hashes or {}, permission_hashes or {}
    plan = {key: [] for key in ("content_changed", "deleted", "metadata_changed", "security_changed",
                               "affected_descendants", "permission_scan_required", "quarantine")}
    for identity in sorted(binding["item_id"] for binding in config["bindings"]):
        if identity not in current or "deleted" in current[identity]:
            plan["deleted"].append(identity)
            plan["quarantine"].append(identity)
            continue
        before, after = previous.get(identity, {}), current[identity]
        if (not before or before.get("cTag") != after.get("cTag")
                or before.get("eTag") != after.get("eTag")
                or before.get("file", {}).get("hashes") != after.get("file", {}).get("hashes")):
            plan["content_changed"].append(identity)
        ancestors = set(_ancestors(previous, identity) + _ancestors(current, identity))
        metadata_changed = any(
            {key: previous.get(parent, {}).get(key) for key in ("name", "parentReference")}
            != {key: current.get(parent, {}).get(key) for key in ("name", "parentReference")}
            for parent in ancestors)
        if metadata_changed:
            plan["metadata_changed"].append(identity)
        shared_changed = any(current.get(parent, {}).get(SHARED_CHANGED) is True for parent in ancestors)
        if (shared_changed or not new_hashes.get(identity)
                or old_hashes.get(identity) != new_hashes.get(identity)):
            plan["security_changed"].append(identity)
        if not new_hashes.get(identity):
            plan["permission_scan_required"].append(identity)
        if metadata_changed or shared_changed:
            plan["affected_descendants"].append(identity)
    plan["complete"] = not plan["deleted"]
    plan["cleanup"] = "Quarantine serving first; clean up owned child indexes only, never shared resources."
    return plan


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BinaryGraphTransport:
    """Native bounded transport compatible with AzureSession.request.

    credential may expose .token(audience) or .get_token(scope). HTTP redirects
    are never automatic. Only Graph receives its bearer; preauthenticated
    SharePoint URLs receive no Authorization or caller-supplied headers.
    """
    def __init__(self, config, credential, *, opener=None):
        self.config = validate_graph_config(config)
        _scan_approved(self.config)
        self.credential = credential
        if (getattr(credential, "tenant_id", self.config["tenant_id"]).lower()
                != self.config["tenant_id"]):
            raise GraphSyncError("The Graph credential belongs to a different tenant.")
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirects())

    def _approved_graph_url(self, url):
        drive = quote(self.config["drive_id"], safe="")
        paths = {f"/v1.0/drives/{drive}/root/delta"}
        for binding in self.config["bindings"]:
            path = f"/v1.0/drives/{drive}/items/{quote(binding['item_id'], safe='')}"
            paths.update({path, path + "/permissions", path + "/content"})
        path = _url_parts(url).path
        if path not in paths and path.startswith(f"/v1.0/drives/{drive}/root/delta("):
            return _graph_url(url, f"/v1.0/drives/{drive}/root/delta")
        if path not in paths:
            raise GraphSyncError("Graph transport is limited to root delta and the two approved items.")
        _graph_url(url, path)

    def request_bytes(self, method, url, *, audience=None, headers=None, max_bytes=MAX_CONTENT_BYTES):
        if (method != "GET" or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CONTENT_BYTES
                or audience not in (None, GRAPH)):
            raise GraphSyncError("Only bounded read-only GET operations are supported.")
        headers = dict(headers or {})
        if any(key.lower() in {"authorization", "cookie", "host", "proxy-authorization"} for key in headers):
            raise GraphSyncError("Caller-supplied authorization headers are forbidden.")
        if audience == GRAPH:
            self._approved_graph_url(url)
        else:
            _download_url(url, self.config["download_hosts"])
            if headers:
                raise GraphSyncError("No Graph or caller-supplied headers may reach signed downloads.")
        try:
            if audience == GRAPH:
                token = (self.credential.token(GRAPH) if hasattr(self.credential, "token")
                         else self.credential.get_token(GRAPH + "/.default").token)
                _permission_scan_token(token, self.config["tenant_id"])
                headers["Authorization"] = "Bearer " + token
            request = Request(url, headers={**headers, "Accept-Encoding": "identity"}, method="GET")
            try:
                response = self.opener.open(request, timeout=60)
            except HTTPError as error:
                response = error
            with response:
                if hasattr(response, "geturl") and response.geturl() != url:
                    raise GraphSyncError("Automatic redirects are forbidden.")
                status = response.status if hasattr(response, "status") else response.code
                response_headers = dict(response.headers)
                length = _header(response_headers, "Content-Length")
                if length is not None and (not str(length).isdigit() or int(length) > max_bytes):
                    raise GraphSyncError("Graph response exceeds the bounded byte budget.")
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise GraphSyncError("Graph response exceeds the bounded byte budget.")
                return status, response_headers, raw
        except GraphSyncError:
            raise
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            raise GraphSyncError("Bounded Graph/download transport failed; sensitive details suppressed.") from None

    def request(self, method, url, *, audience=GRAPH, headers=None):
        if audience != GRAPH:
            raise GraphSyncError("JSON Graph operations require the Graph audience.")
        status, response_headers, raw = self.request_bytes(
            method, url, audience=audience, headers=headers, max_bytes=self.config["max_page_bytes"])
        if status != 200:
            code = None
            if status == 410:
                try:
                    code = json.loads(raw).get("error", {}).get("code")
                except (ValueError, AttributeError):
                    pass
            raise GraphResponseError(status, code=code, location=_header(response_headers, "Location"))
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise GraphSyncError("Graph returned invalid JSON.") from None


class GraphDeltaClient:
    """Root delta plus bound-item inspection, with injectable read-only transports."""
    def __init__(self, config, transport, *, binary_transport=None):
        self.config = validate_graph_config(config)
        _scan_approved(self.config)
        self.transport = transport
        self.binary_transport = binary_transport or (
            transport if hasattr(transport, "request_bytes") else None)
        self.drive_path = "/v1.0/drives/" + quote(self.config["drive_id"], safe="")
        self.delta_url = GRAPH + self.drive_path + "/root/delta"
        self.selected = {binding["item_id"] for binding in self.config["bindings"]}

    def _item_url(self, item_id, suffix=""):
        if item_id not in self.selected:
            raise GraphSyncError("Item reads are restricted to the two explicit source bindings.")
        return GRAPH + self.drive_path + "/items/" + quote(item_id, safe="") + suffix

    def _read_json(self, url, *, prefer=False):
        try:
            page = self.transport.request(
                "GET", url, audience=GRAPH, headers={"Prefer": PREFER} if prefer else {})
        except GraphResponseError:
            raise
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as error:
            status = getattr(error, "status", getattr(error, "code", None))
            cause = error if isinstance(error, HTTPError) else error.__cause__
            if status == 410 and isinstance(cause, HTTPError):
                location = _header(cause.headers or {}, "Location")
                try:
                    raw = cause.read(self.config["max_page_bytes"] + 1)
                    body = json.loads(raw) if len(raw) <= self.config["max_page_bytes"] else {}
                    code = body.get("error", {}).get("code")
                except (ValueError, AttributeError):
                    code = None
                raise GraphResponseError(410, code=code, location=location) from None
            raise GraphSyncError("Graph metadata read failed; sensitive transport details suppressed.") from None
        try:
            size = len(_json_bytes(page))
        except (ValueError, TypeError):
            raise GraphSyncError("Graph returned malformed JSON metadata.") from None
        if not isinstance(page, dict) or size > self.config["max_page_bytes"]:
            raise GraphSyncError("Graph JSON response exceeds the bounded page contract.")
        return page, size

    def fetch(self, cursor=None):
        """Read every opaque continuation, including empty pages, before returning.

        A supported 410 restarts at its validated Location once and discards every
        partial item from the expired round. Both Graph recovery codes are treated
        as source-authoritative inventories; neither can cause an upload to Graph.
        """
        if cursor is not None and not isinstance(cursor, str):
            raise GraphSyncError("The delta cursor must be an opaque URL or None.")
        url = self.delta_url if cursor is None else cursor
        expected = self.drive_path + "/root/delta"
        seen, items = set(), {}
        full_resync, recovered = cursor is None, False
        pages, total, item_count = 0, 0, 0
        while True:
            _graph_url(url, expected)
            if url in seen or pages >= self.config["max_pages"]:
                raise GraphSyncError("Graph continuation cycle or page budget exhausted.")
            seen.add(url)
            pages += 1
            try:
                page, size = self._read_json(url, prefer=True)
            except GraphResponseError as error:
                if error.status != 410 or error.code not in RESYNC_CODES or recovered:
                    raise GraphSyncError("Graph cursor recovery requires a reviewed complete resync.") from None
                url = _graph_url(error.location, expected)
                full_resync, recovered, items, seen = True, True, {}, set()
                continue
            total += size
            values = page.get("value")
            if not isinstance(values, list):
                raise GraphSyncError("Graph delta page is missing its item list.")
            item_count += len(values)
            if total > self.config["max_round_bytes"] or item_count > self.config["max_items"]:
                raise GraphSyncError("Graph inventory byte or item budget exhausted.")
            for value in values:
                value = compact_item(value, self.config["drive_id"])
                items[value["id"]] = value
            next_url, delta_url = page.get("@odata.nextLink"), page.get("@odata.deltaLink")
            if bool(next_url) == bool(delta_url):
                raise GraphSyncError("Each delta page needs exactly one nextLink or final deltaLink.")
            if delta_url:
                _graph_url(delta_url, expected)
                return {"items": list(items.values()), "delta_link": delta_url, "full_resync": full_resync}
            url = next_url

    def permissions(self, item_id):
        _scan_approved(self.config)
        url = self._item_url(item_id, "/permissions")
        path = _url_parts(url).path
        seen, result, total = set(), [], 0
        while url:
            _graph_url(url, path)
            if url in seen or len(seen) >= self.config["max_pages"]:
                raise GraphSyncError("Permission pagination cycle or page budget exhausted.")
            seen.add(url)
            page, size = self._read_json(url)
            total += size
            if not isinstance(page.get("value"), list) or "@odata.deltaLink" in page:
                raise GraphSyncError("Malformed Graph permissions page.")
            result.extend(page["value"])
            if total > self.config["max_round_bytes"] or len(result) > self.config["max_items"]:
                raise GraphSyncError("Permission enumeration exceeded its bounded budget.")
            url = page.get("@odata.nextLink")
            if "@odata.nextLink" in page and (not isinstance(url, str) or not url):
                raise GraphSyncError("Malformed permission continuation URL.")
        project_permissions(self.config, result)
        return result

    def metadata(self, item_id):
        url = self._item_url(item_id)
        page, _ = self._read_json(url)
        item = compact_item(page, self.config["drive_id"])
        if (item["id"] != item_id or "file" not in item or "deleted" in item
                or set(item) & {"folder", "remoteItem", "package", "malware"} or not item.get("eTag")):
            raise IncompleteInventory("A required source binding is not a live, versioned file.")
        return item

    def content(self, item_id, etag):
        url = self._item_url(item_id, "/content")
        if not isinstance(etag, str) or not etag:
            raise GraphSyncError("A pinned source ETag is required before downloading.")
        if self.metadata(item_id)["eTag"] != etag:
            raise GraphSyncError("Source changed before the bounded download; retry reconciliation.")
        if self.binary_transport is None:
            if not hasattr(self.transport, "token"):
                raise GraphSyncError("A bounded binary transport or explicit credential provider is required.")
            self.binary_transport = BinaryGraphTransport(self.config, self.transport)
        try:
            status, headers, raw = self.binary_transport.request_bytes(
                "GET", url, audience=GRAPH, headers={"If-Match": etag},
                max_bytes=self.config["max_content_bytes"])
            if status == 302:
                location = _download_url(_header(headers, "Location"), self.config["download_hosts"])
                status, _, raw = self.binary_transport.request_bytes(
                    "GET", location, audience=None, headers={}, max_bytes=self.config["max_content_bytes"])
            if status != 200 or not isinstance(raw, bytes) or len(raw) > self.config["max_content_bytes"]:
                raise GraphSyncError("Content read failed or exceeded its bounded byte budget.")
        except GraphSyncError:
            raise
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            raise GraphSyncError("Source download failed; signed URLs and transport details suppressed.") from None
        if self.metadata(item_id)["eTag"] != etag:
            raise GraphSyncError("Source changed during download; do not publish this candidate.")
        return raw

    def inspect_selected(self, inventory):
        _validate_inventory(inventory)
        if any(identity not in inventory or "deleted" in inventory[identity] for identity in self.selected):
            raise IncompleteInventory("Both required source partitions must be present; partial totals are forbidden.")
        result = {}
        for binding in self.config["bindings"]:
            identity = binding["item_id"]
            metadata = self.metadata(identity)
            previous = compact_item(inventory[identity], self.config["drive_id"])
            pinned_fields = ("id", "name", "eTag", "cTag")
            old_parent, new_parent = previous.get("parentReference", {}), metadata.get("parentReference", {})
            if (any(previous[key] != metadata.get(key) for key in pinned_fields if key in previous)
                    or any(value != new_parent.get(key) for key, value in old_parent.items())):
                raise GraphSyncError("Selected source metadata changed after delta; reconcile again.")
            permissions = self.permissions(identity)
            policy = project_permissions(self.config, permissions)
            raw = self.content(identity, metadata["eTag"])
            final_permissions = self.permissions(identity)
            if permission_fingerprint(final_permissions) != policy["permission_sha256"]:
                raise GraphSyncError("Source permissions changed during download; serving remains closed.")
            result[binding["partition"]] = {
                "raw": raw, "item": metadata, "permissions": final_permissions,
                "permission_sha256": policy["permission_sha256"], "policy": policy}
        return result
