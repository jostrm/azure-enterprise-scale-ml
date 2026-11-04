import asyncio
import json
import unittest

import httpx
from fastapi.testclient import TestClient

from sales_agent.config import Settings
from sales_agent.contracts import SalesError
from sales_agent.web import create_app, answer_until_disconnect
from test_config import values
from test_service import FakeFabric, FakeGateway, answer, call
from sales_agent.service import SalesConversation

ORIGIN = "http://127.0.0.1:8765"


class DisconnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_asgi_disconnect_through_middleware_cancels_pending_fabric(self):
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Fabric(FakeFabric):
            async def query(self, question):
                entered.set()
                try:
                    await release.wait()
                    return await super().query(question)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        service = SalesConversation(FakeGateway([call(), answer()]), Fabric())
        app = create_app(Settings.from_mapping(values()), lambda: service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            session = await client.post("/api/session", json={}, headers={"Origin": ORIGIN})
            queue = asyncio.Queue()
            await queue.put({"type": "http.request", "body": json.dumps({"text": "Sales?"}).encode(),
                             "more_body": False})
            scope = {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": "POST", "scheme": "http", "path": "/api/chat", "raw_path": b"/api/chat",
                "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000),
                "server": ("127.0.0.1", 8765),
                "headers": [(b"host", b"127.0.0.1:8765"), (b"origin", ORIGIN.encode()),
                            (b"content-type", b"application/json"),
                            (b"cookie", session.headers["set-cookie"].split(";")[0].encode())],
            }

            async def send(message):
                pass

            running = asyncio.create_task(app(scope, queue.get, send))
            observed = asyncio.create_task(cancelled.wait())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                await queue.put({"type": "http.disconnect"})
                done, _ = await asyncio.wait({observed}, timeout=0.5)
            finally:
                release.set()
                await asyncio.wait_for(running, 2)
                observed.cancel()
                await asyncio.gather(observed, return_exceptions=True)
            self.assertTrue(done, "The complete middleware stack did not propagate disconnection.")
            self.assertFalse(service._lock.locked())
            self.assertIsNone(service.conversation_id)
            reset = await client.post("/api/conversation/reset", json={}, headers={"Origin": ORIGIN})
            self.assertEqual(reset.status_code, 200)

    async def test_receive_consuming_cancellation_cannot_hang_completed_answer(self):
        class Request:
            closed = False

            async def receive(self):
                try:
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    pass
                return {"type": "http.disconnect" if self.closed else "http.request"}

        request = Request()
        service = SalesConversation(FakeGateway([call(), answer()]), FakeFabric())
        pending = asyncio.create_task(answer_until_disconnect(request, service, "Sales?", None))
        done, _ = await asyncio.wait({pending}, timeout=0.5)
        if not done:
            request.closed = True
            await asyncio.wait_for(pending, 1)
        self.assertTrue(done, "A swallowed probe cancellation blocked the completed answer.")

    async def test_disconnect_cancels_fabric_and_releases_conversation_lock(self):
        entered, disconnected, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Request:
            async def receive(self):
                await disconnected.wait()
                return {"type": "http.disconnect"}

        class Fabric:
            async def query(self, question):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        service = SalesConversation(FakeGateway([call()]), Fabric())
        pending = asyncio.create_task(answer_until_disconnect(Request(), service, "Sales?", None))
        await entered.wait()
        disconnected.set()
        with self.assertRaises(SalesError) as error:
            await asyncio.wait_for(pending, 2)
        self.assertEqual(error.exception.code, "client_disconnected")
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(service.conversation_id)
        self.assertFalse(service._lock.locked())

    async def test_total_deadline_includes_identity_and_returns_safe_timeout(self):
        class Request:
            async def receive(self):
                await asyncio.Event().wait()

        async def verify():
            await asyncio.Event().wait()

        service = SalesConversation(FakeGateway([]), FakeFabric())
        with self.assertRaises(SalesError) as error:
            await answer_until_disconnect(Request(), service, "Sales?", verify, deadline=0.01)
        self.assertEqual(error.exception.status, 504)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            Settings.from_mapping(values()),
            lambda: SalesConversation(FakeGateway([call(), answer()]), FakeFabric()),
        )
        self.client = TestClient(self.app, base_url=ORIGIN)

    def tearDown(self):
        self.client.close()

    def session(self):
        return self.client.post("/api/session", json={}, headers={"Origin": ORIGIN})

    def test_health_does_not_claim_cloud_success(self):
        data = self.client.get("/api/health").json()
        self.assertEqual(data["application"], "foundry-voice-sales")
        self.assertFalse(data["cloud_verified"])

    def test_cross_origin_or_rebinding_cannot_create_session(self):
        for origin in (None, "https://evil.invalid"):
            response = self.client.post("/api/session", json={}, headers={"Origin": origin} if origin else {})
            self.assertEqual(response.status_code, 403)
        response = self.client.get("/api/health", headers={"Host": "evil.invalid"})
        self.assertEqual(response.status_code, 400)

    def test_session_cookie_is_not_javascript_readable(self):
        response = self.session()
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertFalse(response.json()["voice_enabled"])

    def test_auth_required_then_grounded_chat_works(self):
        self.assertEqual(self.client.post("/api/chat", json={"text": "Sales?"},
                                         headers={"Origin": ORIGIN}).status_code, 401)
        self.session()
        response = self.client.post("/api/chat", json={"text": "Sales?"}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["provenance"][0]["id"], "F1")

    def test_browser_cannot_select_tools_or_other_conversations(self):
        self.session()
        for payload in ({"text": "Sales?", "tools": ["write"]},
                        {"text": "Sales?", "conversation": "someone-else"}, {"text": ""}):
            response = self.client.post("/api/chat", json=payload, headers={"Origin": ORIGIN})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
