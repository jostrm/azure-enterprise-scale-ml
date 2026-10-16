"""Plan-first Graph security subscriptions and a stdlib-only ASGI callback.

The store is the durability boundary, not an in-memory work queue:

* ``signal_many([(scope_id, reason), ...])`` must atomically dirty each scope,
  invalidate serving proofs, and enqueue work before returning.
* ``signal_notifications(records)`` rechecks subscription activity and secret
  binding in the same transaction as dirtying, so recreation cannot race an old event.
* ``mark_subscription_attempt(scope_id, operation)`` must durably reject an
  unresolved earlier create/recreate attempt, including after process restart.
  Only explicit operator reconciliation may clear an uncertain attempt.
* ``register_subscription(id, scope, tenant, resource, client_state, expires)``
  stores ONLY SHA-256 of client_state, persists the actual expiry for the serving
  gate, and completes the creation journal. Registration is reserved for this
  manager's acknowledged security-webhook creates, so the local record itself
  represents that intent; no extra schema field is required. This API must not be
  used to import/adopt existing content-only subscriptions.
* ``subscription(id)`` returns that record or None;
  ``update_subscription_expiry(id, expires)`` updates expiry without changing the
  secret hash or locally registered security intent.

Expired, reauthorization-required, and unsupported lifecycle signals must block
serving until renewal/recreation and reconciliation, not merely a delta poll.
``missed`` and ``subscriptionRemoved`` are NOT documented driveItem lifecycle
guarantees; their defensive handling is no substitute for polling and expiry gates.
No callback invokes Graph, Storage, Search, or a model. Hosting/TLS is external.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID


GRAPH = "https://graph.microsoft.com"
MAX_LIFETIME_MINUTES = 42300
DEFAULT_LIFETIME_MINUTES = 1440
RENEWAL_WINDOW_SECONDS = 7200
_SEGMENT = re.compile(r"[A-Za-z0-9!_~.-]{1,256}\Z")
_ROOT_RESOURCE = re.compile(r"/?drives/([A-Za-z0-9!_~.-]{1,256})/root\Z", re.IGNORECASE)
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class SubscriptionOperationError(RuntimeError):
    """A sanitized, fail-closed lifecycle failure."""


class SubscriptionRecreationRequired(SubscriptionOperationError):
    """A renewal returned 404; explicit manual recreation is required."""


def generate_client_state() -> str:
    """Return a fresh 256-bit secret; the caller controls its secret storage."""
    return secrets.token_urlsafe(32)


def _client_state(value):
    if (not isinstance(value, str) or not 32 <= len(value) <= 128
            or any(not 33 <= ord(character) <= 126 for character in value)):
        raise ValueError("Supply a cryptographically random 32–128 character clientState.")
    return value


def client_state_from_env(variable: str) -> str:
    """Read only the caller-selected variable; never include its value in errors."""
    if not isinstance(variable, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
        raise ValueError("An explicit clientState environment-variable name is required.")
    return _client_state(os.environ.get(variable))


def _segment(value):
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError("An exact literal Graph identifier is required.")
    return value


def _callback_url(value):
    try:
        parsed = urlsplit(value)
        valid = (isinstance(value, str) and parsed.scheme == "https" and parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.query
                 and not parsed.fragment and parsed.port in {None, 443}
                 and not any(character.isspace() or ord(character) < 32 for character in value)
                 and "\\" not in value)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Use an explicit HTTPS callback without credentials, query, or fragment.")
    return value


def _config(config):
    if not isinstance(config, dict):
        raise ValueError("An explicit subscription configuration is required.")
    try:
        result = {key: config[key] for key in (
            "scope_id", "tenant_id", "drive_id", "drive_type", "notification_url")}
        if not isinstance(result["scope_id"], str) or not result["scope_id"]:
            raise ValueError
        result["tenant_id"] = str(UUID(result["tenant_id"]))
        _segment(result["drive_id"])
        if result["drive_type"] not in {"business", "documentLibrary"}:
            raise ValueError
        _callback_url(result["notification_url"])
        if config.get("lifecycle_notification_url"):
            result["lifecycle_notification_url"] = _callback_url(config["lifecycle_notification_url"])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("Select one explicit business or documentLibrary drive and HTTPS callback.") from None
    return result


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("An explicit timezone-aware expiration is required.") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit timezone-aware expiration is required.")
    return value.astimezone(timezone.utc)


def _expiration(now, expiration=None):
    now = _aware(now)
    expiration = _aware(expiration) if expiration is not None else (
        now + timedelta(minutes=DEFAULT_LIFETIME_MINUTES))
    if not timedelta(0) < expiration - now <= timedelta(minutes=MAX_LIFETIME_MINUTES):
        raise ValueError("Subscription expiry must be future and at most 42300 minutes away.")
    return expiration


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _resource(config):
    return f"/drives/{config['drive_id']}/root"


def _canonical_resource(value):
    match = _ROOT_RESOURCE.fullmatch(value) if isinstance(value, str) else None
    if not match or match[1] in {".", ".."}:
        raise ValueError("Expected one literal drive root resource.")
    return f"/drives/{match[1]}/root"


def _request(config, now, expiration=None):
    body = {
        "changeType": "updated", "notificationUrl": config["notification_url"],
        "lifecycleNotificationUrl": config.get("lifecycle_notification_url", config["notification_url"]),
        "resource": _resource(config),
        "latestSupportedTlsVersion": "v1_2",
        "expirationDateTime": _iso(_expiration(now, expiration)),
    }
    return {
        "method": "POST", "url": GRAPH + "/v1.0/subscriptions",
        "headers": {"Prefer": "includesecuritywebhooks"}, "body": body,
    }


def build_subscription(config: dict, client_state: str, *, now=None, expiration=None) -> dict:
    """Build the actual request. This secret-bearing object is for the caller only.

    Use ``SubscriptionManager.plan`` for display/persistence, never serialize this
    request into a general configuration/state dump. Nothing is executed here.
    """
    request = _request(_config(config), now if now is not None else datetime.now(timezone.utc), expiration)
    request["body"]["clientState"] = _client_state(client_state)
    return request


class SubscriptionManager:
    """AzureSession-compatible transport; construction and default calls are offline."""

    def __init__(self, config, transport, store, *, clock=time.time):
        self.config = _config(config)
        self.transport, self.store, self.clock = transport, store, clock

    def _now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    def _preflight(self):
        return {
            "method": "GET",
            "url": GRAPH + f"/v1.0/drives/{self.config['drive_id']}?$select=id,driveType",
        }

    def plan(self, *, expiration=None):
        request = _request(self.config, self._now(), expiration)
        request["body"]["clientState"] = "<redacted>"
        return dict(request, preflight=self._preflight(), apply_required=True,
                    security_webhooks=True, scope_id=self.config["scope_id"])

    def _signal(self, reason):
        self.store.signal_many([(self.config["scope_id"], reason)])

    def _send(self, request):
        return self.transport.request(
            request["method"], request["url"], body=request.get("body"),
            audience=GRAPH, headers=request.get("headers", {}),
        )

    def _response(self, response, *, expected_id=None, client_state=None):
        if not isinstance(response, dict):
            raise ValueError("Invalid subscription acknowledgement.")
        subscription_id = _segment(response.get("id"))
        if (expected_id is not None and subscription_id != expected_id
                or _canonical_resource(response.get("resource")) != _resource(self.config)
                or response.get("changeType") != "updated"
                or response.get("notificationUrl") != self.config["notification_url"]):
            raise ValueError("Subscription acknowledgement does not match the request.")
        if ("lifecycleNotificationUrl" in response and response["lifecycleNotificationUrl"]
                != self.config.get("lifecycle_notification_url", self.config["notification_url"])):
            raise ValueError("Subscription acknowledgement does not match the request.")
        if (client_state is not None and "clientState" in response
                and (not isinstance(response["clientState"], str)
                     or not hmac.compare_digest(response["clientState"].encode(), client_state.encode()))):
            raise ValueError("Subscription acknowledgement does not match the request.")
        if not isinstance(response.get("expirationDateTime"), str):
            raise ValueError("Missing acknowledged subscription expiry.")
        expires = _expiration(self._now(), response["expirationDateTime"])
        safe = {key: response[key] for key in (
            "id", "resource", "changeType", "notificationUrl")}
        safe["resource"] = _resource(self.config)
        safe.update(expirationDateTime=_iso(expires), security_webhooks=True,
                    scope_id=self.config["scope_id"])
        return safe, expires.timestamp()

    def create(self, client_state=None, *, apply=False, expiration=None):
        if apply is not True:
            return self.plan(expiration=expiration)
        return self._create(client_state, expiration=expiration, operation="create")

    def _create(self, client_state, *, expiration, operation, previous_id=None):
        request = build_subscription(self.config, client_state, now=self._now(), expiration=expiration)
        try:
            if not callable(getattr(self.store, "mark_subscription_attempt", None)):
                raise ValueError("A durable subscription creation journal is required.")
            self._signal("subscription-creation")
            metadata = self._send(self._preflight())
            if (not isinstance(metadata, dict) or metadata.get("id") != self.config["drive_id"]
                    or metadata.get("driveType") != self.config["drive_type"]):
                raise ValueError("Drive identity/type verification failed.")
            if self.store.mark_subscription_attempt(self.config["scope_id"], operation) is False:
                raise ValueError("An earlier subscription creation attempt is unresolved.")
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, sqlite3.Error):
            raise SubscriptionOperationError(
                "Subscription creation preconditions failed; no new create request was sent. "
                "Reconcile any pending attempt."
            ) from None
        try:
            response, expires_at = self._response(self._send(request), client_state=client_state)
            if response["id"] == previous_id:
                raise ValueError("Recreation did not return a new subscription.")
            self.store.register_subscription(
                response["id"], self.config["scope_id"], self.config["tenant_id"],
                response["resource"], client_state, expires_at,
            )
            return response
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, sqlite3.Error):
            # A timeout, malformed acknowledgement, or failed local commit may
            # follow a successful POST. Keep the journal and never retry blindly.
            raise SubscriptionOperationError(
                "Subscription creation outcome is uncertain; reconcile the durable attempt before retrying."
            ) from None

    def _registered(self, subscription_id):
        try:
            _segment(subscription_id)
            record = self.store.subscription(subscription_id)
            if (not isinstance(record, dict) or record.get("scope_id") != self.config["scope_id"]
                    or record.get("tenant_id") != self.config["tenant_id"]
                    or record.get("resource") != _resource(self.config)
                    or record.get("active", 1) != 1
                    or record.get("security_webhooks", True) is not True
                    or not isinstance(record.get("client_state_sha256"), str)
                    or not _HASH.fullmatch(record["client_state_sha256"])
                    or isinstance(record.get("expires_at"), bool)
                    or not math.isfinite(float(record["expires_at"]))):
                raise ValueError
            return record
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, sqlite3.Error):
            raise SubscriptionOperationError(
                "Only a locally registered security subscription in this exact scope can be managed."
            ) from None

    def renew(self, subscription_id, *, apply=False, expiration=None, force=False):
        record = self._registered(subscription_id)
        expires = _expiration(self._now(), expiration)
        due = float(record["expires_at"]) - self.clock() <= RENEWAL_WINDOW_SECONDS
        request = {
            "method": "PATCH", "url": GRAPH + f"/v1.0/subscriptions/{subscription_id}",
            "headers": {}, "body": {"expirationDateTime": _iso(expires)},
        }
        if apply is not True or not (due or force is True):
            return dict(request, apply_required=True, renewal_due=due,
                        security_webhooks=True, scope_id=self.config["scope_id"])
        try:
            if not callable(getattr(self.store, "update_subscription_expiry", None)):
                raise ValueError("Durable renewal recording is required.")
            self._signal("subscription-renewal")
            response = self._send(request)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, sqlite3.Error) as error:
            if getattr(error, "status", getattr(error, "code", getattr(error, "status_code", None))) == 404:
                try:
                    self._signal("subscription-recreation-required")
                except (ValueError, TypeError, KeyError, OSError, RuntimeError, sqlite3.Error):
                    raise SubscriptionOperationError("Unable to persist subscription recreation requirement.") from None
                raise SubscriptionRecreationRequired(
                    "Subscription no longer exists; explicitly recreate with a new secret and security preference."
                ) from None
            raise SubscriptionOperationError("Subscription renewal failed; local state remains fail-closed.") from None
        try:
            safe, expires_at = self._response(response, expected_id=subscription_id)
            self.store.update_subscription_expiry(subscription_id, expires_at)
            return safe
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, sqlite3.Error):
            raise SubscriptionOperationError("Subscription renewal was not safely recorded; serving remains blocked.") from None

    def recreate(self, subscription_id, client_state=None, *, apply=False, expiration=None):
        record = self._registered(subscription_id)
        if apply is not True:
            return dict(self.plan(expiration=expiration), replaces_subscription_id=subscription_id,
                        automatic_deletion=False)
        client_state = _client_state(client_state)
        if hmac.compare_digest(hashlib.sha256(client_state.encode()).hexdigest(),
                               record["client_state_sha256"]):
            raise ValueError("Explicit recreation requires a new cryptographically random clientState.")
        return self._create(client_state, expiration=expiration, operation="recreate",
                            previous_id=subscription_id)


class _Rejected(Exception):
    def __init__(self, status):
        self.status = status


class _Disconnected(Exception):
    pass


class _StoreFailure(Exception):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-JSON constant.")


class GraphWebhookApp:
    """Mount at an existing HTTPS endpoint; acknowledgements follow durable writes.

    Validation is independent of registered IDs, so Graph can validate a URL
    before the create response is locally committed. No access token is required
    for the validation-token exchange. Normal delivery authenticates clientState.
    """

    def __init__(self, store, *, path="/notifications", clock=time.time,
                 max_body_bytes=1024 * 1024, body_timeout=2.0):
        if (not isinstance(path, str) or not path.startswith("/") or "?" in path
                or not 0 < max_body_bytes <= 1024 * 1024 or not 0 < body_timeout <= 2.5):
            raise ValueError("Use a bounded callback path, body, and receive timeout.")
        self.store, self.path, self.clock = store, path, clock
        self.max_body_bytes, self.body_timeout = max_body_bytes, body_timeout

    @staticmethod
    async def _respond(send, status, body=b""):
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"x-content-type-options", b"nosniff"),
            (b"cache-control", b"no-store"),
        ]
        if status == 405:
            headers.append((b"allow", b"POST"))
        if status == 503:
            headers.append((b"retry-after", b"5"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _validation_token(query):
        try:
            if not isinstance(query, bytes) or len(query) > 65536:
                raise ValueError
            text = query.decode("ascii")
            if re.search(r"%(?![0-9a-fA-F]{2})", text):
                raise ValueError
            pairs = parse_qsl(text, keep_blank_values=True, encoding="utf-8",
                              errors="strict", max_num_fields=100)
            tokens = [value for key, value in pairs if key == "validationToken"]
            if not tokens:
                return None
            if len(tokens) != 1 or not 0 < len(tokens[0]) <= 4096:
                raise ValueError
            return tokens[0].encode("utf-8")
        except (ValueError, UnicodeError):
            raise _Rejected(400) from None

    async def _read(self, scope, receive):
        lengths = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
        length = None
        if lengths:
            if len(lengths) != 1 or not re.fullmatch(rb"[0-9]{1,12}", lengths[0]):
                raise _Rejected(400)
            length = int(lengths[0])
            if length > self.max_body_bytes:
                raise _Rejected(413)
        content_types = [value for key, value in scope.get("headers", []) if key.lower() == b"content-type"]
        if content_types and (len(content_types) != 1 or
                              content_types[0].split(b";", 1)[0].strip().lower() != b"application/json"):
            raise _Rejected(415)
        body = bytearray()
        while True:
            event = await receive()
            if event.get("type") == "http.disconnect":
                raise _Disconnected
            if (event.get("type") != "http.request" or not isinstance(event.get("body", b""), bytes)
                    or not isinstance(event.get("more_body", False), bool)):
                raise _Rejected(400)
            chunk = event.get("body", b"")
            if len(body) + len(chunk) > self.max_body_bytes:
                raise _Rejected(413)
            body.extend(chunk)
            if not event.get("more_body", False):
                break
        if length is not None and length != len(body):
            raise _Rejected(400)
        return bytes(body)

    def _notification(self, item):
        if not isinstance(item, dict):
            raise _Rejected(400)
        subscription_id, client_state = item.get("subscriptionId"), item.get("clientState")
        if (not isinstance(subscription_id, str) or not 0 < len(subscription_id) <= 256
                or not isinstance(client_state, str) or not 0 < len(client_state) <= 128):
            raise _Rejected(401)
        try:
            record = self.store.subscription(subscription_id)
        except (OSError, RuntimeError, sqlite3.Error):
            raise _StoreFailure from None
        if record is None:
            raise _Rejected(401)
        try:
            digest = record["client_state_sha256"]
            scope_id, tenant_id = record["scope_id"], str(UUID(record["tenant_id"]))
            expected_resource = _canonical_resource(record["resource"])
            expires = float(record["expires_at"])
            if (not isinstance(digest, str) or not _HASH.fullmatch(digest)
                    or not isinstance(scope_id, str) or not scope_id or not math.isfinite(expires)
                    or isinstance(record["expires_at"], bool)):
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _StoreFailure from None
        try:
            incoming_digest = hashlib.sha256(client_state.encode("utf-8")).hexdigest()
        except UnicodeError:
            raise _Rejected(401) from None
        if not hmac.compare_digest(incoming_digest, digest) or record.get("security_webhooks", True) is not True:
            raise _Rejected(401)
        for key in ("tenantId", "organizationId"):
            if key in item:
                try:
                    matches = str(UUID(item[key])) == tenant_id
                except (ValueError, TypeError, AttributeError):
                    matches = False
                if not matches:
                    raise _Rejected(401)
        if record.get("active", 1) != 1:
            return None
        lifecycle = item.get("lifecycleEvent")
        if "lifecycleEvent" in item and (not isinstance(lifecycle, str) or not lifecycle):
            raise _Rejected(400)
        if not lifecycle or "resource" in item:
            try:
                if _canonical_resource(item.get("resource")) != expected_resource:
                    raise ValueError
            except ValueError:
                raise _Rejected(400) from None
        if (not lifecycle or "changeType" in item) and item.get("changeType") != "updated":
            raise _Rejected(400)
        def signal(priority, reason):
            return {
                "subscription_id": subscription_id, "scope_id": scope_id,
                "client_state_sha256": digest, "expires_at": expires,
                "priority": priority, "reason": reason,
            }
        if expires <= self.clock():
            return signal(4, "graph-subscription-expired")
        if lifecycle == "reauthorizationRequired":
            return signal(3, "graph-reauthorization-required")
        if lifecycle:
            reason = "graph-unsupported-lifecycle"
            if lifecycle in {"missed", "subscriptionRemoved"}:
                reason += "-" + lifecycle
            return signal(2, reason)
        return signal(1, "graph-notification")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            raise ValueError("This callback handles only ASGI HTTP requests.")
        if scope.get("path") != self.path:
            return await self._respond(send, 404)
        if scope.get("method") != "POST":
            return await self._respond(send, 405)
        try:
            token = self._validation_token(scope.get("query_string", b""))
            if token is not None:
                return await self._respond(send, 200, token)
            raw = await asyncio.wait_for(self._read(scope, receive), timeout=self.body_timeout)
            try:
                document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                      parse_constant=_invalid_constant)
            except (ValueError, UnicodeError, RecursionError):
                raise _Rejected(400) from None
            if (not isinstance(document, dict) or not isinstance(document.get("value"), list)
                    or not 1 <= len(document["value"]) <= 100):
                raise _Rejected(400)
            signals = []
            for item in document["value"]:
                validated = self._notification(item)
                if validated is None:
                    continue
                signals.append(validated)
            try:
                if signals:
                    self.store.signal_notifications(signals)
            except (OSError, RuntimeError, ValueError, sqlite3.Error):
                raise _StoreFailure from None
        except _Rejected as error:
            return await self._respond(send, error.status, b"Invalid notification.")
        except _StoreFailure:
            return await self._respond(send, 503, b"Notification temporarily unavailable.")
        except asyncio.TimeoutError:
            return await self._respond(send, 408)
        except _Disconnected:
            return
        return await self._respond(send, 202)
