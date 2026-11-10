"""Microphone selection/consent regressions; mocked media only, never real capture."""

import json

import pytest

from test_voice_frontend import CLIENT_HARNESS, PAGE_HARNESS, STATIC, node


HARNESS = r"""
const assert = require("node:assert/strict");
const audio = require(process.argv[2]);
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function rig() {
  const calls = [], events = {}, states = [], stopped = [];
  let devices = [{kind: "audioinput", deviceId: "mic-a", label: "", groupId: "a"}];
  const tracks = [0, 1].map(id => ({stop() { stopped.push(id); }}));
  const media = {
    enumerateDevices: async () => devices,
    getUserMedia(constraints) { calls.push(constraints); return Promise.resolve({getTracks: () => tracks}); },
    addEventListener(name, fn) { events[name] = fn; },
    removeEventListener(name, fn) { if (events[name] === fn) delete events[name]; }
  };
  const env = {isSecureContext: true, navigator: {mediaDevices: media, userActivation: {isActive: true}},
    document: {permissionsPolicy: {allowsFeature: () => true}}};
  let stops = 0;
  const controller = audio.createAudioInput({env, onInputChange: () => { stops++; }});
  controller.subscribe(value => states.push(value));
  return {controller, env, media, calls, events, states, tracks, stopped,
    devices(value) { devices = value; }, get stops() { return stops; }};
}
"""


def run(body):
    node(HARNESS + "\n(async () => {\n" + body
         + "\n})().catch(error => { console.error(error); process.exit(1); });", STATIC / "audio-input.js")


def test_enumeration_is_passive_and_exact_constraints_are_shared():
    run(r"""
const r = rig();
assert.equal(r.calls.length, 0);
await r.controller.refresh();
assert.equal(r.calls.length, 0);
assert.equal(r.controller.snapshot().devices[0].label, "");
assert.equal(r.controller.constraints().audio.deviceId, undefined);
r.controller.select("mic-a");
assert.deepEqual(r.controller.constraints().audio.deviceId, {exact: "mic-a"});
assert.equal(r.controller.constraints().audio.channelCount, 1);
assert.equal(r.calls.length, 0);
r.controller.select("");
assert.equal(r.controller.constraints().audio.deviceId, undefined);
""")


def test_allow_is_synchronous_local_only_and_closes_all_tracks_before_enumerating():
    run(r"""
const r = rig();
r.media.enumerateDevices = async () => {
  assert.deepEqual(r.stopped, [0, 1], "temporary capture must already be closed");
  return [{kind: "audioinput", deviceId: "mic-a", label: "Desk mic"}];
};
const pending = r.controller.allow();
assert.equal(r.calls.length, 1, "permission API stays inside the explicit user gesture");
assert.equal(r.calls[0].video, undefined);
await pending;
assert.deepEqual(r.stopped, [0, 1]);
assert.equal(r.controller.snapshot().code, "ready");
assert.equal(r.controller.snapshot().devices[0].label, "Desk mic");
""")


def test_allow_closes_tracks_even_when_enumeration_and_one_track_stop_fail():
    run(r"""
const r = rig();
r.tracks[0].stop = () => { r.stopped.push(0); throw Error("already ended"); };
r.media.enumerateDevices = async () => { throw Error("enumeration failed"); };
await r.controller.allow();
assert.deepEqual(r.stopped, [0, 1]);
assert.equal(r.controller.snapshot().code, "enumerationFailed");
""")


@pytest.mark.parametrize("operation", ["dispose", "cancelPermission"])
def test_late_permission_completion_is_closed_without_updating_cancelled_ui(operation):
    run(r"""
const r = rig();
let complete;
r.media.getUserMedia = () => new Promise(resolve => { complete = resolve; });
const pending = r.controller.allow();
r.controller[OPERATION]();
const before = r.states.length;
complete({getTracks: () => r.tracks});
await pending;
assert.deepEqual(r.stopped, [0, 1]);
assert.equal(r.states.length, before);
""".replace("OPERATION", json.dumps(operation)))


