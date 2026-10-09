"""Live voice for the AI Factory Agent: Azure Voice Live as a *speech shell*.

Voice Live listens (streaming speech to text with semantic turn detection, noise suppression and echo
cancellation) and speaks (Azure neural/HD text to speech). It never writes an answer: every spoken reply is the
governed backend's own answer (`Conversation.answer`), sent as a predefined message. Authorization, readiness,
retrieval, tool policy, citation validation and audit therefore stay exactly as in the typed chat.

Browser <-WSS-> this relay <-WSS (managed identity)-> Voice Live. The browser never receives Foundry credentials,
the Voice Live session is configured only from server settings, and nothing here stores audio or transcripts.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import importlib.util
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol
from urllib.parse import urlencode

from .speech import spoken_text
from .voice_settings import VoiceSettings, effective_endpoint

LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 24000
BYTES_PER_SECOND = SAMPLE_RATE * 2
MAX_AUDIO_FRAME = 16384
AUDIO_BURST_SECONDS = 10.0
AUDIO_SUSTAINED_FACTOR = 2.0
MAX_UPSTREAM_MESSAGE = 4 * 1024 * 1024
PROTOCOL_VERSION = 1

INSTRUCTIONS = (
    "You are a speech shell for the Enterprise Scale AI Factory Agent. Never generate answers or call tools; "
    "the application supplies every reply as predefined text to be spoken."
)
APOLOGY = "Sorry, I could not complete that. The details are on screen."
VOICE_ERROR = "The speech service reported a problem. Typing still works."
BENIGN_UPSTREAM_ERRORS = frozenset({"response_cancel_not_active"})


class VoiceAnswerError(Exception):
    """A safe, user-presentable failure of the governed answer path (never carries internal exception text)."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


class VoiceProtocolError(Exception):
    """The browser violated the relay protocol (bad frame, unknown control message, excessive audio rate)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class VoiceUnavailable(RuntimeError):
    """Live voice cannot start in this deployment (for example the websocket library is missing)."""


class ClientGone(ConnectionError):
    """The browser connection is gone; nothing more can be delivered."""


class VoiceUpstream(Protocol):
    async def send(self, event: dict) -> None: ...

    def __aiter__(self) -> AsyncIterator[dict]: ...

    async def close(self) -> None: ...


class ClientChannel(Protocol):
    async def send_json(self, message: dict) -> None: ...

    async def send_audio(self, data: bytes) -> None: ...


Answerer = Callable[[str], Awaitable[dict]]


def connection_url(voice: VoiceSettings, foundry_account: str) -> str:
    host = effective_endpoint(voice, foundry_account).removeprefix("https://")
    return f"wss://{host}/voice-live/realtime?" + urlencode({"api-version": voice.api_version, "model": voice.model})


def session_update_event(voice: VoiceSettings, session_id: str) -> dict:
    """The only session configuration ever sent; no field comes from the browser."""
    session: dict[str, Any] = {
        "modalities": ["text", "audio"],
        "instructions": INSTRUCTIONS,
        "voice": {"type": "azure-standard", "name": voice.voice_name,
                  **({"temperature": voice.voice_temperature} if voice.voice_temperature is not None else {})},
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "input_audio_sampling_rate": SAMPLE_RATE,
        "turn_detection": {"type": voice.turn_detection, "silence_duration_ms": voice.silence_duration_ms,
                           "create_response": False, "interrupt_response": True},
        "input_audio_transcription": {"model": "azure-speech", "language": ",".join(voice.input_languages)},
        "metadata": {"app": "aifactory-agent-voice", "session": session_id},
    }
    if voice.noise_suppression:
        session["input_audio_noise_reduction"] = {"type": "azure_deep_noise_suppression"}
    if voice.echo_cancellation:
        session["input_audio_echo_cancellation"] = {"type": "server_echo_cancellation"}
    return {"type": "session.update", "session": session}


def speak_event(text: str) -> dict:
    return {"type": "response.create", "response": {"pre_generated_assistant_message": {
        "type": "message", "role": "assistant", "content": [{"type": "text", "text": text}]}}}


class _AudioBudget:
    """Token bucket: absorbs a stalled connection's backlog (up to ten seconds of audio), sustained at most twice real time."""

    def __init__(self, clock: Callable[[], float]):
        self.capacity = BYTES_PER_SECOND * AUDIO_BURST_SECONDS
        self.rate = BYTES_PER_SECOND * AUDIO_SUSTAINED_FACTOR
        self.level, self.clock = self.capacity, clock
        self.updated = clock()

    def take(self, amount: int) -> bool:
        now = self.clock()
        self.level = min(self.capacity, self.level + (now - self.updated) * self.rate)
        self.updated = now
        if amount > self.level:
            return False
        self.level -= amount
        return True


