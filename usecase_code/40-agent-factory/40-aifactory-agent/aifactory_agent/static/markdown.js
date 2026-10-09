(() => {
  "use strict";

  const MAX_SOURCE = 250000;
  const MAX_TOKENS = 12000;
  const MAX_DEPTH = 64;
  const OPTIONS = Object.freeze({
    html: false, linkify: true, typographer: false, maxNesting: MAX_DEPTH
  });
  const CITATION_ID = /^[SGA]\d{1,9}$/;
  const CONTROL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/;
  const ALIGNMENT = new Map([
    ["text-align:left", "markdown-left"],
    ["text-align:right", "markdown-right"],
    ["text-align:center", "markdown-center"]
  ]);

  const SPECS = new Map();
  for (const [name, tag, mode] of [
    ["paragraph", "p", "block"], ["heading", null, "block"],
    ["bullet_list", "ul", "block"], ["ordered_list", "ol", "block"],
    ["list_item", "li", "block"], ["blockquote", "blockquote", "block"],
    ["table", "table", "block"], ["thead", "thead", "block"],
    ["tbody", "tbody", "block"], ["tr", "tr", "block"],
    ["th", "th", "block"], ["td", "td", "block"],
    ["em", "em", "inline"], ["strong", "strong", "inline"],
    ["s", "s", "inline"], ["link", "a", "inline"]
  ]) {
    SPECS.set(`${name}_open`, {tag, mode, nesting: 1, close: `${name}_close`});
    SPECS.set(`${name}_close`, {tag, mode, nesting: -1});
  }
  for (const [type, tag, mode] of [
    ["inline", "", "block"], ["text", "", "inline"],
    ["code_inline", "code", "inline"], ["softbreak", "br", "inline"],
    ["hardbreak", "br", "inline"], ["image", "img", "inline"],
    ["fence", "code", "block"], ["code_block", "code", "block"],
    ["hr", "hr", "block"]
  ]) {
    SPECS.set(type, {tag, mode, nesting: 0});
  }

  const DOM_ATTRIBUTES = new Map();
  for (const tag of [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "em", "strong", "s",
    "ul", "li", "pre", "code", "blockquote", "hr", "br",
    "table", "thead", "tbody", "tr"
  ]) DOM_ATTRIBUTES.set(tag, new Set());
  DOM_ATTRIBUTES.set("div", new Set(["class", "tabindex", "role", "aria-label"]));
  DOM_ATTRIBUTES.set("th", new Set(["class"]));
  DOM_ATTRIBUTES.set("td", new Set(["class"]));
  DOM_ATTRIBUTES.set("ol", new Set(["start"]));
  DOM_ATTRIBUTES.set("a", new Set(["href", "title", "rel", "target"]));

  /**
   * Inject a markdown-it factory or instance and a DOM document.
   * render(markdown, target, citations = []) commits one .markdown-body child.
   * Limits: 250,000 UTF-16 units, 12,000 tokens including inline/alt children,
   * and 64 nesting levels. Unknown/plugin tokens fail rather than degrade.
   */
  class FactoryMarkdownRenderer {
    constructor({parser, document} = {}) {
      if (!document || typeof document.createElement !== "function"
          || typeof document.createTextNode !== "function") {
        throw new Error("Markdown renderer requires an injected DOM document");
      }
      this.document = document;
      this.parser = typeof parser === "function" ? parser({...OPTIONS}) : parser;
      if (!this.parser || typeof this.parser.parse !== "function") {
        throw new Error("Markdown renderer requires an injected markdown-it parser");
      }
      if (typeof this.parser.set === "function") this.parser.set({...OPTIONS});
      // Tokenize unsafe destinations too, preserving labels/alt text. Navigation
      // is exclusively decided by _safeLink; the parser's HTML renderer is unused.
      if (typeof this.parser.validateLink === "function") this.parser.validateLink = () => true;
    }

    render(markdown, target, citations = []) {
      if (!target || typeof target.replaceChildren !== "function") {
        throw new Error("Markdown renderer requires a target with replaceChildren");
      }
      if (typeof markdown !== "string") throw new Error("Markdown source must be a string");
      if (markdown.length > MAX_SOURCE) throw new Error("Markdown source limit exceeded");
      if (!Array.isArray(citations) || citations.length > MAX_TOKENS) {
        throw new Error("Markdown citations must be a bounded array");
      }
      const ids = new Set();
      for (const citation of citations) {
        if (citation && typeof citation.citation_id === "string"
            && CITATION_ID.test(citation.citation_id)) ids.add(citation.citation_id);
      }
      const tokens = this.parser.parse(markdown, {});
      this._validate(tokens, "block", 0, {count: 0});
      const root = this._element("div", {class: "markdown-body"});
      this._build(tokens, root, ids);
      target.replaceChildren(root);
      return root;
    }

    _attributes(token) {
      if (token.attrs === null || token.attrs === undefined) return new Map();
      if (!Array.isArray(token.attrs)) throw new Error("Invalid Markdown token attributes");
      const attributes = new Map();
      for (const pair of token.attrs) {
        if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string"
            || attributes.has(pair[0])) throw new Error("Invalid Markdown token attribute");
        let value = pair[1];
        // markdown-it's ordered-list start is numeric, unlike link/cell attrs.
        if (token.type === "ordered_list_open" && pair[0] === "start"
            && Number.isSafeInteger(value) && value >= 0 && value <= 999999999) value = String(value);
        if (typeof value !== "string" || value.length > MAX_SOURCE) {
          throw new Error("Invalid Markdown token attribute");
        }
        attributes.set(pair[0], value);
      }
      let allowed = [];
      if (token.type === "link_open") allowed = ["href", "title"];
      else if (token.type === "image") allowed = ["src", "alt", "title"];
      else if (token.type === "ordered_list_open") allowed = ["start"];
      else if (token.type === "th_open" || token.type === "td_open") allowed = ["style"];
      for (const name of attributes.keys()) {
        if (!allowed.includes(name)) throw new Error("Unsupported Markdown token attribute");
      }
      if (attributes.has("style") && !ALIGNMENT.has(attributes.get("style"))) {
        throw new Error("Unsupported Markdown table alignment");
      }
      if (attributes.has("start") && !/^\d{1,9}$/.test(attributes.get("start"))) {
        throw new Error("Invalid Markdown ordered list start");
      }
      if (token.type === "link_open" && !attributes.has("href")) {
        throw new Error("Markdown link token requires a destination");
      }
      if (token.type === "image" && !attributes.has("src")) {
        throw new Error("Markdown image token requires a source");
      }
      return attributes;
    }

    _validate(tokens, mode, baseDepth, state) {
      if (!Array.isArray(tokens)) throw new Error("Markdown parser must return token arrays");
      if (baseDepth > MAX_DEPTH) throw new Error("Markdown depth limit exceeded");
      const stack = [];
      for (const token of tokens) {
        if (++state.count > MAX_TOKENS) throw new Error("Markdown token limit exceeded");
        if (!token || typeof token !== "object" || typeof token.type !== "string") {
          throw new Error("Invalid Markdown token");
        }
        const spec = SPECS.get(token.type);
        if (!spec || spec.mode !== mode) throw new Error("Unsupported Markdown token");
        if (token.nesting !== spec.nesting
            || (spec.tag === null ? !/^h[1-6]$/.test(token.tag) : token.tag !== spec.tag)) {
          throw new Error("Invalid Markdown token tag or nesting");
        }
        if (typeof token.content !== "string" || token.content.length > MAX_SOURCE) {
          throw new Error("Invalid Markdown token content");
        }
        if (token.hidden !== undefined && typeof token.hidden !== "boolean") {
          throw new Error("Invalid Markdown token visibility");
        }
        if (token.hidden && !["paragraph_open", "paragraph_close"].includes(token.type)) {
          throw new Error("Unsupported hidden Markdown token");
        }
        this._attributes(token);
        if (spec.nesting === 1) {
          if (token.type === "link_open" && stack.some(frame => frame.token.type === "link_open")) {
            throw new Error("Nested Markdown links are unsupported");
          }
          stack.push({token, spec});
        } else if (spec.nesting === -1) {
          const open = stack.pop();
          if (!open || open.spec.close !== token.type || open.token.tag !== token.tag
              || Boolean(open.token.hidden) !== Boolean(token.hidden)) {
            throw new Error("Unbalanced Markdown tokens");
          }
        }
        if (baseDepth + stack.length > MAX_DEPTH) throw new Error("Markdown depth limit exceeded");
        if (token.type === "inline" || token.type === "image") {
          this._validate(token.children, "inline", baseDepth + stack.length + 1, state);
        } else if (token.children !== undefined && token.children !== null) {
          throw new Error("Unsupported Markdown token children");
        }
      }
      if (stack.length) throw new Error("Unbalanced Markdown tokens");
    }

    _element(tag, attributes = {}) {
      const allowed = DOM_ATTRIBUTES.get(tag);
      if (!allowed) throw new Error("Unsupported Markdown DOM tag");
      const element = this.document.createElement(tag);
      for (const [name, value] of Object.entries(attributes)) {
        if (!allowed.has(name)) throw new Error("Unsupported Markdown DOM attribute");
        element.setAttribute(name, value);
      }
      return element;
    }

    _text(parent, value) {
      parent.append(this.document.createTextNode(value));
    }

    _safeLink(href, ids) {
      if (CONTROL.test(href) || /[\s\\]/.test(href)) return null;
      if (href.startsWith("#source-")) {
        const id = href.slice(8);
        return ids.has(id) ? {href, external: false} : null;
      }
      const authority = /^https?:\/\/([^/?#]+)/i.exec(href);
      if (!authority || authority[1].includes("@") || /%(?![a-f0-9]{2})/i.test(href)) return null;
      let decoded = href;
      for (let round = 0; /%[a-f0-9]{2}/i.test(decoded); round++) {
        if (round >= 8) return null;
        try { decoded = decodeURIComponent(decoded); } catch { return null; }
        if (CONTROL.test(decoded) || decoded.includes("\\")) return null;
      }
      try {
        const url = new URL(href);
        if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) {
          return null;
        }
        return {href, external: true};
      } catch {
        return null;
      }
    }

    _citationText(parent, value, ids, suppressed) {
      if (suppressed || !ids.size) {
        this._text(parent, value);
        return;
      }
      const matcher = /\[([SGA]\d{1,9})\]/g;
      let offset = 0;
      for (let match; (match = matcher.exec(value)) !== null;) {
        if (!ids.has(match[1])) continue;
        if (match.index > offset) this._text(parent, value.slice(offset, match.index));
        const link = this._element("a", {href: `#source-${match[1]}`});
        this._text(link, match[0]);
        parent.append(link);
        offset = match.index + match[0].length;
      }
      if (offset < value.length) this._text(parent, value.slice(offset));
    }

    _altText(tokens) {
      const parts = [];
      for (const token of tokens) {
        if (token.type === "text" || token.type === "code_inline") parts.push(token.content);
        else if (token.type === "softbreak" || token.type === "hardbreak") parts.push("\n");
        else if (token.type === "image") parts.push(this._altText(token.children));
      }
      return parts.join("");
    }

    _build(tokens, root, ids) {
      const stack = [{node: root, suppressed: false}];
      for (const token of tokens) {
        const frame = stack[stack.length - 1];
        const spec = SPECS.get(token.type);
        if (spec.nesting === -1) {
          stack.pop();
        } else if (spec.nesting === 1) {
          let node = frame.node;
          const attributes = this._attributes(token);
          if (token.type === "link_open") {
            const safe = this._safeLink(attributes.get("href"), ids);
            if (safe) {
              const linkAttributes = {href: safe.href};
              if (attributes.has("title")) linkAttributes.title = attributes.get("title");
              if (safe.external) {
                linkAttributes.rel = "noopener noreferrer";
                linkAttributes.target = "_blank";
              }
              node = this._element("a", linkAttributes);
              frame.node.append(node);
            }
          } else if (!token.hidden) {
            const domAttributes = {};
            if (token.type === "ordered_list_open" && attributes.has("start")) {
              domAttributes.start = attributes.get("start");
            }
            if (attributes.has("style")) domAttributes.class = ALIGNMENT.get(attributes.get("style"));
            node = this._element(token.tag, domAttributes);
            if (token.type === "table_open") {
              const wrapper = this._element("div", {
                class: "markdown-table-wrap", tabindex: "0",
                role: "region", "aria-label": "Scrollable table"
              });
              frame.node.append(wrapper);
              wrapper.append(node);
            } else frame.node.append(node);
          }
          stack.push({node, suppressed: frame.suppressed || token.type === "link_open"});
        } else if (token.type === "inline") {
          this._build(token.children, frame.node, ids);
        } else if (token.type === "text") {
          this._citationText(frame.node, token.content, ids, frame.suppressed);
        } else if (token.type === "image") {
          this._text(frame.node, this._altText(token.children));
        } else if (token.type === "code_inline") {
          const code = this._element("code");
          this._text(code, token.content);
          frame.node.append(code);
        } else if (token.type === "fence" || token.type === "code_block") {
          const pre = this._element("pre");
          const code = this._element("code");
          this._text(code, token.content);
          pre.append(code);
          frame.node.append(pre);
        } else if (token.type === "softbreak") {
          this._text(frame.node, "\n");
        } else if (token.type === "hardbreak" || token.type === "hr") {
          frame.node.append(this._element(token.tag));
        } else {
          throw new Error("Unsupported Markdown token");
        }
      }
    }
  }

  window.FactoryMarkdownRenderer = FactoryMarkdownRenderer;
})();