def test_missing_device_stays_selected_and_replug_does_not_capture():
    run(r"""
const r = rig();
await r.controller.refresh();
r.controller.select("mic-a");
r.devices([{kind: "audioinput", deviceId: "mic-b", label: "Other"}]);
r.events.devicechange();
await tick();
assert.equal(r.controller.snapshot().selectedId, "mic-a");
assert.equal(r.controller.snapshot().code, "missing");
assert.ok(r.controller.snapshot().devices.some(d => d.deviceId === "mic-a" && d.unavailable));
assert.throws(() => r.controller.constraints(), e => e.audioInputCode === "missing");
assert.equal(r.stops, 2, "selection and unplug both notify voice to stop");
r.devices([{kind: "audioinput", deviceId: "mic-a", label: "Desk"}]);
r.events.devicechange();
await tick();
assert.equal(r.controller.snapshot().selectedId, "mic-a");
assert.equal(r.controller.snapshot().code, "ready");
assert.equal(r.calls.length, 0);
r.controller.dispose();
assert.equal(r.events.devicechange, undefined);
""")


def test_default_device_changes_stop_voice_without_selecting_a_specific_device():
    run(r"""
const r = rig();
r.devices([{kind: "audioinput", deviceId: "default", label: "Default A", groupId: "a"}]);
await r.controller.refresh();
r.devices([{kind: "audioinput", deviceId: "default", label: "Default B", groupId: "b"}]);
r.events.devicechange();
await tick();
assert.equal(r.stops, 1);
assert.equal(r.controller.snapshot().selectedId, "");
assert.equal(r.controller.constraints().audio.deviceId, undefined);
assert.equal(r.calls.length, 0);
""")


def test_permission_revealing_labels_is_not_treated_as_an_input_switch():
    run(r"""
const r = rig();
r.devices([{kind: "audioinput", deviceId: "", label: "", groupId: ""}]);
await r.controller.refresh();
r.devices([{kind: "audioinput", deviceId: "default", label: "Desk", groupId: "a"},
  {kind: "audioinput", deviceId: "desk", label: "Desk", groupId: "a"}]);
r.events.devicechange();
await tick();
assert.equal(r.stops, 0, "revealing labels on first permission must not cancel Start talking");
assert.equal(r.calls.length, 0);
""")


@pytest.mark.parametrize(("name", "code"), [
    ("NotAllowedError", "denied"), ("SecurityError", "restricted"),
    ("NotReadableError", "busy"), ("AbortError", "busy"),
    ("NotFoundError", "noDevices"), ("OverconstrainedError", "missing"),
    ("UnexpectedError", "captureFailed"),
])
def test_capture_failures_are_distinct_and_not_retried(name, code):
    run(r"""
const r = rig();
r.media.getUserMedia = () => { r.calls.push({}); return Promise.reject({name: NAME}); };
await r.controller.allow();
assert.equal(r.controller.snapshot().code, CODE);
assert.equal(r.calls.length, 1, "never retry a different microphone");
assert.equal(r.controller.snapshot().busy, false);
""".replace("NAME", json.dumps(name)).replace("CODE", json.dumps(code)))


@pytest.mark.parametrize(("setup", "code"), [
    ("r.env.navigator.userActivation.isActive = false;", "gesture"),
    ("r.env.document.permissionsPolicy.allowsFeature = () => false;", "policy"),
    ("r.env.isSecureContext = false;", "insecure"),
    ("delete r.media.getUserMedia;", "unsupported"),
])
def test_permission_preflight_never_captures(setup, code):
    run(setup.join(["const r = rig();\n", "\n"]) + r"""
await r.controller.allow();
assert.equal(r.controller.snapshot().code, CODE);
assert.equal(r.calls.length, 0);
""".replace("CODE", json.dumps(code)))


def test_empty_list_is_visible_but_explicit_permission_is_still_possible():
    run(r"""
const r = rig();
r.devices([]);
await r.controller.refresh();
assert.equal(r.controller.snapshot().code, "noDevices");
assert.equal(r.calls.length, 0);
await r.controller.allow();
assert.equal(r.calls.length, 1);
assert.deepEqual(r.stopped, [0, 1]);
""")


