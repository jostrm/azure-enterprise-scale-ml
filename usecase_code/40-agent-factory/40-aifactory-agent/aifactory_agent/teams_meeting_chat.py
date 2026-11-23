"""Explicitly confirmed, process-local citation links to an operator-approved Teams chat.

No history, transcripts, model-authored links or chat credentials are retained. A pending
operation survives voice reset; an ambiguous delivery is never retried.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from azure.core.exceptions import AzureError, HttpResponseError
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse

from . import web
from .security import Principal, authorize
from .teams_meeting_settings import validate_chat_thread_id

OFFER_TTL_SECONDS = 300
SEND_TIMEOUT_SECONDS = 70
MAX_LINKS = 5
MAX_CITATIONS = 100


@dataclass(frozen=True)
class ChatLink:
    title: str
    url: str = field(repr=False)

    def public(self):
        return {"title": self.title, "url": self.url}


@dataclass(frozen=True)
class ChatOffer:
    id: str
    generation: int
    created_at: float
    expires_at: float
    links: tuple[ChatLink, ...] = field(repr=False)


@dataclass
class ChatDraft:
    id: str
    offer_id: str
    generation: int
    thread_id: str = field(repr=False)
    content: str = field(repr=False)
    links: tuple[ChatLink, ...] = field(repr=False)
    expires_at: float
    status: Literal["preview", "in_flight", "sent", "failed", "uncertain"] = "preview"
    message_id: str | None = None
    error_code: str | None = None
    error_status: int = 502
    send_started: bool = False
    task: asyncio.Task | None = field(default=None, repr=False)

    def public(self):
        return {"draft_id": self.id, "voice_generation": self.generation, "thread_id": self.thread_id,
                "content": self.content, "links": [link.public() for link in self.links],
                "expires_at": self.expires_at}


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    voice_generation: int = Field(ge=0)
    offer_id: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$")
    thread_id: str = Field(max_length=512)

    @field_validator("thread_id")
    @classmethod
    def valid_thread(cls, value):
        return validate_chat_thread_id(value)


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    voice_generation: int = Field(ge=0)
    draft_id: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$")
    thread_id: str = Field(max_length=512)
    confirmed: Literal[True]

    @field_validator("thread_id")
    @classmethod
    def valid_thread(cls, value):
        return validate_chat_thread_id(value)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation of the exact preview is required.")
        return value


class AcsChatSender:
    """Lazy SDK 1.3 client; every transport is bounded and owned by this one send."""

    def __init__(self, *, transport_factory=None):
        self._transport_factory = transport_factory

    def _client(self, stack, factory, *args, **options):
        from azure.core.pipeline.transport import RequestsTransport

        transport = (self._transport_factory() if self._transport_factory is not None
                     else RequestsTransport(connection_timeout=10, read_timeout=20))
        try:
            client = factory(*args, transport=transport, **options)
        except BaseException:
            transport.close()
            raise
        stack.callback(client.close)
        return client

    def send(self, endpoint, token, thread_id, content, display_name):
        from azure.communication.chat import ChatClient, ChatMessageType, CommunicationTokenCredential

        options = {"logging_enable": False, "retry_total": 0, "redirect_max": 0,
                   "connection_timeout": 10, "read_timeout": 20}
        with ExitStack() as stack:
            credential = CommunicationTokenCredential(token)
            stack.callback(credential.close)
            client = self._client(stack, ChatClient, endpoint, credential, **options)
            # SDK 1.3 does not inherit parent-client options or its transport.
            thread = self._client(stack, client.get_chat_thread_client, thread_id, **options)
            result = thread.send_message(
                content, sender_display_name=display_name, chat_message_type=ChatMessageType.TEXT)
            message_id = result.id
            if (not isinstance(message_id, str) or not 1 <= len(message_id) <= 512
                    or any(unicodedata.category(char).startswith("C") for char in message_id)):
                raise ValueError("Chat returned an invalid message ID.")
            return message_id


def _safe_url(value, hosts):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return None
    if any(ord(char) < 33 or ord(char) > 126 for char in value) or any(char in value for char in ("\\", "?")):
        return None
    try:
        decoded = unquote(value, errors="strict")
        if (any(unicodedata.category(char).startswith("C") or char.isspace() for char in decoded)
                or any(char in decoded for char in ("\\", "?", "%"))):
            return None
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.netloc != parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.port is not None
                or parsed.query or not re.fullmatch(r"[A-Za-z0-9._~-]*", unquote(parsed.fragment))):
            return None
    except (ValueError, UnicodeError):
        return None
    return value


def _links(citations, hosts):
    if not isinstance(citations, list):
        return ()
    links, seen = [], set()
    for citation in citations[:MAX_CITATIONS]:
        if not isinstance(citation, dict):
            continue
        url = _safe_url(citation.get("source_url"), hosts)
        if url is None or url in seen:
            continue
        seen.add(url)
        # Even a public URL can have a private heading/path; do not copy either into chat.
        links.append(ChatLink(f"Source {len(links) + 1}", url))
        if len(links) == MAX_LINKS:
            break
    return tuple(links)


def capture_meeting_links(app, principal, voice_session, message):
    """Synchronous server-frame hook. Authorization/filtering only, never a cloud call."""
    from .teams_meeting_routes import MeetingPrincipal, _check_session

    result = {key: value for key, value in message.items() if key != "chat_links"}
    if message.get("type") != "answer" or not isinstance(principal, MeetingPrincipal):
        return result
    registry = app.state.teams_meeting_registry
    with registry.lock:
        entry = registry.sessions.get(principal.meeting_session_id)
        if (entry is None or not entry.chat_enabled or not entry.consumed or entry.resetting
                or entry.generation != principal.meeting_generation or entry.voice_session is not voice_session
                or voice_session is None):
            return result
        entry.chat_offer = entry.chat_draft = None
        try:
            _check_session(app, entry)
            authorize(app.state.settings, principal, entry.scope_key, "knowledge.read")
        except PermissionError:
            return result
        if (message.get("scope_key") != entry.scope_key or message.get("audience") != entry.audience
                or message.get("authoritative", True) is not True
                or message.get("citation_validation", "passed") not in ("passed", "sources_attached")):
            return result
        links = _links(message.get("citations"), entry.chat_allowed_link_hosts)
        if not links:
            return result
        now = time.time()
        entry.chat_offer = ChatOffer(secrets.token_urlsafe(24), entry.generation, now,
                                     min(now + OFFER_TTL_SECONDS, entry.expires_at), links)
        result["chat_links"] = {"offer_id": entry.chat_offer.id, "count": len(links)}
        return result


def _error(status, code):
    raise HTTPException(status, {"code": code})


def _authorized(app, session_id, principal, generation, thread_id):
    from .teams_meeting_routes import _check_session

    entry = app.state.teams_meeting_registry.sessions.get(session_id)
    if entry is None:
        _error(410, "meeting_ended")
    if (principal.authorization_context == "teams_meeting"
            or (principal.tenant_id, principal.object_id, principal.client_id)
            != (entry.principal.tenant_id, entry.principal.object_id, entry.principal.client_id)):
        raise PermissionError("Only the original authenticated meeting host and client may post links.")
    _check_session(app, entry)
    authorize(app.state.settings, principal, entry.scope_key, "knowledge.read")
    if not entry.chat_enabled or not entry.chat_disclosure_approved or thread_id != entry.chat_thread_id:
        raise PermissionError("Meeting chat disclosure and the exact thread must be approved.")
    if (entry.resetting or not entry.consumed or entry.generation != generation or entry.voice_session is None):
        _error(409, "voice_generation_changed")
    return entry


def _offer(entry, offer_id):
    offer = entry.chat_offer
    if offer is None or offer.id != offer_id or offer.generation != entry.generation:
        _error(409, "offer_changed")
    if offer.expires_at <= time.time():
        _error(410, "offer_expired")
    return offer


def _fail(draft, code, *, uncertain=False, status=502):
    draft.status = "uncertain" if uncertain else "failed"
    draft.error_code, draft.error_status = code, status


def _deliver(app, entry, principal, draft):
    """Runs once in a worker. Cancellation of the HTTP waiter cannot cancel or replay this write."""
    from .teams_meeting_routes import TokenServiceError, _failure

    registry = app.state.teams_meeting_registry
    try:
        token = app.state.teams_meeting_token_service.chat_token(entry.identity)
        with registry.lock:
            if draft.status != "in_flight":
                return
            current = _authorized(app, entry.id, principal, draft.generation, draft.thread_id)
            _offer(current, draft.offer_id)
            if current.chat_draft is not draft or current.chat_operation is not draft:
                _error(409, "draft_changed")
            draft.send_started = True
        message_id = app.state.teams_meeting_chat_sender.send(
            entry.chat_acs_endpoint, token, draft.thread_id, draft.content, entry.chat_display_name)
        if (not isinstance(message_id, str) or not 1 <= len(message_id) <= 512
                or any(unicodedata.category(char).startswith("C") for char in message_id)):
            raise ValueError("Invalid message ID.")
        with registry.lock:
            # Delivery may have completed after revocation/timeout; report its actual outcome, never retry.
            draft.status, draft.message_id, draft.error_code = "sent", message_id, None
    except (PermissionError, HTTPException) as error:
        with registry.lock:
            _fail(draft, "chat_authorization_changed",
                  status=error.status_code if isinstance(error, HTTPException) else 403)
    except HttpResponseError as error:
        with registry.lock:
            if error.status_code in {401, 403, 429}:
                _fail(draft, f"chat_rejected_{error.status_code}")
            else:
                _fail(draft, "delivery_unknown" if draft.send_started else "chat_token_unavailable",
                      uncertain=draft.send_started)
    except (AzureError, TokenServiceError, ValueError, ImportError) as error:
        with registry.lock:
            unknown = draft.send_started and not isinstance(error, ImportError)
            _fail(draft, "delivery_unknown" if unknown else "chat_unavailable", uncertain=unknown)
    except Exception as error:
        with registry.lock:
            _fail(draft, "delivery_unknown" if draft.send_started else "chat_unavailable",
                  uncertain=draft.send_started)
        _failure("meeting_chat_unexpected", error)


def _response(draft, *, duplicate=False):
    if draft.status == "sent":
        return JSONResponse({"status": "sent", "message_id": draft.message_id, "thread_id": draft.thread_id},
                            headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    if draft.status == "in_flight":
        _error(409, "sending")
    _error(409 if duplicate else draft.error_status, draft.error_code or "delivery_unknown")


def register_meeting_chat(app):
    registry = app.state.teams_meeting_registry
    app.state.teams_meeting_chat_sender = AcsChatSender()

    @app.post("/api/teams-meetings/sessions/{session_id}/links/preview")
    def preview(session_id: str, body: PreviewRequest, principal: Annotated[Principal, Depends(web.get_principal)]):
        with registry.lock:
            entry = _authorized(app, session_id, principal, body.voice_generation, body.thread_id)
            offer = _offer(entry, body.offer_id)
            if entry.chat_draft is None:
                content = "ESAF Agent Chat sources:\n" + "\n".join(
                    f"{i}. {link.title}\n{link.url}" for i, link in enumerate(offer.links, start=1))
                entry.chat_draft = ChatDraft(secrets.token_urlsafe(24), offer.id, offer.generation,
                                             entry.chat_thread_id, content, offer.links, offer.expires_at)
            return JSONResponse(entry.chat_draft.public(),
                                headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @app.post("/api/teams-meetings/sessions/{session_id}/links/send")
    async def send(session_id: str, body: SendRequest, principal: Annotated[Principal, Depends(web.get_principal)]):
        with registry.lock:
            entry = _authorized(app, session_id, principal, body.voice_generation, body.thread_id)
            draft = entry.chat_draft
            if draft is None or draft.id != body.draft_id:
                _error(409, "draft_changed")
            _offer(entry, draft.offer_id)
            if draft.status != "preview":
                return _response(draft, duplicate=True)
            previous = entry.chat_operation
            if previous is not None and previous.task is not None and not previous.task.done():
                _error(409, "sending")
            draft.status = "in_flight"
            entry.chat_operation = draft
            draft.task = asyncio.create_task(asyncio.to_thread(_deliver, app, entry, principal, draft))
            task = draft.task
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=SEND_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.CancelledError) as error:
            with registry.lock:
                if draft.status == "in_flight":
                    _fail(draft, "delivery_unknown" if draft.send_started else "chat_token_unavailable",
                          uncertain=draft.send_started)
            if isinstance(error, asyncio.CancelledError):
                raise
        with registry.lock:
            return _response(draft)
