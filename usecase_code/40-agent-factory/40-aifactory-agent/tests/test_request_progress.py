"""Use the real page request lifecycle and companion progress renderer in Node."""
import json
import subprocess

import pytest

from aifactory_agent import web
from test_web import EMBEDDED_HOST_HARNESS


@pytest.mark.parametrize("outcome", ["success", "failure", "network", "signout"])
def test_typed_request_exposes_busy_state_until_settlement(outcome):
    harness = EMBEDDED_HOST_HARNESS.split("(async () => {", 1)[0]
    harness = harness.replace(
        'if (url === "/api/chat") {',
        'if (url === "/api/chat") return new Promise((resolve, reject) => {'
        ' releaseChat = (result, failed = false) => failed ? reject(result) : resolve(result); });\n'
        '    if (url === "/unused-chat") {',
    )
    script = harness + r"""
(async () => {
  await waitFor(() => sandbox.AIFactoryAgent.voiceSession(), "authenticated");
  assert.equal(ui("question-form")["aria-busy"], "false");
  ui("question").value = "A scoped question";
  await ui("question").handlers.input({});
  const pending = ui("question-form").handlers.submit({preventDefault() {}});
  await waitFor(() => releaseChat, "request pending");
  assert.equal(ui("question-form")["aria-busy"], "true",
    "typed requests must expose progress independently of voice, labels and button state");
  if (OUTCOME === "signout") {
    await ui("sign-out").handlers.click({});
    assert.equal(ui("question-form")["aria-busy"], "false");
  }
  if (OUTCOME === "network") releaseChat(Error("offline"), true);
  else if (OUTCOME === "failure") releaseChat(response({error: {code: "dependency_unavailable"}}, 503));
  else releaseChat(response({answer: "Completed answer", scope_key: "project001-dev", audience: "project",
    correlation_id: "c", tool_activity: [], citations: []}));
  await pending;
  await waitFor(() => ui("question-form")["aria-busy"] === "false", "request settled");
  assert.equal(ui("question-form")["aria-busy"], "false");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    script = script.replace("OUTCOME", json.dumps(outcome))
    result = subprocess.run(
        ["node", "-", str(web.STATIC / "app.js"), "host-success"], input=script,
        capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize("typed,voice,voice_visible,expected", [
    (True, "Voice is off", False, True),
    (True, "Voice unavailable", True, True),
    (False, "Thinking...", True, True),
    (False, "Thinking...", False, False),
    (False, "Listening...", True, False),
    (False, "Voice is off", False, False),
])
def test_companion_combines_actual_text_request_and_voice_progress(typed, voice, voice_visible, expected):
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(process.argv[2], "utf8");
const renderer = source.match(/const renderThinking = \(\) => \{[\s\S]*?\n    \};/);
assert(renderer, "the shipped companion renderer must exist");
const input = JSON.parse(process.argv[3]);
const thinking = {hidden: true};
const scroll = {setAttribute(name, value) { this[name] = value; }};
const sandbox = {thinking, scroll, textPending: false, text: {voiceThinkingState: "Thinking..."},
  n: {
    "question-form": {getAttribute: name => name === "aria-busy" ? String(input.typed) : null},
    "voice-card": {hidden: !input.voice_visible},
    "voice-state": {textContent: input.voice}
  }};
vm.runInNewContext(renderer[0] + "\nrenderThinking();", sandbox);
assert.equal(!thinking.hidden, input.expected);
assert.equal(scroll["aria-busy"], String(input.expected));
assert(source.includes('observe(n["question-form"], renderThinking,'),
  "request state changes must refresh the existing bar");
assert(!source.includes("textPending = true"), "submission heuristics must not own progress state");
"""
    result = subprocess.run(
        ["node", "-", str(web.STATIC / "esaif-maui-layout.js"),
         json.dumps(dict(typed=typed, voice=voice, voice_visible=voice_visible, expected=expected))],
        input=script, capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
