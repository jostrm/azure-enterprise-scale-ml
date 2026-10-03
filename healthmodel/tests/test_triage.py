from __future__ import annotations

import json

import pytest

from aifactory_healthmodel import triage

SUMMARY = {
    "model": "hm-spider-prj001-sdc-dev-001",
    "root": {"name": "hm-spider-prj001-sdc-dev-001", "displayName": "AI Factory project 001 (dev)", "state": "Degraded"},
    "layers": [{"name": "layer-analytics", "displayName": "Machine learning and analytics", "state": "Degraded"}],
    "counts": {"Degraded": 3, "Healthy": 15, "Unknown": 9},
    "problems": [{"name": "aks-x", "displayName": "AKS cluster: aks001-sdc-dev", "state": "Degraded",
                  "path": ["AI Factory project 001 (dev)", "Machine learning and analytics", "AKS cluster: aks001-sdc-dev"],
                  "signals": [{"name": "resource-health", "displayName": "Azure Resource Health", "state": "Degraded",
                               "value": None, "reportedAt": "2026-10-03T20:52:41Z"}]}],
    "unknown": [{"name": f"u{i}", "displayName": f"Unknown {i}"} for i in range(9)],
    "signalErrors": [{"entity": "aks-x", "displayName": "AKS", "signal": "node-cpu", "error": "x" * 900}],
    "hints": ["grant Monitoring Reader"],
}
ALERTS = [{"id": "/a/1", "name": "Entity AI Factory project 001 (dev) is Degraded", "entity": "hm-spider-prj001-sdc-dev-001",
           "severity": "Sev3", "state": "New", "condition": "Fired", "firedAt": "2026-10-03T20:47:40Z"}]


def test_messages_contain_only_health_model_facts_and_instructions():
    messages = triage.build_messages(SUMMARY, ALERTS, {"aks-x": [{"previousState": "Healthy", "newState": "Degraded",
                                                                  "occurredAt": "2026-10-03T20:47:40Z"}]})
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Do not invent" in messages[0]["content"]
    payload = json.loads(messages[1]["content"].split("\n", 1)[1])
    assert payload["root"]["state"] == "Degraded"
    assert payload["problems"][0]["displayName"] == "AKS cluster: aks001-sdc-dev"
    assert payload["openAlerts"][0]["severity"] == "Sev3"
    assert payload["recentTransitions"]["aks-x"][0]["newState"] == "Degraded"
    assert payload["unknownCount"] == 9 and len(payload["signalErrors"][0]["error"]) <= 300


def test_messages_are_bounded():
    big = dict(SUMMARY, problems=SUMMARY["problems"] * 200)
    messages = triage.build_messages(big, ALERTS * 200, max_chars=6000)
    assert len(messages[1]["content"]) <= 6100


@pytest.mark.parametrize("endpoint", [
    "https://aif2contoso.openai.azure.com", "https://aif2contoso.services.ai.azure.com/",
    "https://aif2contoso.cognitiveservices.azure.com/",
])
def test_allowed_endpoints(endpoint):
    assert triage.chat_url(endpoint).endswith("/openai/v1/chat/completions")


@pytest.mark.parametrize("endpoint", ["http://aif2contoso.openai.azure.com", "https://evil.example.com",
                                      "https://openai.azure.com.evil.example.com", ""])
def test_rejected_endpoints(endpoint):
    with pytest.raises(ValueError):
        triage.chat_url(endpoint)


def test_triage_posts_to_the_deployment_and_returns_text():
    seen = {}

    def requester(url, body):
        seen.update(url=url, body=body)
        return {"model": "gpt-6.1-sol", "choices": [{"message": {"content": "- AKS degraded"}}]}

    text = triage.triage(SUMMARY, ALERTS, endpoint="https://aif2contoso.openai.azure.com",
                         deployment="aifactory-agent-gpt-6-1-sol", requester=requester)
    assert text == "- AKS degraded"
    assert seen["body"]["model"] == "aifactory-agent-gpt-6-1-sol"
    assert seen["body"]["max_completion_tokens"] == 1200
    assert seen["url"] == "https://aif2contoso.openai.azure.com/openai/v1/chat/completions"
