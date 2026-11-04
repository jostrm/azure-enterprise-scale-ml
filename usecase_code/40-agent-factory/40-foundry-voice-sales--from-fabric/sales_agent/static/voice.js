import { decodeAudio, MAX_PLAYBACK_SAMPLES } from "./audio-core.js";

export const textAvailable = (sessionReady, busy, voiceActive) => Boolean(sessionReady && !busy && !voiceActive);

export function createVoiceClient(options = {}) {
  const env = options.env || globalThis;
  let current = null, generation = 0, state = "off";
  const emit = (name, ...args) => options[name]?.(...args);
  const setState = (next) => {
    state = next;
    emit("onState", next);
  };
  const valid = (run) => current === run && run.generation === generation;
  const send = (run, message) => {
    if (!valid(run) || run.socket?.readyState !== 1) return false;
    if (run.socket.bufferedAmount > 96000) throw new Error("connection_slow");
    run.socket.send(typeof message === "object" && !(message instanceof ArrayBuffer) ? JSON.stringify(message) : message);
    return true;
  };
  const stopTracks = (stream) => {
    for (const track of stream?.getTracks() || []) {
      try { track.onended = null; track.stop(); } catch { /* Already released. */ }
    }
  };
  const clearTimer = (run, key) => {
    if (run[key]) env.clearTimeout(run[key]);
    run[key] = null;
  };

  function release() {
    const run = current;
    current = null;
    generation++;
    if (!run) return;
    clearTimer(run, "timer");
    clearTimer(run, "flushTimer");
    stopTracks(run.stream);
    for (const node of run.nodes) {
      try {
        if (node.port) { node.port.onmessage = null; node.port.close(); }
        node.onprocessorerror = null;
        node.disconnect();
      } catch { /* Continue releasing the remaining resources. */ }
    }
    if (run.socket) {
      run.socket.onopen = run.socket.onclose = run.socket.onerror = run.socket.onmessage = null;
      try { if (run.socket.readyState < 2) run.socket.close(1000); } catch { /* Already closed. */ }
    }
    if (run.context) {
      run.context.onstatechange = null;
      try { Promise.resolve(run.context.close()).catch(() => {}); } catch { /* Already closed. */ }
    }
    emit("onMute", false);
  }

  function fail(code) {
    release();
    setState("error");
    emit("onError", code || "voice_unavailable");
  }

  function show(run) {
    if (valid(run)) setState(run.playing ? "speaking" : run.serverState);
  }

  function interrupt() {
    const run = current;
    if (!run?.ready || run.flushing) return;
    try {
      run.output.gain.value = 0;
      run.flushing = true;
      run.epoch++;
      run.playing = false;
      run.serverState = "listening";
      run.playback.port.postMessage({ type: "flush", epoch: run.epoch });
      run.flushTimer = env.setTimeout(() => { if (valid(run)) fail("playback_stalled"); }, 2000);
      show(run);
    } catch { fail("voice_unavailable"); }
  }

  function handlePlayback(run, data) {
    if (!valid(run)) return;
    if (data.type === "error") { fail(data.code); return; }
    if (data.epoch !== run.epoch) return;
    try {
      if (data.type === "flushed" && run.flushing) {
        clearTimer(run, "flushTimer");
        const position = {
          item_id: typeof data.item_id === "string" ? data.item_id : null,
          audio_end_ms: Math.max(0, Math.floor(data.audio_end_ms || 0)),
        };
        if (position.item_id) send(run, { type: "played", ...position });
        send(run, { type: "interrupt", ...position });
        run.flushing = false;
        run.interruptionAcknowledged = true;
        run.queued = 0;
        run.output.gain.value = 1;
        show(run);
      } else if (data.type === "progress" && !run.flushing) {
        run.queued = Math.max(0, run.queued - (data.consumed || 0));
        if (typeof data.item_id === "string") {
          send(run, { type: "played", item_id: data.item_id, audio_end_ms: Math.max(0, Math.floor(data.audio_end_ms)) });
        }
        if (data.drained && run.queued < 0.01) {
          run.queued = 0;
          run.playing = false;
          show(run);
        }
      }
    } catch (error) { fail(error.message); }
  }

  function handleServer(run, event) {
    if (!valid(run)) return;
    try {
      if (typeof event.data !== "string" || event.data.length > 2000000) throw new Error("invalid_response");
      const message = JSON.parse(event.data);
      switch (message.type) {
        case "ready":
          clearTimer(run, "timer");
          run.ready = true;
          run.serverState = "listening";
          show(run);
          break;
        case "state":
          if (["listening", "processing", "speaking"].includes(message.state)) {
            run.serverState = message.state;
            show(run);
          }
          break;
        case "audio": {
          if (run.flushing) break;
          if (typeof message.item_id !== "string" || !message.item_id || message.item_id.length > 512) throw new Error("invalid_audio");
          const samples = decodeAudio(message.audio);
          if (run.queued + samples.length > MAX_PLAYBACK_SAMPLES) throw new Error("playback_overflow");
          run.interruptionAcknowledged = false;
          run.queued += samples.length;
          run.playing = true;
          run.playback.port.postMessage({ type: "audio", item_id: message.item_id, buffer: samples.buffer, epoch: run.epoch }, [samples.buffer]);
          show(run);
          break;
        }
        case "transcript":
          if (["user", "assistant"].includes(message.role) && typeof message.text === "string") emit("onTranscript", message);
          break;
        case "answer":
          if (typeof message.answer === "string") emit("onAnswer", message);
          break;
        case "tool":
          if (["query_sales_data", "fabric_mcp"].includes(message.name) && ["running", "completed"].includes(message.status)) emit("onTool", message);
          break;
        case "interrupted":
          if (!run.interruptionAcknowledged) interrupt();
          break;
        case "error":
          if (message.fatal) fail(message.code);
          else emit("onError", message.code || "service_unavailable");
          break;
        case "closed":
          release();
          setState("off");
          emit("onError", message.reason === "session_expired" ? "session_expired" : "voice_ended");
          break;
        default:
          break;
      }
    } catch (error) { fail(error.message); }
  }

  async function start() {
    if (current) return;
    if (env.isSecureContext !== true) { fail("insecure_context"); return; }
    if (!env.AudioContext || !env.AudioWorkletNode || !env.WebSocket || !env.navigator?.mediaDevices?.getUserMedia) {
      fail("unsupported_browser");
      return;
    }
    const run = {
      generation: ++generation, nodes: [], ready: false, serverState: "connecting",
      epoch: 0, queued: 0, playing: false, muted: false, flushing: false,
    };
    current = run;
    setState("connecting");
    run.timer = env.setTimeout(() => { if (valid(run)) fail("connection_timeout"); }, 30000);
    try {
      run.context = new env.AudioContext({ latencyHint: "interactive" });
      // Both calls originate in the Connect button gesture, before the first await.
      const resumed = Promise.resolve(run.context.resume());
      resumed.catch(() => {});
      const stream = await env.navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      } });
      if (!valid(run)) { stopTracks(stream); return; }
      run.stream = stream;
      for (const track of stream.getTracks()) track.onended = () => { if (valid(run)) fail("microphone_lost"); };
      await resumed;
      if (!valid(run)) return;
      await Promise.all([
        run.context.audioWorklet.addModule("/static/voice-capture-worklet.js"),
        run.context.audioWorklet.addModule("/static/voice-playback-worklet.js"),
      ]);
      if (!valid(run)) return;
      const register = (node) => { run.nodes.push(node); return node; };
      const source = register(run.context.createMediaStreamSource(stream));
      const capture = register(new env.AudioWorkletNode(run.context, "sales-capture", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] }));
      const silent = register(run.context.createGain());
      silent.gain.value = 0;
      source.connect(capture); capture.connect(silent); silent.connect(run.context.destination);
      run.capture = capture;
      run.playback = register(new env.AudioWorkletNode(run.context, "sales-playback", { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1] }));
      run.output = register(run.context.createGain());
      run.playback.connect(run.output); run.output.connect(run.context.destination);
      run.playback.port.onmessage = ({ data }) => handlePlayback(run, data);
      for (const node of [capture, run.playback]) node.onprocessorerror = () => { if (valid(run)) fail("audio_failed"); };
      run.context.onstatechange = () => {
        if (valid(run) && ["suspended", "closed", "interrupted"].includes(run.context.state)) fail("audio_failed");
      };
      const url = new URL("/api/voice", env.location.href);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      run.socket = new env.WebSocket(url.href);
      run.socket.onmessage = (event) => handleServer(run, event);
      run.socket.onerror = () => { if (valid(run)) fail("connection_failed"); };
      run.socket.onclose = (event) => {
        if (valid(run)) fail([4401, 4403, 1008].includes(event?.code) ? "session_expired" : "connection_closed");
      };
      capture.port.onmessage = ({ data }) => {
        if (!valid(run) || !run.ready || run.muted) return;
        try {
          if (!(data instanceof ArrayBuffer) || data.byteLength !== 960) throw new Error("invalid_audio");
          send(run, data);
        } catch (error) { fail(error.message); }
      };
    } catch (error) {
      if (!valid(run)) return;
      fail(error.name === "NotAllowedError" ? "microphone_denied" :
        error.name === "NotFoundError" ? "microphone_missing" :
          error.name === "NotReadableError" ? "microphone_busy" : "audio_failed");
    }
  }

  return {
    start,
    interrupt,
    disconnect() { release(); setState("off"); },
    mute() {
      const run = current;
      if (!run?.ready) return;
      try {
        run.muted = !run.muted;
        for (const track of run.stream.getTracks()) track.enabled = !run.muted;
        run.capture.port.postMessage({ enabled: !run.muted });
        send(run, { type: "mute", muted: run.muted });
        emit("onMute", run.muted);
      } catch { fail("connection_failed"); }
    },
    get state() { return state; },
    get active() { return current !== null; },
  };
}
