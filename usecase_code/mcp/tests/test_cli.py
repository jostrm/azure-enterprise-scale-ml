import io

import pytest

from aifactory_mcp.__main__ import approve_interactively, parser


class Terminal(io.StringIO):
    def isatty(self):
        return True


class Backend:
    calls = None

    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        return {"ok": True, "operation": {
            "id": "operation", "plan_hash": "a" * 64, "status": "pending",
            "preview": {"confirmation_phrase": "DELETE factory-ai"},
        }}

    def approve(self, operation_id, plan_hash, confirmation_phrase):
        self.calls.append((operation_id, plan_hash, confirmation_phrase))
        return {"ok": True, "operation": {"status": "approved"}}


def test_approval_rejects_piped_input():
    backend = Backend()
    with pytest.raises(ValueError, match="interactive"):
        approve_interactively(backend, "operation", input_stream=io.StringIO("yes\n"))
    assert backend.calls == []


def test_approval_shows_plan_and_requires_hash_and_phrase():
    backend, output = Backend(), io.StringIO()
    result = approve_interactively(backend, "operation", input_stream=Terminal(
        "a" * 64 + "\nDELETE factory-ai\n"
    ), output_stream=output)
    assert result["operation"]["status"] == "approved"
    assert "DELETE factory-ai" in output.getvalue()
    assert backend.calls == [("operation", "a" * 64, "DELETE factory-ai")]


@pytest.mark.parametrize("answers", ["yes\n", "b" * 64 + "\n", "a" * 64 + "\nWRONG\n"])
def test_inexact_approval_does_not_write(answers):
    backend = Backend()
    with pytest.raises(ValueError, match="match"):
        approve_interactively(backend, "operation", input_stream=Terminal(answers),
                              output_stream=io.StringIO())
    assert backend.calls == []


def test_parser_exposes_transport_and_rejects_approval_bypass():
    parsed = parser().parse_args([
        "serve", "--config", "config.json", "--scope", "dev", "--transport", "streamable-http",
        "--resource-url", "https://mcp.example.com/mcp",
    ])
    assert parsed.object_id is None
    with pytest.raises(SystemExit):
        parser().parse_args(["approve", "--config", "config.json", "--scope", "dev",
                             "--object-id", "operator", "--operation-id", "operation", "--yes"])


def test_cli_application_auth_is_explicit_http_configuration():
    parsed = parser().parse_args([
        "serve", "--config", "agent.json", "--scope", "dev", "--transport", "streamable-http",
        "--application-auth", "application-auth.json", "--resource-url", "https://example.com/mcp",
    ])
    assert parsed.application_auth == "application-auth.json"
