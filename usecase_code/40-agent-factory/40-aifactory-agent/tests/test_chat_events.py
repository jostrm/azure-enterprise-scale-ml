"""aifactory.chat custom events (My Project "Usage & outcomes"): contract, privacy and fail-closed placement. No Azure calls."""

import json
import logging
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from aifactory_agent import telemetry
from aifactory_agent.chat_events import CHAT_EVENT, EVENT_LOGGER, ChatEvents
from aifactory_agent.config import Settings

ROOT = Path(__file__).parents[1]
FACTORY_ID = "0b6f1c9e-8d0a-4e8f-9d43-1f2a3b4c5d6e"
SCALE_SET_ID = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
PLACEMENT = {"factory_id": FACTORY_ID, "scale_set_id": SCALE_SET_ID, "project_number": "001", "environment": "dev"}
CONVERSATION = "5f0c3a6b2d1e4f7a8b9c0d1e2f3a4b5c"
HEX = re.compile(r"^[0-9a-f]{32}$")


def make_settings(telemetry_section=PLACEMENT, connection="InstrumentationKey=00000000-0000-0000-0000-000000000000"):
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    config["azure"]["application_insights_connection_string"] = connection
    if telemetry_section is not None:
        config["telemetry"] = dict(telemetry_section)
    else:
        config.pop("telemetry", None)
    return Settings.model_validate(config)


def recorder(settings=None):
    sink = []
    return ChatEvents.from_settings(settings or make_settings(), sink=sink.append), sink


def test_question_event_has_exactly_the_contract_properties():
    events, sink = recorder()
    question_id = events.question(CONVERSATION)
    assert len(sink) == 1
    event = sink[0]
    assert set(event) == {"event_id", "factory", "scaleset", "project", "environment", "kind",
                          "conversation_id", "question_id"}
    assert event["factory"] == FACTORY_ID and event["scaleset"] == SCALE_SET_ID
    assert event["project"] == "001" and event["environment"] == "dev" and event["kind"] == "question"
    assert event["conversation_id"] == CONVERSATION and event["question_id"] == question_id
    assert HEX.fullmatch(event["event_id"]) and HEX.fullmatch(question_id) and event["event_id"] != question_id
    assert all(isinstance(value, str) for value in event.values())


def test_every_event_and_question_gets_a_fresh_identity():
    events, sink = recorder()
    first, second = events.question(CONVERSATION), events.question(CONVERSATION)
    assert first != second
    assert sink[0]["event_id"] != sink[1]["event_id"]
    assert sink[0]["conversation_id"] == sink[1]["conversation_id"] == CONVERSATION


def test_store_is_sent_only_when_configured():
    events, sink = recorder(make_settings({**PLACEMENT, "store": "store-a"}))
    events.question(CONVERSATION)
    assert sink[0]["store"] == "store-a"
    events, sink = recorder()
    events.question(CONVERSATION)
    assert "store" not in sink[0]


def test_pseudonymous_device_id_is_optional_and_only_on_questions():
    device = "a" * 64
    events, sink = recorder()
    events.question(CONVERSATION, device_id=device)
    assert sink[0]["device_id"] == device
    events.feedback(CONVERSATION, sink[0]["question_id"], "up")
    assert "device_id" not in sink[1]


@pytest.mark.parametrize("missing", ["factory_id", "scale_set_id", "project_number", "environment"])
def test_no_event_and_one_warning_when_a_placement_dimension_is_missing(missing, caplog):
    placement = {key: value for key, value in PLACEMENT.items() if key != missing}
    with caplog.at_level(logging.WARNING):
        events, sink = recorder(make_settings(placement))
        assert events.enabled is False
        assert events.question(CONVERSATION) is None
        assert events.question(CONVERSATION) is None
        assert events.feedback(CONVERSATION, CONVERSATION, "up") is False
    assert sink == []
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert missing in warnings[0].getMessage() and "aifactory.chat" in warnings[0].getMessage()
    assert FACTORY_ID not in warnings[0].getMessage()


def test_no_telemetry_section_means_no_events_and_one_warning(caplog):
    with caplog.at_level(logging.WARNING):
        events, sink = recorder(make_settings(None))
        events.question(CONVERSATION)
    assert sink == [] and len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_catalog_ids_default_to_the_factory_api_registration():
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    config["azure"]["application_insights_connection_string"] = "InstrumentationKey=x"
    config["factory"].update(factory_id=FACTORY_ID, scale_set_id=SCALE_SET_ID)
    config["telemetry"] = {"project_number": "7", "environment": "prod"}
    events, sink = recorder(Settings.model_validate(config))
    events.question(CONVERSATION)
    assert (sink[0]["factory"], sink[0]["scaleset"], sink[0]["project"], sink[0]["environment"]) == (
        FACTORY_ID, SCALE_SET_ID, "7", "prod")


def test_disabled_cleanly_without_a_connection_string(caplog):
    with caplog.at_level(logging.WARNING):
        events, sink = recorder(make_settings(connection=None))
        assert events.enabled is False
        assert events.question(CONVERSATION) is None
    assert sink == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("field,value", [
    ("project_number", "0001"), ("project_number", "project001"), ("project_number", ""),
    ("environment", "test"), ("factory_id", "all"), ("factory_id", "Unknown"), ("scale_set_id", "unavailable"),
    ("factory_id", "has space"), ("store", "All"), ("scale_set_id", "x" * 200),
])
def test_placement_settings_reject_non_catalog_identities(field, value):
    with pytest.raises(ValidationError):
        make_settings({**PLACEMENT, field: value})


