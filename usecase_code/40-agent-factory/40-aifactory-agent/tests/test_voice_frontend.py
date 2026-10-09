"""Node-driven tests for the browser voice assets. Node's VM runs the shipped scripts against mocks; no browser."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from aifactory_agent import web

STATIC = web.STATIC


def node(script, *args):
    result = subprocess.run(["node", "-", *map(str, args)], input=script, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout


WORKLET_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
function load(file, rate) {
  const registered = {};
  class AudioWorkletProcessor { constructor() { this.port = {posts: [], postMessage(message) { this.posts.push(message); }, onmessage: null}; } }
  vm.runInNewContext(fs.readFileSync(file, "utf8"), {AudioWorkletProcessor, registerProcessor: (name, type) => { registered[name] = type; }, sampleRate: rate});
  return registered;
}
"""


@pytest.mark.parametrize("script", ["voice-capture-worklet.js", "voice-playback-worklet.js", "voice-orb.js", "voice.js"])
def test_voice_scripts_are_syntactically_valid_and_avoid_unsafe_apis(script):
    path = STATIC / script
    assert subprocess.run(["node", "--check", str(path)], capture_output=True, text=True).returncode == 0
    source = path.read_text("utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function|localStorage|sessionStorage", source)
    assert "client_secret" not in source and "api-key" not in source.lower() and "ai.azure.com" not in source


def test_capture_passes_24khz_audio_through_as_clamped_pcm16_in_20ms_frames():
    node(WORKLET_HARNESS + r"""
const processors = load(process.argv[2], 24000);
const capture = new processors["voice-capture"]();
const block = new Float32Array(128).map((_, index) => index % 2 ? 2.0 : -2.0);
for (let round = 0; round < 8; round++) capture.process([[block]]);          // 1024 samples -> two 480-sample frames
const frames = capture.port.posts;
assert.equal(frames.length, 2);
assert.equal(frames[0].byteLength, 960);
const view = new Int16Array(frames[0]);
assert.equal(view[0], -32768);
assert.equal(view[1], 32767);
const ramp = new Float32Array(128).map((_, index) => index / 128);
const second = new processors["voice-capture"]();
for (let round = 0; round < 4; round++) second.process([[ramp]]);              // 512 samples
const out = new Int16Array(second.port.posts[0]);
assert.equal(out.length, 480);
assert.equal(out[0], 0);
assert.equal(out[1], Math.trunc((1 / 128) * 0x7fff));
assert.equal(out[128], 0);                                                      // ramp restarts every 128 samples
assert.ok(capture.process([[]]) === true && capture.process([]) === true);
""", STATIC / "voice-capture-worklet.js")


@pytest.mark.parametrize("rate", [48000, 44100, 16000])
def test_capture_resamples_to_24khz_without_losing_continuity(rate):
    node(WORKLET_HARNESS + r"""
const rate = Number(process.argv[3]);
const processors = load(process.argv[2], rate);
const capture = new processors["voice-capture"]();
const seconds = 1, frequency = 1000;
const total = rate * seconds;
let produced = [];
for (let start = 0; start < total; start += 128) {
  const block = new Float32Array(128).map((_, index) => 0.8 * Math.sin(2 * Math.PI * frequency * (start + index) / rate));
  capture.process([[block]]);
}
for (const buffer of capture.port.posts) produced.push(...new Int16Array(buffer));
const expected = 24000 * seconds;
assert.ok(Math.abs(produced.length - expected) <= 480, `samples ${produced.length} vs ${expected}`);
let crossings = 0, peak = 0;
for (let index = 1; index < produced.length; index++) {
  if ((produced[index - 1] < 0) !== (produced[index] < 0)) crossings++;
  peak = Math.max(peak, Math.abs(produced[index]));
}
assert.ok(Math.abs(crossings - 2 * frequency * (produced.length / 24000)) < 12, `zero crossings ${crossings}`);
assert.ok(peak > 0.7 * 32767 && peak <= 0.81 * 32767, `peak ${peak}`);
let largestJump = 0;
for (let index = 1; index < produced.length; index++) largestJump = Math.max(largestJump, Math.abs(produced[index] - produced[index - 1]));
assert.ok(largestJump < 0.8 * 32767 * 2 * Math.PI * frequency / 24000 * 1.3, `discontinuity ${largestJump}`);
""", STATIC / "voice-capture-worklet.js", rate)


