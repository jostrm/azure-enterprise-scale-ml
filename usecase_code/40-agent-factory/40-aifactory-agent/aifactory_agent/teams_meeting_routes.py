"""Attended meeting admission and short-lived ACS identities.

The opaque relay ticket and cleanup registry are process-local: deployment requires exactly
one replica and one ASGI worker; generic session affinity is insufficient. ACS credentials are not
meeting-bound; the server's governed voice relay and disclosure policy always are.
No meeting URL, credential, transcript or audio is persisted or logged here.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import secrets
import threading
import time
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Annotated, Callable, Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from azure.core.exceptions import AzureError, HttpResponseError, ResourceNotFoundError
from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse

from . import web
from .security import Principal, authorize
from .teams_meeting_settings import validate_meeting_url

LOGGER = logging.getLogger(__name__)
CleanupStatus = Literal["complete", "pending", "expired_unconfirmed"]


@dataclass(frozen=True)
class MeetingIdentity:
    user_id: str = field(repr=False)
    token: str = field(repr=False)
    expires_at: float


class TokenServiceError(RuntimeError):
    """Expected ACS/credential failures, with safe diagnostics and recoverable identity ownership."""

    def __init__(self, code: Literal["acs_issue_failed", "acs_delete_failed", "acs_invalid_response"],
                 source_type: str, *, identity: MeetingIdentity | None = None):
        if code not in {"acs_issue_failed", "acs_delete_failed", "acs_invalid_response"}:
            raise ValueError("Invalid token service error code.")
        super().__init__(code)
        self.code = code
        self.source_type = re.sub(r"[^A-Za-z0-9_]", "", source_type)[:64] or "UnknownError"
        self.identity = identity
        self.cleanup_pending = False


def _failure(code, error):
    error_type = (error.source_type if isinstance(error, TokenServiceError)
                  else re.sub(r"[^A-Za-z0-9_]", "", type(error).__name__)[:64])
    LOGGER.warning("teams_meeting_failure code=%s error_type=%s", code, error_type)


class AcsTokenService:
    """Lazy managed-identity-only client; constructing the app never contacts ACS."""

    def __init__(self, settings, *, managed_identity_client_id=None):
        self.settings = settings
        self.managed_identity_client_id = settings.managed_identity_client_id or managed_identity_client_id

    @contextmanager
    def _client(self):
        from azure.communication.identity import CommunicationIdentityClient
        from azure.core.pipeline.transport import RequestsTransport
        from azure.identity import ManagedIdentityCredential

        kwargs = ({"client_id": str(self.managed_identity_client_id)} if self.managed_identity_client_id else {})
        with ExitStack() as stack:
            credential = ManagedIdentityCredential(**kwargs)
            stack.callback(credential.close)
            # Identity SDK 1.5 has no public close(). Own its transport rather than calling a nonexistent method.
            transport = RequestsTransport()
            stack.callback(transport.close)
            yield CommunicationIdentityClient(
                self.settings.acs_endpoint, credential, transport=transport, logging_enable=False,
                connection_timeout=10, read_timeout=20, retry_total=2,
            )

    def issue(self) -> MeetingIdentity:
        from azure.communication.identity import CommunicationTokenScope

        identity = None
        try:
            with self._client() as client:
                # ACS permits 1-24 hours. Use its minimum; the relay has a shorter independent limit.
                user, token = client.create_user_and_token(
                    scopes=[CommunicationTokenScope.VOIP], token_expires_in=timedelta(hours=1))
                identity = MeetingIdentity(user.properties["id"], token.token, time.time() + 3600)
                try:
                    # SDK 1.5 returns the service's ISO-8601 string in AccessToken.expires_on.
                    expiry = token.expires_on
                    if isinstance(expiry, str):
                        parsed = datetime.fromisoformat(expiry)
                        if parsed.tzinfo is None:
                            raise ValueError("Timezone required")
                        expiry = parsed.timestamp()
                    if type(expiry) not in {int, float} or not math.isfinite(expiry):
                        raise ValueError("Invalid lifetime")
                    identity = replace(identity, expires_at=float(expiry))
                except (ValueError, OverflowError) as error:
                    raise TokenServiceError("acs_invalid_response", type(error).__name__, identity=identity) from None
            return identity
        except AzureError as error:
            raise TokenServiceError("acs_issue_failed", type(error).__name__, identity=identity) from None
        except Exception as error:
            # Preserve ownership on programming failures without disguising their original type.
            if identity is not None:
                error.meeting_identity = identity
            raise

    def revoke(self, identity: MeetingIdentity) -> None:
        from azure.communication.identity import CommunicationUserIdentifier

        try:
            with self._client() as client:
                try:
                    client.delete_user(CommunicationUserIdentifier(identity.user_id))
                except ResourceNotFoundError:
                    return
                except HttpResponseError as error:
                    if error.status_code == 404:
                        return
                    raise
        except AzureError as error:
            raise TokenServiceError("acs_delete_failed", type(error).__name__, identity=identity) from None

    def close(self):
        return None  # All transports and credentials are owned by individual calls.


@dataclass(frozen=True)
class MeetingPrincipal(Principal):
    permission_ceiling: frozenset[str] = field(default_factory=lambda: frozenset({"knowledge.read"}))
    scope_ceiling: frozenset[str] = field(default_factory=frozenset)
    meeting_session_id: str = field(default="", repr=False)
    meeting_generation: int = 0
    authorization_guard: Callable | None = field(default=None, repr=False, compare=False)


@dataclass
class MeetingSession:
    id: str
    ticket_hash: str = field(repr=False)
    principal: Principal
    policy_id: str
    scope_key: str
    audience: str
    meeting_url: str = field(repr=False)
    expires_at: float
    identity: MeetingIdentity = field(repr=False)
    meeting_tenant_id: str
    external_audience_disclosure_approved: bool
    allowed_participant_object_ids: frozenset[str] = field(default_factory=frozenset)
    generation: int = 0
    resetting: bool = False
    consumed: bool = False
    revoked: bool = False
    cleaning: bool = False
    cleanup_attempts: int = 0
    timer: asyncio.Task | None = field(default=None, repr=False)
    voice_session: object | None = field(default=None, repr=False)


class MeetingRegistry:
    def __init__(self):
        self.sessions: dict[str, MeetingSession] = {}
        self.lock = threading.RLock()
        self.pending: set[tuple[str, str]] = set()
        self.closing = False


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    meeting_url: str = Field(max_length=4096)
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    audience: Literal["platform", "project"]
    consent_acknowledged: Literal[True]

    @field_validator("consent_acknowledged", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit consent is required.")
        return value

    @field_validator("meeting_url")
    @classmethod
    def valid_url(cls, value):
        return validate_meeting_url(value)


class VoiceResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    voice_generation: int = Field(ge=0)


async def _issue_identity(service, reclaim):
    async def recover(error):
        identity = getattr(error, "identity", None) or getattr(error, "meeting_identity", None)
        if identity is not None:
            result = await reclaim(identity)
            if isinstance(error, TokenServiceError):
                error.cleanup_pending = result != "complete"
        _failure(error.code if isinstance(error, TokenServiceError) else "meeting_issue_unexpected", error)

    task = asyncio.create_task(asyncio.to_thread(service.issue))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        async def finish_creation():
            try:
                identity = await task
            except TokenServiceError as error:
                await recover(error)
            except Exception as error:
                await recover(error)
                raise
            else:
                await reclaim(identity)

        cleanup = asyncio.create_task(finish_creation())
        # A second disconnect/shutdown cancellation must not detach the still-running SDK thread.
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()
        raise
    except Exception as error:
        await recover(error)
        raise


def _policy(settings, principal, meeting_url, scope_key):
    meeting = getattr(settings, "teams_meetings", None)
    if not meeting or not meeting.enabled or not settings.voice.enabled:
        raise PermissionError("Meeting delegation is disabled.")
    if (principal.tenant_id != settings.tenant_id
            or principal.object_id not in {str(host) for host in meeting.allowed_host_object_ids}):
        raise PermissionError("The caller is not an approved meeting host.")
    # This is the original authenticated host, not the derived delegate; retain all channel ceilings.
    if principal.authorization_context == "teams_meeting":
        raise PermissionError("Meeting delegates cannot delegate their own sessions.")
    authorize(settings, principal, scope_key, "knowledge.read")
    policy = next((policy for policy in meeting.policies
                   if policy.scope_key == scope_key and policy.meeting_url == meeting_url
                   and policy.meeting_safe_knowledge), None)
    if policy is None:
        raise PermissionError("This exact meeting and disclosure scope are not approved.")
    listeners = policy.allowed_participant_object_ids
    if (not 1 <= len(listeners) <= 32 or len(set(listeners)) != len(listeners)
            or any(not listener.int for listener in listeners)):
        raise PermissionError("Meeting disclosure requires a bounded, exact listener allowlist.")
    if policy.meeting_tenant_id is not None and not policy.meeting_tenant_id.int:
        raise PermissionError("The explicit meeting tenant must be nonzero.")
    meeting_tenant_id = str(policy.meeting_tenant_id or settings.tenant_id)
    if meeting_tenant_id == settings.tenant_id:
        if policy.external_audience_disclosure_approved is not False:
            raise PermissionError("External disclosure approval is not valid for a same-tenant meeting.")
        if any(
            not any(str(grant.object_id) == str(listener) and scope_key in grant.scopes
                    and "knowledge.read" in grant.permissions for grant in settings.auth.grants)
            for listener in listeners
        ):
            raise PermissionError("Every approved listener must retain an existing exact-scope knowledge grant.")
    elif policy.meeting_tenant_id is None or policy.external_audience_disclosure_approved is not True:
        raise PermissionError("External meeting disclosure requires explicit tenant and audience approval.")
    # External approval permits disclosure only; the authenticated host and app grants remain unchanged.
    parsed = urlsplit(meeting_url)
    context = parse_qs(parsed.query, keep_blank_values=True).get("context")
    if context is not None or parsed.path.startswith("/l/meetup-join/"):
        try:
            if context is None or len(context) != 1:
                raise ValueError
            tenant = json.loads(context[0])["Tid"]
            if not isinstance(tenant, str) or str(UUID(tenant)) != meeting_tenant_id:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise PermissionError("The meeting URL tenant does not match the approved meeting tenant.") from None
    return policy


def _check_session(app, entry, settings=None):
    if entry.revoked or entry.expires_at <= time.time():
        raise PermissionError("The meeting session has ended.")
    current = settings or app.state.settings
    policy = _policy(current, entry.principal, entry.meeting_url, entry.scope_key)
    if (policy.id != entry.policy_id
            or str(policy.meeting_tenant_id or current.tenant_id) != entry.meeting_tenant_id
            or policy.external_audience_disclosure_approved != entry.external_audience_disclosure_approved
            or frozenset(map(str, policy.allowed_participant_object_ids)) != entry.allowed_participant_object_ids):
        raise PermissionError("The meeting policy changed.")


def assert_meeting_policy(settings, principal, scope_key, permission="knowledge.read"):
    """Security.authorize hook: never accept a meeting marker without its server-bound guard."""
    guard = getattr(principal, "authorization_guard", None)
    if not isinstance(principal, MeetingPrincipal) or not callable(guard):
        raise PermissionError("A server-bound meeting session is required.")
    guard(settings, principal, scope_key, permission)


def constrain_meeting_principal(settings, principal, scope_key):
    """Intersect an admitted delegate's ceilings; never manufacture admission from a host JWT.

    The admission path is consume_meeting_session after delegated authentication. Its guard
    checks the original host, not this derived principal, so authorize cannot recurse here.
    """
    assert_meeting_policy(settings, principal, scope_key)
    if (principal.permission_ceiling is None or principal.scope_ceiling is None
            or "knowledge.read" not in principal.permission_ceiling or scope_key not in principal.scope_ceiling):
        raise PermissionError("The admitted meeting principal lacks the required scope ceiling.")
    return replace(
        principal, permission_ceiling=principal.permission_ceiling & frozenset({"knowledge.read"}),
        scope_ceiling=principal.scope_ceiling & frozenset({scope_key}), authorization_context="teams_meeting",
    )


def consume_meeting_session(app, principal, ticket, scope_key, audience):
    """Called ONLY after normal delegated authentication by the existing voice relay."""
    registry = getattr(app.state, "teams_meeting_registry", None)
    if registry is None or not isinstance(ticket, str) or not 32 <= len(ticket) <= 256:
        raise PermissionError("A valid meeting session is required.")
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    with registry.lock:
        entry = next((entry for entry in registry.sessions.values()
                      if secrets.compare_digest(entry.ticket_hash, digest)), None)
        if (entry is None or entry.consumed or entry.resetting or entry.principal.tenant_id != principal.tenant_id
                or entry.principal.object_id != principal.object_id or entry.principal.client_id != principal.client_id
                or entry.scope_key != scope_key or entry.audience != audience):
            raise PermissionError("The meeting session is not valid for this caller and scope.")
        _check_session(app, entry)
        entry.consumed = True
        generation = entry.generation

    def guard(settings, current_principal, requested_scope, permission):
        if requested_scope != entry.scope_key or permission != "knowledge.read":
            raise PermissionError("Meeting delegates have only approved, exact-scope knowledge access.")
        if (current_principal.tenant_id, current_principal.object_id, current_principal.client_id,
                current_principal.meeting_session_id, current_principal.meeting_generation) != (
                entry.principal.tenant_id, entry.principal.object_id, entry.principal.client_id, entry.id, generation):
            raise PermissionError("The meeting delegate does not match its admitted host.")
        with registry.lock:
            if registry.sessions.get(entry.id) is not entry or entry.generation != generation:
                raise PermissionError("The meeting session has ended.")
            # Prepared turns may retain old settings while operators revoke live grants.
            _check_session(app, entry)
            if settings is not app.state.settings:
                _check_session(app, entry, settings)

    admitted = MeetingPrincipal(
        tenant_id=principal.tenant_id, object_id=principal.object_id, scopes=frozenset({scope_key}),
        permissions=frozenset({"knowledge.read"}), client_id=principal.client_id,
        scope_ceiling=frozenset({scope_key}), meeting_session_id=entry.id, authorization_guard=guard,
        authorization_context="teams_meeting", meeting_generation=generation,
    )
    return constrain_meeting_principal(app.state.settings, admitted, scope_key)


def meeting_session_seconds(app, principal):
    registry = getattr(app.state, "teams_meeting_registry", None)
    if registry is None:
        return 0.0
    with registry.lock:
        entry = registry.sessions.get(getattr(principal, "meeting_session_id", ""))
        if entry is None:
            return 0.0
        if entry.generation != getattr(principal, "meeting_generation", None):
            raise PermissionError("The meeting voice generation has ended.")
        _check_session(app, entry)
        return max(0.0, entry.expires_at - time.time())


def bind_meeting_voice_session(app, principal, voice_session):
    """Relay hook after construction, before run: expiry/DELETE must also stop active audio."""
    registry = app.state.teams_meeting_registry
    with registry.lock:
        entry = registry.sessions.get(principal.meeting_session_id)
        if (entry is None or entry.voice_session is not None
                or entry.generation != getattr(principal, "meeting_generation", None)):
            raise PermissionError("The meeting relay is no longer available.")
        _check_session(app, entry)
        entry.voice_session = voice_session


def _background(work):
    task = asyncio.create_task(work)

    def observed(completed):
        if not completed.cancelled():
            error = completed.exception()
            if error is not None:
                _failure("meeting_background_failed", error)

    task.add_done_callback(observed)
    return task


def _pending_cleanup(app, entry) -> CleanupStatus:
    registry = app.state.teams_meeting_registry
    with registry.lock:
        remaining = entry.identity.expires_at - time.time()
        if remaining <= 0:
            registry.sessions.pop(entry.id, None)
            LOGGER.error("teams_meeting_failure code=acs_cleanup_expired_unconfirmed")
            return "expired_unconfirmed"
        if not registry.closing:
            delay = min(30 * 2 ** min(max(0, entry.cleanup_attempts - 1), 4), remaining)

            async def retry():
                await asyncio.sleep(delay)
                await end_meeting_session(app, entry.id)

            entry.timer = _background(retry())
    return "pending"


async def _delete_identity(app, entry) -> CleanupStatus:
    entry.cleanup_attempts += 1
    try:
        await asyncio.to_thread(app.state.teams_meeting_token_service.revoke, entry.identity)
    except TokenServiceError as error:
        _failure(error.code, error)
        return _pending_cleanup(app, entry)
    except asyncio.CancelledError as error:
        _failure("meeting_cleanup_cancelled", error)
        _pending_cleanup(app, entry)
        raise
    except Exception as error:
        _failure("meeting_cleanup_unexpected", error)
        _pending_cleanup(app, entry)
        raise
    with app.state.teams_meeting_registry.lock:
        app.state.teams_meeting_registry.sessions.pop(entry.id, None)
    return "complete"


async def end_meeting_session(app, session_id, *, expected_generation: int | None = None) -> CleanupStatus:
    """Invalidate immediately; report ACS completion separately and retain pending cleanup for retry."""
    registry = getattr(app.state, "teams_meeting_registry", None)
    if registry is None:
        return "complete"
    with registry.lock:
        entry = registry.sessions.get(session_id)
        if entry is None or (expected_generation is not None and entry.generation != expected_generation):
            return "complete"
        if entry.cleaning:
            return "pending"
        entry.revoked = True
        entry.cleaning = True
        if entry.timer and entry.timer is not asyncio.current_task():
            entry.timer.cancel()
    try:
        try:
            if entry.voice_session is not None:
                await entry.voice_session.end("meeting_ended")
        except Exception as error:
            _failure("meeting_relay_cleanup_failed", error)
            raise
        finally:
            entry.voice_session = None
            result = await _delete_identity(app, entry)
    finally:
        entry.cleaning = False
    return result


async def _reclaim_identity(app, principal, policy, body, identity) -> CleanupStatus:
    entry = MeetingSession(
        secrets.token_urlsafe(24), "", principal, policy.id, body.scope_key,
        body.audience, body.meeting_url, time.time(), identity, revoked=True,
        meeting_tenant_id=str(policy.meeting_tenant_id or principal.tenant_id),
        external_audience_disclosure_approved=policy.external_audience_disclosure_approved,
    )
    with app.state.teams_meeting_registry.lock:
        app.state.teams_meeting_registry.sessions[entry.id] = entry
    return await end_meeting_session(app, entry.id)


def register_teams_meetings(app: FastAPI) -> None:
    meeting = app.state.settings.teams_meetings
    app.state.teams_meeting_registry = registry = MeetingRegistry()
    app.state.teams_meeting_token_service = AcsTokenService(
        meeting, managed_identity_client_id=app.state.settings.azure.managed_identity_client_id)

    @app.get("/api/teams-meetings/status")
    def status(principal: Annotated[Principal, Depends(web.get_principal)]):
        current = app.state.settings
        policies = []
        for policy in current.teams_meetings.policies:
            try:
                _policy(current, principal, policy.meeting_url, policy.scope_key)
            except PermissionError:
                continue
            policies.append({
                "id": policy.id, "scope_key": policy.scope_key,
                "meeting_tenant_id": str(policy.meeting_tenant_id or current.tenant_id),
                "external_audience_disclosure_approved": policy.external_audience_disclosure_approved,
            })
        return JSONResponse({"enabled": current.teams_meetings.enabled, "policies": policies,
                             "attended_only": True}, headers={"Cache-Control": "no-store"})

    @app.post("/api/teams-meetings/sessions")
    async def create(body: JoinRequest, principal: Annotated[Principal, Depends(web.get_principal)]):
        current = app.state.settings
        policy = _policy(current, principal, body.meeting_url, body.scope_key)
        host = (principal.tenant_id, principal.object_id)
        with registry.lock:
            if host in registry.pending or any((entry.principal.tenant_id, entry.principal.object_id) == host
                                                for entry in registry.sessions.values()):
                raise HTTPException(409, "Leave the existing meeting session first.")
            if len(registry.sessions) + len(registry.pending) >= current.teams_meetings.max_concurrent_sessions:
                raise HTTPException(429, "Meeting capacity is exhausted.")
            registry.pending.add(host)
        identity = None
        reclaim = lambda identity: _reclaim_identity(app, principal, policy, body, identity)
        try:
            try:
                identity = await _issue_identity(app.state.teams_meeting_token_service, reclaim)
            except TokenServiceError as error:
                raise HTTPException(503, {"code": error.code, "message": "Meeting identity service is unavailable.",
                                          "cleanup_pending": error.cleanup_pending}) from None
            # Policy may have changed while obtaining the external identity.
            current = app.state.settings
            if _policy(current, principal, body.meeting_url, body.scope_key) != policy:
                raise PermissionError("The meeting policy changed during admission.")
            now = time.time()
            expires = min(now + current.teams_meetings.max_session_seconds, identity.expires_at - 15)
            if expires <= now + 30:
                raise HTTPException(503, "The meeting identity has insufficient lifetime.")
            ticket = secrets.token_urlsafe(48)
            entry = MeetingSession(
                secrets.token_urlsafe(24), hashlib.sha256(ticket.encode()).hexdigest(), principal,
                policy.id, body.scope_key, body.audience, body.meeting_url, expires, identity,
                meeting_tenant_id=str(policy.meeting_tenant_id or current.tenant_id),
                external_audience_disclosure_approved=policy.external_audience_disclosure_approved,
                allowed_participant_object_ids=frozenset(map(str, policy.allowed_participant_object_ids)),
            )
            with registry.lock:
                registry.sessions[entry.id] = entry

            async def expire():
                await asyncio.sleep(max(0, entry.expires_at - time.time()))
                await end_meeting_session(app, entry.id)

            entry.timer = _background(expire())
            identity = None  # Ownership has moved to the session registry.
            return JSONResponse({
                "session_id": entry.id, "meeting_session": ticket, "meeting_url": entry.meeting_url,
                "voice_generation": entry.generation,
                "scope_key": entry.scope_key, "audience": entry.audience, "acs_token": entry.identity.token,
                "acs_expires_at": entry.identity.expires_at, "expires_at": entry.expires_at,
                "display_name": current.teams_meetings.display_name,
                "meeting_tenant_id": entry.meeting_tenant_id,
                "external_audience_disclosure_approved": entry.external_audience_disclosure_approved,
                "allowed_participant_object_ids": list(map(str, policy.allowed_participant_object_ids)),
                "lobby_timeout_seconds": current.teams_meetings.lobby_timeout_seconds,
                "audio": {"encoding": "pcm16", "sample_rate": 24000, "channels": 1},
            }, status_code=201, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        finally:
            with registry.lock:
                registry.pending.discard(host)
            if identity is not None:
                await reclaim(identity)

    @app.post("/api/teams-meetings/sessions/{session_id}/voice-reset")
    async def reset_voice(session_id: str, body: VoiceResetRequest,
                          principal: Annotated[Principal, Depends(web.get_principal)]):
        with registry.lock:
            entry = registry.sessions.get(session_id)
            if entry is None:
                raise HTTPException(404, "The meeting session was not found.")
            if (principal.authorization_context == "teams_meeting"
                    or (entry.principal.tenant_id, entry.principal.object_id, entry.principal.client_id)
                    != (principal.tenant_id, principal.object_id, principal.client_id)):
                raise PermissionError("Only this meeting host and client may reset its voice session.")
            _check_session(app, entry)
            authorize(app.state.settings, principal, entry.scope_key, "knowledge.read")
            if entry.resetting or entry.generation != body.voice_generation:
                raise HTTPException(409, "The meeting voice generation changed; do not replay this reset.")
            ticket = secrets.token_urlsafe(48)
            entry.generation += 1
            generation = entry.generation
            entry.ticket_hash = hashlib.sha256(ticket.encode()).hexdigest()
            entry.consumed = False
            entry.resetting = True
            previous, entry.voice_session = entry.voice_session, None
        completed = False
        try:
            if previous is not None:
                await previous.end("meeting_voice_reset")
            with registry.lock:
                if registry.sessions.get(entry.id) is not entry or entry.generation != generation:
                    raise PermissionError("The meeting session ended during its voice reset.")
                _check_session(app, entry)
                response = JSONResponse({
                    "session_id": entry.id, "meeting_session": ticket, "voice_generation": generation,
                }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
                entry.resetting = False
                completed = True
                return response
        except Exception as error:
            _failure("meeting_voice_reset_failed", error)
            raise
        finally:
            if not completed:
                await end_meeting_session(app, entry.id, expected_generation=generation)

    @app.delete("/api/teams-meetings/sessions/{session_id}")
    async def end(session_id: str, principal: Annotated[Principal, Depends(web.get_principal)]):
        with registry.lock:
            entry = registry.sessions.get(session_id)
            if entry is None:
                return Response(status_code=204, headers={"Cache-Control": "no-store"})
            if (entry.principal.tenant_id, entry.principal.object_id) != (principal.tenant_id, principal.object_id):
                raise PermissionError("Only this meeting host may end the session.")
        result = await end_meeting_session(app, session_id)
        if result != "complete":
            return JSONResponse({"relay_invalidated": True, "acs_cleanup": result}, status_code=202,
                                headers={"Cache-Control": "no-store", "Retry-After": "30"})
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    async def shutdown():
        registry.closing = True
        failures = []
        try:
            for session_id in list(registry.sessions):
                try:
                    await end_meeting_session(app, session_id)
                except Exception as error:
                    failures.append(error)
        finally:
            for entry in registry.sessions.values():
                if entry.timer:
                    entry.timer.cancel()
            if registry.sessions:
                LOGGER.error("teams_meeting_failure code=acs_cleanup_pending_shutdown count=%d", len(registry.sessions))
            await asyncio.to_thread(app.state.teams_meeting_token_service.close)
        if failures:
            raise ExceptionGroup("Meeting shutdown cleanup failed.", failures)

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application) as state:
            try:
                yield state
            finally:
                await shutdown()

    app.router.lifespan_context = lifespan
