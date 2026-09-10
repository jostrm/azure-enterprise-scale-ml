// Run with the Playwright browser tool after serving Resources\Raw\terminal on 127.0.0.1:18794.
async (page) => {
  const test = await page.context().newPage();
  const errors = [];
  const requests = [];
  test.on("pageerror", error => errors.push(error.message));
  test.on("request", request => requests.push(request.url()));
  try {
    await test.setViewportSize({ width: 1100, height: 280 });
    await test.addInitScript(() => {
      window.fixtureMessages = [];
      window.chrome.webview = { postMessage: message => window.fixtureMessages.push(message) };
    });
    await test.goto("http://127.0.0.1:18794/index.html?scoutTheme=dark");
    await test.waitForFunction(() => window.fixtureMessages.some(message => message.type === "ready"));
    await test.evaluate(() => window.esaifTerminal.write("\x1b[31mANSI RED\x1b[0m\r\nPrompt> ", true, 1));
    await test.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("Prompt>"));
    const output = await test.locator(".xterm-rows").innerText();
    if (!output.includes("ANSI RED")) throw new Error("ANSI text missing");
    if (!await test.locator(".xterm-fg-1").count()) throw new Error("ANSI color not rendered");
    await test.evaluate(() => window.esaifTerminal.enable(true, "fixture-scope"));
    await test.keyboard.type("yes");
    await test.keyboard.press("Enter");
    const inputs = await test.evaluate(() =>
      window.fixtureMessages.filter(message => message.type === "input").map(message => message.data).join(""));
    if (inputs !== "yes\r") throw new Error("Keyboard bridge mismatch");
    if (await test.evaluate(() => window.fixtureMessages.some(message =>
      message.type === "input" && message.scope !== "fixture-scope"))) throw new Error("Input scope missing");
    await test.evaluate(() => window.esaifTerminal.write(
      '\r\n\x1b]52;c;c2VjcmV0\x07\x1bPignored\x1b\\<img src="https://evil.invalid" onerror="window.injected=true">\r\nSafe output',
      false, 2));
    await test.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("Safe output"));
    const safe = await test.locator(".xterm-rows").innerText();
    if (!safe.includes("<img src=") || safe.includes("ignored") || await test.evaluate(() => !!window.injected))
      throw new Error("Output isolation failed");
    await test.setViewportSize({ width: 700, height: 320 });
    await test.waitForFunction(() => {
      const sizes = window.fixtureMessages.filter(message => message.type === "resize");
      return sizes.length > 1 && sizes[0].columns !== sizes[sizes.length - 1].columns;
    });
    const sizes = await test.evaluate(() =>
      window.fixtureMessages.filter(message => message.type === "resize").map(message => [message.columns, message.rows]));
    if (sizes.length < 2 || sizes[0][0] === sizes[sizes.length - 1][0]) throw new Error("Fit resize bridge missing");
    const box = await test.locator(".xterm-screen").boundingBox();
    await test.mouse.move(box.x + 1, box.y + 8);
    await test.mouse.down();
    await test.mouse.move(box.x + 65, box.y + 8, { steps: 8 });
    await test.mouse.up();
    const selection = await test.evaluate(() => window.esaifTerminal.selection());
    if (!selection.includes("ANSI")) throw new Error("Mouse selection failed");
    await test.evaluate(() => window.esaifTerminal.enable(false));
    await test.keyboard.type("not-sent");
    if (await test.evaluate(() => window.fixtureMessages.filter(message => message.type === "input").length) !== 4)
      throw new Error("Disabled input escaped to the bridge");
    await test.evaluate(() => window.esaifTerminal.write(
      Array.from({ length: 2200 }, (_, index) => `line ${index}\r\n`).join(""), true, 3));
    await test.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("line 2199"));
    await test.waitForTimeout(300);
    const beforeScroll = await test.locator(".xterm-rows").innerText();
    await test.locator(".xterm-screen").hover();
    await test.mouse.wheel(0, -160);
    await test.waitForFunction(before => document.querySelector(".xterm-rows").innerText !== before, beforeScroll);
    await test.evaluate(() => {
      window.esaifTerminal.enable(true, "fixture-scope");
      window.esaifTerminal.write("\x1b[c", false, 4);
    });
    await test.waitForFunction(() => window.fixtureMessages.some(message =>
      message.type === "input" && message.data.startsWith("\x1b[") && message.data.endsWith("c")));
    const inputCount = await test.evaluate(() => window.fixtureMessages.filter(message => message.type === "input").length);
    await test.evaluate(() => window.esaifTerminal.write("\x1b[c", true, 5));
    await test.waitForFunction(() => window.fixtureMessages.some(message => message.type === "rendered" && message.id === 5));
    if (await test.evaluate(() => window.fixtureMessages.filter(message => message.type === "input").length) !== inputCount)
      throw new Error("Historical device queries were replayed to the PTY");
    await test.evaluate(() => window.esaifTerminal.write("\x1b[1t\x1b[c\x1b[?1004h\x1b[?9001h", false, 6));
    await test.waitForFunction(() => window.fixtureMessages.filter(message =>
      message.type === "input" && message.data === "\x1b[?1;2c").length === 2);
    if (errors.length) throw new Error(errors.join("; "));
    if (requests.some(url => !url.startsWith("http://127.0.0.1:18794/"))) throw new Error("Non-local request");
    return { passed: ["local assets", "ANSI + prompt", "keyboard bridge", "OSC52/DCS suppression",
      "output isolation", "resize", "selection", "input disabled", "readonly scrollback after reset",
      "live device attributes response", "historical device query suppression",
      "production ConPTY handshake after reset without re-enabling"],
      sizes, selection, localRequests: requests.length };
  } finally {
    await test.close();
  }
}
