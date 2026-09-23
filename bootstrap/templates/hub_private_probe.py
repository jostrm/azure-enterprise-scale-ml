"""Bounded, stdlib-only probe executed by ARM RunCommand on a reviewed runner VM.

The controller supplies the request as base64 argv[1], never accepts a caller's
probe result, and obtains stdout only from the exact authenticated ARM operation.
No CLI login, shared keys, SAS, DNS override, or public-address fallback is used.
"""

import base64
import copy
import hashlib
from http.client import HTTPSConnection
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time
from email.utils import formatdate
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4
from xml.etree import ElementTree


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def account_snapshot(value):
    result = copy.deepcopy(value)
    result.pop("etag", None)
    return result


class PrivateHTTPSConnection(HTTPSConnection):
    """Connect to the reviewed NIC IP; keep canonical-host SNI/certificate checks."""

    def __init__(self, host, private_ip):
        super().__init__(host, 443, timeout=45, context=ssl.create_default_context())
        self.private_ip = private_ip

    def connect(self):
        raw = socket.create_connection((self.private_ip, 443), timeout=self.timeout)
        try:
            check(raw.getpeername()[0] == self.private_ip, "unexpected-storage-peer-address")
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class Runner:
    def __init__(self, request):
        self.request = request
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.tokens = {}

    def authorize(self):
        now = time.time()
        check(self.request["issued_at"] <= now + 30 and now < self.request["expires_at"], "probe-request-expired")

    def token(self, resource):
        if resource not in self.tokens:
            query = {"api-version": "2018-02-01", "resource": resource}
            if self.request.get("client_id"):
                query["client_id"] = self.request["client_id"]
            url = "http://169.254.169.254/metadata/identity/oauth2/token?" + urlencode(query)
            # IMDS must never traverse a configured HTTP proxy.
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(Request(url, headers={"Metadata": "true"}), timeout=15) as response:
                token = json.loads(response.read(65536))["access_token"]
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            check(claims["tid"].lower() == self.request["tenant_id"]
                  and claims["oid"].lower() == self.request["principal_id"]
                  and claims["exp"] > time.time() + 60, "managed-identity-mismatch")
            allowed = {resource.rstrip("/")}
            if resource == "https://management.azure.com/":
                allowed |= {"https://management.core.windows.net", "797f4846-ba00-4fd7-ba43-dac1f8f63013"}
            check(claims["aud"].rstrip("/") in allowed, "managed-identity-audience-mismatch")
            self.tokens[resource] = token
        return self.tokens[resource]

    def http(self, method, url, resource, data=None, headers=None, allowed=(200,)):
        if method not in ("GET", "HEAD"):
            self.authorize()
        outgoing = dict(headers or {})
        outgoing["Authorization"] = "Bearer " + self.token(resource)
        if resource == "https://storage.azure.com/":
            outgoing.update({"x-ms-version": "2023-11-03", "x-ms-date": formatdate(usegmt=True)})
        if data is not None and not isinstance(data, bytes):
            data = canonical(data)
            outgoing["Content-Type"] = "application/json"
        connection = None
        try:
            if method not in ("GET", "HEAD"):
                self.authorize()
            if resource == "https://storage.azure.com/":
                parsed = urlsplit(url)
                host = self.request["account_url"].removeprefix("https://")
                check(parsed.scheme == "https" and parsed.hostname == host and parsed.port in (None, 443)
                      and not parsed.username and not parsed.password and not parsed.fragment,
                      "unreviewed-storage-endpoint")
                connection = PrivateHTTPSConnection(host, self.request["private_ip"])
                target = parsed.path + ("?" + parsed.query if parsed.query else "")
                connection.request(method, target, body=data, headers=outgoing)
                response = connection.getresponse()
            else:
                try:
                    response = self.opener.open(Request(url, method=method, data=data, headers=outgoing), timeout=45)
                except HTTPError as exc:
                    response = exc
            with response:
                check(response.status in allowed, "request-status-" + str(response.status))
                raw = response.read(1024 * 1024 + 1)
                check(len(raw) <= 1024 * 1024, "response-too-large")
                headers = {k.lower(): v for k, v in response.headers.items()}
        finally:
            if connection:
                connection.close()
        return headers, json.loads(raw) if raw and raw.lstrip()[:1] in (b"{", b"[") else raw

    def blob(self, method, name, data=None, headers=None, query="", allowed=(200,)):
        return self.http(method, self.request["account_url"] + "/hub-locks/" + quote(name, safe="/") + query,
                         "https://storage.azure.com/", data, headers, allowed)

    def arm(self, method, identifier, data=None, headers=None, allowed=(200,)):
        return self.http(method, "https://management.azure.com" + identifier + "?api-version=2023-05-01",
                         "https://management.azure.com/", data, headers, allowed)

    def runner_identity(self):
        r = self.request
        path = Path(r["runner_config_path"])
        check(path.is_absolute() and not path.is_symlink() and path.stat().st_size < 65536,
              "runner-registration-file-invalid")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        check(str(value.get("agentId")) == str(r["runner_id"])
              and value.get("agentName") == r["runner_name"], "runner-registration-mismatch")
        if r["provider"] == "gha":
            check(value.get("gitHubUrl", "").lower().rstrip("/") == r["repository"].lower().rstrip("/"),
                  "runner-repository-mismatch")
            check(os.name != "nt", "github-linux-runner-required")
        else:
            check(str(value.get("poolId")) == str(r["pool_id"])
                  and value.get("serverUrl", "").lower().rstrip("/") == r["organization_url"].lower().rstrip("/"),
                  "runner-pool-or-organization-mismatch")

    def probe(self):
        r = self.request
        host = r["account_url"].removeprefix("https://")
        addresses = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        check(addresses == {r["private_ip"]} and ipaddress.ip_address(r["private_ip"]).is_private,
              "canonical-storage-dns-not-exact-private-endpoint")
        name = "private-transition/probes/" + r["nonce"] + ".json"
        value = {"nonce": r["nonce"], "writer_id": r["writer_id"], "at": time.time()}
        headers, _ = self.blob("PUT", name, value, {"If-None-Match": "*", "x-ms-blob-type": "BlockBlob"},
                               allowed=(201,))
        lease = str(uuid4())
        self.blob("PUT", name, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "60",
                  "x-ms-proposed-lease-id": lease}, query="?comp=lease", allowed=(201,))
        try:
            self.blob("PUT", name, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease},
                      query="?comp=lease")
            value["leased_write"] = True
            self.blob("PUT", name, value, {"x-ms-lease-id": lease, "If-Match": headers["etag"],
                      "x-ms-blob-type": "BlockBlob"}, allowed=(201,))
            _, actual = self.blob("GET", name)
            check(actual == value, "private-blob-roundtrip-failed")
        finally:
            self.blob("PUT", name, headers={"x-ms-lease-action": "release", "x-ms-lease-id": lease},
                      query="?comp=lease")
        return sorted(addresses)

    def close(self):
        r = self.request
        self.authorize()
        self.ensure_lease(r["lock_blob"], r["lease_id"])
        for name, lease in r.get("registry_leases", {}).items():
            self.ensure_lease(name, lease)
        for blob, expected in r["registry_hashes"].items():
            _, value = self.blob("GET", blob)
            check(digest(value) == expected, "writer-inventory-changed")
        for proof in r["writer_proofs"]:
            _, value = self.blob("GET", proof["blob"])
            check(digest(value) == proof["hash"] and value["expires_at"] > time.time(),
                  "writer-private-proof-stale")
        _, account = self.arm("GET", r["account_id"])
        current = {k: account["properties"].get(k) for k in ("networkAcls", "publicNetworkAccess")}
        closed_snapshot = copy.deepcopy(r["expected_account_snapshot"])
        closed_snapshot["properties"].update(r["desired_network"])
        if current != r["desired_network"]:
            check(account_snapshot(account) == r["expected_account_snapshot"] and current == r["expected_network"],
                  "account-network-changed")
            self.blob("PUT", r["remote_receipt"], {"status": "closing", "plan_hash": r["plan_hash"],
                      "nonce": r["nonce"]}, {"x-ms-blob-type": "BlockBlob"}, allowed=(201,))
            # Storage Accounts PATCH has no supported If-Match contract. All
            # participating writers hold the hub lease; recheck the frozen
            # resource immediately before the narrow network-only PATCH.
            _, account = self.arm("GET", r["account_id"])
            check(account_snapshot(account) == r["expected_account_snapshot"], "account-snapshot-changed")
            self.authorize()
            self.arm("PATCH", r["account_id"], {"properties": r["desired_network"]}, allowed=(200, 202))
            for _ in range(60):
                _, account = self.arm("GET", r["account_id"])
                if account["properties"].get("provisioningState") == "Succeeded":
                    break
                time.sleep(2)
        check(account_snapshot(account) == closed_snapshot, "network-close-unverified")
        # A fresh blob name ensures success cannot be replayed from the preflight.
        r["nonce"] = r["nonce"] + "-final"
        addresses = self.probe()
        r["nonce"] = r["nonce"].removesuffix("-final")
        self.blob("PUT", r["remote_receipt"], {"status": "closed-private-verified",
                  "plan_hash": r["plan_hash"], "nonce": r["nonce"], "at": time.time()},
                  {"x-ms-blob-type": "BlockBlob"}, allowed=(201,))
        for name, lease in r.get("registry_leases", {}).items():
            self.blob("PUT", name, headers={"x-ms-lease-action": "release", "x-ms-lease-id": lease},
                      query="?comp=lease")
        self.blob("PUT", r["lock_blob"], headers={"x-ms-lease-action": "release", "x-ms-lease-id": r["lease_id"]},
                  query="?comp=lease")
        return addresses

    def ensure_lease(self, name, lease):
        _, body = self.blob("PUT", name, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease},
                            query="?comp=lease", allowed=(200, 409, 412))
        if body:
            check(isinstance(body, bytes) and len(body) < 65536, "lease-state-unknown")
            code = ElementTree.fromstring(body).findtext("Code")
            check(code == "LeaseNotPresentWithLeaseOperation", "another-writer-holds-lease")
            self.blob("PUT", name, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                      "x-ms-proposed-lease-id": lease}, query="?comp=lease", allowed=(201,))

    def run(self):
        r = self.request
        self.authorize()
        self.runner_identity()
        addresses = self.probe()
        if r["phase"] == "close":
            addresses = self.close()
        elif r["phase"] == "verify-closed":
            _, account = self.arm("GET", r["account_id"])
            expected = copy.deepcopy(r["expected_account_snapshot"])
            expected["properties"].update(r["desired_network"])
            check(account_snapshot(account) == expected,
                  "closed-network-no-longer-matches")
        result = {k: r[k] for k in ("nonce", "plan_hash", "writer_id", "tenant_id", "principal_id",
                                   "source_commit", "source_sha256", "operation_id", "phase")}
        result.update(at=time.time(), addresses=addresses, success=True,
                      runner_id=r["runner_id"], repository=r["repository"])
        if r["phase"] == "probe":
            self.blob("PUT", "private-transition/attestations/" + r["nonce"] + ".json",
                      {"attestation": result, "expires_at": r["expires_at"]},
                      {"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))
        return result


if __name__ == "__main__":
    try:
        request = json.loads(base64.b64decode(sys.argv[1], validate=True))
        result = Runner(request).run()
        print("AFHUB_ATTESTATION:" + json.dumps(result, separators=(",", ":")))
    except Exception as error:
        print("AFHUB_PROBE_FAILED:" + type(error).__name__, file=sys.stderr)
        sys.exit(1)
