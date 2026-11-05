import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const root = new URL("../sales_agent/static/", import.meta.url);
const source = await readFile(new URL("branding.js", root), "utf8");

function fixture(saved = null, storageError = null) {
  const writes = [], attributes = new Map([["data-theme", "dark"]]);
  const storage = {
    getItem(key) {
      assert.equal(key, "foundry-sales.brand");
      if (storageError) throw storageError;
      return saved;
    },
    setItem(key, value) { writes.push([key, value]); },
  };
  const window = { localStorage: storage };
  const document = { documentElement: { setAttribute(key, value) { attributes.set(key, value); } } };
  vm.runInNewContext(source, { window, document, DOMException });
  return { controller: window.salesBranding, attributes, writes, storage };
}

test("Gray defaults before first paint without changing light/dark appearance", () => {
  const { controller, attributes, writes } = fixture();
  assert.equal(controller.value, "gray");
  assert.equal(attributes.get("data-brand"), "gray");
  assert.equal(attributes.get("data-theme"), "dark");
  assert.deepEqual(writes, []);
});

test("brand choice restores and persists only its allowlisted cosmetic identifier", () => {
  const { controller, attributes, writes } = fixture("swedish-retail");
  assert.equal(controller.value, "swedish-retail");
  assert.equal(attributes.get("data-brand"), "swedish-retail");
  assert.equal(controller.select("gray"), true);
  assert.deepEqual(writes, [["foundry-sales.brand", "gray"]]);
  assert.equal(attributes.get("data-theme"), "dark");
  assert.equal(attributes.get("data-brand"), "gray");
});

test("unknown stored values cannot become selectors, URLs or markup", () => {
  for (const value of ["unknown", "", "<script>bad</script>", "https://example.invalid/theme.css"]) {
    const { controller, attributes, writes } = fixture(value);
    assert.equal(controller.value, "gray");
    assert.throws(() => controller.select(value), { name: "RangeError" });
    assert.equal(attributes.get("data-brand"), "gray");
    assert.deepEqual(writes, []);
  }
});

test("blocked storage is explicit and selection still works for the current page", () => {
  const { controller, attributes } = fixture(null, new DOMException("Blocked", "SecurityError"));
  assert.equal(controller.persistent, false);
  assert.equal(controller.select("swedish-retail"), false);
  assert.equal(attributes.get("data-brand"), "swedish-retail");
});

test("quota failure preserves the selected brand and reports non-persistence", () => {
  const { controller, storage, attributes } = fixture();
  storage.setItem = () => { throw new DOMException("Full", "QuotaExceededError"); };
  assert.equal(controller.select("swedish-retail"), false);
  assert.equal(controller.persistent, false);
  assert.equal(attributes.get("data-brand"), "swedish-retail");
});

test("unexpected storage/programming errors are not silently hidden", () => {
  assert.throws(() => fixture(null, new TypeError("Unexpected")), /Unexpected/);
});

test("branding initializes before CSS, with separate localized Theme and Appearance controls", async () => {
  const html = await readFile(new URL("index.html", root), "utf8");
  const locale = JSON.parse(await readFile(new URL("locales/en.json", root), "utf8"));
  const app = await readFile(new URL("app.js", root), "utf8");
  assert.ok(html.indexOf('src="/static/branding.js"') < html.indexOf('href="/static/theme.css"'));
  assert.match(html, /<label for="brand-theme" data-i18n="branding.label"/);
  assert.match(html, /id="brand-theme"/);
  assert.doesNotMatch(html, /<select id="brand-theme"[^>]*aria-describedby/);
  assert.match(html, /value="swedish-retail" data-i18n="branding.swedishRetail"/);
  assert.match(html, /value="gray" data-i18n="branding.gray"/);
  assert.equal(locale.branding.label, "Theme");
  assert.equal(locale.branding.swedishRetail, "Swedish Retail");
  assert.equal(locale.branding.gray, "Gray");
  assert.equal(locale.app.theme, "Appearance");
  assert.match(app, /salesBranding/);
  assert.match(app, /\$\("brand-theme"\)\.addEventListener\("change"/);
});

test("brand palettes cover both appearances without using external brand assets", async () => {
  const css = await readFile(new URL("theme.css", root), "utf8");
  for (const brand of ["gray", "swedish-retail"]) {
    assert.ok(css.includes(`html[data-brand="${brand}"]`));
    assert.ok(css.includes(`html[data-brand="${brand}"][data-theme="dark"]`));
  }
  assert.match(css, /--cp-banner-bg:\s*#ffda1a/i);
  assert.match(css, /--cp-accent:\s*#0058a3/i);
  assert.match(css, /\.brand-banner/);
  assert.doesNotMatch(css, /@import|url\(\s*["']?https?:/);
});

test("theme switches cannot animate backgrounds through unreadable intermediate contrast", async () => {
  const css = await readFile(new URL("theme.css", root), "utf8");
  const button = css.match(/(?:^|\n)button\s*\{([^}]+)\}/);
  assert.ok(button);
  assert.doesNotMatch(button[1], /transition:\s*[^;]*\bbackground\b/);
});
