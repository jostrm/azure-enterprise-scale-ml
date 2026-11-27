"""Private provider-repository state; immutable Git objects and a CAS state ref.

No checkout, local file, storage account, credential, or deployment payload is
stored here. Repository administrators remain trusted: deleting/rewinding the
ref or changing code can defeat these guards. This is not cross-repository
exclusion and is not a replacement for exclusive shared-hub governance.
"""

import base64
import copy
import hashlib
import json
import re
from urllib.parse import quote, unquote, urlsplit


STATE_REF = "refs/heads/aifactory-state/single-writer-v1"
PROVIDER = "provider-repository-cas"
MODE = "single-writer"
PROTOCOL = "aifactory-single-writer-v1"
WARNING = "Bypassing lock, due to issues, dont do parallell updates on same AI Factory"
HUB_WARNING = "Do not make concurrent changes to a shared hub, including from other repositories; repository claims do not provide global exclusion."
# aif-134 (2026-10-27): bootstrap_final_closure alone made state.json 6.4 MB; PROJECT closures add more.
MAX_BYTES = 32 * 1024 * 1024
# Doubled 2026-10-27 (pinned in test_time_budgets.py): restarts of a moving-ref snapshot read.
STATE_READ_ATTEMPTS = 6


def same_repository(agent_uri, bound_repository):
    """Compare a provider-reported repository URI with the bound one.

    ADO agents report BUILD_REPOSITORY_URI as https://<org>@dev.azure.com/...; the
    user-info is routing only. Scheme, host and path must still match exactly.
    """
    def normal(value):
        parts = urlsplit(value or "")
        return (parts.scheme.lower(), (parts.hostname or "").lower(), parts.port,
                parts.path.rstrip("/").lower())
    actual, expected = normal(agent_uri), normal(bound_repository)
    return actual[0] == "https" and bool(actual[1]) and actual == expected


def ado_job_name(row):
    """The YAML job name of an ADO timeline Job record.

    Live timelines identify jobs as <Stage>.<Job>.<Instance> (the instance is the
    deployment name or '__default'); the bare form is accepted for older readers.
    """
    identifier = row.get("identifier") if isinstance(row, dict) else None
    if not isinstance(identifier, str) or not identifier:
        return None
    parts = identifier.split(".")
    return parts[1] if len(parts) == 3 and all(parts) else (identifier if len(parts) == 1 else None)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def git_blob_id(raw):
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def coordinates(repository):
    return {"provider": PROVIDER, "coordination_mode": MODE,
            "repository": repository, "state_ref": STATE_REF}


