from opentelemetry import metrics

METER = metrics.get_meter("aifactory_agent")
RETRIEVAL_REQUESTS = METER.create_counter("aifactory.retrieval.requests")
RETRIEVAL_FAILURES = METER.create_counter("aifactory.retrieval.failures")
ANSWER_LATENCY = METER.create_histogram("aifactory.answer.duration", unit="s")
MODEL_TOKENS = METER.create_counter("aifactory.model.tokens")
TOOL_CALLS = METER.create_counter("aifactory.tool.calls")
TOOL_FAILURES = METER.create_counter("aifactory.tool.failures")
MODEL_FAILURES = METER.create_counter("aifactory.model.failures")
VOICE_SESSIONS = METER.create_counter("aifactory.voice.sessions")
VOICE_SESSION_SECONDS = METER.create_histogram("aifactory.voice.session.duration", unit="s")
VOICE_TURNS = METER.create_counter("aifactory.voice.turns")
VOICE_FAILURES = METER.create_counter("aifactory.voice.failures")


def configure(settings):
    connection = settings.azure.application_insights_connection_string
    if connection:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(
            connection_string=connection, logger_name="aifactory_agent",
            disable_offline_storage=True,
            instrumentation_options={
                "azure_sdk": {"enabled": False}, "httpx": {"enabled": False},
                "requests": {"enabled": False}, "urllib": {"enabled": False},
                "urllib3": {"enabled": False},
            },
        )