def test_document_policy_denial_survives_url_change_and_explains_reload_without_capture():
    node(HARNESS + r"""
(async () => {
  const r = rig();
  const text = require(process.argv[3]);
  r.env.document = {featurePolicy: {allowsFeature: name => name !== "microphone"}};
  r.env.location = {search: "?host=esaif-maui&voice=on"};
  await r.controller.allow();
  assert.equal(r.controller.snapshot().code, "policy");
  assert.equal(r.calls.length, 0, "changing a URL does not change the loaded document's policy");
  assert.match(text.policy, /reload/i);
  assert.match(text.policy, /voice-enabled page/i);
  assert.match(text.policy, /cannot override/i);
})().catch(error => { console.error(error); process.exit(1); });
""", STATIC / "audio-input.js", STATIC / "audio-input.en.js")


def test_newer_refresh_wins_and_selection_cancels_pending_allow():
    run(r"""
const r = rig();
const completions = [];
r.media.enumerateDevices = () => new Promise(resolve => completions.push(resolve));
const old = r.controller.refresh(), current = r.controller.refresh();
completions[1]([{kind: "audioinput", deviceId: "mic-b", label: "New"}]);
await current;
completions[0]([{kind: "audioinput", deviceId: "mic-a", label: "Old"}]);
await old;
assert.equal(r.controller.snapshot().devices[0].deviceId, "mic-b");
let complete;
r.media.getUserMedia = () => new Promise(resolve => { complete = resolve; });
const pending = r.controller.allow();
r.controller.select("mic-b");
complete({getTracks: () => r.tracks});
await pending;
assert.deepEqual(r.stopped, [0, 1]);
assert.equal(r.controller.snapshot().selectedId, "mic-b");
""")


def test_voice_client_applies_exact_constraint_before_first_await_and_reports_capture_error():
    node(CLIENT_HARNESS + r"""
(async () => {
  const audio = require(process.argv[3]);
  const env = environment();
  env.navigator.mediaDevices.enumerateDevices = async () => [{kind: "audioinput", deviceId: "desk"}];
  const input = audio.createAudioInput({env});
  await input.refresh();
  input.select("desk");
  const rig = make({audioInput: input}, env);
  const pending = rig.client.start();
  assert.deepEqual(env.navigator.mediaDevices.requests[0].audio.deviceId, {exact: "desk"});
  await pending;
  await rig.client.stop();
  env.navigator.mediaDevices.getUserMedia = async () => { throw {name: "NotReadableError"}; };
  await rig.client.start();
  assert.equal(input.snapshot().code, "busy");
  assert.equal(session.token, "TOKEN-ABC-123");
})().catch(error => { console.error(error); process.exit(1); });
""", STATIC / "voice.js", STATIC / "audio-input.js")


PAGE_AUDIO = PAGE_HARNESS + r"""
const originalEnvironment = environment;
environment = (overrides) => {
  const env = originalEnvironment(overrides);
  env.AIFactoryAudioInput = require(process.argv[3]);
  env.AIFactoryAudioInputUI = require(process.argv[4]);
  env.AIFactoryAudioInputText = require(process.argv[5]);
  env.events = {};
  const addEventListener = env.addEventListener;
  env.addEventListener = (name, fn) => { env.events[name] = fn; addEventListener(name, fn); };
  env.navigator.userActivation = {isActive: true};
  env.navigator.mediaDevices.enumerateDevices = async () => [
    {kind: "audioinput", deviceId: "desk", label: "Desk mic"},
    {kind: "audioinput", deviceId: "headset", label: "Headset"},
  ];
  return env;
};
"""


def page_run(body, *args):
    node(PAGE_AUDIO + "\n(async () => {\n" + body
         + "\n})().catch(error => { console.error(error); process.exit(1); });",
         STATIC / "voice.js", STATIC / "audio-input.js", STATIC / "audio-input-ui.js",
         STATIC / "audio-input.en.js", *args)


