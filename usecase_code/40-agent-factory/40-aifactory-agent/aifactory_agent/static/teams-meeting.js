/* Attended Teams interop. Only remote call audio enters the existing governed voice relay.
 * The outbound ACS stream contains relay audio, never the operator's microphone.
 */
(() => {
  "use strict";
  const TEXT = {
    en: {
      title: "Teams meeting assistant (attended)", link: "Approved Teams meeting link",
      join: "Join with AI audio", leave: "Leave meeting", interrupt: "Stop speaking",
      pause: "Mute assistant", resume: "Resume assistant", paused: "Assistant audio muted",
      participants: "The participant roster is unapproved, incomplete or changed. The assistant left. Pause before admitting anyone and rejoin only after everyone is authorized and consents.",
      recording: "Teams recording, transcription or additional consent is active. The assistant stopped. This test requires recording and transcription off; no consent is granted automatically.",
      consentLabel: "I am an approved host, all participants have been informed and consent to AI audio processing, and this scope's knowledge is approved for everyone in this meeting.",
      notice: "Keep this page open and attend the meeting. Audio is processed live; this bridge does not record or save transcripts. Teams or participants may record separately. Do not share private information. Only approved shared knowledge is available; administration and writes are blocked. No automatic rejoin. Use headphones if also attending with another client.",
      off: "Not joined", connecting: "Joining…", lobby: "Waiting for admission…", listening: "Listening to the meeting",
      speaking: "Speaking to the meeting", stopping: "Leaving…", consent: "Consent is required before joining.",
      signin: "Sign in again before joining.", unavailable: "The meeting bridge is unavailable in this browser or deployment.",
      failed: "The meeting bridge stopped. Check the approved link, policy, admission and connection before joining again.",
      expired: "The meeting session expired. Join again explicitly if everyone still consents.",
      changed: "Sign-in or scope changed; the meeting bridge has left.", timeout: "Admission or audio timed out; the assistant left.",
      cleanup_pending: "Cleanup is not confirmed. Check that the assistant has left the meeting and ask the operator to check server/ACS cleanup before rejoining.",
      chatTitle: "Share source links in meeting chat", chatPreview: "Preview source links",
      chatSend: "Post approved links", chatDestination: "Destination meeting chat",
      chatWarning: "This message contains source links from your private Agent Chat session. Teams chat persists and may be visible to people not currently in the meeting. Confirm before sending.",
      chatConfirm: "I approve this exact message for everyone with access to this meeting chat.",
      chat_available: "Source links are ready for preview. Nothing has been posted.",
      chat_unavailable: "No shareable source links for an active approved meeting.",
      chat_previewing: "Preparing the exact message…", chat_preview: "Review the destination and message before posting.",
      chat_sending: "Posting the approved message…", chat_sent: "Source links posted to meeting chat.",
      chat_unknown: "Delivery is unconfirmed. Check Teams before posting again; this send will not be retried automatically.",
      chat_failed: "Link sharing failed. Audio can continue; check chat policy and access before trying a new answer.",
      chat_expired: "This preview expired. Ask again for fresh source links.",
    },
    sv: {
      title: "Teams-mötesassistent (bemannad)", link: "Godkänd Teams-möteslänk",
      join: "Anslut med AI-ljud", leave: "Lämna mötet", interrupt: "Sluta tala",
      pause: "Stäng av assistentens ljud", resume: "Återuppta assistenten", paused: "Assistentens ljud är avstängt",
      participants: "Deltagarlistan är inte godkänd, är ofullständig eller har ändrats. Assistenten lämnade mötet. Pausa före insläpp och anslut igen först när alla är behöriga och samtycker.",
      recording: "Teams-inspelning, transkription eller ytterligare samtycke är aktivt. Assistenten stoppades. Testet kräver att inspelning och transkription är avstängda; samtycke ges aldrig automatiskt.",
      consentLabel: "Jag är godkänd värd, alla deltagare har informerats och samtycker till AI-ljudbehandling, och kunskapen i detta omfång är godkänd för alla i mötet.",
      notice: "Ha sidan öppen och delta i mötet. Ljud behandlas direkt; denna brygga spelar inte in eller sparar transkriptioner. Teams eller deltagare kan spela in separat. Dela inte privat information. Endast godkänd gemensam kunskap är tillgänglig; administration och ändringar blockeras. Ingen automatisk återanslutning. Använd hörlurar om du även deltar med en annan klient.",
      off: "Inte ansluten", connecting: "Ansluter…", lobby: "Väntar på att släppas in…", listening: "Lyssnar på mötet",
      speaking: "Talar till mötet", stopping: "Lämnar…", consent: "Samtycke krävs innan du ansluter.",
      signin: "Logga in igen innan du ansluter.", unavailable: "Mötesbryggan är inte tillgänglig i denna webbläsare eller distribution.",
      failed: "Mötesbryggan stoppades. Kontrollera godkänd länk, policy, insläpp och anslutning innan du ansluter igen.",
      expired: "Mötessessionen har löpt ut. Anslut uttryckligen igen om alla fortfarande samtycker.",
      changed: "Inloggning eller omfång ändrades; mötesbryggan har lämnat.", timeout: "Tidsgränsen för insläpp eller ljud nåddes; assistenten lämnade.",
      cleanup_pending: "Rensningen är inte bekräftad. Kontrollera att assistenten har lämnat mötet och be operatören kontrollera serverns/ACS rensning innan du ansluter igen.",
      chatTitle: "Dela källänkar i möteschatten", chatPreview: "Förhandsgranska källänkar",
      chatSend: "Publicera godkända länkar", chatDestination: "Mottagande möteschatt",
      chatWarning: "Meddelandet innehåller källänkar från din privata Agent Chat-session. Teams-chatten sparas och kan läsas av personer som inte deltar just nu. Bekräfta innan du skickar.",
      chatConfirm: "Jag godkänner detta exakta meddelande för alla som har åtkomst till möteschatten.",
      chat_available: "Källänkar kan förhandsgranskas. Inget har publicerats.",
      chat_unavailable: "Inga delbara källänkar för ett aktivt godkänt möte.",
      chat_previewing: "Förbereder det exakta meddelandet…", chat_preview: "Granska mottagare och meddelande innan du publicerar.",
      chat_sending: "Publicerar det godkända meddelandet…", chat_sent: "Källänkarna har publicerats i möteschatten.",
      chat_unknown: "Leveransen är inte bekräftad. Kontrollera Teams innan du publicerar igen; meddelandet skickas inte om automatiskt.",
      chat_failed: "Länkdelningen misslyckades. Ljudet kan fortsätta; kontrollera chattpolicy och åtkomst före ett nytt svar.",
      chat_expired: "Förhandsgranskningen har gått ut. Fråga igen för aktuella källänkar.",
    },
  };
  let sdkPromise;
  function loadSdk(env) {
    if (env.ESAFMeetingSDK) return Promise.resolve(env.ESAFMeetingSDK);
    if (!sdkPromise) sdkPromise = new Promise((resolve, reject) => {
      const script = env.document.createElement("script");
      script.src = "/static/vendor/teams-meeting-sdk.min.js";
      script.onload = () => resolve(env.ESAFMeetingSDK);
      script.onerror = () => { sdkPromise = null; script.remove(); reject(new Error("unavailable")); };
      env.document.head.append(script);
    });
    return sdkPromise;
  }

  function createMeetingClient(options) {
    const env = options.env || globalThis;
    const now = () => env.Date.now();
    let active = null, phase = "off", stopping = null;
    let linkView = {state: "unavailable"};
    const emit = (name, value) => {
      try { options[name]?.(value); } catch { env.console?.warn("teams_meeting_ui_callback_failed"); }
    };
    const show = value => { phase = value; emit("onState", value); };
    const alive = current => active === current && !current.stopped;
    const sameSession = current => {
      const latest = options.getSession();
      return latest && latest.token === current.session.token && latest.scopeKey === current.session.scopeKey
        && latest.audience === current.session.audience && latest.expiresAt > now();
    };
    const headers = session => ({Authorization: `Bearer ${session.token}`, "Content-Type": "application/json"});
    const showLinks = (state, details = {}) => {
      linkView = {state, ...details};
      emit("onLinks", linkView);
    };
    function clearLinks(current) {
      current.linkEpoch = (current.linkEpoch || 0) + 1;
      current.linkOffer = null;
      current.linkDraft = null;
      showLinks("unavailable");
    }
    function chatReady(current) {
      return alive(current) && current.ready && !current.paused && !current.resetting
        && sameSession(current) && current.call.state === "Connected"
        && current.admission.chat_enabled === true
        && typeof current.admission.chat_thread_id === "string"
        && current.call.info?.threadId === current.admission.chat_thread_id;
    }
    async function chatRequest(current, operation, body) {
      let timer;
      const controller = new env.AbortController();
      try {
        return await Promise.race([
          (async () => {
            const response = await env.fetch(`/api/teams-meetings/sessions/${encodeURIComponent(current.admission.session_id)}/links/${operation}`,
              {method: "POST", headers: headers(current.session), cache: "no-store",
                body: JSON.stringify(body), signal: controller.signal});
            return {ok: response.ok, status: response.status, body: response.ok ? await response.json() : null};
          })(),
          new Promise((resolve, reject) => {
            timer = env.setTimeout(() => {
              controller.abort(); reject(new Error("chat_timeout"));
            }, 30000);
          }),
        ]);
      } finally { env.clearTimeout(timer); }
    }
    async function previewLinks() {
      const current = active;
      if (!current || linkView.state !== "available") return;
      if (!chatReady(current)) { clearLinks(current); return; }
      if (!safe(current)) return;
      const epoch = current.linkEpoch;
      showLinks("previewing");
      try {
        const response = await chatRequest(current, "preview", {
          voice_generation: current.admission.voice_generation,
          offer_id: current.linkOffer.offer_id, thread_id: current.call.info.threadId,
        });
        if (!alive(current) || epoch !== current.linkEpoch) return;
        if (!response.ok) { showLinks("failed"); return; }
        const draft = response.body;
        if (!alive(current) || epoch !== current.linkEpoch) return;
        if (!chatReady(current)) { clearLinks(current); return; }
        if (typeof draft.draft_id !== "string" || !draft.draft_id
            || draft.voice_generation !== current.admission.voice_generation
            || draft.thread_id !== current.call.info.threadId || typeof draft.content !== "string"
            || !draft.content || draft.content.length > 16000 || !Number.isFinite(draft.expires_at)
            || draft.expires_at * 1000 <= now()) { showLinks("failed"); return; }
        current.linkDraft = draft;
        showLinks("preview", {draft});
        const expiry = env.setTimeout(() => {
          if (alive(current) && epoch === current.linkEpoch && linkView.state === "preview") {
            current.linkDraft = null; showLinks("expired");
          }
        }, draft.expires_at * 1000 - now());
        current.timers.push(expiry);
        return draft;
      } catch {
        if (alive(current) && epoch === current.linkEpoch) showLinks("failed");
      }
    }
    async function postLinks({confirmed} = {}) {
      const current = active;
      if (!current || linkView.state !== "preview") return;
      if (confirmed !== true) { emit("onMessage", "consent"); return; }
      if (!chatReady(current)) { clearLinks(current); return; }
      if (!safe(current)) return;
      const draft = current.linkDraft;
      if (!draft || draft.expires_at * 1000 <= now()) { showLinks("expired"); return; }
      const epoch = current.linkEpoch;
      showLinks("sending");
      try {
        const response = await chatRequest(current, "send", {
          voice_generation: current.admission.voice_generation, draft_id: draft.draft_id,
          thread_id: draft.thread_id, confirmed: true,
        });
        if (!alive(current) || epoch !== current.linkEpoch) return;
        if (!response.ok) { showLinks(response.status >= 500 ? "unknown" : "failed"); return; }
        const result = response.body;
        if (!alive(current) || epoch !== current.linkEpoch) return;
        if (result.status !== "sent" || typeof result.message_id !== "string" || !result.message_id
            || result.thread_id !== draft.thread_id) { showLinks("unknown"); return; }
        current.linkDraft = null;
        showLinks("sent", {message_id: result.message_id});
        return result;
      } catch {
        // A lost response may already have delivered the message. Never automatically resend.
        if (alive(current) && epoch === current.linkEpoch) showLinks("unknown");
      }
    }
    function cleanupWarning(current) {
      current.cleanupPending = true;
      emit("onMessage", "cleanup_pending");
    }
    function attemptCleanup(current, work) {
      try { work(); } catch { cleanupWarning(current); }
    }
    function boundedCleanup(current, work) {
      return new Promise(resolve => {
        const timer = env.setTimeout(() => { cleanupWarning(current); resolve(); }, 5000);
        Promise.resolve().then(work).catch(() => { cleanupWarning(current); })
          .finally(() => { env.clearTimeout(timer); resolve(); });
      });
    }
    async function revoke(current, admission) {
      if (!admission?.session_id) return;
      try {
        const response = await env.fetch(`/api/teams-meetings/sessions/${encodeURIComponent(admission.session_id)}`,
          {method: "DELETE", headers: headers(current.session), cache: "no-store", keepalive: true});
        if (response.status !== 204) cleanupWarning(current);
      } catch { cleanupWarning(current); }
    }

    async function stop(reason) {
      if (stopping) return stopping;
      const current = active;
      if (!current) return;
      active = null;
      current.stopped = true;
      clearLinks(current);
      show("stopping");
      for (const timer of current.timers) env.clearTimeout(timer);
      for (const cancel of current.cancel) attemptCleanup(current, cancel);
      for (const [object, name, handler] of current.listeners) {
        attemptCleanup(current, () => object.off(name, handler));
      }
      if (current.socket) {
        current.socket.onclose = null;
        attemptCleanup(current, () => {
          if (current.socket.readyState === 1) current.socket.send(JSON.stringify({type: "end"}));
        });
        attemptCleanup(current, () => current.socket.close(1000));
      }
      for (const node of current.nodes) {
        attemptCleanup(current, () => node.disconnect());
      }
      for (const stream of current.streams) {
        for (const track of stream.getTracks()) attemptCleanup(current, () => track.stop());
      }
      attemptCleanup(current, () => current.constant?.stop());
      // Stop local media immediately, even when ACS hang-up or server cleanup is slow.
      const closed = boundedCleanup(current, () => current.context?.close());
      stopping = (async () => {
        const revoked = boundedCleanup(current, () => revoke(current, current.admission));
        await boundedCleanup(current, () => current.call?.hangUp());
        await boundedCleanup(current, () => current.agent?.dispose());
        attemptCleanup(current, () => current.credential?.dispose());
        await boundedCleanup(current, () => current.callClient?.dispose());
        await Promise.all([closed, revoked]);
        show("off");
        if (current.cleanupPending) emit("onMessage", "cleanup_pending");
        else if (reason) emit("onMessage", reason);
      })();
      try { await stopping; } finally { stopping = null; }
    }

    function listen(current, object, event, handler) {
      object.on(event, handler);
      current.listeners.push([object, event, handler]);
    }

    function rosterKey(current) {
      const participants = current.call.remoteParticipants;
      const allowed = current.admission.allowed_participant_object_ids;
      if (!Array.isArray(allowed) || !allowed.length || !Array.isArray(participants)
          || !participants.length || participants.length > 32
          || current.call.totalParticipantCount !== participants.length + 1) {
        throw new Error("participants");
      }
      const approved = new Set(allowed.map(id => id.toLowerCase()));
      const seen = new Set();
      return participants.map(participant => {
        const identity = participant.identifier;
        const id = identity?.microsoftTeamsUserId?.toLowerCase();
        const endpoints = participant.endpointDetails;
        if (!id || identity.isAnonymous === true || !approved.has(id) || seen.has(id)
            || participant.state !== "Connected" || !Array.isArray(endpoints)
            || endpoints.length !== 1 || typeof endpoints[0]?.participantId !== "string"
            || !endpoints[0].participantId) {
          throw new Error("participants");
        }
        seen.add(id);
        return `${id}:${endpoints[0].participantId}`;
      }).sort().join("|");
    }

    function requireSafety(current) {
      if (rosterKey(current) !== current.roster) throw new Error("participants");
      if (current.recording.isTeamsConsentRequired || current.transcription.isTeamsConsentRequired
          || current.recording.isRecordingActive
          || current.transcription.isTranscriptionActive) throw new Error("recording");
    }

    function safe(current) {
      try { requireSafety(current); return true; }
      catch (error) {
        void stop(["participants", "recording"].includes(error?.message) ? error.message : "failed");
        return false;
      }
    }

    function watchSafety(current, sdk) {
      current.roster = rosterKey(current);
      current.recording = current.call.feature(sdk.Features.Recording);
      current.transcription = current.call.feature(sdk.Features.Transcription);
      if (typeof current.recording?.isRecordingActive !== "boolean"
          || typeof current.transcription?.isTranscriptionActive !== "boolean") {
        throw new Error("unavailable");
      }
      requireSafety(current);
      listen(current, current.call, "remoteParticipantsUpdated", () => { void stop("participants"); });
      listen(current, current.call, "totalParticipantCountChanged", () => { if (alive(current)) safe(current); });
      for (const participant of current.call.remoteParticipants) {
        listen(current, participant, "stateChanged", () => { if (alive(current)) safe(current); });
      }
      listen(current, current.recording, "isRecordingActiveChanged", () => { if (alive(current)) safe(current); });
      listen(current, current.transcription, "isTranscriptionActiveChanged", () => { if (alive(current)) safe(current); });
    }

    function awaitConnected(current) {
      if (current.call.state === "Connected") return Promise.resolve();
      return new Promise((resolve, reject) => {
        const timer = env.setTimeout(() => reject(new Error("timeout")),
          current.admission.lobby_timeout_seconds * 1000);
        current.timers.push(timer);
        current.cancel.push(() => reject(new Error("cancelled")));
        const changed = () => {
          if (current.call.state === "Connected") { env.clearTimeout(timer); resolve(); }
          else if (current.call.state === "Disconnected") reject(new Error("failed"));
          else if (current.call.state === "InLobby") show("lobby");
        };
        listen(current, current.call, "stateChanged", changed);
        changed();
      });
    }

    async function attachRemote(current, remote) {
      if (current.remote.has(remote) || !alive(current)) return;
      current.remote.set(remote, null);
      const stream = await remote.getMediaStream();
      if (!alive(current) || !current.remote.has(remote)) {
        for (const track of stream.getTracks()) attemptCleanup(current, () => track.stop());
        return;
      }
      current.streams.push(stream);
      const source = current.context.createMediaStreamSource(stream);
      current.remote.set(remote, {source, stream});
      current.nodes.push(source);
      source.connect(current.input);
      current.hasRemote = true;
    }

    async function muteLocalMonitor(current) {
      let timer;
      const deadline = new Promise((resolve, reject) => {
        timer = env.setTimeout(() => reject(new Error("timeout")), 10000);
        current.cancel.push(() => reject(new Error("cancelled")));
      });
      current.timers.push(timer);
      try {
        // Silence the SDK's local speaker, not the remote stream or our outgoing reply.
        await Promise.race([current.call.muteIncomingAudio(), deadline]);
      } finally {
        env.clearTimeout(timer);
      }
      if (!alive(current)) return;
      if (!current.call.isIncomingAudioMuted) throw new Error("failed");
      listen(current, current.call, "isIncomingAudioMutedChanged", () => {
        if (alive(current) && !current.call.isIncomingAudioMuted) void stop("failed");
      });
    }

    function relay(current) {
      current.audioMetadata = null;
      current.delegated = false;
      const protocol = env.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new env.WebSocket(`${protocol}//${env.location.host}/api/voice/ws`);
      current.socket = socket;
      socket.binaryType = "arraybuffer";
      const readyTimer = env.setTimeout(() => { if (!current.ready) void stop("timeout"); }, 30000);
      current.timers.push(readyTimer);
      socket.onopen = () => {
        if (!alive(current) || current.socket !== socket || current.resetting) return;
        if (!sameSession(current)) { void stop("changed"); return; }
        socket.send(JSON.stringify({type: "hello", token: current.session.token,
          scope_key: current.admission.scope_key, audience: current.admission.audience,
          meeting_session: current.admission.meeting_session}));
      };
      socket.onmessage = event => {
        if (!alive(current) || current.socket !== socket || current.resetting) return;
        if (!sameSession(current)) { void stop("changed"); return; }
        if (!safe(current)) return;
        if (typeof event.data !== "string") {
          if (!current.ready || !(event.data instanceof ArrayBuffer) || event.data.byteLength % 2) {
            void stop("failed"); return;
          }
          if (current.paused) return;
          if (current.delegated) {
            const metadata = current.audioMetadata;
            current.audioMetadata = null;
            if (!metadata || event.data.byteLength !== (metadata.end_sample - metadata.start_sample) * 2) {
              void stop("failed"); return;
            }
          }
          current.playing = true;
          if (!current.fullDuplex) current.pending = [];
          // ACS sender rendering does not prove remote hearing. Do not send playback receipts.
          current.playback.port.postMessage(event.data, [event.data]);
          show("speaking");
          return;
        }
        let message;
        try { message = JSON.parse(event.data); } catch { void stop("failed"); return; }
        if (message.type === "ready") {
          current.delegated = message.mode === "delegated" && message.playback_receipts === true;
          current.ready = true; env.clearTimeout(readyTimer); show("listening");
        } else if (message.type === "voice_mode") {
          current.delegated = message.mode === "delegated" && message.playback_receipts === true;
        } else if (message.type === "audio_chunk" && current.delegated) {
          if (current.paused) return;
          if (current.audioMetadata || typeof message.playback_id !== "string"
              || typeof message.item_id !== "string" || typeof message.response_id !== "string"
              || message.content_index !== 0 || !Number.isSafeInteger(message.start_sample)
              || !Number.isSafeInteger(message.end_sample) || message.start_sample < 0
              || message.end_sample <= message.start_sample) {
            void stop("failed"); return;
          }
          current.audioMetadata = message;
        } else if (message.type === "interrupted") {
          current.audioMetadata = null;
          current.playback.port.postMessage(null);
          current.playing = false; current.echoUntil = now() + 500;
          show(current.paused ? "paused" : "listening");
        } else if (message.type === "answer") {
          clearLinks(current);
          const offer = message.chat_links;
          if (chatReady(current) && typeof offer?.offer_id === "string"
              && offer.offer_id.length > 0 && offer.offer_id.length <= 128
              && Number.isInteger(offer.count) && offer.count >= 1 && offer.count <= 5) {
            current.linkOffer = {offer_id: offer.offer_id};
            showLinks("available");
          }
        } else if (message.type === "closed" || (message.type === "error" && message.fatal)) {
          void stop("failed");
        }
        // Speech content is never copied to chat. Only server-owned source offers can be previewed.
      };
      socket.onclose = () => { if (alive(current) && current.socket === socket && !current.resetting) void stop("failed"); };
      socket.onerror = () => { if (alive(current) && current.socket === socket && !current.resetting) void stop("failed"); };
    }

    async function start({meetingUrl, consentAcknowledged}) {
      if (active || stopping) return;
      if (consentAcknowledged !== true) { emit("onMessage", "consent"); return; }
      const session = options.getSession();
      if (!session || session.expiresAt < now() + 60000) { emit("onMessage", "signin"); return; }
      if (!env.isSecureContext || !env.AudioContext || !env.AudioWorkletNode || !env.WebSocket) {
        emit("onMessage", "unavailable"); return;
      }
      const current = {session: {...session}, nodes: [], streams: [], timers: [], listeners: [], cancel: [],
        remote: new Map(), pending: [], stopped: false, ready: false, playing: false, echoUntil: 0};
      active = current; emit("onMessage", ""); show("connecting");
      clearLinks(current);
      try {
        current.context = new env.AudioContext({sampleRate: 24000, latencyHint: "interactive"});
        await current.context.resume();
        if (!alive(current)) return;
        const sdk = options.sdk || await loadSdk(env);
        if (!alive(current)) return;
        const response = await env.fetch("/api/teams-meetings/sessions", {method: "POST",
          headers: headers(current.session), cache: "no-store",
          body: JSON.stringify({meeting_url: meetingUrl, scope_key: session.scopeKey,
            audience: session.audience, consent_acknowledged: true})});
        if (!response.ok) {
          const failure = await response.json();
          if (failure?.detail?.cleanup_pending === true) cleanupWarning(current);
          throw new Error("failed");
        }
        const admission = await response.json();
        if (!alive(current)) { await revoke(current, admission); return; }
        current.admission = admission;
        current.fullDuplex = admission.full_duplex === true;
        if (admission.meeting_url !== meetingUrl || admission.scope_key !== session.scopeKey
            || admission.audience !== session.audience || !admission.meeting_session || !admission.acs_token
            || admission.voice_generation !== 0
            || !Number.isFinite(admission.expires_at) || !Number.isFinite(admission.acs_expires_at)) {
          throw new Error("failed");
        }
        const remaining = Math.min(admission.expires_at * 1000, admission.acs_expires_at * 1000,
          session.expiresAt) - now();
        if (remaining < 30000 || !sameSession(current)) throw new Error("signin");
        current.timers.push(env.setTimeout(() => { void stop("expired"); }, remaining));
        const context = current.context;
        await context.audioWorklet.addModule("/static/voice-capture-worklet.js");
        await context.audioWorklet.addModule("/static/voice-playback-worklet.js");
        if (!alive(current)) return;
        current.outbound = context.createMediaStreamDestination();
        current.streams.push(current.outbound.stream);
        current.input = context.createGain();
        current.input.channelCount = 1;
        current.input.channelCountMode = "explicit";
        const capture = new env.AudioWorkletNode(context, "voice-capture",
          {numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: "explicit"});
        const silent = context.createGain();
        silent.gain.value = 0;
        current.input.connect(capture); capture.connect(silent); silent.connect(context.destination);
        current.playback = new env.AudioWorkletNode(context, "voice-playback",
          {numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1]});
        current.playback.connect(current.outbound);
        current.constant = context.createConstantSource();
        const silence = context.createGain(); silence.gain.value = 0;
        current.constant.connect(silence); silence.connect(current.outbound); current.constant.start();
        current.nodes.push(current.outbound, current.input, capture, silent, current.playback, current.constant, silence);
        current.playback.port.onmessage = event => {
          if (alive(current) && event.data?.drained) {
            current.playing = false; current.echoUntil = now() + 500;
            show(current.paused ? "paused" : "listening");
          }
        };
        capture.port.onmessage = event => {
          if (!alive(current) || !current.ready) return;
          if (!sameSession(current)) { void stop("changed"); return; }
          if (!safe(current)) return;
          const suppressEcho = !current.fullDuplex && (current.playing || now() < current.echoUntil);
          if (current.paused || current.resetting || suppressEcho || current.socket.readyState !== 1
              || current.socket.bufferedAmount > 96000) { current.pending = []; return; }
          current.pending.push(event.data);
          if (current.pending.length === 3) {
            const bytes = new Uint8Array(current.pending.reduce((sum, frame) => sum + frame.byteLength, 0));
            let offset = 0;
            for (const frame of current.pending) { bytes.set(new Uint8Array(frame), offset); offset += frame.byteLength; }
            current.pending = []; current.socket.send(bytes.buffer);
          }
        };
        current.credential = new sdk.AzureCommunicationTokenCredential(admission.acs_token);
        current.callClient = new sdk.CallClient();
        const agent = await current.callClient.createCallAgent(current.credential, {displayName: admission.display_name});
        if (!alive(current)) { await boundedCleanup(current, () => agent.dispose()); return; }
        current.agent = agent;
        current.call = agent.join({meetingLink: admission.meeting_url},
          {audioOptions: {localAudioStreams: [new sdk.LocalAudioStream(current.outbound.stream)], muted: false}});
        await awaitConnected(current);
        if (!alive(current)) return;
        watchSafety(current, sdk);
        listen(current, current.call, "stateChanged", () => {
          if (alive(current) && current.call.state !== "Connected") void stop("failed");
        });
        await muteLocalMonitor(current);
        if (!alive(current)) return;
        listen(current, current.call, "remoteAudioStreamsUpdated", event => {
          for (const removed of event.removed) {
            const old = current.remote.get(removed);
            attemptCleanup(current, () => old?.source.disconnect());
            if (old) for (const track of old.stream.getTracks()) attemptCleanup(current, () => track.stop());
            current.remote.delete(removed);
          }
          for (const added of event.added) {
            void attachRemote(current, added).catch(() => { if (alive(current)) void stop("failed"); });
          }
        });
        current.timers.push(env.setTimeout(() => { if (!current.hasRemote) void stop("timeout"); }, 30000));
        for (const remote of current.call.remoteAudioStreams) {
          void attachRemote(current, remote).catch(() => { if (alive(current)) void stop("failed"); });
        }
        if (!alive(current)) return;
        relay(current);
      } catch (error) {
        if (alive(current)) await stop(["timeout", "signin", "unavailable", "participants", "recording"].includes(error?.message) ? error.message : "failed");
      }
    }

    function resetVoice(resumeAfterReset) {
      const current = active;
      if (!current) return Promise.resolve();
      if (current.resetPromise) {
        if (resumeAfterReset) current.resumeRequested = true;
        return current.resetPromise;
      }
      if (!current.ready || current.socket?.readyState !== 1) return Promise.resolve();
      current.paused = true;
      current.ready = false;
      current.resetting = true;
      clearLinks(current);
      current.resumeRequested = resumeAfterReset;
      current.playback.port.postMessage(null);
      current.pending = [];
      current.playing = false; current.echoUntil = now() + 500;
      show("paused");
      const oldSocket = current.socket, generation = current.admission.voice_generation;
      const timeout = env.setTimeout(() => { if (alive(current) && current.resetting) void stop("timeout"); }, 15000);
      current.timers.push(timeout);
      current.resetPromise = (async () => {
        try {
          // Rotate server ownership before closing the old socket so its cleanup cannot revoke ACS.
          const response = await env.fetch(`/api/teams-meetings/sessions/${encodeURIComponent(current.admission.session_id)}/voice-reset`,
            {method: "POST", headers: headers(current.session), cache: "no-store",
              body: JSON.stringify({voice_generation: generation})});
          if (!response.ok) throw new Error("failed");
          const next = await response.json();
          if (!alive(current)) return;
          if (!sameSession(current)) { await stop("changed"); return; }
          if (!safe(current)) return;
          if (next.session_id !== current.admission.session_id || !next.meeting_session
              || next.voice_generation !== generation + 1) throw new Error("failed");
          current.admission = {...current.admission, meeting_session: next.meeting_session,
            voice_generation: next.voice_generation};
          current.socket = null;
          oldSocket.onclose = null; oldSocket.onerror = null; oldSocket.close(1000);
          current.resetting = false;
          if (current.resumeRequested) {
            current.paused = false; current.resumeRequested = false;
            show("connecting"); relay(current);
          }
        } catch {
          if (alive(current)) await stop("failed");
        } finally {
          env.clearTimeout(timeout);
          current.resetPromise = null;
        }
      })();
      return current.resetPromise;
    }

    function interrupt() {
      return resetVoice(true);
    }

    function pause() {
      const current = active;
      if (!current?.ready || current.paused) return Promise.resolve();
      return resetVoice(false);
    }

    function resume({consentAcknowledged} = {}) {
      const current = active;
      if (!current?.paused) return;
      if (consentAcknowledged !== true) { emit("onMessage", "consent"); return; }
      if (!sameSession(current)) { void stop("changed"); return; }
      if (!safe(current)) return;
      if (current.resetPromise) { current.resumeRequested = true; return current.resetPromise; }
      current.paused = false;
      show("connecting");
      relay(current);
    }

    function sessionChanged() {
      if (active && !sameSession(active)) void stop("changed");
    }
    return {start, stop, interrupt, pause, resume, previewLinks, postLinks, sessionChanged,
      get phase() { return phase; }, get linkState() { return linkView; }};
  }

  function initialize(env = globalThis) {
    const doc = env.document, host = env.AIFactoryAgent;
    if (!doc || !host || doc.getElementById("teams-meeting-card")) return null;
    const locale = (doc.documentElement.lang || env.navigator?.language || "en").toLowerCase().split("-")[0];
    const labels = TEXT[locale] || TEXT.en;
    const element = (tag, text) => { const node = doc.createElement(tag); if (text) node.textContent = text; return node; };
    const card = element("section"); card.id = "teams-meeting-card"; card.hidden = true;
    const title = element("h2", labels.title), notice = element("p", labels.notice);
    const urlLabel = element("label", labels.link), url = element("input");
    url.type = "url"; url.maxLength = 4096; url.autocomplete = "off"; url.id = "teams-meeting-url";
    urlLabel.htmlFor = url.id;
    const consentLabel = element("label"), consent = element("input"); consent.type = "checkbox";
    consentLabel.className = "teams-meeting-consent"; consentLabel.append(consent, doc.createTextNode(labels.consentLabel));
    const actions = element("div"); actions.className = "teams-meeting-actions";
    const join = element("button", labels.join), leave = element("button", labels.leave);
    const mute = element("button", labels.pause), resume = element("button", labels.resume);
    const interrupt = element("button", labels.interrupt), status = element("p", labels.off), error = element("p");
    for (const button of [join, leave, interrupt, mute, resume]) button.type = "button";
    status.setAttribute("role", "status"); error.setAttribute("role", "alert");
    actions.append(join, mute, resume, leave, interrupt);
    card.append(title, notice, urlLabel, url, consentLabel, actions, status, error);
    const chatSection = element("section"), chatTitle = element("h3", labels.chatTitle);
    chatSection.className = "teams-link-sharing";
    const preview = element("button", labels.chatPreview), send = element("button", labels.chatSend);
    preview.type = send.type = "button";
    const chatState = element("p", labels.chat_unavailable), destination = element("p");
    chatState.setAttribute("aria-live", "polite");
    const textPreview = element("pre"), warning = element("p", labels.chatWarning);
    const confirmLabel = element("label"), confirm = element("input"); confirm.type = "checkbox";
    confirmLabel.append(confirm, doc.createTextNode(labels.chatConfirm));
    chatSection.append(chatTitle, preview, chatState, destination, textPreview, warning, confirmLabel, send);
    card.append(chatSection);
    let previewOpen = false;
    const linkControls = value => {
      previewOpen = value.state === "preview";
      preview.disabled = value.state !== "available";
      confirm.checked = false;
      send.disabled = true;
      destination.hidden = textPreview.hidden = warning.hidden = confirmLabel.hidden = send.hidden = !previewOpen;
      destination.textContent = previewOpen ? `${labels.chatDestination}: ${value.draft.thread_id}` : "";
      textPreview.textContent = previewOpen ? value.draft.content : "";
      chatState.textContent = labels[`chat_${value.state}`] || labels.chat_failed;
    };
    const anchor = doc.getElementById("voice-card");
    if (anchor) anchor.after(card); else (doc.querySelector("main") || doc.body).append(card);
    let approved = false, probe = 0, lastToken = null, policies = [], wasLive = false;
    const controls = state => {
      const live = state !== "off";
      if (!live && wasLive) consent.checked = false;
      wasLive = live;
      join.disabled = live || !approved || !consent.checked || !url.value;
      leave.disabled = !live || state === "stopping";
      interrupt.disabled = !["listening", "speaking"].includes(state);
      mute.disabled = !["listening", "speaking"].includes(state);
      resume.disabled = state !== "paused";
      url.disabled = live; consent.disabled = live;
      status.textContent = labels[state] || labels.off;
    };
    const client = createMeetingClient({env, getSession: () => host.voiceSession(),
      onState: controls, onLinks: linkControls,
      onMessage: key => { error.textContent = key ? labels[key] || labels.failed : ""; }});
    preview.addEventListener("click", () => { void client.previewLinks(); });
    confirm.addEventListener("change", () => { send.disabled = !previewOpen || !confirm.checked; });
    send.addEventListener("click", () => { void client.postLinks({confirmed: confirm.checked}); });
    linkControls({state: "unavailable"});
    async function changed() {
      client.sessionChanged();
      const session = host.voiceSession();
      if (!session) { probe++; lastToken = null; approved = false; card.hidden = true; return; }
      if (lastToken !== session.token) {
        const ownProbe = ++probe; lastToken = session.token;
        try {
          const response = await env.fetch("/api/teams-meetings/status",
            {headers: {Authorization: `Bearer ${session.token}`}, cache: "no-store"});
          const body = response.ok ? await response.json() : null;
          if (ownProbe !== probe) return;
          policies = body?.enabled && Array.isArray(body.policies) ? body.policies : [];
        } catch { if (ownProbe !== probe) return; policies = []; }
      }
      approved = policies.some(policy => policy.scope_key === host.voiceSession()?.scopeKey);
      card.hidden = !approved;
      controls(client.phase);
    }
    consent.addEventListener("change", () => {
      join.disabled = client.phase !== "off" || !approved || !consent.checked || !url.value;
    });
    url.addEventListener("input", () => { consent.checked = false; join.disabled = true; });
    join.addEventListener("click", () => { void client.start({meetingUrl: url.value, consentAcknowledged: consent.checked}); });
    leave.addEventListener("click", () => { void client.stop(); });
    interrupt.addEventListener("click", client.interrupt);
    mute.addEventListener("click", client.pause);
    resume.addEventListener("click", () => client.resume({consentAcknowledged: consent.checked}));
    host.subscribe(() => { void changed(); });
    env.addEventListener("pagehide", () => { void client.stop(); });
    controls("off"); void changed();
    return client;
  }
  globalThis.AIFactoryTeamsMeeting = Object.freeze({createMeetingClient, initialize, labels: TEXT});
  if (globalThis.document) {
    if (globalThis.document.readyState === "loading") {
      globalThis.document.addEventListener("DOMContentLoaded", () => initialize(), {once: true});
    } else initialize();
  }
})();
