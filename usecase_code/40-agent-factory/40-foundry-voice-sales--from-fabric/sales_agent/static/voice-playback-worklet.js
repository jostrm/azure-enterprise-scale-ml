import { PlaybackQueue } from "./audio-core.js";

class SalesPlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.audio = new PlaybackQueue(sampleRate);
    this.port.onmessage = ({ data }) => {
      try {
        if (data.type === "flush") {
          const position = this.audio.flush(data.epoch);
          this.port.postMessage({ type: "flushed", epoch: data.epoch, ...position });
        } else if (data.type === "audio") {
          this.audio.enqueue(data.item_id, new Int16Array(data.buffer), data.epoch);
        }
      } catch (error) {
        this.audio.flush(this.audio.epoch + 1);
        this.port.postMessage({ type: "error", code: error.message });
      }
    };
  }

  process(inputs, outputs) {
    if (outputs[0]?.[0]) this.audio.render(outputs[0][0]);
    for (const report of this.audio.takeReports()) {
      this.port.postMessage({ type: "progress", epoch: this.audio.epoch, ...report });
    }
    return true;
  }
}

registerProcessor("sales-playback", SalesPlaybackProcessor);
