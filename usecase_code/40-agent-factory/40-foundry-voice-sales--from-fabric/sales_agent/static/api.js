export function translate(locale) {
  return (key, values = {}) => {
    const value = key.split(".").reduce((node, part) => node?.[part], locale);
    return typeof value === "string" ? value.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? `{${name}}`)) : key;
  };
}

export function createApi(fetcher = globalThis.fetch.bind(globalThis)) {
  const pending = new Set();
  const error = (code) => Object.assign(new Error(code), { code });
  const pause = (milliseconds, signal) => new Promise((resolve, reject) => {
    if (signal.aborted) { reject(error("request_cancelled")); return; }
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(error("request_cancelled"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", abort, { once: true });
  });
  const api = {
    async request(path, body, method = "POST", { signal } = {}) {
      if (!["/api/session", "/api/chat", "/api/conversation/reset", "/api/health"].includes(path)) throw error("invalid_endpoint");
      if (signal?.aborted) throw error("request_cancelled");
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal?.addEventListener("abort", abort, { once: true });
      pending.add(controller);
      let timedOut = false;
      // The server owns a 240-second total chat deadline, including identity and cleanup.
      const timer = setTimeout(() => { timedOut = true; controller.abort(); }, path === "/api/chat" ? 250000 : 30000);
      try {
        const response = await fetcher(path, {
          method, credentials: "same-origin", cache: "no-store",
          headers: { "Content-Type": "application/json" },
          ...(method !== "GET" ? { body: JSON.stringify(body ?? {}) } : {}),
          signal: controller.signal,
        });
        if ([401, 403].includes(response.status)) throw error("session_expired");
        let data;
        try { data = await response.json(); } catch (cause) {
          if (controller.signal.aborted || cause.name === "AbortError") throw cause;
          throw error("invalid_response");
        }
        if (controller.signal.aborted) throw error("request_cancelled");
        if (!response.ok) {
          throw error(data?.error?.code || "service_unavailable");
        }
        if (!data || typeof data !== "object" || Array.isArray(data)) throw error("invalid_response");
        return data;
      } catch (cause) {
        if (controller.signal.aborted || cause.name === "AbortError") throw error(timedOut ? "request_timeout" : "request_cancelled");
        if (typeof cause.code === "string") throw cause;
        throw error("service_unavailable");
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
        pending.delete(controller);
      }
    },
    async resetAfterVoiceDisconnect(justDisconnected = false) {
      if (!justDisconnected) return api.request("/api/conversation/reset", {});
      const controller = new AbortController();
      pending.add(controller);
      let expired = false, lastError;
      const timer = setTimeout(() => { expired = true; controller.abort(); }, 10000);
      try {
        for (;;) {
          try {
            return await api.request("/api/conversation/reset", {}, "POST", { signal: controller.signal });
          } catch (cause) {
            // Only a rejected reset is safe to retry while the just-closed voice relay releases its session.
            if (cause.code !== "voice_active") throw cause;
            lastError = cause;
          }
          await pause(250, controller.signal);
        }
      } catch (cause) {
        if (expired) throw lastError || error("request_timeout");
        throw cause;
      } finally {
        clearTimeout(timer);
        pending.delete(controller);
      }
    },
    cancel() { for (const controller of pending) controller.abort(); },
  };
  return api;
}