def test_playback_plays_chunks_in_order_then_reports_drained_once_and_flushes_on_barge_in():
    node(WORKLET_HARNESS + r"""
const processors = load(process.argv[2], 24000);
const player = new processors["voice-playback"]();
const chunk = (...samples) => Int16Array.from(samples).buffer;
player.port.onmessage({data: chunk(16384, -16384, 8192)});
player.port.onmessage({data: chunk(32767)});
const out = [new Float32Array(8)];
player.process([], [out]);
assert.deepEqual(Array.from(out[0].slice(0, 4)).map(value => Math.round(value * 32768)), [16384, -16384, 8192, 32767]);
assert.deepEqual(Array.from(out[0].slice(4)), [0, 0, 0, 0]);
assert.equal(player.port.posts.filter(message => message && message.drained).length, 1);
player.process([], [out]);
assert.equal(player.port.posts.filter(message => message && message.drained).length, 1, "drained is reported once per run of audio");
player.port.onmessage({data: chunk(1000, 1000, 1000, 1000, 1000, 1000)});
player.process([], [[new Float32Array(2)]]);
player.port.onmessage({data: null});
const flushed = [new Float32Array(4)];
player.process([], [flushed]);
assert.deepEqual(Array.from(flushed[0]), [0, 0, 0, 0]);
assert.equal(player.port.posts.filter(message => message && message.drained).length, 2);
""", STATIC / "voice-playback-worklet.js")


def test_playback_resamples_to_the_device_rate_without_dropping_samples():
    node(WORKLET_HARNESS + r"""
const processors = load(process.argv[2], 48000);
const player = new processors["voice-playback"]();
const input = Int16Array.from({length: 240}, (_, index) => Math.round(20000 * Math.sin(2 * Math.PI * index / 24)));
player.port.onmessage({data: input.slice(0, 100).buffer});
player.port.onmessage({data: input.slice(100).buffer});
const rendered = [];
for (let round = 0; round < 8; round++) { const block = [new Float32Array(128)]; player.process([], [block]); rendered.push(...block[0]); }
const lastSound = rendered.findLastIndex(value => Math.abs(value) > 1e-6);
assert.ok(Math.abs(lastSound - 480) <= 3, `sound spans ${lastSound} output samples`);
let largestJump = 0;
for (let index = 1; index < 470; index++) largestJump = Math.max(largestJump, Math.abs(rendered[index] - rendered[index - 1]));
assert.ok(largestJump < 0.30, `chunk boundary discontinuity ${largestJump}`);
""", STATIC / "voice-playback-worklet.js")

ORB_HARNESS = r"""
const orb = require(process.argv[2]);
const assert = require("node:assert/strict");
"""


def test_orb_states_have_distinct_tones_and_the_right_kind_of_motion():
    node(ORB_HARNESS + r"""
const {describe} = orb;
const at = (state, time, level) => describe(state, time, level, false);
// listening is teal and answers the microphone level: louder -> bigger core, brighter glow, stronger ripples
assert.equal(at("listening", 0.4, 0).tone, "action");
assert.ok(at("listening", 0.4, 0.8).core.radius > at("listening", 0.4, 0).core.radius + 0.05);
assert.ok(at("listening", 0.4, 0.8).glow.alpha > at("listening", 0.4, 0).glow.alpha);
const ripple = (frame) => Math.max(...frame.rings.map((ring) => ring.alpha));
assert.ok(ripple(at("listening", 0.4, 0.9)) > ripple(at("listening", 0.4, 0)));
// speaking is the brightest, accent coloured and follows the output level
assert.equal(at("speaking", 0.4, 0).tone, "accent");
assert.ok(at("speaking", 0.4, 0.5).glow.alpha > at("listening", 0.4, 0.5).glow.alpha);
assert.ok(at("speaking", 0.4, 1).core.radius > at("speaking", 0.4, 0).core.radius);
// thinking has three rotating arcs and does not depend on sound
const first = at("thinking", 0, 0.9), later = at("thinking", 0.5, 0);
assert.equal(first.arcs.length, 3);
assert.notEqual(first.arcs[0].start, later.arcs[0].start);
assert.equal(first.core.radius !== undefined, true);
// connecting shows one expanding ring; error is red and still; off is dim
assert.equal(at("connecting", 0.2, 0).rings.length, 1);
assert.equal(at("error", 0, 0).tone, "danger");
assert.deepEqual(at("error", 0, 0), at("error", 9.1, 0.7));
assert.ok(at("off", 0, 0).core.alpha < 0.5 && at("off", 0, 0).glow.alpha <= 0.1);
// idle breathing is slow and subtle
const breathing = [0, 1, 2, 3, 4, 5].map((time) => at("off", time, 0).core.radius);
assert.ok(Math.max(...breathing) - Math.min(...breathing) < 0.05);
""", STATIC / "voice-orb.js")