@pytest.mark.parametrize("change", [{"enabled": False}, {"ready": False}, {"protocol": 2}, {"mode": "speech_shell"}])
def test_allow_permission_preserves_existing_capability_gate(change):
    page_run(r"""
const r = page({...capabilities, ...JSON.parse(process.argv[6])});
r.element("voice-input-allow").handlers.click();
assert.equal(r.env.navigator.mediaDevices.requests.length, 0, "native grant is not yet available");
r.grant(true);
await tick();
r.element("voice-input-allow").handlers.click();
assert.equal(r.env.navigator.mediaDevices.requests.length, 0, "incompatible capability cannot request permission");
""", json.dumps(change))


def test_allow_button_needs_gesture_and_never_opens_transport_or_overlaps_live_capture():
    page_run(r"""
const r = page(capabilities);
r.grant(true);
await tick();
r.element("voice-input-allow").handlers.click({isTrusted: false});
assert.equal(r.env.navigator.mediaDevices.requests.length, 0);
assert.match(r.element("voice-input-status").textContent, /directly/);
r.element("voice-input-allow").handlers.click({isTrusted: true});
assert.equal(r.env.navigator.mediaDevices.requests.length, 1, "request happens in the click, not a later task");
await tick();
assert.equal(r.env.tracks[0].stopped, 1);
assert.equal(FakeContext.instances.length, 0);
assert.equal(FakeSocket.instances.length, 0);
r.element("voice-toggle").handlers.click();
await tick();
r.element("voice-input-allow").handlers.click({isTrusted: true});
assert.equal(r.env.navigator.mediaDevices.requests.length, 2, "the permission button cannot create a second active stream");
await r.controller.client.stop();
""")


@pytest.mark.parametrize("teardown", ["r.grant(false)", 'r.env.events.pagehide()'])
def test_pending_local_permission_is_cancelled_on_native_revocation_or_navigation(teardown):
    page_run(r"""
const r = page(capabilities);
r.grant(true);
await tick();
let complete;
r.env.navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { complete = resolve; });
r.element("voice-input-allow").handlers.click({isTrusted: true});
TEARDOWN;
const before = r.element("voice-input-status").textContent;
complete({getTracks: () => r.env.tracks});
await tick();
assert.equal(r.env.tracks[0].stopped, 1);
assert.equal(r.element("voice-input-status").textContent, before);
assert.equal(FakeSocket.instances.length, 0);
assert.equal(session.token, "TOKEN-ABC-123");
""".replace("TEARDOWN", teardown))


def test_denial_is_visible_and_passive_refresh_does_not_claim_permission_was_granted():
    page_run(r"""
const r = page(capabilities);
r.grant(true);
await tick();
r.env.navigator.mediaDevices.getUserMedia = async () => { throw {name: "NotAllowedError"}; };
r.element("voice-input-allow").handlers.click({isTrusted: true});
await tick();
assert.equal(r.element("voice-audio-settings").open, true);
assert.match(r.element("voice-input-status").textContent, /denied.*operating system/);
await r.controller.audioInput.refresh();
assert.equal(r.controller.audioInput.snapshot().code, "denied");
assert.equal(session.token, "TOKEN-ABC-123");
""")


def test_legacy_embed_without_optional_settings_resources_keeps_existing_capture_errors():
    page_run(r"""
const enhancedEnvironment = environment;
environment = overrides => {
  const env = enhancedEnvironment(overrides);
  delete env.AIFactoryAudioInputUI;
  delete env.AIFactoryAudioInputText;
  return env;
};
const r = page(capabilities);
r.grant(true);
await tick();
r.env.navigator.mediaDevices.getUserMedia = async () => { throw {name: "NotAllowedError"}; };
r.element("voice-toggle").handlers.click();
await tick();
assert.match(r.element("voice-error").textContent, /Microphone access was blocked/);
assert.equal(r.controller.audioInput, null);
""")


