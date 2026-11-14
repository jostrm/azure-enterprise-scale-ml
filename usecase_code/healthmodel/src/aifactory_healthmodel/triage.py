"""AI-assisted triage of health model state with a Foundry model deployment.

The prompt is built only from health model data (states, failing signals,
alerts, transitions). Answers are advisory and never trigger changes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .infrastructure.azure_cli import az_command

SYSTEM_PROMPT = (
    "You are an Azure site reliability engineer for an Enterprise Scale AI Factory. Using only the health model "
    "data provided, explain in at most 12 short bullet points: the overall health, the most likely cause, the user "
    "impact, and the next three concrete checks (portal blade, metric or CLI command). Do not invent resources, "
    "metrics or values that are not in the data. Never recommend deleting resources or disabling monitoring. "
    "Treat 'Unknown' as missing data, not as a failure."
)
ALLOWED_HOSTS = re.compile(r"[a-z0-9-]{2,64}\.(openai\.azure\.com|services\.ai\.azure\.com|cognitiveservices\.azure\.com)")
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com"


def chat_url(endpoint: str) -> str:
    parts = urlsplit(endpoint or "")
    if parts.scheme != "https" or not ALLOWED_HOSTS.fullmatch(parts.hostname or ""):
        raise ValueError("endpoint must be an https Azure AI Foundry / Azure OpenAI endpoint.")
    return f"https://{parts.hostname}/openai/v1/chat/completions"


def build_messages(summary: dict, alerts: list[dict] | None = None, histories: dict | None = None,
                   max_chars: int = 12000) -> list[dict]:
    facts = {
        "model": summary.get("model"),
        "root": summary.get("root"),
        "layers": summary.get("layers", []),
        "counts": summary.get("counts", {}),
        "problems": summary.get("problems", [])[:25],
        "unknownCount": len(summary.get("unknown", [])),
        "signalErrors": [{**e, "error": e.get("error", "")[:300]} for e in summary.get("signalErrors", [])[:10]],
        "hints": summary.get("hints", []),
        "openAlerts": [{k: a.get(k) for k in ("severity", "state", "condition", "entity", "name", "firedAt")}
                       for a in (alerts or []) if a.get("condition") != "Resolved"][:20],
        "recentTransitions": {k: v[-10:] for k, v in (histories or {}).items()},
    }
    text = json.dumps(facts, indent=1, default=str)
    while len(text) > max_chars and (facts["problems"] or facts["openAlerts"]):
        for key in ("openAlerts", "problems"):
            if facts[key]:
                facts[key] = facts[key][: max(len(facts[key]) // 2, 0)]
        text = json.dumps(facts, indent=1, default=str)
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Health model data (JSON):\n" + text[:max_chars]}]


def az_requester(url: str, body: dict) -> dict:
    """POST with the signed-in Azure CLI identity (needs a data-plane role such as Azure AI User)."""
    handle, path = tempfile.mkstemp(prefix="hm-triage-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(body, stream)
        result = subprocess.run([*az_command(), "rest", "--method", "post", "--url", url, "--resource", COGNITIVE_SCOPE,
                                 "--body", f"@{path}", "--headers", "Content-Type=application/json",
                                 "--output", "json", "--only-show-errors"], capture_output=True, text=True, shell=False)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode:
        raise RuntimeError("The model call failed. Check network access to the private endpoint and the caller's "
                           "Azure AI User / Cognitive Services OpenAI User role.")
    return json.loads(result.stdout)


def triage(summary: dict, alerts: list[dict] | None = None, histories: dict | None = None, *, endpoint: str,
           deployment: str, requester=az_requester, max_completion_tokens: int = 1200) -> str:
    body = {"model": deployment, "messages": build_messages(summary, alerts, histories),
            "max_completion_tokens": max_completion_tokens}
    response = requester(chat_url(endpoint), body)
    return response["choices"][0]["message"]["content"].strip()
