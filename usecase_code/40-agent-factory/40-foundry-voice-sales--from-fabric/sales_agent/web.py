from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketState

from .contracts import SalesError
from .voice import VoiceRelay

STATIC = Path(__file__).resolve().parent / "static"
SESSION_SECONDS = 1800


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatBody(EmptyBody):
    text: str = Field(min_length=1, max_length=6000)


@dataclass
class Session:
    conversation: object
    expires: float
    voice: bool = False


async def answer_until_disconnect(request, conversation, question, verify_identity, *, deadline=240):
    stopping = asyncio.Event()

    async def execute():
        try:
            async with asyncio.timeout(deadline):
                if verify_identity:
                    await verify_identity()
                return await conversation.answer(question)
        except TimeoutError as exc:
            raise SalesError("answer_timeout", "The request timed out. Try a narrower question.", 504) from exc

    async def monitor():
        while not stopping.is_set():
            # FastAPI has consumed the body; this dedicated reader now waits for disconnect.
            if (await request.receive())["type"] == "http.disconnect":
                return

    answer_task, disconnect_task = asyncio.create_task(execute()), asyncio.create_task(monitor())
    try:
        await asyncio.wait({answer_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED)
        if answer_task.done():
            return answer_task.result()
        disconnect_task.result()
        raise SalesError("client_disconnected", "The browser disconnected; the pending turn was cancelled.", 499)
    finally:
        # Also bound cleanup when a receive adapter consumes task cancellation.
        stopping.set()
        answer_task.cancel()
        disconnect_task.cancel()
        await asyncio.gather(answer_task, disconnect_task, return_exceptions=True)


def create_app(settings, conversation_factory, voice_connector=None, *, port=8765, verify_identity=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sessions: dict[str, Session] = {}
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def same_origin(headers):
        return headers.get("host") in hosts and headers.get("origin") == f"http://{headers.get('host')}"

    def get_session(cookies):
        session = sessions.get(cookies.get("sales_session", ""))
        if session is None or session.expires <= time.monotonic():
            raise SalesError("session_expired", "The local session expired. Reload the page.", 401)
        return session

    @app.exception_handler(SalesError)
    async def sales_error(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status)

    @app.middleware("http")
    async def browser_boundary(request: Request, call_next):
        if request.headers.get("host") not in hosts:
            return JSONResponse({"error": {"code": "host", "message": "Only the local DSVM address is allowed."}},
                                status_code=400)
        if request.method != "GET" and not same_origin(request.headers):
            return JSONResponse({"error": {"code": "origin", "message": "A same-origin browser request is required."}},
                                status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
        })
        # Hash the owned inline theme bootstrap instead of enabling arbitrary inline scripts.
        inline = re.findall(r"<script>(.*?)</script>", (STATIC / "index.html").read_text(encoding="utf-8"),
                            flags=re.DOTALL) if (STATIC / "index.html").exists() else []
        hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(code.encode()).digest()).decode() + "'"
                          for code in inline)
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self' {hashes}; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "application": "foundry-voice-sales", "cloud_verified": False}

    @app.post("/api/session")
    async def new_session(body: EmptyBody):
        for key in [key for key, value in sessions.items() if value.expires <= time.monotonic()]:
            del sessions[key]
        if len(sessions) >= 32:
            raise SalesError("session_limit", "Too many local sessions. Close unused sessions and restart the app.", 429)
        token = secrets.token_urlsafe(32)
        sessions[token] = Session(conversation_factory(), time.monotonic() + SESSION_SECONDS)
        response = JSONResponse({"voice_enabled": settings.voice_enabled, "session_expires_in": SESSION_SECONDS})
        response.set_cookie("sales_session", token, httponly=True, samesite="strict",
                            max_age=SESSION_SECONDS, path="/")
        return response

    @app.post("/api/chat")
    async def chat(body: ChatBody, request: Request):
        session = get_session(request.cookies)
        if session.voice:
            raise SalesError("voice_active", "Disconnect voice before sending a typed question.", 409)
        return await answer_until_disconnect(request, session.conversation, body.text, verify_identity)

    @app.post("/api/conversation/reset")
    async def reset(body: EmptyBody, request: Request):
        session = get_session(request.cookies)
        if session.voice:
            raise SalesError("voice_active", "Disconnect voice before starting a new conversation.", 409)
        session.conversation.reset()
        return {"status": "ok"}

    @app.websocket("/api/voice")
    async def voice(browser: WebSocket):
        if not same_origin(browser.headers):
            await browser.close(code=1008)
            return
        await browser.accept()
        session = None
        acquired = False
        try:
            session = get_session(browser.cookies)
            if not settings.voice_enabled or voice_connector is None:
                raise SalesError("voice_disabled", "Voice is not configured. Text chat remains available.", 400)
            if session.voice:
                raise SalesError("voice_active", "Voice is already connected in another tab.", 409)
            session.voice = True
            acquired = True
            if verify_identity:
                await verify_identity()
            async with voice_connector() as upstream:
                relay = VoiceRelay(settings, upstream, browser, session.conversation.answer)
                async with asyncio.timeout(max(0.1, session.expires - time.monotonic())):
                    await relay.run(browser)
        except (SalesError, TimeoutError) as exc:
            message = exc.message if isinstance(exc, SalesError) else "The voice session expired. Reload the page."
            code = exc.code if isinstance(exc, SalesError) else "session_expired"
            if browser.client_state == WebSocketState.CONNECTED:
                await browser.send_json({"type": "error", "code": code, "message": message, "fatal": True})
        except WebSocketDisconnect:
            pass
        finally:
            if session and acquired:
                session.voice = False
            if browser.application_state == WebSocketState.CONNECTED:
                await browser.close()

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return app
