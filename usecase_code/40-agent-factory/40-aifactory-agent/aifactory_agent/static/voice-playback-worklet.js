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
    this.port.onmessage = (event) => {
      if (event.data === null) {
        this.queue = [];
        this.current = null;
        this.position = 0;
      } else {
        this.queue.push(new Int16Array(event.data));
      }
    };
  }

  next() {
    this.current = this.queue.shift() || null;
    this.position = 0;
    return this.current !== null;
  }

  process(inputs, outputs) {
    const output = outputs[0][0];
    if (!output) return true;
    let sounded = false;
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
      sounded = true;
    }
    const active = this.current !== null || this.queue.length > 0;
    if ((this.playing || sounded) && !active) this.port.postMessage({drained: true});
    this.playing = active;
    return true;
  }
}

registerProcessor("voice-playback", VoicePlaybackProcessor);
