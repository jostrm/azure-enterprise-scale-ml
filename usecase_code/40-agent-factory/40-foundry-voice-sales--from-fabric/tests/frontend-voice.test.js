import test from "node:test";
import assert from "node:assert/strict";
import { createVoiceClient, textAvailable } from "../sales_agent/static/voice.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));

function environment(getUserMedia = async (stream) => stream) {
  const nodes = [], sockets = [], timers = new Set();
  let stops = 0, closes = 0;
  const track = { enabled: true, stop() { stops++; } };
  const stream = { getTracks: () => [track] };
  class Node {
    constructor(context, name) {
      this.name = name;
      this.gain = { value: 1 };
      this.messages = [];
      this.port = { postMessage: (message) => this.messages.push(message), close() {} };
      nodes.push(this);
    }
    connect() {}
    disconnect() { this.disconnected = true; }
  }
  class AudioContext {
    constructor() { this.audioWorklet = { addModule: async () => {} }; this.destination = {}; }
    resume() { return Promise.resolve(); }
    close() { closes++; return Promise.resolve(); }
    createMediaStreamSource() { return new Node(); }
    createGain() { return new Node(); }
  }
  class WebSocket {
    constructor(url) { this.url = url; this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
    send(value) { this.sent.push(typeof value === "string" ? JSON.parse(value) : value); }
    close() { this.readyState = 3; }
  }
  const env = {
    isSecureContext: true, location: { href: "http://localhost:8765/" },
    AudioContext, AudioWorkletNode: Node, WebSocket,
    navigator: { mediaDevices: { getUserMedia: () => getUserMedia(stream) } },
    setTimeout(fn) { const timer = { fn }; timers.add(timer); return timer; },
    clearTimeout(timer) { timers.delete(timer); },
  };
  return { env, nodes, sockets, timers, track, stream, stops: () => stops, closes: () => closes };
}

test("microphone is never acquired on construction; late permission result is stopped", async () => {
  let resolve, calls = 0;
  const fake = environment(() => { calls++; return new Promise((done) => { resolve = done; }); });
  const voice = createVoiceClient({ env: fake.env });
  assert.equal(calls, 0);
  const start = voice.start();
  assert.equal(calls, 1);
  voice.disconnect();
  resolve(fake.stream);
  await start;
  assert.equal(fake.stops(), 1);
  assert.equal(fake.closes(), 1);
  assert.equal(voice.state, "off");
  assert.equal(fake.timers.size, 0);
  assert.equal(fake.sockets.length, 0);
});

test("microphone failure retains typed chat and insecure contexts never acquire it", async () => {
  const denied = environment(async () => { throw Object.assign(new Error(), { name: "NotAllowedError" }); });
  const errors = [];
  const voice = createVoiceClient({ env: denied.env, onError: (code) => errors.push(code) });
  await voice.start();
  assert.equal(voice.state, "error");
  assert.equal(errors[0], "microphone_denied");
  assert.equal(textAvailable(true, false, voice.active), true);
  let calls = 0;
  const insecure = environment(async () => { calls++; });
  insecure.env.isSecureContext = false;
  const blocked = createVoiceClient({ env: insecure.env });
  await blocked.start();
  assert.equal(calls, 0);
  assert.equal(blocked.state, "error");
});

test("interrupt silences immediately, flushes consumed position, and sends played before interrupt", async () => {
  const fake = environment(async (stream) => stream);
  const voice = createVoiceClient({ env: fake.env });
  await voice.start();
  const socket = fake.sockets[0];
  socket.onmessage({ data: JSON.stringify({ type: "ready" }) });
  const playback = fake.nodes.find((node) => node.name === "sales-playback");
  voice.interrupt();
  const flush = playback.messages.at(-1);
  assert.equal(flush.type, "flush");
  assert.ok(fake.nodes.some((node) => node.gain.value === 0));
  playback.port.onmessage({ data: { type: "flushed", epoch: flush.epoch, item_id: "a", audio_end_ms: 87 } });
  assert.deepEqual(socket.sent.slice(-2), [
    { type: "played", item_id: "a", audio_end_ms: 87 },
    { type: "interrupt", item_id: "a", audio_end_ms: 87 },
  ]);
  voice.disconnect();
  assert.equal(voice.state, "off");
  assert.equal(fake.stops(), 1);
  assert.equal(fake.timers.size, 0);
  assert.ok(fake.nodes.every((node) => node.disconnected));
});

test("server interruption is acknowledged once and native completion waits for playback drain", async () => {
  const fake = environment(async (stream) => stream);
  const voice = createVoiceClient({ env: fake.env });
  await voice.start();
  const socket = fake.sockets[0], playback = fake.nodes.find((node) => node.name === "sales-playback");
  const server = (message) => socket.onmessage({ data: JSON.stringify(message) });
  server({ type: "ready" });
  server({ type: "audio", audio: "AQACAA==", item_id: "a" });
  server({ type: "state", state: "listening" });
  assert.equal(voice.state, "speaking");
  playback.port.onmessage({ data: { type: "progress", epoch: 0, item_id: "a", audio_end_ms: 0, consumed: 2, drained: true } });
  assert.equal(voice.state, "listening");
  server({ type: "interrupted" });
  const flush = playback.messages.at(-1);
  playback.port.onmessage({ data: { type: "flushed", epoch: flush.epoch, item_id: "a", audio_end_ms: 0 } });
  server({ type: "interrupted" });
  assert.equal(socket.sent.filter((message) => message.type === "interrupt").length, 1);
  voice.disconnect();
});

test("outbound backpressure fails voice rather than building an unbounded microphone backlog", async () => {
  const fake = environment(async (stream) => stream);
  const voice = createVoiceClient({ env: fake.env });
  await voice.start();
  const socket = fake.sockets[0];
  socket.onmessage({ data: JSON.stringify({ type: "ready" }) });
  socket.bufferedAmount = 96001;
  fake.nodes.find((node) => node.name === "sales-capture").port.onmessage({ data: new ArrayBuffer(960) });
  assert.equal(voice.state, "error");
  assert.equal(textAvailable(true, false, voice.active), true);
  assert.equal(fake.stops(), 1);
  await tick();
});

test("incoming playback overflow and missing item IDs release every resource", async () => {
  for (const badAudio of [
    { type: "audio", audio: "AQACAA==" },
    { type: "audio", audio: Buffer.alloc(480002).toString("base64"), item_id: "too-long" },
  ]) {
    const fake = environment();
    const voice = createVoiceClient({ env: fake.env });
    await voice.start();
    const socket = fake.sockets[0], lateClose = socket.onclose;
    socket.onmessage({ data: JSON.stringify({ type: "ready" }) });
    socket.onmessage({ data: JSON.stringify(badAudio) });
    assert.equal(voice.state, "error");
    assert.equal(voice.active, false);
    assert.equal(fake.stops(), 1);
    assert.equal(fake.closes(), 1);
    assert.equal(fake.timers.size, 0);
    voice.disconnect();
    lateClose({ code: 1006 });
    assert.equal(voice.state, "off");
  }
});

test("muting stops tracks and capture while sending the explicit mute control", async () => {
  const fake = environment();
  const voice = createVoiceClient({ env: fake.env });
  await voice.start();
  const socket = fake.sockets[0];
  socket.onmessage({ data: JSON.stringify({ type: "ready" }) });
  voice.mute();
  assert.equal(fake.track.enabled, false);
  assert.deepEqual(socket.sent.at(-1), { type: "mute", muted: true });
  const capture = fake.nodes.find((node) => node.name === "sales-capture");
  assert.deepEqual(capture.messages.at(-1), { enabled: false });
  const count = socket.sent.length;
  capture.port.onmessage({ data: new ArrayBuffer(960) });
  assert.equal(socket.sent.length, count);
  voice.mute();
  assert.equal(fake.track.enabled, true);
  voice.disconnect();
});

test("connection deadline cleans up an unresolved permission prompt and its late stream", async () => {
  let resolve;
  const fake = environment(() => new Promise((done) => { resolve = done; }));
  const voice = createVoiceClient({ env: fake.env });
  const start = voice.start();
  [...fake.timers][0].fn();
  assert.equal(voice.state, "error");
  assert.equal(fake.timers.size, 0);
  resolve(fake.stream);
  await start;
  assert.equal(fake.stops(), 1);
  assert.equal(fake.closes(), 1);
});
