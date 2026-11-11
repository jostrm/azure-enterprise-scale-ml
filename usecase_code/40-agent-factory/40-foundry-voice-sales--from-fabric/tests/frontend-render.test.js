import test from "node:test";
import assert from "node:assert/strict";
import { safeHttpsUrl, renderMessage, renderProvenance, renderAnnotations, mergeTranscript } from "../sales_agent/static/render.js";

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; }
  set innerHTML(_) { throw new Error("HTML injection"); }
  setAttribute(key, value) { this.attributes[key] = value; }
  append(...children) { this.children.push(...children); }
}
const document = { createElement: (tag) => new Element(tag) };
const t = (key) => key;

test("provenance links only permit absolute HTTPS without embedded credentials", () => {
  assert.equal(safeHttpsUrl("https://example.com/data"), "https://example.com/data");
  for (const value of ["javascript:alert(1)", "//example.com", "http://example.com", "https://a:b@example.com", "data:text/html,x"]) {
    assert.equal(safeHttpsUrl(value), null);
  }
});

test("transcripts use literal text, never agent HTML", () => {
  const message = renderMessage(document, t, "assistant", "<img src=x onerror=alert(1)>", "provisional");
  assert.equal(message.children.find((child) => child.tagName === "p").textContent, "<img src=x onerror=alert(1)>");
});

test("tool provenance is collapsed, explicitly untrusted, and safely rendered", () => {
  const result = renderProvenance(document, t, [{
    id: "F1", tool: "<script>", endpoint: "https://example.com/tool",
    content: [{ type: "text", text: "<img onerror=alert(1)>" }], structured_content: { revenue: 100 },
  }]);
  assert.equal(result.children[0].tagName, "details");
  const details = result.children[0];
  assert.equal(details.open, undefined);
  assert.ok(details.children.some((child) => child.textContent === "sources.untrusted"));
  assert.ok(details.children.some((child) => child.tagName === "pre" && child.textContent.includes("<img onerror")));
  assert.ok(details.children.some((child) => child.tagName === "a" && child.rel.includes("noopener")));
});

test("agent annotations remain collapsed untrusted metadata, never authoritative clickable links", () => {
  const annotations = [{ type: "url_citation", url: "javascript:alert(1)", title: "<img onerror=alert(1)>" }];
  const details = renderAnnotations(document, t, annotations);
  assert.equal(details.tagName, "details");
  assert.equal(details.open, undefined);
  assert.ok(details.children.some((child) => child.textContent === "sources.annotationsUntrusted"));
  assert.ok(details.children.some((child) => child.tagName === "pre" && child.textContent.includes("<img onerror")));
  assert.ok(details.children.every((child) => child.tagName !== "a"));
  assert.equal(renderAnnotations(document, t, []), null);
  assert.equal(renderAnnotations(document, t, undefined), null);
});

test("native speech deltas accumulate, while the final transcript replaces provisional text", () => {
  let text = mergeTranscript("", { text: "Sales ", final: false });
  text = mergeTranscript(text, { text: "increased.", final: false });
  assert.equal(text, "Sales increased.");
  assert.equal(mergeTranscript(text, { text: "Sales increased by 5%.", final: true }), "Sales increased by 5%.");
});
