import httpx
import pytest

from aifactory_mcp.readiness import ApiReadinessProbe
from aifactory_mcp.server import create_http_app
from test_server import Runtime


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, json={"status": "ok"}), True),
    (httpx.Response(200, json={"status": "starting"}), False),
    (httpx.Response(200, json=[]), False),
    (httpx.Response(503, json={"status": "ok"}), False),
    (httpx.Response(302, headers={"Location": "https://unrelated.example"}), False),
    (httpx.Response(200, text="not-json"), False),
])
def test_api_readiness_is_bounded_and_requires_health_contract(response, expected):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url == "http://127.0.0.1:8765/health"
        assert "authorization" not in request.headers and "x-api-key" not in request.headers
        assert request.extensions["timeout"]["read"] == 2.0
        return response

    probe = ApiReadinessProbe("http://127.0.0.1:8765", transport=httpx.MockTransport(handle))
    assert probe.ready() is expected
    assert len(requests) == 1


def test_api_readiness_does_not_leak_dependency_error():
    def unavailable(request):
        raise httpx.ConnectError("private details", request=request)

    assert not ApiReadinessProbe("http://127.0.0.1:8765", transport=httpx.MockTransport(unavailable)).ready()


@pytest.mark.parametrize("url", ["https://factory.example.com/pilot", "https://factory.example.com/pilot/"])
def test_readiness_preserves_supported_api_base_path(url):
    requests = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == "https://factory.example.com/pilot/health"
        assert "authorization" not in request.headers and "x-api-key" not in request.headers
        return httpx.Response(200, json={"status": "ok"})

    assert ApiReadinessProbe(url, transport=httpx.MockTransport(handle)).ready()
    assert len(requests) == 1


@pytest.mark.anyio
async def test_health_routes_are_not_mcp_auth_bypasses():
    class Probe:
        ready_value = True

        def ready(self):
            return self.ready_value

    probe = Probe()
    app = create_http_app(Runtime(), "scope", resource_url="http://127.0.0.1:8899/mcp", readiness=probe)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://127.0.0.1:8899") as client:
        response = await client.get("/health/live")
        assert response.status_code == 200 and response.json() == {"status": "live"}
        response = await client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["coverage"] == "Factory API health only; not deployment or action readiness."
        probe.ready_value = False
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert (await client.post("/mcp", json={})).status_code == 401


@pytest.mark.anyio
async def test_missing_readiness_dependency_is_not_success():
    app = create_http_app(Runtime(), "scope", resource_url="http://127.0.0.1:8899/mcp")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://127.0.0.1:8899") as client:
        assert (await client.get("/health/ready")).status_code == 503
