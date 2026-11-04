import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from sales_demo.graph_webhooks import (
    GRAPH, MAX_LIFETIME_MINUTES, GraphWebhookApp, SubscriptionManager,
    SubscriptionOperationError, SubscriptionRecreationRequired,
    build_subscription, client_state_from_env, generate_client_state,
)


NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
SECRET = "a" * 43
CONFIG = {
    "scope_id": "tenant-drive", "tenant_id": "11111111-1111-1111-1111-111111111111",
    "drive_id": "b!business-drive", "drive_type": "business",
    "notification_url": "https://callback.example/notifications",
}


class FakeStore:
    def __init__(self):
        self.records = {}
        self.signals = []
        self.attempts = {}
        self.queue_error = None

    def subscription(self, subscription_id):
        return deepcopy(self.records.get(subscription_id))

    def signal_many(self, signals):
        if self.queue_error:
            raise self.queue_error
        self.signals.append(list(signals))

    def signal_notifications(self, notifications):
        selected = {}
        for event in notifications:
            scope = event["scope_id"]
            if scope not in selected or selected[scope][0] < event["priority"]:
                selected[scope] = (event["priority"], event["reason"])
        self.signal_many([(scope, value[1]) for scope, value in selected.items()])

    def mark_subscription_attempt(self, scope_id, operation):
        if scope_id in self.attempts:
            raise RuntimeError("Unresolved subscription attempt.")
        self.attempts[scope_id] = operation

    def register_subscription(self, subscription_id, scope_id, tenant_id,
                              resource, client_state, expires_at):
        self.records[subscription_id] = {
            "scope_id": scope_id, "tenant_id": tenant_id, "resource": resource,
            "client_state_sha256": hashlib.sha256(client_state.encode()).hexdigest(),
            "expires_at": expires_at,
        }
        self.attempts.pop(scope_id, None)

    def update_subscription_expiry(self, subscription_id, expires_at):
        self.records[subscription_id]["expires_at"] = expires_at


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, body=None, *, audience, headers=None):
        self.calls.append((method, url, deepcopy(body), audience, deepcopy(headers)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


def drive(config=CONFIG):
    return {"id": config["drive_id"], "driveType": config["drive_type"]}


def subscription_response(config=CONFIG):
    body = build_subscription(config, SECRET, now=NOW)["body"]
    return dict(body, id="subscription-1")


def registered_store(expires_at=None):
    store = FakeStore()
    store.register_subscription(
        "subscription-1", CONFIG["scope_id"], CONFIG["tenant_id"],
        "/drives/b!business-drive/root", SECRET,
        expires_at if expires_at is not None else NOW.timestamp() + 86400,
    )
    return store


def notification(**changes):
    value = {
        "subscriptionId": "subscription-1", "clientState": SECRET,
        "resource": "/drives/b!business-drive/root", "changeType": "updated",
    }
    value.update(changes)
    return value


async def invoke(app, document=None, *, query=b"", method="POST", path="/notifications",
                 raw=None, chunks=None, headers=None):
    if raw is None:
        raw = json.dumps(document if document is not None else {}).encode()
    chunks = chunks if chunks is not None else [raw]
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await app({"type": "http", "method": method, "path": path, "query_string": query,
               "headers": headers or []}, receive, send)
    return sent[0]["status"], dict(sent[0]["headers"]), sent[1]["body"]


class SubscriptionTests(unittest.TestCase):
    def manager(self, transport=None, store=None, config=None):
        return SubscriptionManager(
            config or CONFIG, transport or FakeTransport(), store or FakeStore(),
            clock=lambda: NOW.timestamp(),
        )

    def test_builder_is_drive_root_updated_security_subscription(self):
        request = build_subscription(CONFIG, SECRET, now=NOW)
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], GRAPH + "/v1.0/subscriptions")
        self.assertEqual(request["headers"]["Prefer"], "includesecuritywebhooks")
        self.assertEqual(request["body"], {
            "resource": "/drives/b!business-drive/root", "changeType": "updated",
            "notificationUrl": CONFIG["notification_url"], "clientState": SECRET,
            "lifecycleNotificationUrl": CONFIG["notification_url"],
            "expirationDateTime": "2026-10-17T09:00:00Z",
            "latestSupportedTlsVersion": "v1_2",
        })

    def test_explicit_lifecycle_callback_is_validated_and_used(self):
        config = dict(CONFIG, lifecycle_notification_url="https://callback.example/lifecycle")
        self.assertEqual(build_subscription(config, SECRET, now=NOW)["body"]["lifecycleNotificationUrl"],
                         "https://callback.example/lifecycle")
        with self.assertRaises(ValueError):
            build_subscription(dict(CONFIG, lifecycle_notification_url="http://callback.example/lifecycle"),
                               SECRET, now=NOW)

    def test_only_business_and_document_library_supported(self):
        for kind in ("business", "documentLibrary"):
            config = dict(CONFIG, drive_type=kind)
            self.assertIn("body", build_subscription(config, SECRET, now=NOW))
        for kind in ("personal", "consumer", "Business", "", None):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                build_subscription(dict(CONFIG, drive_type=kind), SECRET, now=NOW)

    def test_scope_and_callback_urls_are_literal_and_https(self):
        for key, value in (
            ("drive_id", "../other"), ("drive_id", "one%2Ftwo"),
            ("drive_id", "id?x=1"), ("drive_id", "https://elsewhere"),
            ("notification_url", "http://callback.example/notifications"),
            ("notification_url", "https://user:pass@callback.example/notifications"),
            ("notification_url", "https://callback.example/notifications#fragment"),
            ("notification_url", "https://callback.example/notifications?secret=private"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                build_subscription(dict(CONFIG, **{key: value}), SECRET, now=NOW)

    def test_expiration_is_aware_future_and_at_most_documented_maximum(self):
        self.assertEqual(MAX_LIFETIME_MINUTES, 42300)
        maximum = NOW + timedelta(minutes=42300)
        build_subscription(CONFIG, SECRET, now=NOW, expiration=maximum)
        for expiration in (
            NOW, NOW - timedelta(seconds=1), maximum + timedelta(seconds=1),
            datetime(2026, 10, 17, 9),
        ):
            with self.subTest(expiration=expiration), self.assertRaises(ValueError):
                build_subscription(CONFIG, SECRET, now=NOW, expiration=expiration)
        request = build_subscription(
            CONFIG, SECRET, now=NOW,
            expiration=datetime(2026, 10, 17, 11, tzinfo=timezone(timedelta(hours=2))),
        )
        self.assertEqual(request["body"]["expirationDateTime"], "2026-10-17T09:00:00Z")

    def test_generated_and_caller_controlled_secrets_are_never_in_plans(self):
        first, second = generate_client_state(), generate_client_state()
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first), 128)
        self.assertGreaterEqual(len(first), 32)
        with patch.dict("os.environ", {"TEST_GRAPH_CLIENT_STATE": first}, clear=False):
            self.assertEqual(client_state_from_env("TEST_GRAPH_CLIENT_STATE"), first)
        with self.assertRaises(ValueError):
            client_state_from_env("ENVIRONMENT_VARIABLE_THAT_IS_NOT_CONFIGURED")
        for value in ("", "short", "a" * 129, "a" * 32 + "\n"):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                build_subscription(CONFIG, value, now=NOW)
        transport, store = FakeTransport(), FakeStore()
        manager = self.manager(transport, store)
        plan = manager.create(SECRET)
        self.assertNotIn(SECRET, json.dumps(plan))
        self.assertIn("includesecuritywebhooks", json.dumps(plan))
        self.assertTrue(plan["apply_required"])
        self.assertEqual(transport.calls, [])
        self.assertEqual(store.signals, [])
        self.assertEqual(store.attempts, {})

    def test_only_literal_true_applies_and_default_create_needs_no_secret(self):
        transport, store = FakeTransport(), registered_store(NOW.timestamp() - 1)
        manager = self.manager(transport, store)
        manager.create()
        for apply in (False, None, "false", "true", 1):
            with self.subTest(apply=apply):
                manager.create(SECRET, apply=apply)
                manager.renew("subscription-1", apply=apply)
                manager.recreate("subscription-1", "b" * 43, apply=apply)
        self.assertEqual(transport.calls, [])
        self.assertEqual(store.signals, [])

    def test_applied_create_verifies_drive_journals_and_registers_hash(self):
        response = subscription_response()
        response["untrusted_extra"] = {"secret": SECRET}
        transport, store = FakeTransport(drive(), response), FakeStore()
        result = self.manager(transport, store).create(SECRET, apply=True)
        self.assertEqual([call[0] for call in transport.calls], ["GET", "POST"])
        self.assertEqual(transport.calls[0][1],
                         GRAPH + "/v1.0/drives/b!business-drive?$select=id,driveType")
        self.assertEqual(transport.calls[1][3], GRAPH)
        self.assertEqual(transport.calls[1][4]["Prefer"], "includesecuritywebhooks")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(SECRET, json.dumps(store.records))
        self.assertEqual(store.records["subscription-1"]["expires_at"],
                         NOW.timestamp() + 86400)
        self.assertEqual(store.attempts, {})
        self.assertIn([(CONFIG["scope_id"], "subscription-creation")], store.signals)

    def test_preflight_mismatch_cannot_mutate_graph(self):
        for metadata in (dict(drive(), driveType="personal"), dict(drive(), id="other"),
                         dict(drive(), driveType="documentLibrary")):
            transport = FakeTransport(metadata)
            with self.subTest(metadata=metadata), self.assertRaises(SubscriptionOperationError):
                self.manager(transport).create(SECRET, apply=True)
            self.assertEqual([call[0] for call in transport.calls], ["GET"])

    def test_missing_journal_or_queue_failure_cannot_post(self):
        for failure in ("journal", "queue"):
            store, transport = FakeStore(), FakeTransport(drive(), subscription_response())
            if failure == "journal":
                store.mark_subscription_attempt = None
            else:
                store.queue_error = sqlite3.OperationalError("locked")
            with self.subTest(failure=failure), self.assertRaises(SubscriptionOperationError):
                self.manager(transport, store).create(SECRET, apply=True)
            self.assertNotIn("POST", [call[0] for call in transport.calls])

    def test_uncertain_create_leaves_durable_attempt_preventing_blind_retry(self):
        store = FakeStore()
        first = FakeTransport(drive(), TimeoutError(SECRET))
        with self.assertRaises(SubscriptionOperationError) as error:
            self.manager(first, store).create(SECRET, apply=True)
        self.assertNotIn(SECRET, str(error.exception))
        self.assertEqual(store.attempts[CONFIG["scope_id"]], "create")
        second = FakeTransport(drive(), subscription_response())
        with self.assertRaises(SubscriptionOperationError):
            self.manager(second, store).create(SECRET, apply=True)
        self.assertNotIn("POST", [call[0] for call in second.calls])

    def test_failed_registration_retains_attempt_and_never_exposes_response_secret(self):
        store, transport = FakeStore(), FakeTransport(drive(), subscription_response())
        with patch.object(store, "register_subscription", side_effect=OSError(SECRET)):
            with self.assertRaises(SubscriptionOperationError) as error:
                self.manager(transport, store).create(SECRET, apply=True)
        self.assertEqual(store.records, {})
        self.assertEqual(store.attempts, {CONFIG["scope_id"]: "create"})
        self.assertNotIn(SECRET, str(error.exception))
        self.assertEqual([call[0] for call in transport.calls], ["GET", "POST"])

    def test_creation_ack_is_verified_before_registration(self):
        for key, value in (
            ("resource", "/drives/other/root"), ("changeType", "created"),
            ("notificationUrl", "https://other.example/notifications"),
            ("expirationDateTime", "2026-10-16T08:00:00Z"),
            ("expirationDateTime", None),
            ("expirationDateTime", "2027-10-16T08:00:00Z"),
            ("expirationDateTime", "2026-10-17T09:00:00"),
            ("clientState", "different"), ("id", "../other"),
            ("lifecycleNotificationUrl", "https://other.example/lifecycle"),
        ):
            response = dict(subscription_response(), **{key: value})
            store = FakeStore()
            with self.subTest(key=key), self.assertRaises(SubscriptionOperationError):
                self.manager(FakeTransport(drive(), response), store).create(SECRET, apply=True)
            self.assertEqual(store.records, {})
            self.assertIn(CONFIG["scope_id"], store.attempts)

    def test_renewal_only_known_security_intent_and_due_window(self):
        store, transport = registered_store(), FakeTransport()
        manager = self.manager(transport, store)
        plan = manager.renew("subscription-1", apply=True)
        self.assertFalse(plan["renewal_due"])
        self.assertEqual(transport.calls, [])
        with self.assertRaises(SubscriptionOperationError):
            manager.renew("content-only-or-unknown", apply=True)
        store.records["subscription-1"]["security_webhooks"] = False
        with self.assertRaises(SubscriptionOperationError):
            manager.renew("subscription-1", apply=True)
        del store.records["subscription-1"]["security_webhooks"]
        self.assertFalse(manager.renew("subscription-1", apply=True)["renewal_due"])

    def test_renewal_patches_expiry_without_claiming_prefer_upgrade(self):
        store = registered_store(NOW.timestamp() + 7200)
        response = subscription_response()
        transport = FakeTransport(response)
        manager = self.manager(transport, store)
        plan = manager.renew("subscription-1")
        self.assertTrue(plan["renewal_due"])
        self.assertEqual(transport.calls, [])
        result = manager.renew("subscription-1", apply=True)
        method, url, body, audience, headers = transport.calls[0]
        self.assertEqual((method, url, audience),
                         ("PATCH", GRAPH + "/v1.0/subscriptions/subscription-1", GRAPH))
        self.assertEqual(set(body), {"expirationDateTime"})
        self.assertNotIn("Prefer", headers)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(store.records["subscription-1"]["expires_at"], NOW.timestamp() + 86400)
        self.assertEqual(store.records["subscription-1"]["client_state_sha256"],
                         hashlib.sha256(SECRET.encode()).hexdigest())

    def test_renewal_404_requires_explicit_recreate_never_post(self):
        class NotFound(RuntimeError):
            status = 404

        store = registered_store(NOW.timestamp() - 1)
        transport = FakeTransport(NotFound())
        with self.assertRaises(SubscriptionRecreationRequired):
            self.manager(transport, store).renew("subscription-1", apply=True)
        self.assertEqual([call[0] for call in transport.calls], ["PATCH"])
        self.assertIn([(CONFIG["scope_id"], "subscription-recreation-required")], store.signals)
        self.assertLess(store.records["subscription-1"]["expires_at"], NOW.timestamp())

    def test_failed_renewal_preserves_original_expiry_and_never_recreates(self):
        for response in (TimeoutError(SECRET), dict(subscription_response(), expirationDateTime=None),
                         dict(subscription_response(), id="other-subscription")):
            store = registered_store(NOW.timestamp() + 60)
            transport = FakeTransport(response)
            with self.subTest(response_type=type(response)), self.assertRaises(SubscriptionOperationError):
                self.manager(transport, store).renew("subscription-1", apply=True)
            self.assertEqual(store.records["subscription-1"]["expires_at"], NOW.timestamp() + 60)
            self.assertEqual([call[0] for call in transport.calls], ["PATCH"])
            self.assertEqual(store.signals, [[(CONFIG["scope_id"], "subscription-renewal")]])

    def test_reauthorization_can_force_renewal_before_normal_window(self):
        store, transport = registered_store(), FakeTransport(subscription_response())
        self.manager(transport, store).renew("subscription-1", apply=True, force=True)
        self.assertEqual([call[0] for call in transport.calls], ["PATCH"])

    def test_explicit_recreate_rotates_secret_and_reuses_security_prefer(self):
        store = registered_store(NOW.timestamp() - 1)
        replacement = "b" * 43
        response = dict(subscription_response(), clientState=replacement, id="subscription-2")
        transport = FakeTransport(drive(), response)
        manager = self.manager(transport, store)
        with self.assertRaises(ValueError):
            manager.recreate("subscription-1", SECRET, apply=True)
        manager.recreate("subscription-1", replacement)
        self.assertEqual(transport.calls, [])
        manager.recreate("subscription-1", replacement, apply=True)
        self.assertEqual(transport.calls[1][4]["Prefer"], "includesecuritywebhooks")
        self.assertEqual(store.records["subscription-2"]["client_state_sha256"],
                         hashlib.sha256(replacement.encode()).hexdigest())


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_subscription_cannot_quarantine_its_healthy_replacement(self):
        store = registered_store(expires_at=NOW.timestamp() - 100)
        store.records["subscription-1"]["active"] = 0
        app = GraphWebhookApp(store, clock=lambda: NOW.timestamp())
        status, _, _ = await invoke(app, {"value": [notification(lifecycleEvent="reauthorizationRequired")]})
        self.assertEqual(status, 202)
        self.assertEqual(store.signals, [])
        status, _, _ = await invoke(app, {"value": [notification(clientState="wrong")]})
        self.assertEqual(status, 401)

    def setUp(self):
        self.store = registered_store()
        self.app = GraphWebhookApp(self.store, clock=lambda: NOW.timestamp())

    async def test_handshake_is_plain_text_decoded_once_without_subscription_or_body(self):
        token = "<script>alert(1)</script>+%2F"
        app = GraphWebhookApp(FakeStore())
        query = urlencode({"validationToken": token, "secret": "do-not-echo"}).encode()
        status, headers, body = await invoke(app, query=query, raw=b"not JSON")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode(), token)
        self.assertEqual(headers[b"content-type"], b"text/plain; charset=utf-8")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertNotIn(b"do-not-echo", body)

    async def test_handshake_does_not_read_slow_body(self):
        sent = []

        async def receive():
            raise AssertionError("Handshake must not read the body.")

        async def send(value):
            sent.append(value)

        await self.app({"type": "http", "method": "POST", "path": "/notifications",
                        "query_string": b"validationToken=valid", "headers": []}, receive, send)
        self.assertEqual(sent[0]["status"], 200)

    async def test_handshake_rejects_duplicates_oversize_invalid_encoding_and_other_methods(self):
        for query in (b"validationToken=a&validationToken=b", b"validationToken=",
                      b"validationToken=" + b"x" * 4097, b"validationToken=%FF",
                      b"validationToken=%xy"):
            with self.subTest(query=query[:60]):
                self.assertEqual((await invoke(self.app, query=query))[0], 400)
        self.assertEqual((await invoke(self.app, query=b"validationToken=x", method="GET"))[0], 405)
        self.assertEqual((await invoke(self.app, method="OPTIONS"))[0], 405)
        self.assertEqual((await invoke(self.app, path="/unrelated"))[0], 404)

    async def test_valid_batch_is_one_durable_coalesced_signal_without_event_ids(self):
        changes = [notification(), notification(resource="drives/b!business-drive/root")]
        with patch("sales_demo.graph_webhooks.hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            status, _, body = await invoke(self.app, {"value": changes})
        self.assertEqual(status, 202)
        self.assertEqual(body, b"")
        self.assertEqual(compare.call_count, 2)
        self.assertEqual(self.store.signals, [[(CONFIG["scope_id"], "graph-notification")]])
        await invoke(self.app, {"value": changes})
        self.assertEqual(len(self.store.signals), 2)

    async def test_multiple_scopes_are_queued_in_one_atomic_call(self):
        self.store.register_subscription(
            "subscription-2", "another-scope", CONFIG["tenant_id"],
            "/drives/another-drive/root", SECRET, NOW.timestamp() + 86400)
        status, _, _ = await invoke(self.app, {"value": [
            notification(), notification(subscriptionId="subscription-2", resource="drives/another-drive/root"),
            notification(),
        ]})
        self.assertEqual(status, 202)
        self.assertEqual(self.store.signals, [[
            (CONFIG["scope_id"], "graph-notification"), ("another-scope", "graph-notification"),
        ]])

    async def test_explicit_non_security_local_record_is_not_silently_adopted(self):
        for intent in (False, None):
            self.store.records["subscription-1"]["security_webhooks"] = intent
            self.assertEqual((await invoke(self.app, {"value": [notification()]}))[0], 401)
        del self.store.records["subscription-1"]["security_webhooks"]
        self.assertEqual(self.store.signals, [])
        self.assertEqual((await invoke(self.app, {"value": [notification()]}))[0], 202)

    async def test_mixed_batch_validated_completely_before_any_queue_write(self):
        for changed in (
            notification(clientState="wrong"), notification(subscriptionId="unknown"),
            notification(tenantId="22222222-2222-2222-2222-222222222222"),
        ):
            with self.subTest(changed=changed):
                status, _, body = await invoke(self.app, {"value": [notification(), changed]})
                self.assertEqual(status, 401)
                self.assertEqual(self.store.signals, [])
                self.assertNotIn(b"subscription-1", body)
                self.assertNotIn(SECRET.encode(), body)

    async def test_unknown_and_bad_secret_have_identical_responses(self):
        first = await invoke(self.app, {"value": [notification(subscriptionId="missing")]})
        second = await invoke(self.app, {"value": [notification(clientState="wrong")]})
        self.assertEqual(first, second)

    async def test_tenant_is_optional_but_must_match_when_supplied(self):
        self.assertEqual((await invoke(self.app, {"value": [notification()]}))[0], 202)
        self.assertEqual((await invoke(self.app, {"value": [
            notification(tenantId=CONFIG["tenant_id"])]}))[0], 202)
        self.assertEqual((await invoke(self.app, {"value": [
            notification(tenantId=None)]}))[0], 401)

    async def test_resource_is_literal_root_not_url_file_or_prefix_match(self):
        for resource in (
            "/drives/other/root", "https://graph.microsoft.com/v1.0/drives/b!business-drive/root",
            "/drives/b!business-drive/root/children", "/drives/b!business-drive/items/file",
            "/drives/b!business-drive/root?x=1", "/drives/b!business-drive%2Froot",
            "/drives/b!business-drive/root/",
        ):
            with self.subTest(resource=resource):
                self.assertEqual((await invoke(self.app, {"value": [
                    notification(resource=resource)]}))[0], 400)
                self.assertEqual(self.store.signals, [])
        self.assertEqual((await invoke(self.app, {"value": [
            notification(resource="/DRIVES/b!business-drive/ROOT")]}))[0], 202)

    async def test_untrusted_resource_data_never_followed_or_used_as_acl(self):
        status, _, _ = await invoke(self.app, {"value": [notification(resourceData={
            "@odata.id": "https://evil.example/resource", "allowedUsers": ["attacker"],
            "permissions": [{"roles": ["owner"]}],
        })]})
        self.assertEqual(status, 202)
        self.assertEqual(self.store.signals, [[(CONFIG["scope_id"], "graph-notification")]])

    async def test_payload_shape_bounds_invalid_json_and_duplicate_properties(self):
        for document in ([], {}, {"value": []}, {"value": [None]}, {"value": "array"},
                         {"value": [notification()] * 101},
                         {"value": [notification(changeType="deleted")]}):
            with self.subTest(document_type=type(document)):
                self.assertEqual((await invoke(self.app, document))[0], 400)
        for raw in (b"{", b'{"value":[],"value":[]}', b'{"value":[NaN]}', b"\xff"):
            self.assertEqual((await invoke(self.app, raw=raw))[0], 400)
        self.assertEqual(self.store.signals, [])

    async def test_body_limit_enforced_even_streamed_or_false_content_length(self):
        app = GraphWebhookApp(self.store, max_body_bytes=32)
        self.assertEqual((await invoke(app, chunks=[b"x" * 20, b"y" * 20]))[0], 413)
        self.assertEqual((await invoke(app, raw=b"{}", headers=[
            (b"content-length", b"1048577")]))[0], 413)
        self.assertEqual((await invoke(app, raw=b"{}", headers=[
            (b"content-length", b"not-a-number")]))[0], 400)
        self.assertEqual((await invoke(self.app, raw=b"{}", headers=[
            (b"content-length", b"1")]))[0], 400)

    async def test_slow_body_is_bounded_and_never_acknowledged(self):
        app = GraphWebhookApp(self.store, body_timeout=0.01)
        sent = []

        async def receive():
            await asyncio.sleep(1)

        async def send(value):
            sent.append(value)

        await app({"type": "http", "method": "POST", "path": "/notifications",
                   "query_string": b"", "headers": []}, receive, send)
        self.assertEqual(sent[0]["status"], 408)
        self.assertEqual(self.store.signals, [])

    async def test_disconnect_never_acknowledges_or_enqueues_partial_body(self):
        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(value):
            sent.append(value)

        await self.app({"type": "http", "method": "POST", "path": "/notifications",
                        "query_string": b"", "headers": []}, receive, send)
        self.assertEqual(sent, [])
        self.assertEqual(self.store.signals, [])

    async def test_store_commit_precedes_acknowledgement(self):
        sent, order = [], []
        raw = json.dumps({"value": [notification()]}).encode()

        async def receive():
            return {"type": "http.request", "body": raw}

        def signal_many(signals):
            order.append("committed")

        async def send(value):
            order.append("sent")
            sent.append(value)

        with patch.object(self.store, "signal_many", side_effect=signal_many):
            await self.app({"type": "http", "method": "POST", "path": "/notifications",
                            "query_string": b"", "headers": []}, receive, send)
        self.assertEqual(order, ["committed", "sent", "sent"])
        self.assertEqual(sent[0]["status"], 202)

    async def test_queue_and_lookup_failures_return_503_not_success(self):
        for error in (sqlite3.OperationalError("locked"), OSError("disk full"),
                      RuntimeError("queue unavailable")):
            self.store.queue_error = error
            with self.subTest(error=type(error)):
                status, headers, _ = await invoke(self.app, {"value": [notification()]})
                self.assertEqual(status, 503)
                self.assertEqual(headers[b"retry-after"], b"5")
        with patch.object(self.store, "subscription", side_effect=OSError("state unavailable")):
            self.assertEqual((await invoke(self.app, {"value": [notification()]}))[0], 503)
        self.assertEqual(self.store.signals, [])

    async def test_expired_known_secret_is_signalled_and_quarantined_not_dropped(self):
        self.store.records["subscription-1"]["expires_at"] = NOW.timestamp()
        self.assertEqual((await invoke(self.app, {"value": [notification()]}))[0], 202)
        self.assertEqual(self.store.signals, [[(CONFIG["scope_id"], "graph-subscription-expired")]])

    async def test_lifecycle_reauthorization_and_unsupported_events_fail_closed(self):
        for event, reason in (
            ("reauthorizationRequired", "graph-reauthorization-required"),
            ("missed", "graph-unsupported-lifecycle-missed"),
            ("subscriptionRemoved", "graph-unsupported-lifecycle-subscriptionRemoved"),
            ("futureEvent", "graph-unsupported-lifecycle"),
        ):
            item = {"subscriptionId": "subscription-1", "clientState": SECRET,
                    "lifecycleEvent": event, "organizationId": CONFIG["tenant_id"]}
            with self.subTest(event=event):
                self.assertEqual((await invoke(self.app, {"value": [item]}))[0], 202)
                self.assertEqual(self.store.signals[-1], [(CONFIG["scope_id"], reason)])
        item["organizationId"] = "22222222-2222-2222-2222-222222222222"
        self.assertEqual((await invoke(self.app, {"value": [item]}))[0], 401)

    async def test_strongest_reason_wins_when_one_scope_has_many_notifications(self):
        values = [notification(), notification(lifecycleEvent="reauthorizationRequired"),
                  notification()]
        self.assertEqual((await invoke(self.app, {"value": values}))[0], 202)
        self.assertEqual(self.store.signals, [[(CONFIG["scope_id"], "graph-reauthorization-required")]])


if __name__ == "__main__":
    unittest.main()