def test_reduced_motion_frames_are_completely_static_for_every_state():
    node(ORB_HARNESS + r"""
for (const state of orb.STATES) {
  const base = orb.describe(state, 0, 0, true);
  for (const [time, level] of [[0.5, 0], [3.3, 0.9], [100, 1]]) {
    assert.deepEqual(orb.describe(state, time, level, true), base, state + " must not move with reduced motion");
  }
  assert.equal(orb.needsAnimation(state, true), false);
}
assert.equal(orb.needsAnimation("listening", false), true);
assert.equal(orb.needsAnimation("thinking", false), true);
assert.equal(orb.needsAnimation("off", false), false);
assert.equal(orb.needsAnimation("error", false), false);
""", STATIC / "voice-orb.js")


def test_every_frame_is_finite_and_within_drawable_ranges():
    node(ORB_HARNESS + r"""
const numbers = (value) => typeof value === "number" ? [value] : value && typeof value === "object" ? Object.values(value).flatMap(numbers) : [];
for (const state of orb.STATES) {
  for (let time = 0; time < 12; time += 0.37) {
    for (const level of [-1, 0, 0.3, 1, 5, NaN]) {
      const frame = orb.describe(state, time, level, false);
      for (const value of numbers(frame)) assert.ok(Number.isFinite(value), `${state} produced ${value}`);
      for (const part of [frame.core, frame.glow, ...frame.rings, ...frame.arcs]) {
        assert.ok(part.alpha >= 0 && part.alpha <= 1, `${state} alpha ${part.alpha}`);
        if (part.radius !== undefined) assert.ok(part.radius > 0 && part.radius < 4, `${state} radius ${part.radius}`);
      }
    }
  }
}
""", STATIC / "voice-orb.js")


def test_colours_come_from_the_theme_and_fall_back_safely():
    node(ORB_HARNESS + r"""
assert.deepEqual(orb.parseColor("#6750A4"), [103, 80, 164]);
assert.deepEqual(orb.parseColor("#fff"), [255, 255, 255]);
assert.deepEqual(orb.parseColor("rgb(1, 2, 3)"), [1, 2, 3]);
assert.deepEqual(orb.parseColor("rgba(300,0,0,0.5)"), [255, 0, 0]);
assert.deepEqual(orb.parseColor("not a colour", "#102030"), [16, 32, 48]);
assert.deepEqual(orb.parseColor("", null), [103, 80, 164]);
const defaults = orb.readPalette(null, null);
assert.deepEqual(Object.keys(defaults).sort(), ["accent", "action", "danger", "muted", "surface"]);
const themed = orb.readPalette({}, () => ({getPropertyValue: (name) => ({"--cp-accent": " #B9A7FF ", "--cp-action": "#62D4D8", "--cp-danger": "#FF8A7E"}[name] || "")}));
assert.deepEqual(themed.accent, [185, 167, 255]);
assert.deepEqual(themed.action, [98, 212, 216]);
assert.deepEqual(themed.muted, defaults.muted);
""", STATIC / "voice-orb.js")


def test_canvas_drawing_uses_only_valid_gradient_geometry_for_every_state():
    node(ORB_HARNESS + r"""
function context() {
  const calls = [];
  const record = (name) => (...args) => { calls.push([name, ...args]); return {addColorStop() {}}; };
  return {calls, clearRect: record("clearRect"), createRadialGradient: record("createRadialGradient"), beginPath: record("beginPath"),
    arc: record("arc"), fill: record("fill"), stroke: record("stroke"), set fillStyle(v) {}, set strokeStyle(v) {}, set lineWidth(v) {}, set lineCap(v) {}};
}
const palette = orb.readPalette(null, null);
for (const state of orb.STATES) {
  const ctx = context();
  orb.draw(ctx, 320, orb.describe(state, 1.3, 0.6, false), palette);
  assert.ok(ctx.calls.some(([name]) => name === "fill"), state + " fills the core");
  for (const [name, ...args] of ctx.calls) {
    if (name === "createRadialGradient") { assert.ok(args.every(Number.isFinite) && args[2] >= 0 && args[5] >= 0, state + " gradient " + args); }
    if (name === "arc") { assert.ok(args.every(Number.isFinite) && args[2] >= 0, state + " arc " + args); }
  }
}
""", STATIC / "voice-orb.js")


