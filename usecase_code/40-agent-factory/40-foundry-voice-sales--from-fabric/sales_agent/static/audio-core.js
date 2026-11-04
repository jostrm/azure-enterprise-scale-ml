export const SOURCE_RATE = 24000;
export const MAX_PLAYBACK_SAMPLES = SOURCE_RATE * 10;

export function pcm16(sample) {
  const value = Number.isFinite(sample) ? Math.max(-1, Math.min(1, sample)) : 0;
  return Math.trunc(value < 0 ? value * 32768 : value * 32767);
}

export function decodeAudio(base64) {
  if (typeof base64 !== "string" || base64.length > 640000 || !/^[A-Za-z0-9+/]*={0,2}$/.test(base64)) {
    throw new Error("invalid_audio");
  }
  const raw = atob(base64);
  if (!raw.length || raw.length % 2) throw new Error("invalid_audio");
  const result = new Int16Array(raw.length / 2);
  for (let index = 0; index < result.length; index++) {
    result[index] = raw.charCodeAt(index * 2) | (raw.charCodeAt(index * 2 + 1) << 8);
  }
  return result;
}

// Adapted from this repository's MIT-licensed sibling voice capture worklet:
// fractional interpolation retains the previous sample across render blocks.
export class CaptureEncoder {
  constructor(sampleRate, onFrame) {
    this.ratio = sampleRate / SOURCE_RATE;
    this.onFrame = onFrame;
    this.position = 0;
    this.previous = 0;
    this.totalSamples = 0;
    this.resetFrame();
  }

  resetFrame() {
    this.frame = new ArrayBuffer(960);
    this.view = new DataView(this.frame);
    this.filled = 0;
  }

  push(value) {
    this.view.setInt16(this.filled++ * 2, pcm16(value), true);
    this.totalSamples++;
    if (this.filled === 480) {
      const frame = this.frame;
      this.resetFrame();
      this.onFrame(frame);
    }
  }

  process(input) {
    if (!input?.length) return;
    if (this.ratio === 1) {
      for (const value of input) this.push(value);
      return;
    }
    let position = this.position;
    for (;;) {
      const base = Math.floor(position);
      if (base + 1 >= input.length) break;
      const left = base < 0 ? this.previous : input[base];
      this.push(left + (input[base + 1] - left) * (position - base));
      position += this.ratio;
    }
    this.position = position - input.length;
    this.previous = input[input.length - 1];
  }
}

// Adapted from the same MIT-licensed sibling playback worklet; positions count
// consumed 24 kHz source samples, independent of the speaker's device rate.
export class PlaybackQueue {
  constructor(sampleRate) {
    this.step = SOURCE_RATE / sampleRate;
    this.queue = [];
    this.queuedSamples = 0;
    this.epoch = 0;
    this.itemId = null;
    this.sourceSamples = 0;
    this.consumed = 0;
    this.reports = [];
    this.positions = new Map();
  }

  enqueue(itemId, samples, epoch = this.epoch) {
    if (epoch !== this.epoch) return false;
    if (typeof itemId !== "string" || !itemId || itemId.length > 512 || !(samples instanceof Int16Array) || !samples.length) {
      throw new Error("invalid_audio");
    }
    if (this.queuedSamples + samples.length > MAX_PLAYBACK_SAMPLES) throw new Error("playback_overflow");
    if (this.queue.length >= 2048) throw new Error("playback_overflow");
    this.queue.push({ itemId, samples, offset: 0 });
    this.queuedSamples += samples.length;
    return true;
  }

  position() {
    return { item_id: this.itemId, audio_end_ms: Math.floor((this.sourceSamples + 1e-7) / 24) };
  }

  report(drained = false) {
    if (!this.itemId || (!this.consumed && !drained)) return;
    this.reports.push({
      ...this.position(), source_samples: Math.floor(this.sourceSamples + 1e-7),
      consumed: this.consumed, drained,
    });
    this.consumed = 0;
  }

  takeReports() {
    const reports = this.reports;
    this.reports = [];
    return reports;
  }

  flush(epoch) {
    const position = this.position();
    this.queue = [];
    this.queuedSamples = 0;
    this.epoch = epoch;
    this.reports = [];
    this.positions.clear();
    this.itemId = null;
    this.sourceSamples = 0;
    this.consumed = 0;
    return position;
  }

  render(output) {
    output.fill(0);
    const hadAudio = this.queue.length > 0;
    for (let index = 0; index < output.length && this.queue.length; index++) {
      const current = this.queue[0];
      const base = Math.floor(current.offset);
      const fraction = current.offset - base;
      const left = current.samples[base];
      const right = current.samples[base + 1] ?? left;
      output[index] = (left + (right - left) * fraction) / 32768;
      let remaining = this.step;
      while (remaining > 1e-8 && this.queue.length) {
        const chunk = this.queue[0];
        if (this.itemId !== chunk.itemId) {
          this.report();
          if (this.itemId) this.positions.set(this.itemId, this.sourceSamples);
          if (this.positions.size > 64) this.positions.delete(this.positions.keys().next().value);
          this.itemId = chunk.itemId;
          this.sourceSamples = this.positions.get(this.itemId) || 0;
        }
        const amount = Math.min(remaining, chunk.samples.length - chunk.offset);
        chunk.offset += amount;
        this.sourceSamples += amount;
        this.consumed += amount;
        this.queuedSamples = Math.max(0, this.queuedSamples - amount);
        remaining -= amount;
        if (chunk.offset >= chunk.samples.length - 1e-8) this.queue.shift();
        if (this.consumed >= 2400 - 1e-8) this.report();
      }
    }
    if (hadAudio && !this.queue.length) {
      this.queuedSamples = 0;
      this.report(true);
    }
  }
}
