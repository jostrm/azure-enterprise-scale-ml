/* AudioWorklet: microphone -> 24 kHz mono PCM16 frames of 20 ms. Runs in AudioWorkletGlobalScope. */
const TARGET_RATE = 24000;
const FRAME_SAMPLES = 480;

class VoiceCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE; // input samples consumed per output sample
    this.position = 0;                     // fractional read position relative to the next block (>= -1)
    this.previous = 0;                     // last sample of the previous block, for interpolation across blocks
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.filled = 0;
  }

  push(sample) {
    const clamped = sample > 1 ? 1 : sample < -1 ? -1 : sample;
    this.frame[this.filled++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    if (this.filled === FRAME_SAMPLES) {
      const buffer = this.frame.buffer;
      this.frame = new Int16Array(FRAME_SAMPLES);
      this.filled = 0;
      this.port.postMessage(buffer, [buffer]);
    }
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input || !input.length) return true;
    if (this.ratio === 1) {
      for (let index = 0; index < input.length; index++) this.push(input[index]);
      return true;
    }
    const length = input.length;
    let position = this.position;
    for (;;) {
      const base = Math.floor(position);
      if (base + 1 > length - 1) break;
      const fraction = position - base;
      const left = base < 0 ? this.previous : input[base];
      this.push(left + (input[base + 1] - left) * fraction);
      position += this.ratio;
    }
    this.position = position - length;
    this.previous = input[length - 1];
    return true;
  }
}

registerProcessor("voice-capture", VoiceCaptureProcessor);
