export function safeHttpsUrl(value) {
  if (typeof value !== "string" || !value.startsWith("https://")) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function element(document, tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

export function renderMessage(document, t, role, text, kind = "final") {
  const message = element(document, "article", undefined, `message ${role === "user" ? "user" : "assistant"} ${kind}`);
  const header = element(document, "div", undefined, "message-header");
  header.append(element(document, "strong", t(role === "user" ? "conversation.you" : "conversation.agent")));
  if (kind === "provisional") header.append(element(document, "span", t("conversation.provisional"), "badge"));
  message.append(header, element(document, "p", text, "message-text"));
  return message;
}

export function mergeTranscript(previous, message) {
  return message.final ? message.text : previous + message.text;
}

export function renderAnnotations(document, t, annotations) {
  if (!Array.isArray(annotations) || !annotations.length) return null;
  const details = element(document, "details", undefined, "answer-sources agent-annotations");
  details.append(
    element(document, "summary", t("sources.annotations")),
    element(document, "p", t("sources.annotationsUntrusted"), "small muted"),
    element(document, "pre", JSON.stringify(annotations, null, 2)),
  );
  return details;
}

export function renderProvenance(document, t, provenance) {
  const container = element(document, "div", undefined, "sources");
  for (const source of Array.isArray(provenance) ? provenance : []) {
    if (!source || typeof source !== "object") continue;
    const details = element(document, "details", undefined, "source");
    const summary = element(document, "summary", `${source.id || ""} · ${source.tool || t("sources.tool")}`);
    details.append(summary, element(document, "p", t("sources.untrusted"), "muted"));
    if (source.endpoint) details.append(element(document, "p", source.endpoint, "source-endpoint"));
    const url = safeHttpsUrl(source.endpoint);
    if (url) {
      const link = element(document, "a", t("sources.open"));
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.referrerPolicy = "no-referrer";
      details.append(link);
    }
    details.append(element(document, "pre", JSON.stringify({
      content: source.content ?? [], structured_content: source.structured_content ?? null,
    }, null, 2)));
    container.append(details);
  }
  return container;
}