def test_selected_device_disappearance_and_track_end_stop_capture_without_reauthentication():
    page_run(r"""
const r = page(capabilities);
r.grant(true);
await tick();
const handlers = {};
r.env.tracks[0].addEventListener = (name, fn) => { handlers[name] = fn; };
r.env.tracks[0].removeEventListener = (name) => { delete handlers[name]; };
r.controller.audioInput.select("desk");
r.element("voice-toggle").handlers.click();
await tick();
const socket = FakeSocket.instances.at(-1);
socket.open(); socket.json({type: "ready"});
handlers.ended();
assert.equal(r.controller.client.phase, "off");
assert.equal(socket.closed, 1000);
assert.equal(r.env.tracks[0].stopped, 1);
assert.match(r.element("voice-input-status").textContent, /stopped or was disconnected/);
await tick();
r.env.navigator.mediaDevices.enumerateDevices = async () => [{kind: "audioinput", deviceId: "headset", label: "Headset"}];
await r.controller.audioInput.refresh();
const missing = r.element("voice-input-device").children.find(option => option.value === "desk");
assert.match(missing.textContent, /Desk mic.*unavailable/);
assert.equal(r.element("voice-input-device").value, "desk");
r.element("voice-toggle").handlers.click();
await tick();
assert.equal(r.env.navigator.mediaDevices.requests.length, 1, "missing exact input never falls back to default");
assert.equal(session.token, "TOKEN-ABC-123");
""")


@pytest.mark.parametrize("search", ["?host=esaif-maui&voice=on", ""])
def test_settings_share_native_and_browser_gates_and_change_stops_until_explicit_restart(search):
    node(PAGE_AUDIO + r"""
(async () => {
  const rig = page(capabilities, process.argv[6]);
  if (process.argv[6]) rig.grant(true);
  await tick();
  const input = rig.controller.audioInput;
  assert(input);
  assert.equal(rig.env.navigator.mediaDevices.requests.length, 0);
  rig.element("voice-input-refresh").handlers.click();
  await tick();
  assert.equal(rig.env.navigator.mediaDevices.requests.length, 0);
  rig.element("voice-input-device").value = "desk";
  rig.element("voice-input-device").handlers.change();
  rig.element("voice-toggle").handlers.click();
  assert.equal(rig.env.navigator.mediaDevices.requests.length, 1);
  await tick();
  const socket = FakeSocket.instances.at(-1);
  socket.open(); socket.json({type: "ready"});
  rig.element("voice-input-device").value = "headset";
  rig.element("voice-input-device").handlers.change();
  assert.equal(rig.controller.client.phase, "off");
  assert.equal(socket.closed, 1000);
  assert.equal(rig.env.tracks[0].stopped, 1);
  assert.equal(rig.env.navigator.mediaDevices.requests.length, 1);
  assert.match(rig.element("voice-input-status").textContent, /Start talking/i);
  assert.equal(session.token, "TOKEN-ABC-123");
  rig.element("voice-toggle").handlers.click();
  assert.deepEqual(rig.env.navigator.mediaDevices.requests[1].audio.deviceId, {exact: "headset"});
  await tick();
  await rig.controller.client.stop();
})().catch(error => { console.error(error); process.exit(1); });
""", STATIC / "voice.js", STATIC / "audio-input.js", STATIC / "audio-input-ui.js",
         STATIC / "audio-input.en.js", search)


def test_settings_markup_is_optional_localized_and_after_existing_more_info():
    source = (STATIC / "index.html").read_text("utf-8")
    assert source.index("More info") < source.index('id="voice-audio-settings"')
    assert source.index("/static/audio-input.js") < source.index("/static/voice.js")
    assert 'id="voice-input-device"' in source
    assert 'for="voice-input-device"' in source
    assert 'id="voice-input-status"' in source
    for name in ("audio-input.js", "audio-input-ui.js", "audio-input.en.js"):
        text = (STATIC / name).read_text("utf-8")
        assert "localStorage" not in text and "sessionStorage" not in text
        assert "innerHTML" not in text
