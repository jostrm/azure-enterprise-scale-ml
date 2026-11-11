import { CaptureEncoder } from "./audio-core.js";

class SalesCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.encoder = new CaptureEncoder(sampleRate, (buffer) => this.port.postMessage(buffer, [buffer]));
    this.enabled = true;
    this.port.onmessage = ({ data }) => {
      this.enabled = data.enabled;
      this.encoder = new CaptureEncoder(sampleRate, (buffer) => this.port.postMessage(buffer, [buffer]));
    };
  }

  process(inputs) {
    if (this.enabled) this.encoder.process(inputs[0]?.[0]);
    return true;
  }
}

registerProcessor("sales-capture", SalesCaptureProcessor);