@pytest.mark.parametrize("conversation", [
    "jane.doe@contoso.com", "Jane Doe", "10.0.0.1", "", "5F0C3A6B2D1E4F7A8B9C0D1E2F3A4B5C", "abc",
])
def test_non_pseudonymous_conversation_ids_are_never_sent(conversation):
    events, sink = recorder()
    assert events.question(conversation) is None
    assert sink == []


@pytest.mark.parametrize("device", ["jane.doe@contoso.com", "user-123", "10.0.0.1", "A" * 64])
def test_non_pseudonymous_device_ids_are_never_sent(device):
    events, sink = recorder()
    assert events.question(CONVERSATION, device_id=device) is None
    assert sink == []


def test_no_text_or_identity_reaches_the_event_properties():
    events, sink = recorder()
    events.question(CONVERSATION)
    allowed = {"event_id", "factory", "scaleset", "project", "environment", "store", "kind",
               "conversation_id", "question_id", "device_id", "rating"}
    assert set(sink[0]) <= allowed
    for value in sink[0].values():
        assert "@" not in value and " " not in value


def test_feedback_event_carries_only_the_rating_contract():
    events, sink = recorder()
    question_id = events.question(CONVERSATION)
    assert events.feedback(CONVERSATION, question_id, "down") is True
    event = sink[1]
    assert set(event) == {"event_id", "factory", "scaleset", "project", "environment", "kind",
                          "conversation_id", "question_id", "rating"}
    assert event["kind"] == "feedback" and event["rating"] == "down"
    assert event["conversation_id"] == CONVERSATION and event["question_id"] == question_id
    assert event["event_id"] != sink[0]["event_id"]


@pytest.mark.parametrize("rating", ["UP", "Down", "neutral", "", "1", None, True])
def test_feedback_requires_a_genuine_up_or_down_rating(rating):
    events, sink = recorder()
    assert events.feedback(CONVERSATION, CONVERSATION, rating) is False
    assert sink == []


@pytest.mark.parametrize("question_id", ["", "question-1", "jane.doe@contoso.com", None])
def test_feedback_requires_the_pseudonymous_question_it_rates(question_id):
    events, sink = recorder()
    assert events.feedback(CONVERSATION, question_id, "up") is False
    assert sink == []


def test_a_failing_exporter_never_breaks_the_chat(caplog):
    def broken(properties):
        raise RuntimeError("exporter down")

    events = ChatEvents.from_settings(make_settings(), sink=broken)
    with caplog.at_level(logging.WARNING):
        assert events.question(CONVERSATION) is None


def test_default_sink_logs_an_application_insights_custom_event(caplog):
    events = ChatEvents.from_settings(make_settings())
    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER.name):
        question_id = events.question(CONVERSATION)
    record = next(record for record in caplog.records if record.name == EVENT_LOGGER.name)
    assert record.getMessage() == CHAT_EVENT == "aifactory.chat"
    assert getattr(record, "microsoft.custom_event.name") == "aifactory.chat"
    assert record.question_id == question_id and record.kind == "question" and record.project == "001"


def test_azure_monitor_exports_it_as_an_unsampled_custom_event():
    pytest.importorskip("azure.monitor.opentelemetry.exporter")
    from azure.monitor.opentelemetry.exporter.export.logs._exporter import _convert_log_to_envelope
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
    try:
        from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter as InMemoryLogExporter
    except ImportError:
        from opentelemetry.sdk._logs.export import InMemoryLogExporter

    exporter = InMemoryLogExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = LoggingHandler(logger_provider=provider)
    EVENT_LOGGER.addHandler(handler)
    try:
        question_id = ChatEvents.from_settings(make_settings()).question(CONVERSATION)
    finally:
        EVENT_LOGGER.removeHandler(handler)
    [record] = exporter.get_finished_logs()
    envelope = _convert_log_to_envelope(record)
    assert envelope.name == "Microsoft.ApplicationInsights.Event"
    assert envelope.data.base_type == "EventData" and envelope.data.base_data.name == "aifactory.chat"
    properties = envelope.data.base_data.properties
    assert properties["question_id"] == question_id and properties["conversation_id"] == CONVERSATION
    assert properties["factory"] == FACTORY_ID and properties["scaleset"] == SCALE_SET_ID
    assert "microsoft.custom_event.name" not in properties
    # No sample rate on the envelope: Application Insights stores ItemCount 1 for every chat event.
    assert envelope.sample_rate in (None, 100, 100.0)


def test_configure_never_samples_logs_and_events_by_trace(monkeypatch):
    calls = []
    distro = pytest.importorskip("azure.monitor.opentelemetry")
    monkeypatch.setattr(distro, "configure_azure_monitor", lambda **kwargs: calls.append(kwargs))
    telemetry.configure(make_settings())
    assert calls and calls[0]["enable_trace_based_sampling_for_logs"] is False
    assert calls[0]["logger_name"] == "aifactory_agent"
    calls.clear()
    telemetry.configure(make_settings(connection=None))
    assert calls == []
