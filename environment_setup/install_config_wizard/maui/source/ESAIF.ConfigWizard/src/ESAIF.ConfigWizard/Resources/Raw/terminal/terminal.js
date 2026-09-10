(() => {
  "use strict";
  const nonce = window.esaifBridgeNonce;
  delete window.esaifBridgeNonce;
  const send = (message) => window.chrome?.webview?.postMessage({ ...message, nonce });
  const styles = getComputedStyle(document.documentElement);
  const color = (name) => styles.getPropertyValue(`--cp-${name}`).trim();
  const terminal = new Terminal({
    cols: 80, rows: 12, scrollback: 2000, fontFamily: 'Consolas, "Courier New", Courier, monospace',
    fontSize: 13, cursorBlink: true, convertEol: false, disableStdin: true,
    allowProposedApi: false, allowTransparency: false, screenReaderMode: true,
    theme: {
      background: color("surface"), foreground: color("text"), cursor: color("text"),
      selectionBackground: color("highlight"), black: color("text"), brightBlack: color("text-muted"),
      red: color("danger"), brightRed: color("danger"), green: color("success"), brightGreen: color("success"),
      yellow: color("warning"), brightYellow: color("warning"), blue: color("link"), brightBlue: color("link"),
      magenta: color("accent"), brightMagenta: color("accent"), cyan: color("link"), brightCyan: color("link"),
      white: color("text-soft"), brightWhite: color("text")
    },
    linkHandler: { activate() {}, hover() {}, leave() {} }
  });
  const fit = new FitAddon.FitAddon();
  terminal.loadAddon(fit);
  terminal.open(document.getElementById("terminal"));
  let enabled = false;
  let replaying = false;
  let filterState = 0;
  let resizeTimer;
  let lastSize = "";
  let inputSequence = 0;
  let outstandingInput = 0;
  let scope = "";

  // Stateful across output chunks: suppress all string controls, including split OSC 52 / OSC 8.
  function safeOutput(value) {
    let output = "";
    for (const character of value) {
      if (filterState === 0) {
        if (character === "\x1b") filterState = 1;
        else if ("\x90\x98\x9d\x9e\x9f".includes(character)) filterState = 2;
        else output += character;
      } else if (filterState === 1) {
        if ("]P_^X".includes(character)) filterState = 2;
        else { output += "\x1b" + character; filterState = 0; }
      } else if (filterState === 2) {
        if (character === "\x07" || character === "\x9c") filterState = 0;
        else if (character === "\x1b") filterState = 3;
      } else {
        filterState = character === "\\" || character === "\x9c" ? 0 : character === "\x1b" ? 3 : 2;
      }
    }
    return output;
  }
  terminal.parser.registerOscHandler(52, () => true);
  terminal.parser.registerOscHandler(8, () => true);
  terminal.onData((data) => {
    if (!enabled || replaying) return;
    if (data.length > 8192 || outstandingInput >= 32) {
      enabled = false;
      terminal.options.disableStdin = true;
      send({ type: "inputOverflow" });
      return;
    }
    outstandingInput++;
    send({ type: "input", data, sequence: ++inputSequence, scope });
  });
  terminal.attachCustomKeyEventHandler((event) => {
    if (event.type === "keydown" && event.ctrlKey && event.shiftKey && event.code === "KeyC") {
      send({ type: "copy" });
      return false;
    }
    return true;
  });
  document.addEventListener("contextmenu", (event) => event.preventDefault());
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("a")) event.preventDefault();
  }, true);
  function resize(force = false) {
    if (!document.getElementById("terminal").clientHeight) return;
    fit.fit();
    const columns = Math.max(20, Math.min(500, terminal.cols));
    const rows = Math.max(5, Math.min(200, terminal.rows));
    if (columns !== terminal.cols || rows !== terminal.rows) terminal.resize(columns, rows);
    const size = `${columns}:${rows}`;
    if (enabled && (force || size !== lastSize)) {
      lastSize = size;
      send({ type: "resize", columns, rows, scope });
    }
  }
  new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 100);
  }).observe(document.getElementById("terminal"));
  window.esaifTerminal = Object.freeze({
    write(data, reset, id) {
      if (typeof data !== "string" || data.length > 524288) return;
      if (reset) {
        terminal.reset();
        terminal.options.disableStdin = !enabled;
        filterState = 0;
      }
      replaying = reset;
      terminal.write(safeOutput(data), () => {
        replaying = false;
        if (reset) resize();
        send({ type: "rendered", id });
      });
    },
    enable(value, inputScope = "") {
      if (typeof inputScope !== "string" || inputScope.length > 128) return;
      const becameEnabled = !enabled || scope !== inputScope;
      scope = inputScope;
      enabled = value === true;
      terminal.options.disableStdin = !enabled;
      if (enabled && becameEnabled) { resize(true); terminal.focus(); }
    },
    acknowledgeInput() { outstandingInput = Math.max(0, outstandingInput - 1); },
    selection() { return terminal.getSelection().slice(0, 65536); },
    fit() { resize(true); }
  });
  resize();
  send({ type: "ready" });
})();
