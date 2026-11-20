import json
import re
import subprocess
from pathlib import Path

from test_voice_frontend import node


STATIC = Path(__file__).parents[1] / "aifactory_agent" / "static"


HARNESS = r"""
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const tick = () => new Promise(resolve => setImmediate(resolve));
let now = 100000, callbacks = [], requests = [], sockets = [], contexts = [], agents = [], credentials = [];
let state = "Connected", remote = true, mediaResolve = null, agentResolve = null, deleteStatus = 204, deleteThrows = false;
const listenerId = "22222222-2222-4222-8222-222222222222";
let roster = [{identifier: {microsoftTeamsUserId: listenerId, isAnonymous: false}, endpointDetails: [{participantId: "endpoint-1"}], state: "Connected"}];
let participantCount = 2, recording = false, transcribing = false, consentRequired = false;
let resetStatus = 200, resetResolve = null, generation = 0;
let incomingMuteError = false, incomingMuteResolve = null;
let session = {token: "delegated-user-token", scopeKey: "project001-dev", audience: "project", expiresAt: now + 800000};
const tracks = () => [{stopped: false, stop() { this.stopped = true; }}];
const stream = () => { const own = tracks(); return {getTracks: () => own}; };
class Node {
  constructor(name) { this.name = name; this.targets = []; this.port = {posts: [], postMessage(value) { this.posts.push(value); }}; this.gain = {value: 1}; }
  connect(target) { this.targets.push(target); return target; }
  disconnect() { this.disconnected = true; }
  start() {}
  stop() {}
}
class Context {
  constructor() { contexts.push(this); this.destination = new Node("speaker"); this.audioWorklet = {addModule: async () => {}}; this.nodes = []; }
  createGain() { const n = new Node("gain"); this.nodes.push(n); return n; }
  createConstantSource() { const n = new Node("constant"); this.nodes.push(n); return n; }
  createMediaStreamDestination() { const n = new Node("outbound"); n.stream = stream(); this.nodes.push(n); return n; }
  createMediaStreamSource(s) { const n = new Node("remote"); n.stream = s; this.nodes.push(n); return n; }
  resume() { return Promise.resolve(); }
  close() { this.closed = true; return Promise.resolve(); }
}
class Worklet extends Node { constructor(context, name) { super(name); context.nodes.push(this); } }
class Socket {
  constructor(url) { this.url = url; this.readyState = 0; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
  send(message) { this.sent.push(message); }
  close() { this.readyState = 3; this.onclose?.(); }
  open() { this.readyState = 1; this.onopen(); }
  receive(value) { this.onmessage({data: typeof value === "object" && !(value instanceof ArrayBuffer) ? JSON.stringify(value) : value}); }
}
class Call {
  constructor() {
    this.state = state; this.listeners = {};
    this.isIncomingAudioMuted = false; this.incomingMuteCalls = 0;
    this.remoteParticipants = roster.map(p => ({...p, on() {}, off() {}}));
    this.totalParticipantCount = participantCount;
    this.features = {
      Recording: {isRecordingActive: recording, isTeamsConsentRequired: consentRequired, listeners: {}, on: this.on, off: this.off},
      Transcription: {isTranscriptionActive: transcribing, isTeamsConsentRequired: consentRequired, listeners: {}, on: this.on, off: this.off}
    };
    this.remoteAudioStreams = remote ? [{getMediaStream: async () => mediaResolve ? await new Promise(resolve => { mediaResolve = resolve; }) : stream()}] : [];
  }
  feature(name) { return this.features[name]; }
  stopAudio() { throw new Error("Never fall back to the operator microphone"); }
  async muteIncomingAudio() {
    this.incomingMuteCalls++;
    if (incomingMuteError) throw new Error("SDK mute failure with private context");
    if (incomingMuteResolve) await new Promise(resolve => { incomingMuteResolve = resolve; });
    this.isIncomingAudioMuted = true;
  }
  mute() { throw new Error("Do not mute the agent's outgoing speech to fix local monitoring"); }
  on(event, handler) {
    if(this.remoteAudioStreams && !["stateChanged", "remoteAudioStreamsUpdated", "remoteParticipantsUpdated", "totalParticipantCountChanged", "isIncomingAudioMutedChanged"].includes(event)) {
      throw new Error("Unsupported Call event: " + event);
    }
    (this.listeners[event] ||= new Set()).add(handler);
  }
  off(event, handler) { this.listeners[event]?.delete(handler); }
  change(next) { this.state = next; for (const fn of [...this.listeners.stateChanged || []]) fn(); }
  hangUp() { this.hungUp = true; this.change("Disconnected"); return Promise.resolve(); }
}
const sdk = {
  Features: {Recording: "Recording", Transcription: "Transcription"},
  CallClient: class { async createCallAgent() { if (agentResolve) await new Promise(resolve => { agentResolve = resolve; }); const agent = {
    join(locator, options) { this.locator = locator; this.options = options; this.call = new Call(); return this.call; },
    dispose() { this.disposed = true; }
  }; agents.push(agent); return agent; } dispose() { this.disposed = true; } },
  LocalAudioStream: class { constructor(s) { this.stream = s; } },
  AzureCommunicationTokenCredential: class { constructor(token) { this.token = token; credentials.push(this); } dispose() { this.disposed = true; } }
};
const issued = {session_id: "one", meeting_session: "opaque-session-ticket", meeting_url: "https://teams.microsoft.com/meet/123?p=approved",
  voice_generation: 0,
  allowed_participant_object_ids: [listenerId],
  scope_key: session.scopeKey, audience: session.audience, acs_token: "acs-credential", expires_at: (now + 700000)/1000,
  acs_expires_at: (now + 3600000)/1000, display_name: "ESAF AI", lobby_timeout_seconds: 30};
const env = {isSecureContext: true, AudioContext: Context, AudioWorkletNode: Worklet, WebSocket: Socket,
  location: {protocol: "https:", host: "esaf.example"}, Date: {now: () => now},
  setTimeout(fn, ms) { const id = {fn, ms, active: true}; callbacks.push(id); return id; },
  clearTimeout(id) { if (id) id.active = false; },
  fetch: async (url, options) => { requests.push({url, options});
    if(url.endsWith("/voice-reset")) {
      if(resetResolve) await new Promise(resolve => {resetResolve = resolve;});
      return {ok: resetStatus === 200, status: resetStatus,
        json: async () => ({session_id: issued.session_id, meeting_session: "new-voice-ticket-" + generation,
          voice_generation: ++generation})};
    }
    if(options.method === "DELETE" && deleteThrows) throw new Error("SECRET token and meeting URL");
    const status = options.method === "DELETE" ? deleteStatus : 201;
    return {ok: status < 400, status, json: async () => issued}; }
};
const scope = {console, globalThis: env, Date: env.Date, URL, URLSearchParams, ArrayBuffer, Uint8Array, Float32Array, Promise};
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), scope);
let states = [], errors = [];
const client = env.AIFactoryTeamsMeeting.createMeetingClient({env, sdk, getSession: () => session,
  onState: state => states.push(state), onMessage: message => errors.push(message)});
const join = () => client.start({meetingUrl: issued.meeting_url, consentAcknowledged: true});
const find = name => contexts[0].nodes.find(n => n.name === name);
"""


