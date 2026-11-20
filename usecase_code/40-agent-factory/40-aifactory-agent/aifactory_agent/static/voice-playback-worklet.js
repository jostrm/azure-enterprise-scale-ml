/* AudioWorklet: queue of 24 kHz mono PCM16 chunks -> speakers. Posting null flushes the queue (barge-in). */
const SOURCE_RATE = 24000;

class VoicePlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = SOURCE_RATE / sampleRate; // source samples consumed per output sample
    this.queue = [];
    this.current = null;
    this.position = 0;
    this.playing = false;
    this.metadata = null;
    this.renderedFrames = 0;
    this.port.onmessage = (event) => {
      if (event.data === null) {
        this.queue = [];
        this.current = null;
        this.position = 0;
        this.metadata = null;
      } else {
        const tagged = event.data && event.data.audio;
        this.queue.push({samples: new Int16Array(tagged || event.data), metadata: tagged ? event.data : null});
      }
    };
  }

  next() {
    const entry = this.queue.shift();
    this.current = entry ? entry.samples : null;
    this.metadata = entry ? entry.metadata : null;
    this.position = 0;
    return this.current !== null;
  }

  process(inputs, outputs) {
    const output = outputs[0][0];
    if (!output) return true;
    let sounded = false;
    const progress = new Map();
    for (let index = 0; index < output.length; index++) {
      while (this.current && this.position >= this.current.length) {
        const overflow = this.position - this.current.length;
        if (!this.next()) break;
        this.position = overflow;
      }
      if (!this.current && !this.next()) {
        output[index] = 0;
        continue;
      }
      const base = Math.floor(this.position);
      const fraction = this.position - base;
      const left = this.current[base];
      const right = base + 1 < this.current.length ? this.current[base + 1] : left;
      output[index] = (left + (right - left) * fraction) / 32768;
      this.position += this.step;
      if (this.metadata) {
        const meta = this.metadata;
        progress.set(meta.playback_id, {playback_id: meta.playback_id, item_id: meta.item_id, epoch: meta.epoch,
          played_samples: meta.start_sample + Math.floor(Math.min(this.position, this.current.length))});
      }
      sounded = true;
    }
    // Rendered is not necessarily audible yet. The page waits for the device's
    // output timestamp before forwarding these positions to the relay.
    const frame = typeof currentFrame === "number" ? currentFrame : this.renderedFrames;
    for (const receipt of progress.values()) {
      this.port.postMessage({...receipt, context_time: (frame + output.length) / sampleRate});
    }
    this.renderedFrames += output.length;
    const active = this.current !== null || this.queue.length > 0;
    if ((this.playing || sounded) && !active) this.port.postMessage({drained: true});
    this.playing = active;
    return true;
  }
}

registerProcessor("voice-playback", VoicePlaybackProcessor);
