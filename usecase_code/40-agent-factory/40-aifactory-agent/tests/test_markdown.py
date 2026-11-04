"""Real vendored browser parser + injected DOM; no network, jsdom or npm install."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "aifactory_agent" / "static"
RENDERER = STATIC / "markdown.js"
VENDOR = STATIC / "vendor"

NODE_DRIVER = r"""
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const request = JSON.parse(fs.readFileSync(0, "utf8"));

class Node {
  constructor(document, type) {
    this.ownerDocument = document;
    this.nodeType = type;
    this.parentNode = null;
    this.childNodes = [];
    this.commits = 0;
  }
  get children() { return this.childNodes.filter(child => child.nodeType === 1); }
  get textContent() { return this.childNodes.map(child => child.textContent).join(""); }
  set textContent(value) {
    this.replaceChildren();
    if (value !== null && value !== "") this.append(this.ownerDocument.createTextNode(String(value)));
  }
  append(...nodes) {
    for (let node of nodes) {
      if (!(node instanceof Node)) node = this.ownerDocument.createTextNode(String(node));
      if (node.parentNode) {
        const old = node.parentNode.childNodes;
        old.splice(old.indexOf(node), 1);
      }
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }
  replaceChildren(...nodes) {
    this.commits++;
    for (const child of this.childNodes) child.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
}
class TextNode extends Node {
  constructor(document, value) { super(document, 3); this.data = String(value); }
  get textContent() { return this.data; }
  set textContent(value) { this.data = value === null ? "" : String(value); }
}
class Element extends Node {
  constructor(document, tag) { super(document, 1); this.tagName = tag.toUpperCase(); this.attributes = {}; }
  setAttribute(name, value) {
    if (/^on/i.test(name) || name === "style") throw Error("Unsafe attribute sink: " + name);
    this.attributes[name] = String(value);
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  get className() { return this.getAttribute("class") || ""; }
  set className(value) { this.setAttribute("class", value); }
  set innerHTML(_) { throw Error("Forbidden HTML sink"); }
  get innerHTML() { throw Error("Forbidden HTML sink"); }
  insertAdjacentHTML() { throw Error("Forbidden HTML sink"); }
}
const allowedTags = new Set([
  "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "em", "strong", "s",
  "ul", "ol", "li", "pre", "code", "blockquote", "hr", "br", "a",
  "table", "thead", "tbody", "tr", "th", "td"
]);
const document = {
  createElement(tag) {
    if (!allowedTags.has(tag)) throw Error("Unsafe tag sink: " + tag);
    return new Element(this, tag);
  },
  createTextNode(value) {
    if (request.failText && value.includes(request.failText)) throw Error("Injected DOM failure");
    return new TextNode(this, value);
  }
};
function snapshot(node) {
  if (node.nodeType === 3) return {text: node.data};
  return {
    tag: node.tagName.toLowerCase(), attrs: {...node.attributes},
    text: node.textContent, children: node.childNodes.map(snapshot)
  };
}
const context = vm.createContext({
  window: {}, URL, TextDecoder, TextEncoder,
  atob: value => Buffer.from(value, "base64").toString("binary")
});
try {
  vm.runInContext(fs.readFileSync(path.join("aifactory_agent", "static", "vendor", "markdown-it.min.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join("aifactory_agent", "static", "markdown.js"), "utf8"), context);
  const environments = [];
  let parser = context.markdownit();
  const parse = parser.parse.bind(parser);
  parser.parse = (source, env) => {
    environments.push(env);
    if (request.parseError) throw Error("Injected parse failure");
    if (request.tokens) return request.tokens;
    if (request.cycle) {
      const inline = {type: "inline", tag: "", nesting: 0, content: "", children: []};
      inline.children.push(inline);
      return [inline];
    }
    return parse(source, env);
  };
  parser.render = () => { throw Error("String HTML rendering must not be used"); };
  if (request.factory) {
    const instance = parser;
    parser = options => instance.set(options);
  }
  if (request.dependency === "parser") parser = null;
  if (request.dependency === "parse") parser = {};
  const injectedDocument = request.dependency === "document" ? null : document;
  const Renderer = context.window.FactoryMarkdownRenderer;
  const renderer = new Renderer({parser, document: injectedDocument});
  const target = new Element(document, "section");
  target.append(document.createTextNode("previous answer"));
  target.commits = 0;
  const oldChild = target.childNodes[0];
  if (request.dependency === "target") target.replaceChildren = undefined;
  const results = [];
  for (const item of request.renders || [request]) {
    let error = null;
    try { renderer.render(item.source, target, item.citations); }
    catch (exception) { error = exception.message; }
    results.push({
      error, tree: snapshot(target), commits: target.commits,
      sameChild: target.childNodes[0] === oldChild
    });
  }
  console.log(JSON.stringify({
    results, config: renderer.parser?.options,
    parseCalls: environments.length,
    freshEnvironments: environments.every((env, index) =>
      env && typeof env === "object" && environments.indexOf(env) === index)
  }));
} catch (exception) {
  console.log(JSON.stringify({error: exception.message}));
}
"""

def run_node(source="", **options):
    request = {"source": source, **options}
    process = subprocess.run(
        ["node", "-e", NODE_DRIVER],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def render(source, **options):
    response = run_node(source, **options)
    assert not response.get("error"), response
    result = response["results"][0]
    assert result["error"] is None, result["error"]
    assert result["commits"] == 1
    body = result["tree"]["children"][0]
    assert body["attrs"] == {"class": "markdown-body"}
    return body


def elements(tree, tag=None):
    found = []
    if "tag" in tree and (tag is None or tree["tag"] == tag):
        found.append(tree)
    for child in tree.get("children", []):
        found.extend(elements(child, tag))
    return found


def token(kind, tag="", nesting=0, **kwargs):
    return {"type": kind, "tag": tag, "nesting": nesting, "content": "", **kwargs}


def paragraph(children):
    return [
        token("paragraph_open", "p", 1),
        token("inline", children=children),
        token("paragraph_close", "p", -1),
    ]


def assert_atomic_error(response, match=None):
    assert not response.get("error"), response
    result = response["results"][0]
    assert result["error"]
    if match:
        assert match.lower() in result["error"].lower()
    assert result["tree"]["text"] == "previous answer"
    assert result["commits"] == 0
    assert result["sameChild"]


def test_renderer_module_exists():
    assert RENDERER.is_file(), "Implement the new dependency-injected Markdown renderer"


def test_vendored_production_parser_integrity_license_and_exact_lock_pin():
    metadata = json.loads((VENDOR / "markdown-it.metadata.json").read_text("utf-8"))
    package = json.loads((ROOT / "package.json").read_text("utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text("utf-8"))
    assert metadata["package"] == "markdown-it"
    assert metadata["version"] == package["dependencies"]["markdown-it"] == "15.0.2"
    assert metadata["browser_distribution"] == "dist/browser/markdown-it.umd.min.js"
    assert lock["packages"][""]["dependencies"]["markdown-it"] == "15.0.2"
    pinned = lock["packages"]["node_modules/markdown-it"]
    assert pinned["version"] == "15.0.2"
    assert pinned["integrity"] == metadata["npm_integrity"]
    assert metadata["npm_integrity"] == (
        "sha512-q4IGxMv56jCqT4OCRCADBoDP3LO4MhmTXjFbphHPXs4g3j9Xg5RDnxqN8IF/"
        "3vIWEU+VCnUq+7JUg/cfy2E6Qw=="
    )
    assert hashlib.sha256((VENDOR / "markdown-it.min.js").read_bytes()).hexdigest() == metadata["sha256"]
    license_text = (VENDOR / "markdown-it.LICENSE").read_text("utf-8")
    assert metadata["license"] == pinned["license"] == "MIT"
    assert "Permission is hereby granted, free of charge" in license_text
    assert "THE SOFTWARE IS PROVIDED" in license_text


def test_semantic_headings_paragraphs_emphasis_rules_and_quotes():
    source = (
        "# Heading\n\n## Second\n\n### Third\n\n#### Fourth\n\n##### Fifth\n\n###### Sixth\n\n"
        "Paragraph *emphasis* and **bold** and ~~deleted~~; \"quotes\" -- stay literal.\n\n"
        "> Quoted\n>\n> **nested**\n\n---\n\nsetext\n======"
    )
    body = render(source)
    assert [node["text"] for node in elements(body, "h1")] == ["Heading", "setext"]
    for level in range(2, 7):
        assert len(elements(body, f"h{level}")) == 1
    assert elements(body, "em")[0]["text"] == "emphasis"
    assert [node["text"] for node in elements(body, "strong")] == ["bold", "nested"]
    assert elements(body, "s")[0]["text"] == "deleted"
    assert len(elements(body, "blockquote")) == len(elements(body, "hr")) == 1
    assert '"quotes" -- stay literal.' in body["text"]


def test_tight_loose_and_nested_ordered_unordered_lists():
    body = render("- parent\n  - child\n    1. ordered\n    2. again\n- sibling\n\n3. loose\n\n4. list")
    lists = elements(body, "ul")
    assert len(lists) == 2
    parent = elements(lists[0], "li")[0]
    assert parent["children"][0] == {"text": "parent"}
    assert parent["children"][1]["tag"] == "ul"
    ordered = elements(body, "ol")
    assert ordered[0]["attrs"] == {}
    assert ordered[1]["attrs"] == {"start": "3"}
    assert [item["text"] for item in elements(ordered[1], "p")] == ["loose", "list"]


def test_tables_alignment_overflow_wrapper_and_escaped_pipes():
    body = render(
        "| left | center | right | default |\n"
        "| :--- | :---: | ---: | --- |\n"
        "| a\\|b | **middle** | `x` | <b>literal</b> |"
    )
    wrapper = next(node for node in elements(body, "div") if node["attrs"].get("class") == "markdown-table-wrap")
    assert wrapper["attrs"] == {
        "class": "markdown-table-wrap", "tabindex": "0", "role": "region", "aria-label": "Scrollable table"
    }
    assert wrapper["children"][0]["tag"] == "table"
    assert len(elements(body, "thead")) == len(elements(body, "tbody")) == 1
    cells = elements(body, "td")
    assert [cell["text"] for cell in cells] == ["a|b", "middle", "x", "<b>literal</b>"]
    assert [cell["attrs"].get("class") for cell in cells] == [
        "markdown-left", "markdown-center", "markdown-right", None
    ]
    assert not any("style" in node["attrs"] for node in elements(body))


def test_fences_indented_code_inline_code_unicode_and_escaped_html():
    body = render(
        "```xml\n<script>[S1] & 雪 😀</script>\n```\n\n"
        "    <svg>[S1]</svg>\n\n"
        "`<b>[S1]</b>` and \\<i\\>literal\\</i\\> &amp; café",
        citations=[{"citation_id": "S1"}],
    )
    code = elements(body, "code")
    assert [node["text"] for node in code] == [
        "<script>[S1] & 雪 😀</script>\n", "<svg>[S1]</svg>\n", "<b>[S1]</b>"
    ]
    assert len(elements(body, "pre")) == 2
    assert "<i>literal</i> & café" in body["text"]
    assert not elements(body, "a")
    assert not any(node["tag"] in {"script", "svg", "b", "i"} for node in elements(body))


def test_soft_and_hard_breaks_reference_links_and_linkification():
    body = render("soft\nline  \nhard\\\nbreak\n\n[reference][r]\n\n[r]: https://example.org \"A title\"\n\nhttps://example.org/path")
    assert "soft\nline" in body["text"]
    assert len(elements(body, "br")) == 2
    links = elements(body, "a")
    assert [link["attrs"]["href"] for link in links] == ["https://example.org", "https://example.org/path"]
    assert links[0]["attrs"]["title"] == "A title"
    assert all(link["attrs"]["rel"] == "noopener noreferrer" and link["attrs"]["target"] == "_blank" for link in links)


def test_citations_only_allow_passed_ids_and_never_inside_existing_links_or_code():
    body = render(
        "[S1] **[S2]** [S3] ` [S1] `\n\n"
        "[[S1]](https://example.org) [[S1]](file:///secret)\n\n"
        "[local](#source-S1) [unknown](#source-S3) [other](#elsewhere)\n\n"
        "```\n[S2]\n```",
        citations=[{"citation_id": "S1"}, {"citation_id": "S2"}, {"citation_id": 'S4" onclick="evil'}],
    )
    links = elements(body, "a")
    assert [(link["text"], link["attrs"]["href"]) for link in links] == [
        ("[S1]", "#source-S1"), ("[S2]", "#source-S2"),
        ("[S1]", "https://example.org"), ("local", "#source-S1")
    ]
    for link in links:
        if link["attrs"]["href"].startswith("#"):
            assert "target" not in link["attrs"] and "rel" not in link["attrs"]
    assert "[S3]" in body["text"] and "unknown" in body["text"] and "other" in body["text"]
    assert all(not elements(link, "a")[1:] for link in links)


def test_images_emit_alt_text_only_even_with_unsafe_or_signed_sources():
    body = render(
        "![plain](https://remote.invalid/a.png) "
        "![*formatted* `code` &amp; 雪 [S1]](data:image/png;base64,abc) "
        "![danger](javascript:alert%281%29) "
        "![signed](https://blob.invalid/file?sig=not-a-secret%2B%2F%3D)",
        citations=[{"citation_id": "S1"}],
    )
    assert body["text"] == "plain formatted code & 雪 [S1] danger signed"
    assert not elements(body, "a")
    assert not any("src" in node["attrs"] for node in elements(body))
    assert "remote.invalid" not in json.dumps(body) and "not-a-secret" not in json.dumps(body)


@pytest.mark.parametrize("destination", [
    "javascript:alert%281%29", "JaVaScRiPt:alert%281%29", "data:text/html,evil",
    "file:///secret", "//evil.invalid/path", "ftp://evil.invalid/path", "mailto:evil@example.org",
    "https://user:password@example.org", "https://user%40example.org@evil.invalid",
    "https://example.org/%0aevil", "https://example.org/%0Devil", "https://example.org/%00evil",
    "https://example.org/%250aevil", "https://example.org/%25250Aevil",
    "https://example.org/a&#10;b", "https://example.org/%C2%85evil",
    "https:///evil.invalid", "#source-S99", "#arbitrary",
])
def test_unsafe_links_keep_label_without_navigation(destination):
    body = render(f"[visible label]({destination})", citations=[{"citation_id": "S1"}])
    assert "visible label" in body["text"]
    assert not elements(body, "a")


def test_safe_http_signed_queries_unicode_and_autolinks_preserve_destination():
    body = render(
        "[signed](https://blob.example.org/path?sv=1&sig=a%2Bb%2Fc%3D) "
        "[http](http://example.org:8080/a) "
        "<https://example.org/unicode/%E9%9B%AA>"
    )
    links = elements(body, "a")
    assert links[0]["attrs"]["href"] == "https://blob.example.org/path?sv=1&sig=a%2Bb%2Fc%3D"
    assert links[1]["attrs"]["href"] == "http://example.org:8080/a"
    assert links[2]["attrs"]["href"] == "https://example.org/unicode/%E9%9B%AA"


def test_raw_script_svg_html_events_styles_and_titles_are_never_interpreted():
    raw = '<script>alert(1)</script><svg onload="evil()"><a href="javascript:evil">x</a></svg>'
    body = render(raw + '\n\n<div style="color:red" onclick="evil()">raw</div>\n\n'
                  '[title](https://example.org "\\\" onclick=\\\"evil()")')
    assert raw in body["text"]
    assert '<div style="color:red" onclick="evil()">raw</div>' in body["text"]
    links = elements(body, "a")
    assert len(links) == 1
    assert links[0]["attrs"]["title"] == '" onclick="evil()'
    assert set(links[0]["attrs"]) == {"href", "title", "rel", "target"}
    assert not any(name.startswith("on") or name == "style" for node in elements(body) for name in node["attrs"])


@pytest.mark.parametrize("dependency", ["parser", "parse", "document", "target"])
def test_missing_dependencies_are_explicit_errors_not_plain_text_success(dependency):
    response = run_node("**not a fallback**", dependency=dependency)
    if dependency == "target":
        assert_atomic_error(response)
        assert response["parseCalls"] == 0
    else:
        assert response.get("error")
        assert dependency in response["error"].lower() or "parser" in response["error"].lower()


def test_factory_and_instance_di_enforce_safe_options_and_parse_not_html_render():
    for factory in (False, True):
        response = run_node("**DI**", factory=factory)
        assert response["results"][0]["error"] is None
        assert response["parseCalls"] == 1
        assert response["config"]["html"] is False
        assert response["config"]["linkify"] is True
        assert response["config"]["typographer"] is False
        assert response["config"]["maxNesting"] == 64


def test_render_state_and_citations_do_not_leak_between_calls():
    response = run_node(renders=[
        {"source": "[S1]", "citations": [{"citation_id": "S1"}]},
        {"source": "[S1]"},
        {"source": "replacement"},
    ])
    assert len(elements(response["results"][0]["tree"], "a")) == 1
    assert not elements(response["results"][1]["tree"], "a")
    assert response["results"][2]["tree"]["text"] == "replacement"
    assert response["results"][2]["commits"] == 3
    assert response["freshEnvironments"]


@pytest.mark.parametrize("tokens", [
    [token("html_block", content="<script>evil()</script>")],
    paragraph([token("html_inline", content="<img onerror=evil()>")]),
    [token("script_open", "script", 1)],
    [token("heading_open", "svg", 1), token("heading_close", "svg", -1)],
    paragraph([token("text", tag="script", content="unsafe")]),
    [token("paragraph_open", "p", 1, attrs=[["onclick", "evil()"]]), token("paragraph_close", "p", -1)],
    [token("paragraph_open", "p", 1, attrs=[["style", "color:red"]]), token("paragraph_close", "p", -1)],
    [token("th_open", "th", 1, attrs=[["style", "text-align:left; background:url(evil)"]]), token("th_close", "th", -1)],
    paragraph([token("link_open", "a", 1, attrs=[["href", "https://example.org"], ["onclick", "evil()"]]),
               token("link_close", "a", -1)]),
    paragraph([token("link_open", "a", 1, attrs=[["href", "https://example.org"], ["href", "javascript:evil()"]]),
               token("link_close", "a", -1)]),
    paragraph([token("image", "img", children=[], attrs=[["src", "https://example.org"], ["alt", ""], ["onerror", "evil()"]])]),
    [token("paragraph_open", "p", 1), token("heading_close", "h1", -1)],
    [token("paragraph_close", "p", -1)],
    [token("paragraph_open", "p", 1)],
    paragraph([token("strong_open", "strong", 0), token("strong_close", "strong", -1)]),
    [token("fence", "code", content="code", children=[token("text", content="hidden")])],
])
def test_custom_unsafe_or_unsupported_tokens_fail_closed_atomically(tokens):
    assert_atomic_error(run_node("placeholder", tokens=tokens))


def test_custom_allowed_links_still_validate_urls_and_never_copy_arbitrary_attributes():
    tokens = paragraph([
        token("link_open", "a", 1, attrs=[["href", "https://example.org/\x00secret"]]),
        token("text", content="[S1]"),
        token("link_close", "a", -1),
    ])
    body = render("placeholder", tokens=tokens, citations=[{"citation_id": "S1"}])
    assert body["text"] == "[S1]" and not elements(body, "a")


def test_parse_and_dom_failures_leave_existing_answer_intact():
    assert_atomic_error(run_node("x", parseError=True), "parse failure")
    assert_atomic_error(run_node("explode", failText="explode"), "DOM failure")


def test_empty_and_source_size_boundary():
    assert render("")["text"] == ""
    assert render("x" * 250000)["text"] == "x" * 250000
    response = run_node("x" * 250001)
    assert_atomic_error(response, "source")
    assert response["parseCalls"] == 0


def test_token_and_depth_limits_also_include_inline_image_children():
    many = paragraph([token("text", content="x") for _ in range(12001)])
    assert_atomic_error(run_node("small source", tokens=many), "token")
    deep = [token("blockquote_open", "blockquote", 1) for _ in range(65)]
    deep += paragraph([token("text", content="x")])
    deep += [token("blockquote_close", "blockquote", -1) for _ in range(65)]
    assert_atomic_error(run_node("small source", tokens=deep), "depth")
    children = [token("text", content="x") for _ in range(12001)]
    image = token("image", "img", attrs=[["src", "https://example.org"], ["alt", ""]], children=children)
    assert_atomic_error(run_node("small source", tokens=paragraph([image])), "token")
    assert_atomic_error(run_node("cycle", cycle=True))


@pytest.mark.parametrize("source", [None, 42, {}, []])
def test_invalid_source_type_leaves_answer_unchanged(source):
    assert_atomic_error(run_node(source))


def test_no_string_html_sinks_external_autoloads_or_remote_image_elements():
    source = RENDERER.read_text("utf-8")
    for forbidden in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "fetch(", "eval("):
        assert forbidden not in source
