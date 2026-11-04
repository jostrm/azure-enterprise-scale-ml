import { createApi, translate } from "./api.js";
import { createVoiceClient, textAvailable } from "./voice.js";
import { element, renderMessage, renderProvenance, renderAnnotations, mergeTranscript } from "./render.js";

const localeResponse = await fetch("/static/locales/en.json", { credentials: "same-origin", cache: "no-store" });
const locale = await localeResponse.json();
const t = translate(locale);
const $ = (id) => document.getElementById(id);
for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
for (const [selector, attribute, key] of [
  ["[data-i18n-placeholder]", "placeholder", "i18nPlaceholder"],
  ["[data-i18n-label]", "aria-label", "i18nLabel"],
  ["[data-i18n-title]", "title", "i18nTitle"],
]) {
  for (const node of document.querySelectorAll(selector)) node.setAttribute(attribute, t(node.dataset[key]));
}

const api = createApi();
let sessionReady = false, voiceEnabled = false, busy = false, muted = false, expiryTimer = null;
const livePending = new Map(), answers = new Set(), toolRows = new Map();
const history = [];

function syncControls() {
  const active = voice.active, canType = textAvailable(sessionReady, busy, active);
  $("question").disabled = !sessionReady || busy;
  $("send").disabled = !canType || !$("question").value.trim() || $("question").value.length > 6000;
  $("send").textContent = t(busy ? "composer.sending" : "composer.send");
  $("composer-hint").textContent = t(!sessionReady ? "composer.notReady" : active ? "composer.voiceActive" : "composer.hint");
  $("new-conversation").disabled = !sessionReady || busy;
  $("voice-toggle").disabled = !active && (!sessionReady || !voiceEnabled || busy);
  $("voice-toggle").textContent = t(active ? "voice.disconnect" : "voice.connect");
  $("voice-toggle").setAttribute("aria-pressed", String(active));
  const connected = active && voice.state !== "connecting";
  $("voice-mute").disabled = !connected;
  $("voice-interrupt").disabled = !connected;
  $("voice-mute").textContent = t(muted ? "voice.unmute" : "voice.mute");
  $("voice-mute").setAttribute("aria-pressed", String(muted));
  $("microphone-state").textContent = t(voice.state === "connecting" ? "voice.connectingHelp" : active ? muted ? "voice.muted" : "voice.enabled" : "voice.offHelp");
  $("question-count").textContent = t("composer.count", { count: $("question").value.length, max: 6000 });
  $("copy-conversation").disabled = !history.length;
  $("thinking").hidden = !busy;
  for (const button of document.querySelectorAll("[data-example]")) button.disabled = !sessionReady || busy;
}

function showError(code) {
  const sessionError = ["session_expired", "session_required", "session_not_found"].includes(code);
  if (sessionError) {
    sessionReady = false;
    clearTimeout(expiryTimer);
    voice.disconnect();
    $("session-status").textContent = t("session.expired");
  }
  $("error-message").textContent = t(Object.hasOwn(locale.errors, code) ? `errors.${code}` : "errors.generic");
  $("error-notice").hidden = false;
  $("reload-session").hidden = !sessionError && sessionReady;
  syncControls();
}

function appendMessage(role, text, kind = "final") {
  $("welcome").hidden = true;
  const message = renderMessage(document, t, role, text, kind);
  $("conversation").append(message);
  history.push({ role, text });
  if (history.length > 100) {
    history.shift();
    $("conversation").firstElementChild.remove();
    $("retention").hidden = false;
  }
  $("conversation-scroll").scrollTop = $("conversation-scroll").scrollHeight;
  syncControls();
  return message;
}

function showAnswer(message) {
  if (message.response_id && answers.has(message.response_id)) return;
  if (message.response_id) {
    answers.add(message.response_id);
    if (answers.size > 100) answers.delete(answers.values().next().value);
  }
  const provenance = Array.isArray(message.provenance) ? message.provenance : [];
  const sourced = message.grounding === "sources_attached" && provenance.length > 0;
  const answer = appendMessage("assistant", message.answer);
  answer.querySelector("strong").textContent = t(sourced ? "conversation.answer" : "conversation.answerReview");
  answer.querySelector(".message-header").append(element(document, "span", t(sourced ? "conversation.sourcesAttached" : "conversation.noSources"), "badge"));
  if (provenance.length) {
    const details = element(document, "details", undefined, "answer-sources");
    details.append(element(document, "summary", t("sources.expand")), renderProvenance(document, t, provenance));
    answer.append(details);
  } else answer.append(element(document, "p", t("sources.noEvidence"), "small muted"));
  const annotations = renderAnnotations(document, t, message.agent_annotations);
  if (annotations) answer.append(annotations);
  $("source-count").textContent = t("sources.count", { count: provenance.length });
  $("conversation-scroll").scrollTop = $("conversation-scroll").scrollHeight;
}

function showTranscript(message) {
  $("live-empty").hidden = true;
  let row = livePending.get(message.role);
  if (!row) {
    row = renderMessage(document, t, message.role, "", "provisional");
    $("live-messages").append(row);
    livePending.set(message.role, row);
  }
  const text = row.querySelector(".message-text");
  text.textContent = mergeTranscript(text.textContent, message);
  if (message.final) {
    livePending.delete(message.role);
    if (message.role === "user" && message.text.trim()) appendMessage("user", message.text);
  }
  while ($("live-messages").children.length > 60) {
    const old = $("live-messages").firstElementChild;
    for (const [role, pending] of livePending) if (pending === old) livePending.delete(role);
    old.remove();
  }
  $("live-messages").scrollTop = $("live-messages").scrollHeight;
}