def test_nothing_the_orb_draws_is_clipped_by_the_canvas_edges():
    node(ORB_HARNESS + r"""
function context() {
  const calls = [];
  const record = (name) => (...args) => { calls.push([name, ...args]); return {addColorStop() {}}; };
  return {calls, clearRect: record("clearRect"), createRadialGradient: record("createRadialGradient"), beginPath: record("beginPath"),
    arc: record("arc"), fill: record("fill"), stroke: record("stroke"), set fillStyle(v) {}, set strokeStyle(v) {}, set lineWidth(v) { this.width = v; }, set lineCap(v) {}};
}
const palette = orb.readPalette(null, null);
for (const size of [200, 320, 520]) {
  for (const state of orb.STATES) {
    for (let time = 0; time < 6; time += 0.31) {
      for (const level of [0, 0.5, 1]) {
        const ctx = context();
        orb.draw(ctx, size, orb.describe(state, time, level, false), palette);
        for (const [name, ...args] of ctx.calls) {
          if (name === "arc") assert.ok(args[2] <= size / 2, `${state} arc radius ${args[2]} exceeds ${size / 2}`);
          if (name === "createRadialGradient") assert.ok(args[5] <= size / 2, `${state} gradient radius ${args[5]} exceeds ${size / 2}`);
        }
      }
    }
  }
}
""", STATIC / "voice-orb.js")


def test_orb_picks_up_theme_changes_without_a_state_change():
    node(ORB_HARNESS + r"""
let accent = "#B9A7FF";
const scheduled = [], colours = [];
const canvas = {width: 0, height: 0, clientWidth: 200, getContext: () => ({clearRect() {},
  createRadialGradient: () => ({addColorStop: (_, colour) => colours.push(colour)}), beginPath() {}, arc() {}, fill() {}, stroke() {},
  set fillStyle(v) {}, set strokeStyle(v) {}, set lineWidth(v) {}, set lineCap(v) {}})};
const environment = {devicePixelRatio: 1, requestAnimationFrame: (callback) => { scheduled.push(callback); return scheduled.length; }, cancelAnimationFrame() {},
  document: {hidden: false, documentElement: {}, addEventListener() {}}, performance: {now: () => 0}, matchMedia: () => ({matches: false}),
  getComputedStyle: () => ({getPropertyValue: (name) => name === "--cp-accent" ? accent : ""})};
const api = orb.createOrb(canvas, {environment});
api.start();
api.setState("thinking");
scheduled.shift()(1000);
assert.ok(colours.some((value) => value.startsWith("rgba(185,167,255")), "initial theme colour is used");
accent = "#102030";
colours.length = 0;
for (let step = 1; step <= 6; step++) { if (scheduled.length) scheduled.shift()(1000 + step * 400); }
assert.ok(colours.some((value) => value.startsWith("rgba(16,32,48")), "the new theme colour appears within about a second");
""", STATIC / "voice-orb.js")

def test_orb_animation_loop_runs_only_while_needed_and_visible():
    node(ORB_HARNESS + r"""
function make(options = {}) {
  const scheduled = [];
  let cancelled = 0;
  const canvas = {width: 0, height: 0, clientWidth: 200, getContext: () => ({clearRect() {}, createRadialGradient: () => ({addColorStop() {}}), beginPath() {}, arc() {}, fill() {}, stroke() {},
    set fillStyle(v) {}, set strokeStyle(v) {}, set lineWidth(v) {}, set lineCap(v) {}})};
  const environment = {devicePixelRatio: 2, requestAnimationFrame: (callback) => { scheduled.push(callback); return scheduled.length; },
    cancelAnimationFrame: () => { cancelled++; }, document: {hidden: false, documentElement: {}, addEventListener() {}}, performance: {now: () => 0},
    matchMedia: () => ({matches: Boolean(options.reduced)}), getComputedStyle: () => ({getPropertyValue: () => ""})};
  return {orb: orb.createOrb(canvas, {environment}), scheduled, canvas, environment, cancelled: () => cancelled};
}
let rig = make();
rig.orb.start();
rig.orb.setState("listening");
assert.ok(rig.scheduled.length >= 1, "an animated state schedules frames");
rig.scheduled.shift()(16);
assert.equal(rig.canvas.width, 400, "backing store follows device pixel ratio");
assert.ok(rig.scheduled.length >= 1, "loop continues while animated");
rig.orb.setState("error");
const before = rig.scheduled.length;
rig.scheduled.shift()(32);
assert.equal(rig.scheduled.length, before - 1, "a still state stops scheduling frames");
assert.throws(() => rig.orb.setState("exploding"), /Unknown orb state/);
rig.orb.stop();
assert.ok(rig.cancelled() >= 0);

rig = make({reduced: true});
rig.orb.start();
rig.orb.setState("speaking");
for (let step = 0; step < 5 && rig.scheduled.length; step++) rig.scheduled.shift()(16 * (step + 1));
assert.equal(rig.scheduled.length, 0, "reduced motion draws single frames but never keeps an animation loop");
assert.equal(rig.canvas.width, 400, "the static frame was still drawn");

rig = make();
rig.environment.document.hidden = true;
rig.orb.start();
rig.orb.setState("thinking");
rig.scheduled.shift()(16);
assert.equal(rig.scheduled.length, 0, "a hidden tab stops animating");
""", STATIC / "voice-orb.js")