def test_module_is_valid_and_does_not_duplicate_auth_or_persist_conversation():
    path = STATIC / "teams-meeting.js"
    assert subprocess.run(["node", "--check", str(path)], capture_output=True).returncode == 0
    source = path.read_text("utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|eval\(|localStorage|sessionStorage|MediaRecorder|getUserMedia", source)
    assert "AIFactoryAgent" in source and "voiceSession" in source and "/api/voice/ws" in source
    assert "ai.azure.com" not in source and "openai.azure.com" not in source
    assert '"sv"' in source or "sv:" in source


def test_offline_sdk_is_pinned_and_supplier_notices_are_preserved():
    package = json.loads((STATIC / "teams-meeting-frontend" / "package.json").read_text("utf-8"))
    assert package["dependencies"] == {
        "@azure/communication-calling": "1.46.1", "@azure/communication-common": "2.5.0",
    }
    bundle = STATIC / "vendor" / "teams-meeting-sdk.min.js"
    assert bundle.stat().st_size > 100000
    assert subprocess.run(["node", "--check", str(bundle)], capture_output=True).returncode == 0
    notices = (STATIC / "teams-meeting-frontend" / "THIRD-PARTY-NOTICES.txt").read_text("utf-8")
    assert "MICROSOFT SOFTWARE LICENSE TERMS" in notices
    assert "@azure/communication-calling 1.46.1" in notices
    assert "@azure/communication-common 2.5.0" in notices