class VoiceSession:
    """One browser conversation. States: listening -> thinking -> speaking -> listening."""

    def __init__(self, voice: VoiceSettings, upstream: VoiceUpstream, channel: ClientChannel, answer: Answerer, *,
                 session_id: str | None = None, idle_timeout: float | None = None, max_duration: float | None = None,
                 handshake_timeout: float = 10.0, answer_timeout: float | None = None,
                 audio_clock: Callable[[], float] = time.monotonic):
        self.voice, self.upstream, self.channel, self._answer = voice, upstream, channel, answer
        self.session_id = session_id or uuid.uuid4().hex
        self._idle_timeout = voice.idle_timeout_seconds if idle_timeout is None else idle_timeout
        self._max_duration = voice.max_session_seconds if max_duration is None else max_duration
        self._answer_timeout = voice.answer_timeout_seconds if answer_timeout is None else answer_timeout
        self._handshake_timeout = handshake_timeout
        self._budget = _AudioBudget(audio_clock)
        self._ready = False
        self._state: str | None = None
        self._turn = 0
        self._answer_task: asyncio.Task | None = None
        self._partials: dict[str, str] = {}
        self._current_response: str | None = None
        self._response_active = False
        self._cancel_next_response = False
        self._cancelled: set[str] = set()
        self._ended = asyncio.Event()
        self._end_reason = "ended"
        self._last_activity = time.monotonic()
        self.turns = 0

    async def run(self) -> str:
        reason, started = "error", time.monotonic()
        tasks: list[asyncio.Task] = []
        try:
            iterator = self.upstream.__aiter__()
            try:
                await self._handshake(iterator)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("voice_handshake_failed session=%s error=%s", self.session_id, type(exc).__name__)
                await self._fatal("voice_unavailable", "Live voice could not start. Typing still works.")
                reason = "handshake_failed"
                return reason
            pump = asyncio.create_task(self._pump(iterator))
            watchdog = asyncio.create_task(self._watchdog())
            ended = asyncio.create_task(self._ended.wait())
            tasks = [pump, watchdog, ended]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if ended in done:
                reason = self._end_reason
            elif watchdog in done:
                reason = watchdog.result()
            else:
                failure = pump.exception()
                if isinstance(failure, ClientGone):
                    reason = "client_closed"
                else:
                    reason = "upstream_closed"
                    await self._fatal("voice_unavailable", "The speech service connection ended. Typing still works.")
            return reason
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._shutdown(reason, time.monotonic() - started)

    async def end(self, reason: str = "ended") -> None:
        self._end_reason = reason
        self._ended.set()

    async def handle_audio(self, data: bytes) -> None:
        if not self._ready:
            return
        if len(data) < 2 or len(data) % 2 or len(data) > MAX_AUDIO_FRAME:
            raise VoiceProtocolError("audio_frame")
        if not self._budget.take(len(data)):
            raise VoiceProtocolError("audio_rate")
        await self.upstream.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(data).decode("ascii")})

    async def handle_control(self, message: Any) -> None:
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "interrupt":
            await self._barge_in()
        elif kind == "end":
            await self.end("ended")
        elif kind == "ping":
            await self.channel.send_json({"type": "pong"})
        else:
            raise VoiceProtocolError("control")

    async def _handshake(self, iterator) -> None:
        first = await asyncio.wait_for(iterator.__anext__(), self._handshake_timeout)
        if first.get("type") != "session.created":
            raise VoiceUnavailable("The speech service did not open a session.")
        await self.upstream.send(session_update_event(self.voice, self.session_id))
        while True:
            event = await asyncio.wait_for(iterator.__anext__(), self._handshake_timeout)
            if event.get("type") == "session.updated":
                break
            if event.get("type") == "error":
                raise VoiceUnavailable("The speech service rejected the session configuration.")
        self._ready = True
        self._touch()
        await self.channel.send_json({
            "type": "ready", "session_id": self.session_id, "protocol": PROTOCOL_VERSION,
            "audio": {"encoding": "pcm16", "sample_rate": SAMPLE_RATE, "channels": 1},
            "limits": {"max_session_seconds": int(self._max_duration), "idle_timeout_seconds": int(self._idle_timeout)},
            "voice": {"name": self.voice.voice_name, "languages": list(self.voice.input_languages)},
        })
        await self._set_state("listening")
        if self.voice.greeting:
            await self.channel.send_json({"type": "transcript", "role": "assistant",
                                          "text": self.voice.greeting, "final": True})
            await self._speak(self.voice.greeting)

    async def _pump(self, iterator) -> None:
        async for event in iterator:
            try:
                await self._handle_upstream(event)
            except ClientGone:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("voice_event_failed session=%s error=%s", self.session_id, type(exc).__name__)

    async def _watchdog(self) -> str:
        started = time.monotonic()
        while True:
            now = time.monotonic()
            if now - started >= self._max_duration:
                return "timeout"
            if now - self._last_activity >= self._idle_timeout:
                return "idle"
            remaining = min(self._max_duration - (now - started), self._idle_timeout - (now - self._last_activity))
            await asyncio.sleep(min(0.5, max(0.01, remaining)))

    async def _handle_upstream(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "input_audio_buffer.speech_started":
            self._touch()
            await self._barge_in()
        elif kind == "input_audio_buffer.speech_stopped":
            self._touch()
            await self._set_state("thinking")
        elif kind == "conversation.item.input_audio_transcription.delta":
            item = str(event.get("item_id", ""))
            self._partials[item] = self._partials.get(item, "") + str(event.get("delta", ""))
            await self.channel.send_json({"type": "transcript", "role": "user",
                                          "text": self._partials[item].strip(), "final": False})
        elif kind == "conversation.item.input_audio_transcription.completed":
            self._partials.pop(str(event.get("item_id", "")), None)
            await self._transcribed(str(event.get("transcript") or "").strip())
        elif kind == "conversation.item.input_audio_transcription.failed":
            self._partials.pop(str(event.get("item_id", "")), None)
            await self.channel.send_json({"type": "error", "code": "transcription_failed", "fatal": False,
                                          "message": "I could not understand the audio. Please try again."})
            await self._set_state("listening")
        elif kind == "response.created":
            identifier = (event.get("response") or {}).get("id")
            self._current_response = identifier
            if self._cancel_next_response and identifier:
                self._cancelled.add(identifier)
            self._cancel_next_response = False
        elif kind == "response.audio.delta":
            await self._audio(event)
        elif kind == "response.done":
            await self._response_done(event)
        elif kind == "error":
            code = (event.get("error") or {}).get("code")
            if code not in BENIGN_UPSTREAM_ERRORS:
                LOGGER.warning("voice_upstream_error session=%s code=%s", self.session_id, code)
                await self.channel.send_json({"type": "error", "code": "voice_error", "fatal": False, "message": VOICE_ERROR})
                if self._response_active and self._current_response is None:
                    # No response exists yet, so the error belongs to the pending response.create, which will never finish.
                    self._response_active = False
                    self._cancel_next_response = False
                    await self._leave_busy_state()

    async def _audio(self, event: dict) -> None:
        identifier = event.get("response_id")
        if not self._response_active or identifier in self._cancelled:
            return
        try:
            data = base64.b64decode(event.get("delta", ""), validate=True)
        except (binascii.Error, ValueError):
            return
        if not data:
            return
        self._touch()
        if self._state != "speaking":
            await self._set_state("speaking")
        await self.channel.send_audio(data)

    async def _response_done(self, event: dict) -> None:
        response = event.get("response") or {}
        identifier = response.get("id")
        stale = identifier in self._cancelled
        self._cancelled.discard(identifier)
        ended = False
        if stale:
            # A response we already cancelled; a newer one may be pending, so it is only forgotten here.
            if identifier == self._current_response:
                self._current_response = None
        elif (identifier is None or identifier == self._current_response
              or (self._response_active and self._current_response is None)):
            self._response_active = False
            self._current_response = None
            ended = True
        if response.get("status") == "failed":
            await self.channel.send_json({"type": "error", "code": "voice_error", "fatal": False, "message": VOICE_ERROR})
        if ended:
            await self._leave_busy_state()
        self._touch()

    def _answer_pending(self) -> bool:
        task = self._answer_task
        return task is not None and not task.done()

    async def _leave_busy_state(self) -> None:
        """Back to listening once nothing is left to wait for or to speak."""
        if self._state in ("thinking", "speaking") and not self._answer_pending():
            await self._set_state("listening")

    async def _transcribed(self, text: str) -> None:
        if not text:
            if self._state == "thinking":
                await self._set_state("listening")
            return
        self._touch()
        await self.channel.send_json({"type": "transcript", "role": "user", "text": text, "final": True})
        self._turn += 1
        turn = self._turn
        self._cancel_pending_answer()
        await self._set_state("thinking")
        self._answer_task = asyncio.create_task(self._answer_turn(turn, text))

    def _cancel_pending_answer(self) -> bool:
        task = self._answer_task
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    async def _barge_in(self) -> None:
        self._turn += 1
        pending = self._cancel_pending_answer()
        speaking = self._response_active
        if speaking:
            await self._cancel_response()
        if pending or speaking or self._state in ("thinking", "speaking"):
            await self.channel.send_json({"type": "interrupted"})
        await self._set_state("listening")

    async def _cancel_response(self) -> None:
        if self._current_response:
            self._cancelled.add(self._current_response)
        else:
            self._cancel_next_response = True
        self._response_active = False
        with contextlib.suppress(Exception):
            await self.upstream.send({"type": "response.cancel"})

    async def _answer_turn(self, turn: int, text: str) -> None:
        self.turns += 1
        failure: tuple[str, str] | None = None
        result: dict = {}
        try:
            result = await asyncio.wait_for(self._answer(text), self._answer_timeout)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            failure = ("answer_timeout", "The answer took too long. Try a narrower question.")
        except VoiceAnswerError as exc:
            failure = (exc.code, exc.message)
        except Exception as exc:
            LOGGER.warning("voice_answer_failed session=%s error=%s", self.session_id, type(exc).__name__)
            failure = ("answer_failed", "The answer could not be completed.")
        if turn != self._turn:
            return
        self._touch()
        if failure is not None:
            await self.channel.send_json({"type": "error", "code": failure[0], "message": failure[1], "fatal": False})
            await self._speak(APOLOGY)
            return
        spoken = spoken_text(str(result.get("answer", "")), max_chars=self.voice.max_spoken_characters)
        await self.channel.send_json({**result, "type": "answer", "spoken": spoken.text,
                                      "spoken_truncated": spoken.truncated})
        if spoken.text:
            await self._speak(spoken.text)
        else:
            await self._set_state("listening")

    async def _speak(self, text: str) -> None:
        if self._response_active:
            await self._cancel_response()
        self._response_active = True
        await self.upstream.send(speak_event(text))

    async def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            await self.channel.send_json({"type": "state", "state": state})

    async def _fatal(self, code: str, message: str) -> None:
        with contextlib.suppress(Exception):
            await self.channel.send_json({"type": "error", "code": code, "message": message, "fatal": True})

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    async def _shutdown(self, reason: str, seconds: float) -> None:
        self._cancel_pending_answer()
        with contextlib.suppress(Exception):
            await self.upstream.close()
        with contextlib.suppress(Exception):
            await self.channel.send_json({"type": "closed", "reason": reason})
        LOGGER.info("voice_session_end session=%s reason=%s seconds=%d turns=%d",
                    self.session_id, reason, int(seconds), self.turns)


class WebSocketUpstream:
    """Adapter over a `websockets` client connection to Voice Live."""

    def __init__(self, socket):
        self._socket = socket

    async def send(self, event: dict) -> None:
        await self._socket.send(json.dumps(event, separators=(",", ":")))

    def __aiter__(self) -> AsyncIterator[dict]:
        return self._events()

    async def _events(self) -> AsyncIterator[dict]:
        from websockets.exceptions import ConnectionClosed
        try:
            async for message in self._socket:
                if isinstance(message, (bytes, bytearray)):
                    continue
                try:
                    event = json.loads(message)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    yield event
        except ConnectionClosed:
            return

    async def close(self) -> None:
        await self._socket.close()


def websockets_available() -> bool:
    return importlib.util.find_spec("websockets") is not None


def _websockets_connect():
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise VoiceUnavailable("Live voice needs the 'websockets' package in the application bundle.") from exc
    return connect


class VoiceLiveGateway:
    """Opens an authenticated Voice Live socket using the application's managed identity (no keys)."""

    requires_websockets = True

    def __init__(self, *, credential_factory: Callable[[Any], Any] | None = None,
                 url_for: Callable[[Any], str] | None = None, connect: Callable[..., Awaitable[Any]] | None = None):
        self._credential_factory = credential_factory
        self._credential = None
        self._url_for = url_for or (lambda settings: connection_url(settings.voice, settings.azure.foundry_account))
        self._connect = connect

    def _token(self, settings) -> str:
        if self._credential is None:
            factory = self._credential_factory
            if factory is None:
                from .config import credential as factory
            self._credential = factory(settings)
        return self._credential.get_token(settings.voice.token_scope).token

    async def connect(self, settings) -> VoiceUpstream:
        connect = self._connect or _websockets_connect()
        token = await asyncio.to_thread(self._token, settings)
        socket = await connect(
            self._url_for(settings), additional_headers={"Authorization": "Bearer " + token},
            max_size=MAX_UPSTREAM_MESSAGE, open_timeout=10, close_timeout=5, ping_interval=20, ping_timeout=20,
            user_agent_header="aifactory-agent-voice",
        )
        return WebSocketUpstream(socket)


class _Entry:
    def __init__(self, owner: str):
        self.owner, self.session, self.replaced = owner, None, False


class SessionRegistry:
    """Bounded in-process registry: one live session per user; a newer one replaces the older (page refresh)."""

    def __init__(self, limit: int):
        self._limit = limit
        self._entries: dict[str, _Entry] = {}

    @property
    def active(self) -> int:
        return len(self._entries)

    def reserve(self, owner: str) -> tuple[_Entry, _Entry | None] | None:
        previous = self._entries.get(owner)
        if previous is None and len(self._entries) >= self._limit:
            return None
        entry = _Entry(owner)
        self._entries[owner] = entry
        if previous is not None:
            previous.replaced = True
        return entry, previous

    def release(self, entry: _Entry) -> None:
        if self._entries.get(entry.owner) is entry:
            del self._entries[entry.owner]
