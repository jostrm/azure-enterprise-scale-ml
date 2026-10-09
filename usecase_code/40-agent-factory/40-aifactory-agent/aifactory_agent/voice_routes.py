"""FastAPI wiring for live voice: GET /api/voice/status and the WebSocket relay at /api/voice/ws.

Only registered when `voice.enabled` is true, so a disabled deployment exposes no voice surface at all.
Authentication is the same Entra delegated token as every other route, sent in the first WebSocket frame (never in
a URL, so it is not logged and works across replicas); authorization is the exact-scope `knowledge.read` grant.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

import jwt
from azure.core.exceptions import AzureError
from fastapi import Depends, FastAPI, Request, WebSocket
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.websockets import WebSocketDisconnect, WebSocketState

from . import security, web
from .config import Settings
from .knowledge import IndexingError, OwnershipError
from .security import Principal, authorize
from .services import AgentServices
from .telemetry import VOICE_FAILURES, VOICE_SESSIONS, VOICE_SESSION_SECONDS, VOICE_TURNS
from .tools import ToolError
from .voice import (
    PROTOCOL_VERSION, SAMPLE_RATE, ClientGone, SessionRegistry, VoiceAnswerError, VoiceLiveGateway,
    VoiceProtocolError, VoiceSession, websockets_available,
)

LOGGER = logging.getLogger(__name__)

HELLO_TIMEOUT_SECONDS = 10.0
MAX_HELLO_CHARS = 16384
MAX_CONTROL_CHARS = 4096
PRE_AUTH_LIMIT = 32

MESSAGES = {
    "invalid_hello": "Send a valid hello with a token, scope and audience.",
    "hello_timeout": "No hello was received in time.",
    "authentication_required": "Sign in with an Entra delegated access token.",
    "authentication_unavailable": "Entra registration or signing keys are unavailable. Ask the deployment operator to check setup.",
    "forbidden": "The caller is not authorized for this exact scope and permission.",
    "voice_busy": "Too many live voice sessions are active. Try again shortly.",
    "voice_unavailable": "Live voice is unavailable right now. Typing still works.",
    "protocol_error": "The voice connection broke the protocol and was closed.",
}
CLOSE_CODES = {"voice_busy": 1013, "voice_unavailable": 1011}


class HelloMessage(BaseModel):
    """The only thing the browser may say before a session exists; it cannot choose model, voice or tools."""

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["hello"]
    token: str = Field(min_length=20, max_length=8192)
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    audience: Literal["platform", "project"]


class StarletteChannel:
    """Serialises frames to the browser and turns a vanished client into ClientGone."""

    def __init__(self, websocket: WebSocket):
        self._socket = websocket
        self._lock = asyncio.Lock()

    async def _send(self, **frame) -> None:
        async with self._lock:
            if self._socket.application_state != WebSocketState.CONNECTED:
                raise ClientGone()
            try:
                if "data" in frame:
                    await self._socket.send_bytes(frame["data"])
                else:
                    await self._socket.send_text(frame["text"])
            except (WebSocketDisconnect, RuntimeError) as exc:
                raise ClientGone() from exc

    async def send_json(self, message: dict) -> None:
        await self._send(text=json.dumps(message, separators=(",", ":")))

    async def send_audio(self, data: bytes) -> None:
        await self._send(data=data)


def _origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        return True  # not a browser; authentication below still applies
    parsed = urlsplit(origin)
    if parsed.netloc.lower() == websocket.headers.get("host", "").lower():
        return True
    return f"https://{parsed.netloc.lower()}" in settings.voice.allowed_origins


async def _receive(websocket: WebSocket) -> tuple[str, str | bytes | None]:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        return "closed", None
    if message.get("bytes") is not None:
        return "audio", message["bytes"]
    if message.get("text") is not None:
        return "text", message["text"]
    return "closed", None


def _services(app: FastAPI) -> AgentServices:
    services = app.state.services
    if services.settings != app.state.settings:
        services = AgentServices(app.state.settings, dependencies=services.dependencies)
        app.state.services = services
    return services


def _answerer(app: FastAPI, principal: Principal, scope_key: str, audience: str):
    """Bind the verified identity and scope; the answer path is the very same Conversation as POST /api/chat."""

    def work(text: str) -> dict:
        services = _services(app)
        return services.conversation(services.knowledge()).answer(text, audience, principal, scope_key)

    async def answer(text: str) -> dict:
        try:
            return await asyncio.to_thread(work, text)
        except PermissionError:
            raise VoiceAnswerError("forbidden", MESSAGES["forbidden"])
        except (IndexingError, OwnershipError):
            raise VoiceAnswerError("knowledge_unavailable",
                                   "Knowledge is unavailable. An approved operator must check ingestion and ownership.")
        except (AzureError, OpenAIError):
            raise VoiceAnswerError("dependency_unavailable",
                                   "An Azure or model dependency is unavailable. Check deployment health.")
        except ToolError:
            raise VoiceAnswerError("operation_blocked", "The operation is blocked or unavailable. Contact the operator.")

    return answer


async def _refuse(websocket: WebSocket, channel: StarletteChannel, code: str, close: int | None = None) -> None:
    try:
        await channel.send_json({"type": "error", "code": code, "fatal": True, "message": MESSAGES[code]})
        await websocket.close(code=close or CLOSE_CODES.get(code, 1008))
    except (ClientGone, RuntimeError, WebSocketDisconnect):
        pass


async def _authenticate(app: FastAPI, hello: HelloMessage) -> Principal:
    settings: Settings = app.state.settings
    if not web._auth_configured(settings):
        raise security.AuthenticationUnavailable("unconfigured")
    principal = await asyncio.to_thread(_services(app).authenticate, hello.token)
    authorize(settings, principal, hello.scope_key, "knowledge.read")
    return principal


def _session_seconds(voice, token: str) -> float:
    """A voice session never outlives the sign-in that opened it (the token was already validated by the authenticator)."""
    limit = float(voice.max_session_seconds)
    try:
        expires = jwt.decode(token, options={"verify_signature": False, "verify_exp": False}).get("exp")
    except jwt.PyJWTError:
        return limit
    if isinstance(expires, int) and not isinstance(expires, bool):
        return max(1.0, min(limit, expires - time.time()))
    return limit


async def _relay_client(websocket: WebSocket, session: VoiceSession, channel: StarletteChannel) -> None:
    while True:
        kind, payload = await _receive(websocket)
        if kind == "closed":
            await session.end("client_closed")
            return
        try:
            if kind == "audio":
                await session.handle_audio(payload)
            else:
                if len(payload) > MAX_CONTROL_CHARS:
                    raise VoiceProtocolError("control")
                try:
                    control = json.loads(payload)
                except ValueError:
                    raise VoiceProtocolError("control")
                await session.handle_control(control)
        except VoiceProtocolError:
            try:
                await channel.send_json({"type": "error", "code": "protocol_error", "fatal": True,
                                         "message": MESSAGES["protocol_error"]})
            except ClientGone:
                pass
            await session.end("protocol_error")
            return
        except ClientGone:
            await session.end("client_closed")
            return
        except Exception as exc:
            LOGGER.warning("voice_relay_failed error=%s", type(exc).__name__)
            await session.end("error")
            return


def register_voice(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.voice_gateway = VoiceLiveGateway()
    app.state.voice_registry = SessionRegistry(settings.voice.max_concurrent_sessions)
    app.state.voice_pre_auth = 0

    @app.get("/api/voice/status")
    def voice_status(
        request: Request,
        principal: Annotated[Principal, Depends(web.get_principal)],
        current: Annotated[Settings, Depends(web.get_settings)],
    ):
        gateway = request.app.state.voice_gateway
        needs_library = getattr(gateway, "requires_websockets", False)
        ready = not needs_library or websockets_available()
        return {
            "enabled": True, "ready": ready, "unavailable_reason": None if ready else "websockets_missing",
            "protocol": PROTOCOL_VERSION,
            "audio": {"encoding": "pcm16", "sample_rate": SAMPLE_RATE, "channels": 1},
            "voice": {"name": current.voice.voice_name, "languages": list(current.voice.input_languages)},
            "limits": {"max_session_seconds": current.voice.max_session_seconds,
                       "idle_timeout_seconds": current.voice.idle_timeout_seconds},
        }

    @app.websocket("/api/voice/ws")
    async def voice_socket(websocket: WebSocket):
        state = websocket.app.state
        current: Settings = state.settings
        if not _origin_allowed(websocket, current):
            await websocket.close(code=1008)
            return
        if state.voice_pre_auth >= PRE_AUTH_LIMIT:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        channel = StarletteChannel(websocket)
        entry = None
        state.voice_pre_auth += 1
        try:
            try:
                kind, payload = await asyncio.wait_for(_receive(websocket), HELLO_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                await _refuse(websocket, channel, "hello_timeout")
                return
            try:
                if kind != "text" or len(payload) > MAX_HELLO_CHARS:
                    raise ValueError
                hello = HelloMessage.model_validate_json(payload)
            except (ValueError, ValidationError):
                await _refuse(websocket, channel, "invalid_hello")
                return
            try:
                principal = await _authenticate(websocket.app, hello)
            except security.AuthenticationUnavailable:
                await _refuse(websocket, channel, "authentication_unavailable")
                return
            except security.AuthenticationError:
                await _refuse(websocket, channel, "authentication_required")
                return
            except PermissionError:
                await _refuse(websocket, channel, "forbidden")
                return
            reservation = state.voice_registry.reserve(principal.object_id)
            if reservation is None:
                await _refuse(websocket, channel, "voice_busy")
                return
            entry, previous = reservation
        finally:
            state.voice_pre_auth -= 1
        try:
            if previous is not None and previous.session is not None:
                await previous.session.end("replaced")
            try:
                upstream = await state.voice_gateway.connect(current)
            except Exception as exc:
                LOGGER.warning("voice_connect_failed error=%s", type(exc).__name__)
                VOICE_FAILURES.add(1, {"stage": "connect"})
                await _refuse(websocket, channel, "voice_unavailable")
                return
            session = VoiceSession(current.voice, upstream, channel,
                                   _answerer(websocket.app, principal, hello.scope_key, hello.audience),
                                   session_id=uuid.uuid4().hex, max_duration=_session_seconds(current.voice, hello.token))
            entry.session = session
            if entry.replaced:
                await session.end("replaced")
            VOICE_SESSIONS.add(1, {"scope": hello.scope_key})
            runner = asyncio.create_task(session.run())
            relay = asyncio.create_task(_relay_client(websocket, session, channel))
            try:
                reason = await runner
            finally:
                relay.cancel()
                await asyncio.gather(relay, return_exceptions=True)
            VOICE_TURNS.add(session.turns, {"scope": hello.scope_key})
            if reason in ("handshake_failed", "upstream_closed", "error"):
                VOICE_FAILURES.add(1, {"stage": reason})
            try:
                await websocket.close(code=1008 if reason == "protocol_error" else 1000)
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            state.voice_registry.release(entry)