CLIENT_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const voice = require(process.argv[2]);

class FakeSocket {
  static instances = [];
  constructor(url) { this.url = url; this.sent = []; this.readyState = 0; this.bufferedAmount = 0; this.closed = null; FakeSocket.instances.push(this); }
  send(data) { this.sent.push(data); }
  close(code) { this.closed = code === undefined ? 1000 : code; this.readyState = 3; }
  open() { this.readyState = 1; this.onopen && this.onopen(); }
  json(message) { this.onmessage({data: JSON.stringify(message)}); }
  audio(bytes) { this.onmessage({data: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)}); }
  drop() { this.readyState = 3; this.onclose && this.onclose({code: 1006}); }
}
class FakeNode {
  constructor(name) { this.name = name; this.connected = []; this.disconnected = false; this.port = {posts: [], postMessage(message) { this.posts.push(message); }, onmessage: null}; this.gain = {value: 1}; }
  connect(target) { this.connected.push(target); return target; }
  disconnect() { this.disconnected = true; }
  getFloatTimeDomainData(buffer) { buffer.fill(this.level || 0); }
}
class FakeContext {
  static instances = [];
  constructor(options) { this.options = options; this.modules = []; this.closed = false; this.state = "suspended"; this.destination = new FakeNode("destination");
    this.audioWorklet = {addModule: async (url) => { this.modules.push(url); }}; FakeContext.instances.push(this); }
  async resume() { this.state = "running"; }
  async close() { this.closed = true; }
  createMediaStreamSource(stream) { const node = new FakeNode("source"); node.stream = stream; return node; }
  createAnalyser() { const node = new FakeNode("analyser"); node.fftSize = 0; (this.analysers ||= []).push(node); return node; }
  createGain() { return new FakeNode("gain"); }
}
class FakeWorkletNode extends FakeNode {
  static instances = [];
  constructor(context, name, options) { super(name); this.options = options; FakeWorkletNode.instances.push(this); }
}
function environment(overrides = {}) {
  const tracks = [{stopped: 0, stop() { this.stopped++; }}];
  const intervals = [];
  const env = {
    isSecureContext: true, WebSocket: FakeSocket, AudioContext: FakeContext, AudioWorkletNode: FakeWorkletNode,
    location: {protocol: "https:", host: "agent.example"},
    navigator: {mediaDevices: {requests: [], async getUserMedia(constraints) { this.requests.push(constraints); return {getTracks: () => tracks}; }}},
    setInterval: (callback, ms) => { intervals.push({callback, ms}); return intervals.length; }, clearInterval: () => {},
    ...overrides,
  };
  env.tracks = tracks; env.intervals = intervals;
  return env;
}
const session = {token: "TOKEN-ABC-123", scopeKey: "project001-dev", audience: "project", expiresAt: Date.now() + 3600e3};
function make(overrides = {}, env = environment()) {
  const log = {states: [], transcripts: [], answers: [], messages: [], levels: []};
  const client = voice.createVoiceClient({env, getSession: () => session, onState: (state) => log.states.push(state),
    onTranscript: (...args) => log.transcripts.push(args), onAnswer: (answer) => log.answers.push(answer),
    onMessage: (text, fatal) => log.messages.push([text, fatal]), onLevel: (level) => log.levels.push(level), ...overrides});
  return {client, env, log};
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
async function started(overrides, env) {
  const rig = make(overrides, env);
  await rig.client.start();
  const socket = FakeSocket.instances.at(-1);
  socket.open();
  return {...rig, socket, context: FakeContext.instances.at(-1), capture: FakeWorkletNode.instances.findLast((n) => n.name === "voice-capture"),
    playback: FakeWorkletNode.instances.findLast((n) => n.name === "voice-playback")};
}
"""


def test_start_requests_the_microphone_loads_worklets_and_authenticates_in_the_first_frame_only():
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  assert.deepEqual(rig.context.modules, ["/static/voice-capture-worklet.js", "/static/voice-playback-worklet.js"]);
  assert.deepEqual(rig.context.options, {sampleRate: 24000, latencyHint: "interactive"});
  assert.deepEqual(rig.env.navigator.mediaDevices.requests[0].audio,
    {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true});
  assert.equal(rig.socket.url, "wss://agent.example/api/voice/ws");
  assert.ok(!rig.socket.url.includes("TOKEN") && !rig.socket.url.includes("?"), "the token must never be in the URL");
  assert.deepEqual(JSON.parse(rig.socket.sent[0]), {type: "hello", token: "TOKEN-ABC-123", scope_key: "project001-dev", audience: "project"});
  assert.equal(rig.socket.sent.length, 1);
  assert.equal(rig.log.states.at(-1), "connecting");
  rig.socket.json({type: "ready", session_id: "s", audio: {sample_rate: 24000}});
  assert.equal(rig.client.phase, "active");
  assert.equal(rig.log.states.at(-1), "listening");
  const local = make({}, environment({location: {protocol: "http:", host: "localhost:8080"}}));
  await local.client.start();
  assert.equal(FakeSocket.instances.at(-1).url, "ws://localhost:8080/api/voice/ws");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_microphone_frames_are_batched_sent_as_binary_and_stop_when_muted():
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  const frame = () => new Int16Array(480).fill(1000).buffer;
  rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 1, "nothing is streamed before the server is ready");
  rig.socket.json({type: "ready"});
  rig.capture.port.onmessage({data: frame()});
  rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 1);
  rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 2);
  assert.equal(rig.socket.sent[1].byteLength, 2880, "three 20 ms frames per message");
  rig.client.setMuted(true);
  for (let index = 0; index < 6; index++) rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 2, "muted audio never leaves the browser");
  rig.client.setMuted(false);
  for (let index = 0; index < 3; index++) rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 3);
  rig.socket.bufferedAmount = 10 * 1024 * 1024;
  for (let index = 0; index < 6; index++) rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 3, "a congested connection drops audio instead of adding latency");
  rig.socket.bufferedAmount = 96001;
  for (let index = 0; index < 3; index++) rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 3, "more than two seconds of backlog is dropped, never queued");
  rig.socket.bufferedAmount = 96000;
  for (let index = 0; index < 3; index++) rig.capture.port.onmessage({data: frame()});
  assert.equal(rig.socket.sent.length, 4, "up to two seconds of backlog is still delivered");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_stopping_or_restarting_while_the_microphone_prompt_is_open_never_leaves_it_on():
    node(CLIENT_HARNESS + r"""
(async () => {
  const pending = [];
  const tracks = [];
  const env = environment();
  env.navigator.mediaDevices.getUserMedia = function (constraints) {
    this.requests.push(constraints);
    return new Promise((resolve) => {
      const track = {stopped: 0, stop() { this.stopped++; }};
      tracks.push(track);
      pending.push(() => resolve({getTracks: () => [track]}));
    });
  };
  const rig = make({}, env);
  const first = rig.client.start();
  await tick();
  assert.equal(env.navigator.mediaDevices.requests.length, 1, "the permission prompt is open");
  await rig.client.stop();
  assert.equal(rig.client.phase, "off");
  const second = rig.client.start();
  await tick();
  assert.equal(env.navigator.mediaDevices.requests.length, 2);
  pending[0]();
  await first;
  await tick();
  assert.equal(tracks[0].stopped, 1, "the stream that arrived after Stop is stopped immediately");
  assert.equal(FakeSocket.instances.length, 0, "no connection is opened for the cancelled start");
  assert.equal(rig.client.phase, "connecting", "the newer start is unaffected");
  pending[1]();
  await second;
  await tick();
  assert.equal(tracks[1].stopped, 0, "the current start keeps its microphone");
  assert.equal(FakeSocket.instances.length, 1);
  await rig.client.stop();
  assert.equal(tracks[1].stopped, 1, "stopping releases the microphone");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_stopping_before_the_worklets_load_never_asks_for_the_microphone():
    node(CLIENT_HARNESS + r"""
(async () => {
  const env = environment();
  let loaded;
  let loads = 0;
  env.AudioContext = class extends FakeContext {
    constructor(options) {
      super(options);
      this.audioWorklet = {addModule: (url) => {
        this.modules.push(url);
        return loads++ === 0 ? new Promise((resolve) => { loaded = resolve; }) : Promise.resolve();
      }};
    }
  };
  const rig = make({}, env);
  const starting = rig.client.start();
  await tick();
  assert.equal(env.navigator.mediaDevices.requests.length, 0);
  await rig.client.stop();
  loaded();
  await starting;
  await tick();
  assert.equal(env.navigator.mediaDevices.requests.length, 0, "a cancelled start never prompts for the microphone");
  assert.equal(rig.client.phase, "off");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_server_state_drives_the_orb_and_speaking_lasts_until_playback_drains():
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  rig.socket.json({type: "ready"});
  rig.socket.json({type: "state", state: "thinking"});
  assert.equal(rig.log.states.at(-1), "thinking");
  rig.socket.json({type: "state", state: "speaking"});
  rig.socket.audio(new Int16Array(480).fill(5));
  assert.equal(rig.log.states.at(-1), "speaking");
  assert.equal(rig.playback.port.posts.length, 1);
  assert.equal(rig.playback.port.posts[0].byteLength, 960, "audio is forwarded to the playback worklet");
  rig.socket.json({type: "state", state: "listening"});
  assert.equal(rig.log.states.at(-1), "speaking", "buffered speech keeps the orb speaking");
  rig.playback.port.onmessage({data: {drained: true}});
  assert.equal(rig.log.states.at(-1), "listening");
  rig.socket.audio(new Int16Array(480).fill(5));
  rig.socket.json({type: "interrupted"});
  assert.equal(rig.playback.port.posts.at(-1), null, "barge-in flushes the playback queue");
  assert.equal(rig.log.states.at(-1), "listening");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_transcripts_answers_and_errors_reach_the_page_without_ending_the_session():
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  rig.socket.json({type: "ready"});
  rig.socket.json({type: "transcript", role: "user", text: "How do", final: false});
  rig.socket.json({type: "transcript", role: "user", text: "How do I start?", final: true});
  assert.deepEqual(rig.log.transcripts, [["user", "How do", false], ["user", "How do I start?", true]]);
  rig.socket.json({type: "answer", answer: "Open the wizard [S1].", citations: [{citation_id: "S1"}], spoken: "Open the wizard."});
  assert.equal(rig.log.answers[0].answer, "Open the wizard [S1].");
  rig.socket.json({type: "error", code: "knowledge_unavailable", message: "Knowledge is unavailable.", fatal: false});
  assert.deepEqual(rig.log.messages.at(-1), ["Knowledge is unavailable.", false]);
  assert.equal(rig.client.phase, "active");
  rig.socket.onmessage({data: "not json"});
  rig.socket.onmessage({data: JSON.stringify({type: "mystery"})});
  assert.equal(rig.client.phase, "active");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_fatal_errors_and_dropped_connections_clean_up_and_explain():
    node(CLIENT_HARNESS + r"""
(async () => {
  let rig = await started();
  rig.socket.json({type: "ready"});
  rig.socket.json({type: "error", code: "forbidden", message: "Not authorized.", fatal: true});
  await tick();
  assert.equal(rig.client.phase, "error");
  assert.equal(rig.log.states.at(-1), "error");
  assert.deepEqual(rig.log.messages.at(-1), ["Not authorized.", true]);
  assert.ok(rig.env.tracks[0].stopped >= 1 && rig.context.closed && rig.socket.closed !== null, "resources are released");

  rig = await started();
  rig.socket.json({type: "ready"});
  rig.socket.drop();
  await tick();
  assert.equal(rig.client.phase, "error");
  assert.match(rig.log.messages.at(-1)[0], /connection was lost/i);

  rig = await started();
  rig.socket.json({type: "ready"});
  rig.socket.json({type: "closed", reason: "idle"});
  await tick();
  assert.equal(rig.client.phase, "off");
  assert.equal(rig.log.states.at(-1), "off");
  assert.match(rig.log.messages.at(-1)[0], /inactivity/i);
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_unavailable_prerequisites_fail_with_a_clear_message_before_touching_the_microphone():
    node(CLIENT_HARNESS + r"""
(async () => {
  let rig = make({getSession: () => null});
  await rig.client.start();
  assert.match(rig.log.messages[0][0], /sign in/i);
  assert.equal(rig.client.phase, "off");

  rig = make({}, environment({isSecureContext: false}));
  await rig.client.start();
  assert.match(rig.log.messages[0][0], /HTTPS/);
  assert.equal(rig.env.navigator.mediaDevices.requests.length, 0);

  rig = make({}, environment({AudioWorkletNode: undefined}));
  await rig.client.start();
  assert.match(rig.log.messages[0][0], /does not support/i);

  rig = make({getSession: () => ({...session, expiresAt: Date.now() + 5e3})});
  await rig.client.start();
  assert.match(rig.log.messages[0][0], /sign in again/i);
  assert.equal(rig.env.navigator.mediaDevices.requests.length, 0);

  const denied = environment();
  denied.navigator.mediaDevices.getUserMedia = async () => { const error = new Error("denied"); error.name = "NotAllowedError"; throw error; };
  rig = make({}, denied);
  await rig.client.start();
  assert.match(rig.log.messages[0][0], /microphone access was blocked/i);
  assert.equal(rig.client.phase, "off");
  const before = FakeSocket.instances.length;
  rig = make({}, denied);
  await rig.client.start();
  assert.equal(FakeSocket.instances.length, before, "no connection is opened without a microphone");
  assert.ok(FakeContext.instances.at(-1).closed, "the audio context is released again");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_stop_ends_the_session_politely_releases_everything_and_is_idempotent():
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  rig.socket.json({type: "ready"});
  await rig.client.stop();
  assert.equal(JSON.parse(rig.socket.sent.at(-1)).type, "end");
  assert.equal(rig.socket.closed, 1000);
  assert.ok(rig.env.tracks[0].stopped >= 1 && rig.context.closed);
  assert.equal(rig.client.phase, "off");
  assert.equal(rig.log.states.at(-1), "off");
  const count = rig.log.states.length;
  await rig.client.stop();
  assert.equal(rig.log.states.length, count);
  await rig.client.start();
  assert.equal(rig.client.phase, "connecting", "a new session can be started afterwards");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_interrupt_sends_a_control_message_and_flushes_local_playback():
    node(CLIENT_HARNESS + r"""
(async () => {
  const rig = await started();
  rig.socket.json({type: "ready"});
  rig.socket.audio(new Int16Array(480).fill(5));
  rig.client.interrupt();
  assert.deepEqual(JSON.parse(rig.socket.sent.at(-1)), {type: "interrupt"});
  assert.equal(rig.playback.port.posts.at(-1), null);
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")


def test_levels_follow_the_microphone_while_listening_and_the_speakers_while_speaking():
    node(CLIENT_HARNESS + r"""
(async () => {
  assert.equal(voice.rms(new Float32Array([0, 0, 0])), 0);
  assert.ok(Math.abs(voice.rms(new Float32Array([0.5, -0.5, 0.5, -0.5])) - 0.5) < 1e-9);
  assert.equal(voice.levelFromRms(0), 0);
  assert.equal(voice.levelFromRms(10), 1);
  assert.ok(voice.levelFromRms(0.1) > 0.2 && voice.levelFromRms(0.1) < 0.7);
  const rig = await started();
  rig.socket.json({type: "ready"});
  const [mic, speaker] = rig.context.analysers;
  assert.ok(mic && speaker, "separate analysers are created for microphone and speakers");
  mic.level = 0.2; speaker.level = 0.05;
  rig.env.intervals.at(-1).callback();
  assert.ok(rig.log.levels.at(-1) > 0.5, "listening shows the microphone level");
  rig.socket.json({type: "state", state: "thinking"});
  rig.env.intervals.at(-1).callback();
  assert.equal(rig.log.levels.at(-1), 0, "thinking is independent of sound");
  rig.socket.audio(new Int16Array(480).fill(5));
  rig.env.intervals.at(-1).callback();
  assert.ok(Math.abs(rig.log.levels.at(-1) - voice.levelFromRms(0.05)) < 1e-6, "speaking shows the speaker level");
})().catch((error) => { console.error(error); process.exit(1); });
""", STATIC / "voice.js")
