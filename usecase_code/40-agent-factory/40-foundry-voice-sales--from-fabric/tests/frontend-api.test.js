import test from "node:test";
import assert from "node:assert/strict";
import { createApi, translate } from "../sales_agent/static/api.js";
import { readFile } from "node:fs/promises";

test("local session and chat use cookie credentials with JSON, never browser tokens", async () => {
  const calls = [];
  const api = createApi(async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ voice_enabled: true }) };
  });
  await api.request("/api/session", {});
  await api.request("/api/chat", { text: "Sales by region" });
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(calls[0].options.body, "{}");
  assert.equal(calls[1].options.body, '{"text":"Sales by region"}');
  assert.equal(calls[0].options.headers.Authorization, undefined);
});

test("session and service errors are safe localizable codes; no automatic replay", async () => {
  let calls = 0;
  const api = createApi(async () => {
    calls++;
    return { ok: false, status: 401, json: async () => ({ error: { code: "anything", message: "<script>secret</script>" } }) };
  });
  await assert.rejects(api.request("/api/chat", { text: "hello" }), { code: "session_expired" });
  assert.equal(calls, 1);
  const unavailable = createApi(async () => { throw new TypeError("internal detail"); });
  await assert.rejects(unavailable.request("/api/session", {}), { code: "service_unavailable" });
});

test("expired sessions still advise reload when an intermediary returns non-JSON", async () => {
  const api = createApi(async () => ({
    ok: false, status: 403, json: async () => { throw new SyntaxError(); },
  }));
  await assert.rejects(api.request("/api/session", {}), { code: "session_expired" });
});

test("API forbids non-local endpoints and can cancel in-flight requests", async () => {
  const api = createApi((path, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(Object.assign(new Error(), { name: "AbortError" })));
  }));
  await assert.rejects(api.request("https://example.com", {}), { code: "invalid_endpoint" });
  const request = api.request("/api/chat", { text: "hello" });
  api.cancel();
  await assert.rejects(request, { code: "request_cancelled" });
});

test("locale lookup interpolates without HTML and every declared UI key exists", async () => {
  const root = new URL("../sales_agent/static/", import.meta.url);
  const locale = JSON.parse(await readFile(new URL("locales/en.json", root), "utf8"));
  const t = translate(locale);
  assert.equal(t("composer.count", { count: 12, max: 6000 }), "12 / 6000 characters");
  const html = await readFile(new URL("index.html", root), "utf8");
  for (const match of html.matchAll(/data-i18n(?:-placeholder|-label|-title)?="([^"]+)"/g)) {
    assert.notEqual(t(match[1]), match[1], `missing locale ${match[1]}`);
  }
  for (const filename of ["app.js", "render.js"]) {
    const source = await readFile(new URL(filename, root), "utf8");
    for (const match of source.matchAll(/\bt\("([^"]+)"\)/g)) {
      assert.notEqual(t(match[1]), match[1], `missing locale ${match[1]}`);
    }
  }
});

test("question input and displayed limit match the server's 6000-character maximum", async () => {
  const root = new URL("../sales_agent/static/", import.meta.url);
  const html = await readFile(new URL("index.html", root), "utf8");
  const app = await readFile(new URL("app.js", root), "utf8");
  assert.match(html, /id="question"[^>]*maxlength="6000"/);
  assert.match(app, /max: 6000/);
  assert.doesNotMatch(app, /\b8000\b/);
});

test("a legitimate 130-second chat response survives the browser deadline", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let aborted = false, calls = 0;
  const api = createApi((path, options) => new Promise((resolve, reject) => {
    calls++;
    options.signal.addEventListener("abort", () => {
      aborted = true;
      reject(Object.assign(new Error(), { name: "AbortError" }));
    });
    setTimeout(() => resolve({ ok: true, json: async () => ({ answer: "Completed after 130 seconds" }) }), 130000);
  }));
  const outcome = api.request("/api/chat", { text: "Sales?" }).then(
    (value) => ({ value }), (error) => ({ error }),
  );
  t.mock.timers.tick(130000);
  const result = await outcome;
  assert.equal(aborted, false);
  assert.equal(result.value?.answer, "Completed after 130 seconds");
  assert.equal(calls, 1);
});