def test_consent_required_and_no_microphone_or_identity_before_approval():
    node(HARNESS + r"""
(async () => {
  await client.start({meetingUrl: issued.meeting_url, consentAcknowledged: false});
  assert.equal(requests.length, 0); assert.equal(contexts.length, 0); assert.equal(agents.length, 0);
  assert.ok(errors.includes("consent"));
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_real_acs_signatures_and_separate_remote_capture_outbound_audio_paths():
    node(HARNESS + r"""
(async () => {
  await join();
  assert.equal(agents.length, 1);
  assert.equal(agents[0].locator.meetingLink, issued.meeting_url);
  const outbound = find("outbound"), playback = find("voice-playback"), capture = find("voice-capture");
  assert.equal(agents[0].options.audioOptions.localAudioStreams[0].stream, outbound.stream);
  assert.ok(playback.targets.includes(outbound));
  assert.ok(!playback.targets.includes(contexts[0].destination));
  assert.equal(requests[0].options.headers.Authorization, "Bearer delegated-user-token");
  const ws = sockets[0]; assert.equal(ws.url, "wss://esaf.example/api/voice/ws");
  ws.open(); const hello = JSON.parse(ws.sent[0]);
  assert.equal(hello.token, session.token); assert.equal(hello.meeting_session, issued.meeting_session);
  ws.receive({type: "ready"});
  const pcm = new ArrayBuffer(960);
  for (let i=0; i<3; i++) capture.port.onmessage({data: pcm});
  assert.equal(ws.sent.filter(v => typeof v !== "string").length, 1);
  ws.receive(new ArrayBuffer(960));
  for (let i=0; i<3; i++) capture.port.onmessage({data: pcm});
  assert.equal(ws.sent.filter(v => typeof v !== "string").length, 1, "half-duplex suppresses remote echoes");
  playback.port.onmessage({data: {drained: true}}); now += 1000;
  for (let i=0; i<3; i++) capture.port.onmessage({data: pcm});
  assert.equal(ws.sent.filter(v => typeof v !== "string").length, 2);
  await client.stop();
  assert.ok(agents[0].disposed && agents[0].call.hungUp && credentials[0].disposed && contexts[0].closed);
  assert.ok(outbound.stream.getTracks().every(track => track.stopped));
  assert.equal(requests.at(-1).options.method, "DELETE");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_lobby_timeout_never_opens_voice_relay_and_cleans_up():
    node(HARNESS + r"""
(async () => {
  state = "InLobby";
  const pending = join(); for(let i=0; i<12; i++) await tick();
  assert.equal(sockets.length, 0);
  const timeout = callbacks.find(c => c.active && c.ms === 30000); assert.ok(timeout);
  timeout.fn(); await pending;
  assert.ok(agents[0].call.hungUp && contexts[0].closed);
  assert.equal(sockets.length, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_relay_loss_leaves_meeting_without_automatic_reconnect():
    node(HARNESS + r"""
(async () => {
  await join(); sockets[0].open(); sockets[0].receive({type: "ready"}); sockets[0].close();
  for(let i=0; i<6; i++) await tick();
  assert.equal(sockets.length, 1); assert.equal(agents.length, 1);
  assert.ok(agents[0].call.hungUp); assert.ok(contexts[0].closed);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_cancel_during_call_agent_creation_disposes_late_agent_without_joining():
    node(HARNESS + r"""
(async () => {
  agentResolve = true;
  const pending = join(); for(let i=0; i<12; i++) await tick();
  await client.stop(); agentResolve(); await pending;
  assert.ok(agents[0].disposed); assert.equal(agents[0].call, undefined);
  assert.equal(sockets.length, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_account_or_scope_change_leaves_and_never_uses_changed_token():
    node(HARNESS + r"""
(async () => {
  await join(); sockets[0].open(); sockets[0].receive({type: "ready"});
  session = {...session, token: "changed-token", scopeKey: "another-scope"};
  client.sessionChanged();
  for(let i=0; i<6; i++) await tick();
  assert.ok(agents[0].call.hungUp && contexts[0].closed);
  assert.equal(requests.at(-1).options.headers.Authorization, "Bearer delegated-user-token");
  assert.equal(sockets.length, 1);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_no_remote_audio_and_sdk_reconnecting_fail_closed():
    node(HARNESS + r"""
(async () => {
  remote = false; await join();
  const timer = callbacks.find(c => c.active && c.ms === 30000); assert.ok(timer); timer.fn();
  for(let i=0; i<6; i++) await tick();
  assert.ok(agents[0].call.hungUp);
  remote = true; await join();
  agents[1].call.change("Connecting");
  for(let i=0; i<6; i++) await tick();
  assert.ok(agents[1].call.hungUp);
  assert.equal(agents.length, 2, "no automatic call recreation");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_unconfirmed_server_cleanup_is_visible_while_local_cleanup_continues():
    node(HARNESS + r"""
(async () => {
  for (const status of [202, 503]) {
    deleteStatus = status;
    await join(); const index = agents.length - 1; await client.stop();
    assert.ok(agents[index].disposed && contexts[index].closed);
    assert.equal(errors.at(-1), "cleanup_pending");
  }
  deleteThrows = true;
  await join(); await client.stop();
  assert.equal(errors.at(-1), "cleanup_pending");
  assert.ok(errors.every(value => !value.includes("SECRET")));
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_local_acs_hangup_error_does_not_skip_dispose_or_server_cleanup():
    node(HARNESS + r"""
(async () => {
  await join();
  agents[0].call.hangUp = async () => { throw new Error("SECRET SDK problem"); };
  await client.stop();
  assert.ok(agents[0].disposed && contexts[0].closed && credentials[0].disposed);
  assert.equal(requests.at(-1).options.method, "DELETE");
  assert.equal(errors.at(-1), "cleanup_pending");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_unknown_anonymous_duplicate_or_incomplete_roster_never_opens_relay():
    node(HARNESS + r"""
(async () => {
  const good = roster[0];
  for (const participants of [
    [{...good, identifier: {microsoftTeamsUserId: "33333333-3333-4333-8333-333333333333"}}],
    [{...good, identifier: {microsoftTeamsUserId: listenerId, isAnonymous: true}}],
    [{...good, identifier: {phoneNumber: "+15550000000"}}],
    [good, {...good, endpointDetails: [{participantId: "endpoint-2"}]}],
    [{...good, endpointDetails: []}],
    [{...good, endpointDetails: [{participantId: "endpoint-1"}, {participantId: "endpoint-2"}]}],
    [],
  ]) {
    roster = participants; participantCount = participants.length + 1;
    await join();
    assert.equal(sockets.length, 0);
    assert.ok(agents.at(-1).call.hungUp);
    assert.equal(errors.at(-1), "participants");
  }
  roster = [good]; participantCount = 100;
  await join(); assert.equal(sockets.length, 0);
  participantCount = 3;
  await join(); assert.equal(sockets.length, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_roster_change_immediately_stops_audio_and_leaves_without_rejoin():
    node(HARNESS + r"""
(async () => {
  await join(); const ws = sockets[0]; ws.open(); ws.receive({type: "ready"});
  const capture = find("voice-capture"), playback = find("voice-playback");
  ws.receive(new ArrayBuffer(960)); const previous = playback.port.posts.length;
  const call = agents[0].call;
  for(const handler of [...call.listeners.remoteParticipantsUpdated || []]) handler({added: [roster[0]], removed: []});
  for(let i=0; i<3; i++) capture.port.onmessage({data: new ArrayBuffer(960)});
  ws.receive(new ArrayBuffer(960));
  assert.equal(playback.port.posts.length, previous);
  assert.equal(ws.sent.filter(v => typeof v !== "string").length, 0);
  for(let i=0; i<12; i++) await tick();
  assert.ok(call.hungUp && contexts[0].closed);
  assert.equal(agents.length, 1); assert.equal(errors.at(-1), "participants");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_roster_is_rechecked_before_audio_even_without_notification():
    node(HARNESS + r"""
(async () => {
  await join(); const ws = sockets[0]; ws.open(); ws.receive({type: "ready"});
  agents[0].call.remoteParticipants[0].identifier = {unknown: "unresolved"};
  ws.receive(new ArrayBuffer(960));
  assert.equal(find("voice-playback").port.posts.length, 0);
  for(let i=0; i<12; i++) await tick();
  assert.ok(agents[0].call.hungUp);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_endpoint_replacement_is_detected_before_new_audio_is_forwarded():
    node(HARNESS + r"""
(async () => {
  await join(); const ws = sockets[0]; ws.open(); ws.receive({type: "ready"});
  agents[0].call.remoteParticipants[0].endpointDetails = [{participantId: "new-endpoint"}];
  for(let i=0; i<3; i++) find("voice-capture").port.onmessage({data: new ArrayBuffer(960)});
  assert.equal(ws.sent.filter(v => typeof v !== "string").length, 0);
  for(let i=0; i<12; i++) await tick();
  assert.ok(agents[0].call.hungUp);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_recording_transcription_or_teams_consent_prevents_processing_and_is_visible():
    node(HARNESS + r"""
(async () => {
  for(const flag of ["recording", "transcribing", "consent"]) {
    recording = flag === "recording"; transcribing = flag === "transcribing"; consentRequired = flag === "consent";
    await join();
    assert.equal(sockets.length, 0); assert.ok(agents.at(-1).call.hungUp);
    assert.equal(errors.at(-1), "recording");
  }
  recording = transcribing = consentRequired = false;
  await join(); sockets[0].open(); sockets[0].receive({type: "ready"});
  const feature = agents.at(-1).call.features.Recording;
  feature.isRecordingActive = true;
  for(const handler of [...feature.listeners.isRecordingActiveChanged || []]) handler();
  for(let i=0; i<12; i++) await tick();
  assert.ok(agents.at(-1).call.hungUp); assert.equal(errors.at(-1), "recording");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_mute_resume_and_stop_speaking_replace_voice_connection_without_rejoining_teams():
    node(HARNESS + r"""
(async () => {
  await join(); const ws = sockets[0]; ws.open(); ws.receive({type: "ready"});
  const capture = find("voice-capture"), playback = find("voice-playback");
  await client.pause();
  assert.equal(client.phase, "paused");
  assert.equal(ws.readyState, 3);
  assert.ok(requests.at(-1).url.endsWith("/voice-reset"));
  assert.equal(JSON.parse(requests.at(-1).options.body).voice_generation, 0);
  const cleared = playback.port.posts.length;
  ws.receive(new ArrayBuffer(960));
  for(let i=0; i<3; i++) capture.port.onmessage({data: new ArrayBuffer(960)});
  assert.equal(playback.port.posts.length, cleared);
  assert.equal(ws.sent.filter(v => typeof v !== "string").length, 0);
  await client.resume({consentAcknowledged: false});
  assert.equal(client.phase, "paused");
  await client.resume({consentAcknowledged: true});
  assert.equal(sockets.length, 2);
  const second = sockets[1]; second.open(); second.receive({type: "ready"});
  assert.equal(client.phase, "listening");
  assert.equal(JSON.parse(second.sent[0]).meeting_session, "new-voice-ticket-0");
  ws.receive({type: "ready"}); ws.receive(new ArrayBuffer(960));
  assert.equal(playback.port.posts.length, cleared, "old provider output stays rejected after resume");
  now += 1000;
  for(let i=0; i<3; i++) capture.port.onmessage({data: new ArrayBuffer(960)});
  assert.equal(second.sent.filter(v => typeof v !== "string").length, 1);
  await client.interrupt();
  assert.equal(sockets.length, 3);
  const stopped = playback.port.posts.length;
  second.receive(new ArrayBuffer(960)); assert.equal(playback.port.posts.length, stopped);
  const third = sockets[2]; third.open(); third.receive({type: "ready"}); third.receive(new ArrayBuffer(960));
  assert.equal(playback.port.posts.length, stopped + 1);
  assert.equal(agents.length, 1, "reset voice, not the Teams call");
  assert.equal(requests.filter(r => r.url === "/api/teams-meetings/sessions").length, 1);
  await client.stop();
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_reset_failure_ends_meeting_without_falling_back_to_old_voice():
    node(HARNESS + r"""
(async () => {
  await join(); sockets[0].open(); sockets[0].receive({type: "ready"});
  resetStatus = 503;
  await client.interrupt();
  assert.ok(agents[0].call.hungUp && contexts[0].closed);
  assert.equal(sockets.length, 1); assert.equal(client.phase, "off");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_leave_during_reset_discards_late_ticket_and_concurrent_controls_do_not_duplicate_reset():
    node(HARNESS + r"""
(async () => {
  await join(); sockets[0].open(); sockets[0].receive({type: "ready"});
  resetResolve = true;
  const pending = client.pause();
  for(let i=0; i<8; i++) await tick();
  const resumed = client.resume({consentAcknowledged: true});
  assert.equal(requests.filter(r => r.url.endsWith("/voice-reset")).length, 1);
  await client.stop(); resetResolve(); await Promise.all([pending, resumed]);
  assert.equal(sockets.length, 1);
  assert.ok(agents[0].call.hungUp);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_delegated_meeting_audio_is_metadata_bound_without_claiming_remote_playback():
    node(HARNESS + r"""
(async () => {
  await join(); const ws = sockets[0]; ws.open();
  ws.receive({type: "ready", mode: "delegated", playback_receipts: true});
  const playback = find("voice-playback");
  ws.receive({type: "audio_chunk", playback_id: "p1", item_id: "i1", response_id: "r1",
    content_index: 0, start_sample: 0, end_sample: 480});
  ws.receive(new ArrayBuffer(960));
  assert.equal(playback.port.posts.length, 1);
  playback.port.onmessage({data: {playback_id: "p1", item_id: "i1", epoch: 0,
    played_samples: 480, context_time: 1}});
  assert.ok(!ws.sent.some(v => typeof v === "string" && JSON.parse(v).type === "playback"),
    "rendering into an ACS sender does not prove remote hearing");
  ws.receive(new ArrayBuffer(960));
  for(let i=0; i<12; i++) await tick();
  assert.ok(agents[0].call.hungUp, "delegated PCM without metadata fails closed");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_delegated_metadata_must_match_pcm_and_never_survives_voice_reset():
    node(HARNESS + r"""
(async () => {
  await join(); const first = sockets[0]; first.open();
  first.receive({type: "ready", mode: "delegated", playback_receipts: true});
  first.receive({type: "audio_chunk", playback_id: "p1", item_id: "i1", response_id: "r1",
    content_index: 0, start_sample: 0, end_sample: 480});
  await client.interrupt();
  const second = sockets[1]; second.open();
  second.receive({type: "ready", mode: "delegated", playback_receipts: true});
  second.receive(new ArrayBuffer(960));
  for(let i=0; i<12; i++) await tick();
  assert.ok(agents[0].call.hungUp, "metadata from the previous provider cannot bind new PCM");
  await join(); const third = sockets[2]; third.open();
  third.receive({type: "ready", mode: "delegated", playback_receipts: true});
  third.receive({type: "audio_chunk", playback_id: "p2", item_id: "i2", response_id: "r2",
    content_index: 0, start_sample: 0, end_sample: 480});
  third.receive(new ArrayBuffer(480));
  for(let i=0; i<12; i++) await tick();
  assert.ok(agents[1].call.hungUp, "PCM length must match its metadata");
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_local_meeting_monitor_is_muted_without_stopping_remote_capture_or_outbound_speech():
    node(HARNESS + r"""
(async () => {
  await join();
  const call = agents[0].call;
  assert.equal(call.incomingMuteCalls, 1);
  assert.equal(call.isIncomingAudioMuted, true);
  const ws = sockets[0]; ws.open(); ws.receive({type: "ready"});
  for(let i=0; i<3; i++) find("voice-capture").port.onmessage({data:new ArrayBuffer(960)});
  assert.equal(ws.sent.filter(value => typeof value !== "string").length, 1, "raw capture continues");
  ws.receive(new ArrayBuffer(960));
  assert.ok(find("voice-playback").targets.includes(find("outbound")), "reply goes to Teams, not local speakers");
  assert.equal(agents[0].options.audioOptions.muted, false);
  await client.stop();
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_local_monitor_mute_failure_or_unexpected_unmute_leaves_and_releases_media():
    node(HARNESS + r"""
(async () => {
  incomingMuteError = true;
  await join();
  assert.equal(sockets.length, 0);
  assert.ok(agents[0].call.hungUp && contexts[0].closed);
  incomingMuteError = false;
  await join();
  const call = agents[1].call;
  call.isIncomingAudioMuted = false;
  for(const handler of [...call.listeners.isIncomingAudioMutedChanged || []]) handler();
  for(let i=0; i<12; i++) await tick();
  assert.ok(call.hungUp && contexts[1].closed);
  assert.ok(!errors.some(value => value.includes("private context")));
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_leave_during_local_monitor_mute_does_not_open_a_late_voice_connection():
    node(HARNESS + r"""
(async () => {
  incomingMuteResolve = true;
  const joining = join();
  for(let i=0; i<12; i++) await tick();
  assert.equal(typeof incomingMuteResolve, "function");
  await client.stop();
  incomingMuteResolve(); await joining;
  assert.equal(sockets.length, 0);
  assert.ok(agents[0].call.hungUp && contexts[0].closed);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", STATIC / "teams-meeting.js")


def test_approved_full_duplex_forwards_speech_during_playback_and_flushes_on_barge_in():
    node(HARNESS + r"""
(async () => {
  issued.full_duplex = true;
  await join(); const ws=sockets[0];ws.open();ws.receive({type:"ready"});
  const capture=find("voice-capture"),playback=find("voice-playback"),pcm=new ArrayBuffer(960);
  capture.port.onmessage({data:pcm});
  ws.receive(new ArrayBuffer(960));
  capture.port.onmessage({data:pcm});
  ws.receive(new ArrayBuffer(960));
  capture.port.onmessage({data:pcm});
  assert.equal(ws.sent.filter(value=>typeof value!=="string").length,1,
    "return audio must not discard partially collected participant speech");
  assert.equal(client.phase,"speaking");
  ws.receive({type:"interrupted"});
  assert.equal(playback.port.posts.at(-1),null);
  assert.equal(client.phase,"listening");
  for(let i=0;i<3;i++)capture.port.onmessage({data:pcm});
  assert.equal(ws.sent.filter(value=>typeof value!=="string").length,2,
    "full duplex does not apply the half-duplex post-playback quiet window");
  assert.ok(agents[0].call.isIncomingAudioMuted);
  await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_full_duplex_still_stops_input_during_pause_reset_and_on_unauthorized_roster():
    node(HARNESS + r"""
(async () => {
  issued.full_duplex=true;
  await join();const ws=sockets[0];ws.open();ws.receive({type:"ready"});
  const capture=find("voice-capture"),pcm=new ArrayBuffer(960);
  await client.pause();
  for(let i=0;i<6;i++)capture.port.onmessage({data:pcm});
  assert.equal(ws.sent.filter(value=>typeof value!=="string").length,0);
  await client.resume({consentAcknowledged:true});
  const next=sockets[1];next.open();next.receive({type:"ready"});
  agents[0].call.remoteParticipants[0].identifier={unknown:"unapproved"};
  for(let i=0;i<3;i++)capture.port.onmessage({data:pcm});
  assert.equal(next.sent.filter(value=>typeof value!=="string").length,0);
  for(let i=0;i<12;i++)await tick();
  assert.ok(agents[0].call.hungUp);
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_full_duplex_requires_explicit_boolean_server_admission():
    node(HARNESS + r"""
(async () => {
  issued.full_duplex="true";
  await join();const ws=sockets[0];ws.open();ws.receive({type:"ready"});
  ws.receive(new ArrayBuffer(960));
  for(let i=0;i<3;i++)find("voice-capture").port.onmessage({data:new ArrayBuffer(960)});
  assert.equal(ws.sent.filter(value=>typeof value!=="string").length,0);
  await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")