class ProviderState:
    def __init__(self, cloud, route, error):
        self.cloud, self.route, self.error = cloud, route, error
        self.write_failed = False
        if route["kind"] == "gha":
            self.base = "repos/" + urlsplit(route["repository"]).path.strip("/").removesuffix(".git")
        else:
            organization, project, _, repository = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
            self.base = ("https://dev.azure.com/" + quote(organization, safe="") + "/" + quote(project, safe="")
                         + "/_apis/git/repositories/" + quote(repository, safe=""))

    def require(self, condition, code):
        if not condition:
            raise self.error(code)

    def request(self, method, suffix="", body=None, allowed=(200,)):
        path = self.base + suffix
        if self.route["kind"] == "ado":
            path += ("&" if "?" in path else "?") + "api-version=7.1"
        return self.cloud.state_request(self.route["kind"], method, path, body, allowed)

    def private(self):
        _, _, body = self.request("GET")
        if self.route["kind"] == "gha":
            self.require(body.get("private") is True and
                         body.get("full_name", "").lower() == self.base.removeprefix("repos/").lower(),
                         "single-writer-private-repository-required")
        else:
            self.require(body.get("project", {}).get("visibility") == "private"
                         and same_repository(str(body.get("remoteUrl", "")), self.route["repository"]),
                         "single-writer-private-repository-required")

    def head(self):
        if self.route["kind"] == "gha":
            status, _, body = self.request("GET", "/git/ref/" + STATE_REF.removeprefix("refs/"), allowed=(200, 404))
            if status == 404:
                return None
            self.require(body.get("ref") == STATE_REF and body.get("object", {}).get("type") == "commit",
                         "single-writer-state-ref-invalid")
            result = body["object"].get("sha")
        else:
            _, headers, body = self.request("GET", "/refs?filter=" + quote(STATE_REF.removeprefix("refs/"), safe=""))
            self.require(not any(k.lower() == "x-ms-continuationtoken" for k in headers)
                         and isinstance(body.get("value"), list), "single-writer-state-ref-incomplete")
            rows = [row for row in body["value"] if row.get("name") == STATE_REF]
            self.require(len(rows) <= 1, "single-writer-state-ref-ambiguous")
            if not rows:
                return None
            result = rows[0].get("objectId")
        self.require(isinstance(result, str) and re.fullmatch(r"[a-f0-9]{40}", result),
                     "single-writer-state-ref-invalid")
        return result

    def read(self):
        """Restart only a moving-ref snapshot; never retry a write or a failed guard."""
        for _ in range(STATE_READ_ATTEMPTS):
            snapshot = self._read_snapshot()
            if snapshot is not None:
                return snapshot
        raise self.error("single-writer-state-changed")

    def _read_snapshot(self):
        self.private()
        head = self.head()
        if head is None:
            return None, None
        if self.route["kind"] == "gha":
            _, _, commit = self.request("GET", "/git/commits/" + head)
            _, _, tree = self.request("GET", "/git/trees/" + commit["tree"]["sha"])
            rows = tree.get("tree", [])
            self.require(not tree.get("truncated") and len(rows) == 1 and rows[0].get("path") == "state.json"
                         and rows[0].get("type") == "blob", "single-writer-state-tree-invalid")
            _, _, blob = self.request("GET", "/git/blobs/" + rows[0]["sha"])
            self.require(blob.get("encoding") == "base64", "single-writer-state-encoding-invalid")
            try:
                raw = base64.b64decode("".join(blob["content"].split()), validate=True)
            except (ValueError, KeyError, TypeError):
                raise self.error("single-writer-state-encoding-invalid") from None
        else:
            # Azure DevOps stops inline item content at 5 MiB and answers 206 Partial Content (aif-172 run 2545,
            # 2026-11-27: an 8.6 MB state.json after project001 Prepare). Name the blob, then read it raw.
            _, _, item = self.request("GET", "/items?path=/state.json"
                                     "&versionDescriptor.versionType=commit&versionDescriptor.version=" + head)
            blob = item.get("objectId") if isinstance(item, dict) else None
            self.require(isinstance(item, dict) and item.get("gitObjectType") == "blob" and item.get("commitId") == head
                         and isinstance(blob, str) and re.fullmatch(r"[a-f0-9]{40}", blob),
                         "single-writer-state-tree-invalid")
            _, _, stored = self.request("GET", "/blobs/" + blob + "?%24format=octetStream")
            # Hard gate, essential: the provider transports parse the octet stream as JSON without the duplicate-key
            # hook below, so the git object id is the only proof that the parsed state is byte for byte the stored
            # blob (no duplicate key, nothing cut short). The product writes canonical(value), so the round trip
            # is exact.
            raw = canonical(stored) if isinstance(stored, dict) else b""
            self.require(git_blob_id(raw) == blob, "single-writer-state-json-invalid")
        self.require(len(raw) <= MAX_BYTES, "single-writer-state-too-large")
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    self.require(key not in result, "single-writer-state-duplicate-key")
                    result[key] = value
                return result
            value = json.loads(raw, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise self.error("single-writer-state-json-invalid") from None
        self.require(isinstance(value, dict) and set(value) == {"schema", "repository", "enrollment", "active", "records"}
                     and value["schema"] == 1 and value["repository"] == self.route["repository"]
                     and isinstance(value["records"], dict), "single-writer-state-invalid")
        if self.head() != head:
            return None
        return head, value

    def empty(self):
        return {"schema": 1, "repository": self.route["repository"], "enrollment": None,
                "active": None, "records": {}}

    def replace(self, expected, value):
        """One attempt only. Lost response/CAS conflict requires reconciliation."""
        self.require(not self.write_failed, "single-writer-write-reconciliation-required")
        self.write_failed = True
        result = self._replace(expected, value)
        self.write_failed = False
        return result

    def _replace(self, expected, value):
        raw = canonical(value)
        self.require(len(raw) <= MAX_BYTES, "single-writer-state-too-large")
        self.private()
        self.require(self.head() == expected, "single-writer-state-cas-conflict")
        if self.route["kind"] == "gha":
            _, _, blob = self.request("POST", "/git/blobs",
                                     {"encoding": "base64", "content": base64.b64encode(raw).decode()}, (201,))
            _, _, tree = self.request("POST", "/git/trees", {"tree": [
                {"path": "state.json", "mode": "100644", "type": "blob", "sha": blob["sha"]}]}, (201,))
            _, _, commit = self.request("POST", "/git/commits", {
                "message": "AI Factory operational state", "tree": tree["sha"],
                "parents": [expected] if expected else []}, (201,))
            head = commit["sha"]
            if expected is None:
                self.request("POST", "/git/refs", {"ref": STATE_REF, "sha": head}, (201,))
            else:
                # A sibling commit has the same parent, so force:false rejects it
                # as non-fast-forward; never retry against a freshly observed ref.
                self.request("PATCH", "/git/refs/" + STATE_REF.removeprefix("refs/"),
                             {"sha": head, "force": False})
        else:
            _, _, pushed = self.request("POST", "/pushes", {
                "refUpdates": [{"name": STATE_REF, "oldObjectId": expected or "0" * 40}],
                "commits": [{"comment": "AI Factory operational state", "changes": [{
                    "changeType": "edit" if expected else "add", "item": {"path": "/state.json"},
                    "newContent": {"content": raw.decode("utf-8"), "contentType": "rawtext"}}]}]}, (201,))
            updates = pushed.get("refUpdates", [])
            self.require(len(updates) == 1 and updates[0].get("name") == STATE_REF,
                         "single-writer-state-write-unverified")
            head = updates[0].get("newObjectId")
        actual, stored = self.read()
        self.require(actual == head and stored == value, "single-writer-state-write-unverified")
        return actual

    def update(self, expected, value, **fields):
        updated = copy.deepcopy(value)
        updated.update(fields)
        return self.replace(expected, updated), updated