test("chat still aborts at exactly 250 seconds without replay", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let aborted = false, calls = 0;
  const api = createApi((path, options) => new Promise((resolve, reject) => {
    calls++;
    options.signal.addEventListener("abort", () => {
      aborted = true;
      reject(new DOMException("Aborted fixture fetch", "AbortError"));
    });
  }));
  const outcome = api.request("/api/chat", { text: "Sales?" }).catch((error) => error);
  t.mock.timers.tick(249999);
  assert.equal(aborted, false);
  t.mock.timers.tick(1);
  assert.equal((await outcome).code, "request_timeout");
  assert.equal(calls, 1);
});

test("chat deadline covers response-body decoding and normalizes browser AbortError", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const api = createApi(async (path, options) => ({
    ok: true,
    json: () => new Promise((resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted fixture body", "AbortError")));
    }),
  }));
  const outcome = api.request("/api/chat", { text: "Sales?" }).catch((error) => error);
  await Promise.resolve();
  t.mock.timers.tick(250000);
  assert.equal((await outcome).code, "request_timeout");
});

const settleMicrotasks = async () => {
  for (let index = 0; index < 12; index++) await Promise.resolve();
};

test("reset waits for five-second voice cleanup and succeeds exactly once", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const started = Date.now(), paths = [];
  let successfulResets = 0;
  const api = createApi(async (path) => {
    paths.push(path);
    if (Date.now() - started < 5000) return {
      ok: false, status: 409, json: async () => ({ error: { code: "voice_active" } }),
    };
    successfulResets++;
    return { ok: true, json: async () => ({ status: "ok" }) };
  });
  const reset = api.resetAfterVoiceDisconnect(true);
  await settleMicrotasks();
  for (let elapsed = 0; elapsed < 5000; elapsed += 250) {
    t.mock.timers.tick(250);
    await settleMicrotasks();
  }
  assert.deepEqual(await reset, { status: "ok" });
  assert.equal(successfulResets, 1);
  assert.equal(paths.length, 21);
  assert.ok(paths.every((path) => path === "/api/conversation/reset"));
  t.mock.timers.tick(20000);
  await settleMicrotasks();
  assert.equal(successfulResets, 1);
  assert.equal(paths.length, 21);
});

test("reset retries stop after ten seconds when voice never releases", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let calls = 0;
  const api = createApi(async () => {
    calls++;
    return { ok: false, status: 409, json: async () => ({ error: { code: "voice_active" } }) };
  });
  const outcome = api.resetAfterVoiceDisconnect(true).catch((error) => error);
  await settleMicrotasks();
  for (let elapsed = 0; elapsed < 10000; elapsed += 250) {
    t.mock.timers.tick(250);
    await settleMicrotasks();
  }
  assert.equal((await outcome).code, "voice_active");
  assert.equal(calls, 40);
  t.mock.timers.tick(20000);
  await settleMicrotasks();
  assert.equal(calls, 40);
});

test("only voice-active reset failures following a disconnect may retry", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  for (const [code, justDisconnected] of [["voice_active", false], ["service_unavailable", true], ["request_timeout", true]]) {
    let calls = 0;
    const api = createApi(async () => {
      calls++;
      return { ok: false, status: 409, json: async () => ({ error: { code } }) };
    });
    await assert.rejects(api.resetAfterVoiceDisconnect(justDisconnected), { code });
    t.mock.timers.tick(20000);
    assert.equal(calls, 1);
  }
  let chats = 0;
  const chatApi = createApi(async () => {
    chats++;
    return { ok: false, status: 409, json: async () => ({ error: { code: "voice_active" } }) };
  });
  await assert.rejects(chatApi.request("/api/chat", { text: "Sales?" }), { code: "voice_active" });
  t.mock.timers.tick(20000);
  assert.equal(chats, 1);
});

test("cancelling during reset backoff prevents further requests", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  let calls = 0;
  const api = createApi(async () => {
    calls++;
    return { ok: false, status: 409, json: async () => ({ error: { code: "voice_active" } }) };
  });
  const outcome = api.resetAfterVoiceDisconnect(true).catch((error) => error);
  await settleMicrotasks();
  api.cancel();
  assert.equal((await outcome).code, "request_cancelled");
  t.mock.timers.tick(20000);
  await settleMicrotasks();
  assert.equal(calls, 1);
});

test("New conversation records active voice before disconnect and awaits the scoped reset helper", async () => {
  const app = await readFile(new URL("../sales_agent/static/app.js", import.meta.url), "utf8");
  const resetHandler = app.slice(app.indexOf('$("new-conversation").addEventListener'));
  assert.match(resetHandler, /const justDisconnected = voice\.active;[\s\S]*?voice\.disconnect\(\);/);
  assert.match(resetHandler, /await api\.resetAfterVoiceDisconnect\(justDisconnected\)/);
});
