"""aifactory.chat custom events for the My Project "Usage & outcomes" report.

One Application Insights custom event per user question (kind=question) and per genuine thumbs up/down
(kind=feedback), stamped with the AI Factory catalog placement. Properties are pseudonymous identifiers only:
never question or answer text, names, emails, IPs or principal ids. Placement is never guessed: without all four
dimensions the emitter is disabled and warns once.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable

CHAT_EVENT = "aifactory.chat"
# Child of the "aifactory_agent" logger that telemetry.configure() exports to Application Insights.
EVENT_LOGGER = logging.getLogger("aifactory_agent.events")
EVENT_LOGGER.setLevel(logging.INFO)
LOGGER = logging.getLogger(__name__)

PSEUDONYMOUS_ID = re.compile(r"^[0-9a-f]{32}$")
DEVICE_ID = re.compile(r"^[0-9a-f]{32,64}$")
RATINGS = ("up", "down")
PLACEMENT = (("factory", "factory_id"), ("scaleset", "scale_set_id"), ("project", "project_number"),
             ("environment", "environment"))


def _log_custom_event(properties: dict[str, str]) -> None:
    # azure-monitor-opentelemetry-exporter >= 1.0.0b37 maps this attribute to customEvents (EventData). Log
    # envelopes carry no sample rate, so each event is stored with ItemCount 1.
    EVENT_LOGGER.info(CHAT_EVENT, extra={"microsoft.custom_event.name": CHAT_EVENT, **properties})


class ChatEvents:
    def __init__(self, placement: dict[str, str] | None, sink: Callable[[dict[str, str]], None] | None = None):
        self._placement = dict(placement) if placement else None
        self._sink = sink or _log_custom_event

    @classmethod
    def from_settings(cls, settings, sink=None) -> "ChatEvents":
        if not settings.azure.application_insights_connection_string:
            return cls(None, sink)
        configured = settings.telemetry
        values = {
            "factory_id": configured.factory_id or _text(settings.factory.factory_id),
            "scale_set_id": configured.scale_set_id or _text(settings.factory.scale_set_id),
            "project_number": configured.project_number,
            "environment": configured.environment,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            LOGGER.warning("%s events are disabled: telemetry placement is incomplete (missing %s).",
                           CHAT_EVENT, ", ".join("telemetry." + name for name in missing))
            return cls(None, sink)
        placement = {dimension: values[name] for dimension, name in PLACEMENT}
        if configured.store:
            placement["store"] = configured.store
        return cls(placement, sink)

    @property
    def enabled(self) -> bool:
        return self._placement is not None

    def question(self, conversation_id: str, *, device_id: str | None = None) -> str | None:
        """Record one user question; returns its question_id (for feedback) or None when nothing was sent."""
        if not self.enabled:
            return None
        if not _pseudonymous(conversation_id) or (device_id is not None and not _device(device_id)):
            LOGGER.warning("%s question skipped: identifiers must be pseudonymous hex ids.", CHAT_EVENT)
            return None
        question_id = uuid.uuid4().hex
        fields = {"conversation_id": conversation_id, "question_id": question_id}
        if device_id is not None:
            fields["device_id"] = device_id
        return question_id if self._emit("question", fields) else None

    def feedback(self, conversation_id: str, question_id: str, rating: str) -> bool:
        """Record one genuine thumbs up/down for the question it rates."""
        if not self.enabled:
            return False
        if not isinstance(rating, str) or rating not in RATINGS:
            return False
        if not _pseudonymous(conversation_id) or not _pseudonymous(question_id):
            LOGGER.warning("%s feedback skipped: identifiers must be pseudonymous hex ids.", CHAT_EVENT)
            return False
        return self._emit("feedback", {"conversation_id": conversation_id, "question_id": question_id,
                                       "rating": rating})

    def _emit(self, kind: str, fields: dict[str, str]) -> bool:
        properties = {"event_id": uuid.uuid4().hex, **self._placement, "kind": kind, **fields}
        try:
            self._sink(properties)
        except Exception:  # Telemetry must never break a chat turn.
            LOGGER.warning("%s event could not be recorded.", CHAT_EVENT)
            return False
        return True


def _text(value) -> str | None:
    return str(value) if value else None


def _pseudonymous(value) -> bool:
    return isinstance(value, str) and PSEUDONYMOUS_ID.fullmatch(value) is not None


def _device(value) -> bool:
    return isinstance(value, str) and DEVICE_ID.fullmatch(value) is not None
