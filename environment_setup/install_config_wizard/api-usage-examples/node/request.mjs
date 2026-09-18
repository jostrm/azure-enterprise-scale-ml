// Raw server-side REST example. Use the Azure Factory SDK for guarded workflows.
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

export function requestUrl(base, path, query = []) {
  const root = new URL(base);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(root.hostname)
      || !["http:", "https:"].includes(root.protocol)
      || root.username || root.password || root.pathname !== "/" || root.search || root.hash) {
    throw new Error("Use the local API origin, without credentials, path, query or fragment.");
  }
  if (!/^\/(?:health|openapi\.json|api\/v1\/[A-Za-z0-9_/-]+)$/.test(path)
      || path.includes("//") || path.includes("..")) {
    throw new Error("Use a literal API path; pass query values with --query.");
  }
  const url = new URL(path, root);
  for (const item of query) {
    const separator = item.indexOf("=");
    if (separator < 1) throw new Error("Each query must be NAME=VALUE.");
    url.searchParams.append(item.slice(0, separator), item.slice(separator + 1));
  }
  return url;
}

export async function request({ base, path, method = "GET", body, query = [], allowWrite = false,
  timeout = 30, apiKey = process.env.AIFACTORY_API_KEY }, fetcher = fetch) {
  const url = requestUrl(base, path, query);
  if (!["GET", "POST"].includes(method)) throw new Error("Only GET and POST are shown by this example.");
  if (method !== "GET" && !allowWrite) throw new Error("POST requires --allow-write, including prepare.");
  if (method === "GET" && body !== undefined) throw new Error("GET cannot have a request body.");
  if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 3600) {
    throw new Error("Timeout must be between 0 (exclusive) and 3600 seconds.");
  }
  const headers = { Accept: "application/json" };
  if (path.startsWith("/api/v1/")) {
    if (!apiKey) throw new Error("Set AIFACTORY_API_KEY in this process.");
    headers["X-API-Key"] = apiKey;
  }
  if (body !== undefined) {
    if (!body || Array.isArray(body) || typeof body !== "object") throw new Error("Body must be a JSON object.");
    if (JSON.stringify(body).includes("${")) throw new Error("Render placeholders before sending.");
    headers["Content-Type"] = "application/json";
  }
  const response = await fetcher(url, {
    method, headers, redirect: "error", signal: AbortSignal.timeout(Math.ceil(timeout * 1000)),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  const safeText = apiKey ? text.replaceAll(apiKey, "[REDACTED]") : text;
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${safeText}`);
  try {
    return JSON.parse(safeText);
  } catch {
    throw new Error("API returned a successful response that is not JSON.");
  }
}

export async function main() {
  const { values } = parseArgs({
    options: {
      path: { type: "string" },
      base: { type: "string", default: process.env.AIFACTORY_API_URL || "http://127.0.0.1:8765" },
      method: { type: "string", default: "GET" },
      body: { type: "string" },
      query: { type: "string", multiple: true, default: [] },
      timeout: { type: "string", default: "30" },
      "allow-write": { type: "boolean", default: false },
      help: { type: "boolean" },
    },
  });
  if (values.help) {
    console.log("node request.mjs --path /health [--base URL] [--query NAME=VALUE]\n"
      + "POST: --method POST --body rendered.json --allow-write\n"
      + "Business routes require AIFACTORY_API_KEY. This raw example does not approve a workflow for you.");
    return 0;
  }
  if (!values.path) throw new Error("--path is required.");
  const body = values.body ? JSON.parse((await readFile(values.body, "utf8")).replace(/^\uFEFF/, "")) : undefined;
  const result = await request({
    base: values.base, path: values.path, method: values.method, body, query: values.query,
    allowWrite: values["allow-write"], timeout: Number(values.timeout),
  });
  console.log(JSON.stringify(result, null, 2));
  if (result?.can_execute === false || (Array.isArray(result?.blockers) && result.blockers.length)) return 3;
  if (["failed", "interrupted"].includes(result?.status)) return 4;
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(code => { process.exitCode = code; }).catch(error => {
    const key = process.env.AIFACTORY_API_KEY;
    const message = key ? error.message.replaceAll(key, "[REDACTED]") : error.message;
    console.error(message);
    process.exitCode = 2;
  });
}
