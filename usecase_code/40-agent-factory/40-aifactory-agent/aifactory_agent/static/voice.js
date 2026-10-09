/* Live voice for the Factory Agent page.
 * createVoiceClient owns one conversation: microphone -> WebSocket relay -> speakers, and reports states, transcripts and
 * answers. It never talks to Azure directly: the backend relay authenticates the user (token in the first frame, never in
 * the URL), enforces scope and permissions, and is the only holder of speech credentials. Audio is never stored.
 */
(() => {
  "use strict";

  const SAMPLE_RATE = 24000;
  const FRAMES_PER_MESSAGE = 3; // 3 x 20 ms
  // Two seconds of 16-bit mono audio. Older audio is useless to live recognition, so a congested connection drops it
  // instead of delivering a long backlog at once (which the relay would treat as a flood).
  const MAX_BUFFERED_BYTES = 2 * SAMPLE_RATE * 2;
  const MIN_TOKEN_LIFETIME_MS = 60 * 1000;
  const LEVEL_INTERVAL_MS = 50;
  const LABELS = {
    off: "Voice is off", connecting: "Connecting…", listening: "Listening…", thinking: "Thinking…",
    speaking: "Speaking…", error: "Voice unavailable",
  };
  const CLOSE_MESSAGES = {
    idle: "The voice session ended after a period of inactivity.",
    timeout: "The voice session reached its time limit. Start again to continue.",
    replaced: "Live voice was started in another tab or window.",
  };

  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

  function rms(samples) {
    if (!samples.length) return 0;
    let sum = 0;
    for (let index = 0; index < samples.length; index++) sum += samples[index] * samples[index];
    return Math.sqrt(sum / samples.length);
  }

  function levelFromRms(value) {
    return clamp(Math.pow(clamp(value * 5, 0, 1e6), 0.7), 0, 1);
  }

  function concatenate(frames) {
    const total = frames.reduce((sum, frame) => sum + frame.byteLength, 0);
    const merged = new Uint8Array(total);
    let offset = 0;
    for (const frame of frames) {
      merged.set(new Uint8Array(frame), offset);
      offset += frame.byteLength;
    }
    return merged.buffer;
  }

  function createVoiceClient(options) {
    const env = options.env || globalThis;
    const emit = (name, ...args) => {
      const callback = options[name];
      if (typeof callback === "function") {
        try { callback(...args); } catch { /* a page callback must never break audio handling */ }
      }
    };
    const run = {phase: "off", muted: false, generation: 0};
    let resources = null;

    function release() {
      const current = resources;
      resources = null;
      if (!current) return;
      if (current.timer) env.clearInterval(current.timer);
      for (const track of current.stream ? current.stream.getTracks() : []) {
        try { track.stop(); } catch { /* already stopped */ }
      }
      for (const node of current.nodes) {
        try { node.disconnect(); } catch { /* not connected */ }
      }
      try {
        if (current.socket && current.socket.readyState < 2) current.socket.close(1000);
      } catch { /* closing */ }
      if (current.context) {
        Promise.resolve(current.context.close()).catch(() => {});
      }
    }

    function show(next) {
      if (!resources) {
        if (next === run.shown) return;
      } else if (resources.playing) {
        next = next === "thinking" || next === "error" || next === "off" || next === "connecting" ? next : "speaking";
      }
      if (next !== run.shown) {
        run.shown = next;
        emit("onState", next);
      }
    }

    function finish(phase, message, fatal) {
      run.generation += 1;
      release();
      run.phase = phase;
      run.shown = phase === "error" ? "error" : "off";
      emit("onState", run.shown);
      if (message) emit("onMessage", message, Boolean(fatal));
    }

    function levelTick() {
      const current = resources;
      if (!current || run.phase !== "active") return;
      let level = 0;
      const state = run.shown;
      const analyser = state === "listening" ? current.micAnalyser : state === "speaking" ? current.speakerAnalyser : null;
      if (analyser && !(state === "listening" && run.muted)) {
        analyser.getFloatTimeDomainData(current.samples);
        level = levelFromRms(rms(current.samples));
      }
      emit("onLevel", level);
    }

    function handleMessage(current, generation, event) {
      if (generation !== run.generation) return;
      if (typeof event.data !== "string") {
        current.playing = true;
        current.playback.port.postMessage(event.data, [event.data]);
        show("speaking");
        return;
      }
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (!message || typeof message.type !== "string") return;
      switch (message.type) {
        case "ready":
          run.phase = "active";
          current.ready = true;
          current.serverState = "listening";
          show("listening");
          break;
        case "state":
          current.serverState = message.state;
          if (message.state === "thinking") current.playing = false;
          show(message.state);
          break;
        case "transcript":
          emit("onTranscript", message.role, String(message.text || ""), Boolean(message.final));
          break;
        case "answer":
          emit("onAnswer", message);
          break;
        case "interrupted":
          current.playing = false;
          current.playback.port.postMessage(null);
          show(current.serverState || "listening");
          break;
        case "error":
          if (message.fatal) finish("error", String(message.message || "Live voice stopped."), true);
          else emit("onMessage", String(message.message || "Live voice reported a problem."), false);
          break;
        case "closed":
          if (run.phase === "off" || run.phase === "error") break;
          finish("off", CLOSE_MESSAGES[message.reason] || "");
          break;
        default:
          break;
      }
    }

    async function start() {
      if (run.phase !== "off" && run.phase !== "error") return;
      const session = options.getSession ? options.getSession() : null;
      const notice = (text) => emit("onMessage", text, false);
      if (!session) return notice("Sign in to use live voice.");
      if (!(session.expiresAt - Date.now() > MIN_TOKEN_LIFETIME_MS)) {
        return notice("Your sign-in is about to expire. Sign in again to use live voice.");
      }
      if (env.isSecureContext !== true) return notice("Live voice needs HTTPS (or localhost) so the browser can use the microphone.");
      if (!env.AudioContext || !env.AudioWorkletNode || !env.WebSocket
          || !(env.navigator && env.navigator.mediaDevices && env.navigator.mediaDevices.getUserMedia)) {
        return notice("This browser does not support live voice (AudioWorklet and microphone capture are required).");
      }
      run.generation += 1;
      const generation = run.generation;
      run.phase = "connecting";
      run.shown = undefined;
      show("connecting");
      const current = {nodes: [], playing: false, ready: false, serverState: "listening", samples: new Float32Array(512),
        pending: [], timer: null};
      resources = current;
      try {
        const context = new env.AudioContext({sampleRate: SAMPLE_RATE, latencyHint: "interactive"});
        current.context = context;
        await context.resume();
        if (generation !== run.generation) return;
        await context.audioWorklet.addModule("/static/voice-capture-worklet.js");
        await context.audioWorklet.addModule("/static/voice-playback-worklet.js");
        if (generation !== run.generation) return;
        const stream = await env.navigator.mediaDevices.getUserMedia({audio: {
          channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
        if (generation !== run.generation) {
          // Stopped or restarted while the permission prompt was open: the late stream must never keep the microphone on.
          for (const track of stream.getTracks()) {
            try { track.stop(); } catch { /* already stopped */ }
          }
          return;
        }
        current.stream = stream;
        const source = context.createMediaStreamSource(current.stream);
        const capture = new env.AudioWorkletNode(context, "voice-capture", {numberOfInputs: 1, numberOfOutputs: 1});
        const silent = context.createGain();
        silent.gain.value = 0;
        source.connect(capture);
        capture.connect(silent);
        silent.connect(context.destination);
        current.micAnalyser = context.createAnalyser();
        current.micAnalyser.fftSize = 512;
        source.connect(current.micAnalyser);
        current.playback = new env.AudioWorkletNode(context, "voice-playback", {
          numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1]});
        current.speakerAnalyser = context.createAnalyser();
        current.speakerAnalyser.fftSize = 512;
        current.playback.connect(current.speakerAnalyser);
        current.speakerAnalyser.connect(context.destination);
        current.nodes.push(source, capture, silent, current.micAnalyser, current.playback, current.speakerAnalyser);
        current.playback.port.onmessage = (event) => {
          if (event.data && event.data.drained && generation === run.generation) {
            current.playing = false;
            show(current.serverState || "listening");
          }
        };
        capture.port.onmessage = (event) => {
          if (generation !== run.generation || !current.ready || run.muted) return;
          const socket = current.socket;
          if (!socket || socket.readyState !== 1 || socket.bufferedAmount > MAX_BUFFERED_BYTES) return;
          current.pending.push(event.data);
          if (current.pending.length >= FRAMES_PER_MESSAGE) {
            socket.send(concatenate(current.pending));
            current.pending = [];
          }
        };
        const protocol = env.location.protocol === "https:" ? "wss:" : "ws:";
        const socket = new env.WebSocket(`${protocol}//${env.location.host}/api/voice/ws`);
        socket.binaryType = "arraybuffer";
        current.socket = socket;
        socket.onopen = () => {
          socket.send(JSON.stringify({type: "hello", token: session.token, scope_key: session.scopeKey,
            audience: session.audience}));
        };
        socket.onmessage = (event) => handleMessage(current, generation, event);
        socket.onclose = () => {
          if (generation === run.generation && run.phase !== "off") {
            finish("error", "The voice connection was lost. Start again to retry.", true);
          }
        };
        socket.onerror = () => {};
        current.timer = env.setInterval(levelTick, LEVEL_INTERVAL_MS);
      } catch (error) {
        if (generation !== run.generation) return;
        const name = error && error.name;
        const text = name === "NotAllowedError" || name === "SecurityError"
          ? "Microphone access was blocked. Allow the microphone for this site and try again."
          : name === "NotFoundError" ? "No microphone was found."
          : "Live voice could not be started on this device.";
        finish("off", text);
      }
    }

    async function stop() {
      if (run.phase === "off") return;
      const socket = resources && resources.socket;
      if (socket && socket.readyState === 1) {
        try { socket.send(JSON.stringify({type: "end"})); } catch { /* closing anyway */ }
      }
      finish("off", "");
    }

    function interrupt() {
      const current = resources;
      if (!current || run.phase !== "active") return;
      if (current.socket && current.socket.readyState === 1) current.socket.send(JSON.stringify({type: "interrupt"}));
      current.playing = false;
      current.playback.port.postMessage(null);
      show(current.serverState || "listening");
    }

    function setMuted(value) {
      run.muted = Boolean(value);
      if (run.muted && resources) resources.pending = [];
      if (resources && resources.stream) {
        for (const track of resources.stream.getTracks()) track.enabled = !run.muted;
      }
    }

    return {
      start, stop, interrupt, setMuted,
      get phase() { return run.phase; },
      get muted() { return run.muted; },
    };
  }

  function statusText(state, muted) {
    return muted && state === "listening" ? "Microphone muted" : LABELS[state] || LABELS.off;
  }

  /* Page glue: wires the Voice card, the orb and the Factory Agent page (app.js) together. */
  function initialize(env = globalThis) {
    const doc = env.document;
    const host = env.AIFactoryAgent;
    const orbApi = env.AIFactoryVoiceOrb;
    const element = (id) => (doc ? doc.getElementById(id) : null);
    const card = element("voice-card");
    if (!doc || !host || !card) return null;
    const toggle = element("voice-toggle");
    const mute = element("voice-mute");
    const interrupt = element("voice-interrupt");
    const stateLabel = element("voice-state");
    const transcript = element("voice-transcript");
    const problem = element("voice-error");
    const help = element("voice-help");
    const orb = orbApi && element("voice-orb") ? orbApi.createOrb(element("voice-orb"), {environment: env}) : null;
    if (orb) orb.start();
    const lines = {user: "", agent: ""};
    let enabled = false;
    let probedFor = null;

    const render = () => {
      transcript.replaceChildren();
      for (const [label, text] of [["You", lines.user], ["Agent", lines.agent]]) {
        if (!text) continue;
        const paragraph = doc.createElement("p");
        const name = doc.createElement("strong");
        name.textContent = label + ": ";
        paragraph.append(name, doc.createTextNode ? doc.createTextNode(text) : text);
        transcript.append(paragraph);
      }
    };
    const message = (text, fatal) => {
      problem.textContent = text || "";
      problem.hidden = !text;
      if (fatal) problem.setAttribute("role", "alert");
    };
    const controls = (state) => {
      const live = state !== "off" && state !== "error";
      toggle.textContent = live ? "Stop talking" : "Start talking";
      toggle.setAttribute("aria-pressed", String(live));
      mute.disabled = !live;
      interrupt.disabled = state !== "speaking" && state !== "thinking";
    };

    const client = createVoiceClient({
      env, getSession: () => host.voiceSession(),
      onState: (state) => {
        stateLabel.textContent = statusText(state, client.muted);
        if (orb) orb.setState(state);
        if (state === "connecting") { lines.user = ""; lines.agent = ""; render(); message("", false); }
        controls(state);
      },
      onLevel: (level) => { if (orb) orb.setLevel(level); },
      onTranscript: (role, text, final) => {
        if (role === "user") lines.user = text;
        else lines.agent = text;
        if (role === "user" && final) lines.agent = "";
        render();
      },
      onAnswer: (answer) => {
        lines.agent = String(answer.spoken || "");
        render();
        host.showAnswer(answer);
      },
      onMessage: message,
    });

    toggle.addEventListener("click", () => {
      if (client.phase === "off" || client.phase === "error") client.start();
      else client.stop();
    });
    mute.addEventListener("click", () => {
      client.setMuted(!client.muted);
      mute.setAttribute("aria-pressed", String(client.muted));
      mute.textContent = client.muted ? "Unmute microphone" : "Mute microphone";
      stateLabel.textContent = statusText(client.phase === "active" ? "listening" : "off", client.muted);
    });
    interrupt.addEventListener("click", () => client.interrupt());

    async function probe() {
      const session = host.voiceSession();
      if (!session) {
        enabled = false;
        probedFor = null;
        card.hidden = true;
        await client.stop();
        return;
      }
      if (probedFor === session.token) return;
      probedFor = session.token;
      try {
        const response = await env.fetch("/api/voice/status", {
          credentials: "omit", cache: "no-store", redirect: "error", headers: {Authorization: "Bearer " + session.token}});
        if (!response.ok) { card.hidden = true; enabled = false; return; }
        const status = await response.json();
        enabled = Boolean(status.enabled);
        card.hidden = !enabled;
        toggle.disabled = !status.ready;
        if (!status.ready && help) help.textContent = "Live voice is enabled but not ready on this deployment; ask the operator to check the voice dependencies.";
      } catch {
        card.hidden = true;
        enabled = false;
      }
    }

    controls("off");
    stateLabel.textContent = statusText("off", false);
    host.subscribe(probe);
    probe();
    return {client, probe, get enabled() { return enabled; }};
  }

  const exported = {createVoiceClient, initialize, rms, levelFromRms, statusText, LABELS};
  if (typeof module === "object" && module.exports) {
    module.exports = exported;
  } else {
    globalThis.AIFactoryVoice = exported;
    const start = () => initialize(globalThis);
    if (globalThis.document && globalThis.document.readyState === "loading") {
      globalThis.document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }
})();
