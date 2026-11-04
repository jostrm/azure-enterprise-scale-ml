import test from "node:test";
import assert from "node:assert/strict";
import { CaptureEncoder, PlaybackQueue, pcm16, decodeAudio } from "../sales_agent/static/audio-core.js";

test("PCM16 clamps and encodes signed little-endian values", () => {
  assert.deepEqual([-2, -1, 0, 1, 2].map(pcm16), [-32768, -32768, 0, 32767, 32767]);
  assert.deepEqual([...decodeAudio("/38AgA==")], [32767, -32768]);
  assert.throws(() => decodeAudio("AA=="));
});

for (const rate of [16000, 24000, 44100, 48000]) {
  test(`capture resamples ${rate}Hz into bounded 20ms 24kHz frames`, () => {
    const frames = [];
    const capture = new CaptureEncoder(rate, (frame) => frames.push(frame));
    for (let index = 0; index < rate; index += 128) {
      capture.process(new Float32Array(Math.min(128, rate - index)).fill(0.5));
    }
    assert.ok(frames.length >= 49 && frames.length <= 50);
    assert.ok(Math.abs(capture.totalSamples - 24000) <= 2);
    assert.ok(frames.every((frame) => frame.byteLength === 960));
    assert.ok(frames.every((frame) => new DataView(frame).getInt16(0, true) === 16383));
  });
}

test("playback accounts consumed source samples, not received or device frames", () => {
  const queue = new PlaybackQueue(48000);
  queue.enqueue("a", new Int16Array(4800).fill(1000));
  queue.render(new Float32Array(4800));
  assert.deepEqual(queue.position(), { item_id: "a", audio_end_ms: 100 });
  assert.equal(queue.queuedSamples, 2400);
  assert.equal(queue.takeReports().at(-1).source_samples, 2400);
});

test("playback flush returns final actual position and rejects stale generations", () => {
  const queue = new PlaybackQueue(48000);
  queue.enqueue("a", new Int16Array(2400).fill(2000), 0);
  queue.render(new Float32Array(240));
  assert.deepEqual(queue.flush(1), { item_id: "a", audio_end_ms: 5 });
  assert.equal(queue.queuedSamples, 0);
  assert.equal(queue.enqueue("a", new Int16Array(2400), 0), false);
  const silence = new Float32Array(128).fill(1);
  queue.render(silence);
  assert.ok(silence.every((value) => value === 0));
  queue.enqueue("b", new Int16Array(2400), 1);
  queue.render(new Float32Array(480));
  assert.deepEqual(queue.position(), { item_id: "b", audio_end_ms: 10 });
});

test("playback has a hard ten-second bound; overflow cannot silently drop audio", () => {
  const queue = new PlaybackQueue(24000);
  queue.enqueue("a", new Int16Array(240000));
  assert.throws(() => queue.enqueue("a", new Int16Array(1)), /playback_overflow/);
  assert.equal(queue.queuedSamples, 240000);
});

test("playback keeps per-item positions across chunks and reports drain", () => {
  const queue = new PlaybackQueue(24000);
  queue.enqueue("a", new Int16Array(240));
  queue.enqueue("a", new Int16Array(240));
  queue.enqueue("b", new Int16Array(240));
  queue.render(new Float32Array(720));
  const reports = queue.takeReports();
  assert.ok(reports.some((report) => report.item_id === "a" && report.source_samples === 480));
  assert.deepEqual(queue.position(), { item_id: "b", audio_end_ms: 10 });
  assert.equal(queue.queuedSamples, 0);
  assert.equal(reports.at(-1).drained, true);
});

test("completed output retains the last played item through silence until interruption flush", () => {
  const queue = new PlaybackQueue(48000);
  queue.enqueue("completed-item", new Int16Array(4800));
  queue.render(new Float32Array(9600));
  assert.equal(queue.takeReports().at(-1).drained, true);
  queue.render(new Float32Array(48000));
  assert.deepEqual(queue.position(), { item_id: "completed-item", audio_end_ms: 200 });
  assert.deepEqual(queue.flush(1), { item_id: "completed-item", audio_end_ms: 200 });
  assert.equal(queue.queuedSamples, 0);
});
