/* Presentation only. The original page retains authentication, permissions, requests and confirmations. */
(() => {
  "use strict";

  const query = new URLSearchParams(location.search);
  const embedded = query.get("host") === "esaif-maui";
  const browser = !query.has("host") && query.get("layout") !== "legacy";
  const loopback = location.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if (window.top !== window || (location.protocol !== "https:" && !(browser && loopback))
      || location.pathname !== "/" || (!embedded && !browser)) return;
  const bridge = embedded ? window.chrome?.webview : null;
  if (embedded && (typeof bridge?.addEventListener !== "function" || typeof bridge?.postMessage !== "function")) return;
  const root = document.documentElement;
  if (root.hasAttribute("data-esaif-layout-state")) return;
  root.setAttribute("data-esaif-layout-state", "loading");

  let hostState, renderHost;
  bridge?.addEventListener("message", event => {
    const data = event?.data;
    if (!data || data.type !== "esaif.agentChat.hostState" || data.version !== 1) return;
    hostState = {
      status: typeof data.status === "string" ? data.status.slice(0, 1000) : "",
      account: typeof data.account === "string" ? data.account.slice(0, 256) : "",
      canSignIn: data.canSignIn === true,
      canRetry: data.canRetry === true,
      canOpenInBrowser: data.canOpenInBrowser === true
    };
    renderHost?.();
  });

  const labels = [
    "appTitle", "brand", "navigation", "workspace", "skip", "newConversation", "newHelp", "newDone", "newBusy", "plus",
    "audio", "voiceEyebrow", "voiceIntro", "voiceUnavailable", "connection", "vpnStatus", "hostWaiting", "hostLogin", "hostRetry",
    "hostOpenVoice", "hostUnavailable", "theme", "gray", "purple", "appearance", "light",
    "dark", "subtitle", "welcomeEyebrow", "welcome", "welcomeIntro", "welcomeSymbol", "currentQuestion",
    "latestAnswer", "conversation", "evidenceEyebrow", "evidence", "evidenceIntro", "tools", "toolsEmpty",
    "transcript", "transcriptHelp", "transcriptEmpty", "actions", "actionsIntro", "actionsClose",
    "actionsUpdated", "skills", "plans", "history", "scopeDetails", "view", "coreTeam", "projectTeam",
    "viewHelp", "more", "fallback", "composerHint", "send", "evidenceEmpty", "evidenceReady", "knowledge",
    "blueYellow", "bannerHint", "thinking", "voiceThinkingState", "messageActions", "thumbUp", "thumbDown", "copyMessage",
    "deleteMessage", "feedbackLocal", "messageCopied", "copyFailed", "deleteTitle", "deleteHelp",
    "deleteConfirm", "deleteCancel", "messageDeleted", "messageChanged"
  ];

  function preflight() {
    const contract = {
      "auth-status": "SPAN", "sign-in": "BUTTON", "sign-out": "BUTTON", "color-theme": "SELECT",
      "scope-selector": "SELECT", "scope-details": "DL", "view-platform": "BUTTON", "view-project": "BUTTON",
      "view-help": "P", "knowledge-status": "P", "refresh-status": "BUTTON", "voice-card": "SECTION",
      "voice-heading": "H2", "voice-toggle": "BUTTON", "voice-mute": "BUTTON", "voice-interrupt": "BUTTON",
      "voice-use-text": "BUTTON", "voice-retry": "BUTTON", "voice-orb": "CANVAS", "voice-state": "P",
      "voice-language": "SELECT", "voice-transcript": "DIV", "voice-error": "P",
      "question-form": "FORM", "question": "TEXTAREA", "ask": "BUTTON", "question-count": "SPAN",
      "request-status": "P", "question-examples": "DIV", "question-heading": "H2",
      "question-examples-help": "P", "answer": "DIV", "answer-context": "P", "answer-heading": "H2",
      "citations": "OL", "tool-activity": "DIV", "skill-form": "FORM", "action-tiles": "DIV",
      "skill-selector": "SELECT", "skill-arguments": "DIV", "run-skill": "BUTTON", "skill-result": "DIV",
      "skill-status": "P", "discover-templates": "BUTTON", "template-result": "DIV",
      "proposal-form": "FORM", "proposed-plans": "DIV", "proposal-status": "P", "operation-history": "DIV",
      "confirmation-dialog": "DIALOG", "setup-blocker": "SECTION", "error-message": "P"
    };
    const allIds = [...document.querySelectorAll("[id]")].map(node => node.id);
    const loader = document.getElementById("esaif-maui-layout-script");
    const nativeLoader = loader?.tagName === "SCRIPT" && loader.src === location.origin + "/static/esaif-maui-layout.js";
    if (new Set(allIds).size !== allIds.length
        || allIds.some(id => id.startsWith("esaif-") && !(nativeLoader && id === loader.id))) return null;
    const nodes = {};
    for (const [id, tag] of Object.entries(contract)) {
      const node = document.getElementById(id);
      if (!node || node.tagName !== tag) return null;
      nodes[id] = node;
    }
    const header = document.querySelector("body > header.topbar");
    const main = document.querySelector("body > main");
    const footer = document.querySelector("body > footer");
    const auth = nodes["auth-status"].closest(".auth-controls");
    const palette = nodes["color-theme"].closest(".theme-control");
    const scope = nodes["scope-selector"].closest("aside");
    const views = nodes["view-platform"].parentElement;
    const question = nodes["question-form"].closest("section");
    const answer = nodes.answer.closest("section");
    const skills = nodes["skill-form"].closest("section");
    const plans = nodes["proposal-form"].closest("section");
    const history = nodes["operation-history"].closest("section");
    const knowledge = nodes["knowledge-status"].closest("section");
    const sections = [question, answer, skills, plans, history, nodes["voice-card"]];
    if (!header || !main || !footer || !auth || !palette || !scope || !knowledge
        || !header.contains(auth) || !auth.contains(palette) || !scope.contains(knowledge)
        || [...header.querySelectorAll("button,input,select,textarea,a,details,[role=alert],[role=status]")].some(node => !auth.contains(node))
        || nodes["confirmation-dialog"].parentElement !== document.body
        || new Set(sections).size !== sections.length || sections.some(node => !node || !main.contains(node))
        || !views.contains(nodes["view-project"]) || !scope.contains(views)
        || !palette.querySelector('label[for="color-theme"]') || !scope.querySelector('label[for="scope-selector"]')
        || !nodes["question-form"].contains(nodes.question) || !nodes["question-form"].contains(nodes.ask)
        || !question.contains(nodes["question-examples"]) || !question.contains(nodes["question-heading"])
        || !answer.contains(nodes["answer-heading"]) || !answer.contains(nodes["answer-context"])
        || !answer.contains(nodes.citations) || !answer.contains(nodes["tool-activity"])
        || !["gray-blue", "purple"].every(value => [...nodes["color-theme"].options].some(option => option.value === value))
        || !["view-platform", "view-project"].every(id => ["true", "false"].includes(nodes[id].getAttribute("aria-pressed")))) return null;
    return { nodes, header, main, footer, auth, palette, scope, views, question, answer, skills, plans, history, knowledge };
  }

  function stylesheet() {
    return new Promise((resolve, reject) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/static/esaif-maui-layout.css";
      const timer = setTimeout(() => { link.remove(); reject(); }, 8000);
      link.onload = () => { clearTimeout(timer); resolve(); };
      link.onerror = () => { clearTimeout(timer); link.remove(); reject(); };
      document.head.append(link);
    });
  }

  function mount(layout, text) {
    const { nodes: n, header, main, footer, auth, palette, scope, views, question, answer, skills, plans, history, knowledge } = layout;
    const make = (tag, key, className, id) => {
      const node = document.createElement(tag);
      if (key) node.textContent = text[key];
      if (className) node.className = className;
      if (id) node.id = id;
      return node;
    };
    const button = (key, id, className = "secondary") => {
      const node = make("button", key, className, id);
      node.type = "button";
      return node;
    };
    const details = (key, className, id) => {
      const node = make("details", null, className, id);
      node.append(make("summary", key));
      return node;
    };
    const picker = (key, id, options) => {
      const wrapper = make("div", null, "esaif-picker");
      const label = make("label", key);
      label.htmlFor = id;
      const select = make("select", null, null, id);
      for (const [value, key] of options) {
        const option = make("option", key);
        option.value = value;
        select.append(option);
      }
      wrapper.append(label, select);
      return { wrapper, select };
    };
    const shell = make("div", null, "esaif-chat-shell");
    const banner = make("div", null, "esaif-brand-banner", "esaif-brand-banner");
    banner.append(make("strong", "appTitle"), make("span", "bannerHint"));
    const skip = make("a", "skip", "esaif-skip");
    skip.href = "#question";
    const left = make("aside", null, "esaif-sidebar");
    left.setAttribute("aria-label", text.workspace);
    const brand = make("div", null, "esaif-brand");
    const mark = make(embedded ? "button" : "span", null, "esaif-brand-mark");
    if (embedded) {
      mark.type = "button";
      mark.id = "esaif-host-menu";
      mark.textContent = "\u2630";
      mark.setAttribute("aria-label", text.navigation);
      mark.title = text.navigation;
      mark.addEventListener("click", event => {
        if (!event.isTrusted) return;
        try { bridge.postMessage({ type: "esaif.agentChat.hostAction", version: 1, action: "menu" }); }
        catch { hostStatus.textContent = text.hostUnavailable; }
      });
    } else {
      for (let index = 0; index < 4; index++) mark.append(make("i"));
      mark.setAttribute("aria-hidden", "true");
    }
    brand.append(mark, make("span", "brand"));
    const newChat = button("newConversation", "esaif-new-conversation", "secondary esaif-new-conversation");
    const plus = make("span", "plus");
    plus.setAttribute("aria-hidden", "true");
    newChat.prepend(plus);
    newChat.title = text.newHelp;
    const unavailable = make("section", null, "esaif-voice-unavailable", "esaif-voice-unavailable");
    const disc = make("div", null, "esaif-voice-disc");
    disc.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 7; index++) disc.append(make("i"));
    const blueYellowDisc = disc.cloneNode(true);
    blueYellowDisc.classList.add("esaif-blue-yellow-voice-disc");
    unavailable.append(make("p", "voiceEyebrow", "esaif-eyebrow"), make("h2", "audio"),
      make("p", "voiceIntro", "muted"), disc, make("p", "voiceUnavailable", "muted"));
    const sidebarBottom = make("div", null, "esaif-sidebar-bottom");
    const connection = details("connection", "esaif-connection", "esaif-connection");
    const hostStatus = make("p", "hostWaiting", "muted", "esaif-host-status");
    hostStatus.setAttribute("role", "status");
    const hostAccount = make("p", null, "muted", "esaif-host-account");
    const hostButtons = make("div", null, "esaif-host-buttons");
    const browserLaunch = make("div", null, "esaif-browser-launch");
    const hostActions = embedded ? [
      ["login", "hostLogin", "canSignIn"], ["retry", "hostRetry", "canRetry"],
      ["openVoice", "hostOpenVoice", "canOpenInBrowser"]
    ] : [];
    const hostControls = new Map();
    for (const [action, key, permission] of hostActions) {
      const control = button(key, "esaif-host-" + action);
      control.disabled = true;
      control.addEventListener("click", event => {
        if (!event.isTrusted || control.disabled || !hostState?.[permission]) return;
        try { bridge.postMessage({ type: "esaif.agentChat.hostAction", version: 1, action }); }
        catch { hostStatus.textContent = text.hostUnavailable; }
      });
      hostControls.set(action, control);
      (action === "openVoice" ? browserLaunch : hostButtons).append(control);
    }
    renderHost = () => {
      hostStatus.textContent = hostState?.status || text.hostWaiting;
      hostAccount.textContent = hostState?.account || "";
      hostAccount.hidden = !hostAccount.textContent;
      for (const [action, , permission] of hostActions) {
        hostControls.get(action).disabled = !hostState?.[permission];
      }
    };
    hostStatus.hidden = !embedded;
    hostButtons.hidden = !embedded;
    connection.append(hostStatus, hostAccount, make("p", "vpnStatus", "muted"), hostButtons);
    const appearance = picker("appearance", "esaif-appearance", [["light", "light"], ["dark", "dark"]]);
    appearance.select.value = root.getAttribute("data-theme") === "dark" ? "dark" : "light";
    appearance.select.addEventListener("change", () => root.setAttribute("data-theme", appearance.select.value));
    const topbar = make("header", null, "esaif-topbar");
    topbar.append(make("h1", "conversation"), make("p", "subtitle", "muted"));
    const scroll = make("div", null, "esaif-conversation-scroll");
    scroll.setAttribute("aria-label", text.conversation);
    const symbol = make("span", "welcomeSymbol", "esaif-welcome-symbol");
    symbol.setAttribute("aria-hidden", "true");
    const currentQuestion = make("section", null, "esaif-user-message", "esaif-current-question");
    currentQuestion.hidden = true;
    currentQuestion.append(make("h2", "currentQuestion"), make("p", null, null, "esaif-current-question-text"));
    const composer = make("div", null, "esaif-composer-area");
    const status = make("p", null, "esaif-layout-status", "esaif-layout-status");
    status.setAttribute("role", "status");
    const thinking = make("div", null, "esaif-thinking", "esaif-thinking");
    thinking.hidden = true;
    thinking.setAttribute("role", "progressbar");
    thinking.setAttribute("aria-label", text.thinking);
    thinking.append(make("span", null, "esaif-thinking-sweep"));
    const right = make("aside", null, "esaif-evidence");
    right.setAttribute("aria-labelledby", "esaif-evidence-heading");
    const evidenceScroll = make("div", null, "esaif-evidence-scroll");
    const evidenceHeading = make("header", null, "esaif-evidence-heading");
    evidenceHeading.append(make("p", "evidenceEyebrow", "esaif-eyebrow"), make("h2", "evidence", null, "esaif-evidence-heading"), make("p", "evidenceIntro", "muted"));
    const sources = details(null, "esaif-sources");
    sources.firstChild.textContent = answer.querySelector("h3")?.textContent || text.evidence;
    sources.open = true;
    const evidenceStatus = make("div", null, "esaif-evidence-status");
    const evidenceIcon = make("span", null, "esaif-evidence-icon");
    evidenceIcon.textContent = "\u2261";
    evidenceIcon.setAttribute("aria-hidden", "true");
    const evidenceLabel = make("strong", "evidenceEmpty");
    const evidenceCopy = make("div");
    evidenceCopy.append(evidenceLabel);
    evidenceStatus.append(evidenceIcon, evidenceCopy);
    const knowledgeDisclosure = details("knowledge", "esaif-knowledge");
    const tools = make("section", null, "esaif-tools");
    const toolsEmpty = make("p", "toolsEmpty", "muted");
    tools.append(make("h3", "tools"), toolsEmpty);
    const transcript = details("transcript", "esaif-transcript");
    const transcriptBody = make("div");
    const transcriptEmpty = make("p", "transcriptEmpty", "muted");
    transcriptBody.append(make("p", "transcriptHelp", "muted"), transcriptEmpty);
    transcript.append(transcriptBody);
    const transcriptUnavailable = make("p", "voiceUnavailable", "muted");
    transcript.append(transcriptUnavailable);
    const bottomRight = make("div", null, "esaif-workspace-bottom");
    const actions = details("actions", "esaif-actions", "esaif-actions");
    const updated = make("span", "actionsUpdated", "esaif-updated");
    updated.hidden = true;
    updated.setAttribute("role", "status");
    actions.firstChild.append(updated);
    const drawer = make("div", null, "esaif-action-drawer");
    const close = button("actionsClose", "esaif-actions-close");
    drawer.append(close, make("p", "actionsIntro", "muted"));
    const actionSections = [[skills, "skills"], [plans, "plans"], [history, "history"]].map(([section, key]) => {
      const disclosure = details(key, "esaif-action-section");
      drawer.append(disclosure);
      return { section, disclosure };
    });
    actions.append(drawer);
    close.addEventListener("click", () => { actions.open = false; actions.firstChild.focus(); });
    actions.addEventListener("toggle", () => { if (actions.open) updated.hidden = true; });
    actions.addEventListener("keydown", event => {
      if (event.key === "Escape" && !n["confirmation-dialog"].open) {
        actions.open = false;
        actions.firstChild.focus();
        event.preventDefault();
      }
    });
    const scopeDetails = details("scopeDetails", "esaif-scope-details");
    const view = picker("view", "esaif-view", [["platform", "coreTeam"], ["project", "projectTeam"]]);
    view.select.setAttribute("aria-describedby", "view-help");
    view.select.title = text.viewHelp;
    const nativeViews = make("div");
    nativeViews.hidden = true;

    // Keep actual nodes, not serialized HTML, for rollback: this preserves listeners and partially completed forms.
    const original = [document.body, ...document.body.querySelectorAll("*")].map(node => ({
      node, children: [...node.childNodes], attributes: [...node.attributes].map(attribute => [attribute.name, attribute.value])
    }));
    const previousTitle = document.title;
    const move = (node, parent, before = null) => {
      parent.insertBefore(node, before);
    };
    const attr = (node, name, value) => {
      node.setAttribute(name, value);
    };
    const content = (node, value) => {
      node.textContent = value;
    };
    try {
      document.body.insertBefore(shell, header);
      shell.after(banner);
      shell.before(skip);
      shell.append(left, right);
      move(main, shell, right);
      attr(main, "class", (main.className + " esaif-main").trim());
      main.prepend(topbar);
      move(n["setup-blocker"], main);
      move(n["error-message"], main);
      main.append(scroll, composer);
      left.append(brand, newChat, unavailable);
      move(n["voice-card"], left);
      left.append(sidebarBottom);
      sidebarBottom.append(connection);
      move(auth, connection);
      move(n["auth-status"], sidebarBottom);
      move(palette, sidebarBottom);
      sidebarBottom.append(appearance.wrapper);
      attr(palette, "class", "theme-control esaif-picker");
      content(palette.querySelector("label"), text.theme);
      for (const option of n["color-theme"].options) {
        if (option.value === "gray-blue") content(option, text.gray);
        if (option.value === "purple") content(option, text.purple);
      }
      const blueYellowOption = make("option", "blueYellow");
      blueYellowOption.value = "blue-yellow";
      n["color-theme"].append(blueYellowOption);
      content(n["voice-heading"], text.audio);
      n["voice-card"].prepend(make("p", "voiceEyebrow", "esaif-eyebrow"));
      n["voice-heading"].after(make("p", "voiceIntro", "muted"));
      n["voice-orb"].before(blueYellowDisc);
      const voiceMore = n["voice-card"].querySelector("details");
      if (voiceMore) {
        const voiceLanguageLabel = n["voice-card"].querySelector('label[for="voice-language"]');
        if (voiceLanguageLabel) move(voiceLanguageLabel, voiceMore);
        move(n["voice-language"], voiceMore);
        if (n["voice-card"].querySelector("#voice-help")) move(n["voice-card"].querySelector("#voice-help"), voiceMore);
        move(voiceMore, n["voice-card"]);
      }
      move(question, scroll);
      attr(question, "class", "esaif-welcome");
      question.prepend(symbol, make("p", "welcomeEyebrow", "esaif-eyebrow"));
      content(n["question-heading"], text.welcome);
      n["question-heading"].after(make("p", "welcomeIntro", "esaif-intro"));
      move(n["question-examples-help"], question);
      move(n["question-form"], composer);
      n["question-form"].before(make("p", "transcriptHelp", "esaif-speech-disclaimer"));
      content(n.ask, text.send);
      n["question-form"].after(make("p", "composerHint", "esaif-composer-hint"));
      move(n["request-status"], composer);
      composer.append(status);
      attr(n.question, "rows", "2");
      scroll.append(currentQuestion);
      scroll.append(thinking);
      move(answer, scroll);
      attr(answer, "class", "esaif-assistant-message");
      content(n["answer-heading"], text.latestAnswer);
      if (embedded) right.append(browserLaunch);
      right.append(evidenceScroll, bottomRight);
      evidenceScroll.append(evidenceHeading, evidenceStatus);
      move(n["answer-context"], evidenceCopy);
      evidenceScroll.append(sources);
      for (const node of [...answer.children]) {
        if (node !== n.answer && node !== n["answer-heading"] && node !== n["tool-activity"]) move(node, sources);
      }
      sources.querySelector("h3")?.classList.add("esaif-sr-only");
      evidenceScroll.append(tools);
      move(n["tool-activity"], tools);
      evidenceScroll.append(transcript);
      move(n["voice-transcript"], transcriptBody);
      evidenceScroll.append(knowledgeDisclosure);
      move(knowledge, knowledgeDisclosure);
      move(footer, evidenceScroll);
      bottomRight.append(actions);
      for (const { section, disclosure } of actionSections) move(section, disclosure);
      move(scope.querySelector('label[for="scope-selector"]'), bottomRight);
      move(n["scope-selector"], bottomRight);
      bottomRight.append(scopeDetails);
      move(scope, scopeDetails);
      attr(scope, "class", "esaif-scope-content");
      bottomRight.append(view.wrapper);
      view.wrapper.append(nativeViews);
      move(views, nativeViews);
      move(n["view-help"], scope);
      attr(header, "hidden", "");
      // Unknown remaining workspace content stays reachable rather than being silently dropped.
      const workspace = main.querySelector(".workspace");
      if (workspace) {
        if (workspace.textContent.trim() || [...workspace.querySelectorAll("*")].some(node => !node.matches(".content") || node.children.length)) {
          const extra = details("more", "esaif-extra");
          drawer.append(extra);
          move(workspace, extra);
        } else attr(workspace, "hidden", "");
      }
      document.title = text.appTitle;
      root.classList.add("esaif-chat");
    } catch (error) {
      for (const { node, children, attributes } of original) {
        node.replaceChildren(...children);
        for (const attribute of [...node.attributes]) node.removeAttribute(attribute.name);
        for (const [name, value] of attributes) node.setAttribute(name, value);
      }
      document.title = previousTitle;
      shell.remove();
      skip.remove();
      root.classList.remove("esaif-chat");
      renderHost = null;
      throw error;
    }

    const observe = (node, callback, options) => {
      const observer = new MutationObserver(callback);
      observer.observe(node, options);
      return observer;
    };
    let blueYellowTheme = query.get("companionTheme") === "blue-yellow", changingPalette = false;
    const saveCompanionTheme = () => {
      const url = new URL(location.href);
      if (blueYellowTheme) url.searchParams.set("companionTheme", "blue-yellow");
      else url.searchParams.delete("companionTheme");
      window.history.replaceState(null, "", url.href);
    };
    const applyCompanionTheme = () => {
      if (blueYellowTheme) {
        root.setAttribute("data-companion-theme", "blue-yellow");
        n["color-theme"].value = "blue-yellow";
      } else {
        root.removeAttribute("data-companion-theme");
      }
    };
    n["color-theme"].addEventListener("change", event => {
      if (changingPalette) return;
      blueYellowTheme = n["color-theme"].value === "blue-yellow";
      if (blueYellowTheme) {
        // Keep the backend palette protocol unchanged; Blue / Yellow is presentation-only.
        event.stopImmediatePropagation();
        changingPalette = true;
        try {
          n["color-theme"].value = "gray-blue";
          n["color-theme"].dispatchEvent(new Event("change", { bubbles: true }));
        } finally { changingPalette = false; }
      }
      applyCompanionTheme();
      saveCompanionTheme();
    }, true);
    observe(root, () => {
      if (blueYellowTheme && root.getAttribute("data-palette") !== "gray-blue") {
        blueYellowTheme = false;
        saveCompanionTheme();
      }
      applyCompanionTheme();
    }, { attributes: true, attributeFilter: ["data-palette"] });
    if (blueYellowTheme || query.get("companionTheme") === "purple-accent") {
      n["color-theme"].value = blueYellowTheme ? "blue-yellow" : "purple";
      n["color-theme"].dispatchEvent(new Event("change", { bubbles: true }));
    }

    const iconPaths = {
      up: ["M7 10v11H3V10z", "M7 10l5-8h2v6h6l1 2-3 11H7"],
      down: ["M7 14V3H3v11z", "M7 14l5 8h2v-6h6l1-2-3-11H7"],
      copy: ["M8 3h12v15H8z", "M5 6H3v15h12v-2"],
      delete: ["M4 6h16M9 6V3h6v3", "M6 6l1 15h10l1-15M10 10v7M14 10v7"]
    };
    const deletion = make("dialog", null, "confirmation-dialog esaif-delete-dialog", "esaif-delete-dialog");
    deletion.setAttribute("aria-labelledby", "esaif-delete-title");
    deletion.setAttribute("aria-describedby", "esaif-delete-help");
    const cancelDelete = button("deleteCancel", "esaif-delete-cancel");
    const confirmDelete = button("deleteConfirm", "esaif-delete-confirm");
    deletion.append(make("h2", "deleteTitle", null, "esaif-delete-title"),
      make("p", "deleteHelp", null, "esaif-delete-help"), cancelDelete, confirmDelete);
    document.body.append(deletion);
    let deleteTarget = null;
    cancelDelete.addEventListener("click", () => deletion.close());
    deletion.addEventListener("close", () => { deleteTarget = null; });
    const messageTools = (role, section, body) => {
      const toolbar = make("div", null, "esaif-message-actions");
      toolbar.dataset.messageRole = role;
      toolbar.setAttribute("role", "group");
      toolbar.setAttribute("aria-label", text.messageActions);
      const tools = new Map();
      let revision = 0;
      const reset = () => {
        revision++;
        for (const name of ["up", "down"]) tools.get(name).setAttribute("aria-pressed", "false");
      };
      for (const [action, label] of [["up", "thumbUp"], ["down", "thumbDown"], ["copy", "copyMessage"], ["delete", "deleteMessage"]]) {
        const control = button(null, null, "esaif-message-action");
        control.dataset.messageAction = action;
        control.setAttribute("aria-label", text[label]);
        control.title = text[label];
        if (action === "up" || action === "down") control.setAttribute("aria-pressed", "false");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        for (const d of iconPaths[action]) {
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute("d", d); svg.append(path);
        }
        control.append(svg);
        control.addEventListener("click", async () => {
          if (action === "up" || action === "down") {
            const pressed = control.getAttribute("aria-pressed") !== "true";
            for (const name of ["up", "down"]) tools.get(name).setAttribute("aria-pressed", String(name === action && pressed));
            status.textContent = text.feedbackLocal;
          } else if (action === "copy") {
            try {
              await navigator.clipboard.writeText(body.innerText || body.textContent);
              status.textContent = text.messageCopied;
            } catch { status.textContent = text.copyFailed; }
          } else {
            deleteTarget = { role, section, body, revision, currentRevision: () => revision, text: body.textContent };
            deletion.showModal(); cancelDelete.focus();
          }
        });
        tools.set(action, control);
        toolbar.append(control);
      }
      section.append(toolbar);
      observe(body, reset, { childList: true, subtree: true, characterData: true });
      return reset;
    };
    const resetUserFeedback = messageTools("user", currentQuestion, currentQuestion.querySelector("p"));
    messageTools("assistant", answer, n.answer);
    confirmDelete.addEventListener("click", () => {
      const target = deleteTarget;
      if (!target || target.revision !== target.currentRevision() || target.text !== target.body.textContent) {
        status.textContent = text.messageChanged;
        deletion.close();
        return;
      }
      target.body.replaceChildren();
      target.section.hidden = true;
      if (target.role === "assistant") {
        n.citations.replaceChildren();
        n["answer-context"].textContent = "";
        n["tool-activity"].replaceChildren();
      }
      status.textContent = text.messageDeleted;
      deletion.close();
    });

    let textPending = false;
    const renderThinking = () => {
      const voicePending = !n["voice-card"].hidden && n["voice-state"].textContent.trim() === text.voiceThinkingState;
      thinking.hidden = !textPending && !voicePending;
      scroll.setAttribute("aria-busy", String(!thinking.hidden));
    };
    observe(n.question, () => {
      if (!n.question.disabled) textPending = false;
      renderThinking();
    }, { attributes: true, attributeFilter: ["disabled"] });
    observe(n["voice-state"], renderThinking, { childList: true, subtree: true, characterData: true });
    observe(n["voice-card"], renderThinking, { attributes: true, attributeFilter: ["hidden"] });
    observe(n["error-message"], () => {
      if (!n["error-message"].hidden && n["error-message"].textContent.trim()) textPending = false;
      renderThinking();
    }, { attributes: true, attributeFilter: ["hidden"], childList: true, subtree: true, characterData: true });
    const syncView = () => {
      const selected = n["view-platform"].getAttribute("aria-pressed") === "true" ? "platform"
        : n["view-project"].getAttribute("aria-pressed") === "true" ? "project" : "";
      view.select.value = selected;
      for (const option of view.select.options) option.disabled = n["view-" + option.value].disabled;
      view.select.disabled = [...view.select.options].every(option => option.disabled);
    };
    view.select.addEventListener("change", () => {
      const native = n["view-" + view.select.value];
      if (native && !native.disabled) native.click();
      syncView();
    });
    for (const id of ["view-platform", "view-project"]) {
      observe(n[id], syncView, { attributes: true, attributeFilter: ["aria-pressed", "disabled"] });
    }
    observe(root, () => {
      appearance.select.value = root.getAttribute("data-theme") === "dark" ? "dark" : "light";
    }, { attributes: true, attributeFilter: ["data-theme"] });
    const syncVoice = () => {
      const hasTranscript = Boolean(n["voice-transcript"].textContent.trim());
      unavailable.hidden = !n["voice-card"].hidden;
      // Capability gates the microphone controls, not an already-rendered transcript in the evidence panel.
      transcriptBody.hidden = n["voice-card"].hidden && !hasTranscript;
      transcriptUnavailable.hidden = !n["voice-card"].hidden;
      transcriptEmpty.hidden = hasTranscript;
    };
    observe(n["voice-card"], syncVoice, { attributes: true, attributeFilter: ["hidden"] });
    observe(n["voice-transcript"], syncVoice, { childList: true, subtree: true, characterData: true });
    const syncTools = () => { toolsEmpty.hidden = Boolean(n["tool-activity"].textContent.trim()); };
    observe(n["tool-activity"], syncTools, { childList: true, subtree: true, characterData: true });
    answer.hidden = !n["answer-context"].textContent.trim() && !n.citations.children.length;
    const syncEvidence = () => {
      const hasAnswer = Boolean(n["answer-context"].textContent.trim() || n.citations.children.length);
      evidenceLabel.textContent = hasAnswer ? text.evidenceReady : text.evidenceEmpty;
      sources.hidden = !hasAnswer;
    };
    observe(n["answer-context"], syncEvidence, { childList: true, subtree: true, characterData: true });
    observe(n.citations, syncEvidence, { childList: true, subtree: true, characterData: true });
    n.question.addEventListener("keydown", event => {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      if (!n.question.disabled && !n.ask.disabled && n.question.value.trim()) n["question-form"].requestSubmit();
    });
    observe(n.answer, () => {
      textPending = false;
      renderThinking();
      answer.hidden = !n.answer.textContent.trim() && !n.answer.children.length;
      if (!answer.hidden) question.hidden = true;
    }, { childList: true, subtree: true, characterData: true });
    for (const { section, disclosure } of actionSections) {
      const signature = () => JSON.stringify([...section.querySelectorAll(
        '[role="status"],[role="alert"],[aria-live],#template-result,#proposed-plans,#operation-history'
      )].map(node => [node.id, node.hidden, node.textContent]));
      let previous = signature();
      observe(section, () => {
        const current = signature();
        if (previous === current) return;
        previous = current;
        if (!actions.open) updated.hidden = false;
        if ([...section.querySelectorAll('[role="alert"]')].some(node => !node.hidden && node.textContent.trim())) {
          actions.open = true;
          disclosure.open = true;
        }
      }, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden"] });
    }

    // app.js disables the question and updates request-status synchronously only after accepting a stateless /api/chat request.
    // Observe that transition after dispatch; never wrap fetch, read the session/token API or submit on the user's behalf.
    n["question-form"].addEventListener("submit", event => {
      const eligible = !n.question.disabled && !n.ask.disabled && n.question.value.trim()
        && n.question.value.length <= n.question.maxLength;
      const submitted = n.question.value, previousStatus = n["request-status"].textContent;
      queueMicrotask(() => {
        if (!eligible || !event.defaultPrevented || !n.question.disabled || n["request-status"].textContent === previousStatus) return;
        document.getElementById("esaif-current-question-text").textContent = submitted;
        currentQuestion.hidden = false;
        resetUserFeedback();
        question.hidden = true;
        status.textContent = "";
        textPending = true;
        renderThinking();
        thinking.scrollIntoView({ block: "nearest" });
      });
    }, true);
    newChat.addEventListener("click", () => {
      if (n.question.disabled || n["confirmation-dialog"].open || deletion.open) {
        status.textContent = text.newBusy;
        return;
      }
      // The deployed typed API has no conversation/reset endpoint. Stop the real voice session first,
      // then clear only the draft and adapter prompt. Completed evidence and all action forms remain authoritative.
      n["voice-use-text"].click();
      n.question.value = "";
      n.question.dispatchEvent(new Event("input", { bubbles: true }));
      document.getElementById("esaif-current-question-text").textContent = "";
      currentQuestion.hidden = true;
      textPending = false;
      renderThinking();
      question.hidden = false;
      status.textContent = text.newDone;
      n.question.focus();
    });
    n["scope-selector"].addEventListener("change", () => {
      currentQuestion.hidden = true;
      textPending = false;
      renderThinking();
      document.getElementById("esaif-current-question-text").textContent = "";
    });
    let lastAuthStatus = n["auth-status"].textContent;
    observe(n["auth-status"], () => {
      if (lastAuthStatus === n["auth-status"].textContent) return;
      lastAuthStatus = n["auth-status"].textContent;
      currentQuestion.hidden = true;
      document.getElementById("esaif-current-question-text").textContent = "";
    }, { childList: true, subtree: true, characterData: true });
    syncView();
    syncVoice();
    syncTools();
    syncEvidence();
    renderHost();
    root.setAttribute("data-esaif-layout-state", "ready");
    try { bridge?.postMessage({ type: "esaif.agentChat.layoutReady", version: 1 }); }
    catch { hostStatus.textContent = text.hostUnavailable; }
  }

  async function start() {
    let text;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch("/static/esaif-maui-layout.en.json", {
          credentials: "omit", mode: "same-origin", redirect: "error", cache: "no-store", signal: controller.signal
        });
        if (!response.ok) throw new Error();
        const candidate = await response.json();
        if (!candidate || !labels.every(key => typeof candidate[key] === "string" && candidate[key].length > 0 && candidate[key].length < 4096)) throw new Error();
        text = candidate;
      } finally { clearTimeout(timer); }
      const layout = preflight();
      if (!layout) throw new Error();
      await stylesheet();
      // Recheck after the asynchronous stylesheet load; no original node has been moved yet.
      const current = preflight();
      if (!current) throw new Error();
      mount(current, text);
    } catch {
      root.setAttribute("data-esaif-layout-state", "fallback");
      // If the localization resource itself failed, keep the complete original interface and its localized statuses.
      if (text) {
        const fallback = document.createElement("p");
        fallback.id = "esaif-layout-fallback";
        fallback.className = "notice";
        fallback.setAttribute("role", "status");
        fallback.textContent = text.fallback;
        document.body.prepend(fallback);
      }
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else void start();
})();