function showTool(message) {
  $("tools-empty").hidden = true;
  let details = toolRows.get(message.name);
  if (!details) {
    details = element(document, "details", undefined, "tool");
    details.append(element(document, "summary"), element(document, "p", t("sources.toolHelp"), "small muted"));
    $("tool-activity").append(details);
    toolRows.set(message.name, details);
  }
  details.querySelector("summary").textContent = `${t(`sources.${message.name}`)} · ${t(`sources.${message.status}`)}`;
  details.dataset.status = message.status;
}

const voice = createVoiceClient({
  onState(state) {
    $("voice-stage").dataset.state = state;
    $("voice-state").textContent = t(`voice.${state}`);
    if (["off", "error"].includes(state)) livePending.clear();
    syncControls();
  },
  onMute(value) { muted = value; syncControls(); },
  onError: showError,
  onTranscript: showTranscript,
  onAnswer: showAnswer,
  onTool: showTool,
});

$("question").addEventListener("input", syncControls);
$("question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!$("send").disabled) $("question-form").requestSubmit();
  }
});
$("question-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!textAvailable(sessionReady, busy, voice.active)) return;
  const text = $("question").value.trim();
  if (!text) { $("feedback").textContent = t("composer.required"); return; }
  if (text.length > 6000) { showError("question_too_long"); return; }
  $("error-notice").hidden = true;
  $("feedback").textContent = "";
  appendMessage("user", text);
  busy = true;
  syncControls();
  try {
    const answer = await api.request("/api/chat", { text });
    if (typeof answer.answer !== "string") throw Object.assign(new Error(), { code: "invalid_response" });
    showAnswer(answer);
    $("question").value = "";
  } catch (error) {
    showError(error.code);
  } finally {
    busy = false;
    syncControls();
    $("question").focus();
  }
});
$("voice-toggle").addEventListener("click", () => {
  $("error-notice").hidden = true;
  if (voice.active) voice.disconnect();
  else {
    $("live-transcript").open = true;
    voice.start();
  }
});
$("voice-mute").addEventListener("click", () => voice.mute());
$("voice-interrupt").addEventListener("click", () => voice.interrupt());
$("use-text").addEventListener("click", () => {
  voice.disconnect();
  $("feedback").textContent = t("voice.textRestored");
  $("question").focus();
});
$("new-conversation").addEventListener("click", async () => {
  if (busy || !sessionReady) return;
  const justDisconnected = voice.active;
  busy = true;
  voice.disconnect();
  syncControls();
  try {
    await api.resetAfterVoiceDisconnect(justDisconnected);
    $("conversation").replaceChildren();
    $("live-messages").replaceChildren();
    $("tool-activity").replaceChildren();
    history.length = 0; livePending.clear(); answers.clear(); toolRows.clear();
    $("welcome").hidden = false;
    $("retention").hidden = true;
    $("live-empty").hidden = false;
    $("tools-empty").hidden = false;
    $("question").value = "";
    $("source-count").textContent = t("sources.none");
    $("error-notice").hidden = true;
    $("feedback").textContent = t("conversation.reset");
  } catch (error) { showError(error.code); }
  finally { busy = false; syncControls(); }
});
for (const button of document.querySelectorAll("[data-example]")) {
  button.addEventListener("click", () => {
    $("question").value = t(`conversation.example${button.dataset.example}`);
    syncControls();
    $("question").focus();
  });
}
$("copy-conversation").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(history.map(({ role, text }) => `${t(role === "user" ? "conversation.you" : "conversation.answer")}\n${text}`).join("\n\n"));
    $("feedback").textContent = t("conversation.copied");
  } catch { $("feedback").textContent = t("conversation.copyFailed"); }
});
$("dismiss-error").addEventListener("click", () => { $("error-notice").hidden = true; });
$("reload-session").addEventListener("click", () => window.location.reload());
$("theme").value = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
$("theme").addEventListener("change", () => { document.documentElement.dataset.theme = $("theme").value; });
window.addEventListener("pagehide", () => { clearTimeout(expiryTimer); voice.disconnect(); api.cancel(); });

syncControls();
try {
  const session = await api.request("/api/session", {});
  sessionReady = true;
  voiceEnabled = session.voice_enabled === true;
  $("session-status").textContent = t("session.ready");
  $("voice-availability").hidden = voiceEnabled;
  $("voice-availability").textContent = t("voice.unavailable");
  const lifetime = Number(session.session_expires_in);
  if (Number.isFinite(lifetime) && lifetime > 0) expiryTimer = setTimeout(() => showError("session_expired"), Math.min(lifetime, 86400) * 1000);
} catch (error) {
  $("session-status").textContent = t("session.offline");
  showError(error.code);
}
syncControls();
api.request("/api/health", undefined, "GET")
  .then(() => { $("health-status").textContent = t("session.health"); })
  .catch(() => { $("health-status").textContent = t("session.healthUnavailable"); });
