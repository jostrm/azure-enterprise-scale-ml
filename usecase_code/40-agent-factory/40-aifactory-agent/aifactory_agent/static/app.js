(() => {
  "use strict";

  const ui = (id) => document.getElementById(id);
  const STATE_KEY = "aifactory.oauth.state";
  const VERIFIER_KEY = "aifactory.oauth.verifier";
  const callbackParams = new URLSearchParams(location.search);
  const callback = {
    present: callbackParams.has("code") || callbackParams.has("error"),
    code: callbackParams.get("code"),
    error: callbackParams.get("error"),
    state: callbackParams.get("state"),
  };
  if (callback.present) {
    history.replaceState(null, "", location.pathname + location.hash);
  }
  const initialFragment = new URLSearchParams(location.hash.slice(1));
  const state = {
    config: null,
    token: null,
    expiresAt: 0,
    context: null,
    sessionVersion: 0,
    scopeKey: initialFragment.get("scope") || "",
    audience: initialFragment.get("view") === "platform" ? "platform" : "project",
    busy: false,
    proposalBusy: false,
    proposalMessage: "",
    refreshing: false,
    operations: [],
    skills: [],
    skillBusy: false,
  };
  const statusLabels = {
    pending: "Pending review — not approved or executed",
    approved: "Approved — execution not started",
    executing: "Executing — completion not confirmed",
    continuing: "Continuing approved workflow — completion not confirmed",
    running: "Factory job running — completion not confirmed",
    awaiting_continuation: "Factory workflow paused — completion not confirmed",
    succeeded: "Succeeded — backend confirmed completion",
    failed: "Failed — no successful completion confirmed",
    uncertain: "Uncertain — completion unknown; do not retry",
    expired: "Expired — prepare a new plan",
    cancelled: "Cancelled plan — no execution requested",
  };
  const knowledgeLabels = {
    ready: "Knowledge ready — execution dependencies are not verified",
    not_initialized: "Not initialized — an approved operator must initialize and ingest the corpus",
    empty: "Empty corpus — no approved sources are indexed",
    blocked: "Refresh blocked — an approved operator must resolve source or setup blockers",
    failed: "Refresh failed — the latest corpus is not confirmed",
    refresh_incomplete: "Reconciliation incomplete — approved operator action is required",
    index_out_of_sync: "Search differs from manifest — approved operator reconciliation is required",
    reindex_required: "Index changed — an approved operator must reindex before readiness is restored",
  };

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }

  function showError(message) {
    ui("error-message").textContent = message;
    ui("error-message").hidden = !message;
  }

  function activeScope() {
    return state.context?.scopes.find((scope) => scope.key === state.scopeKey);
  }

  function permitted(permission) {
    return Boolean(activeScope()?.permissions.includes(permission));
  }

  function saveSelection() {
    const fragment = new URLSearchParams({view: state.audience});
    if (state.scopeKey) fragment.set("scope", state.scopeKey);
    history.replaceState(null, "", location.pathname + location.search + "#" + fragment);
  }

  function clearSession() {
    state.sessionVersion += 1;
    state.token = null;
    state.expiresAt = 0;
    state.context = null;
    state.operations = [];
    state.skills = [];
    state.skillBusy = false;
    state.busy = false;
    state.proposalBusy = false;
    state.proposalMessage = "";
    ui("scope-selector").replaceChildren(node("option", "Sign in to see authorized scopes"));
    ui("scope-details").replaceChildren();
    ui("answer").textContent = "Session cleared. Sign in to ask a question.";
    ui("answer-context").textContent = "";
    ui("citations").replaceChildren();
    ui("tool-activity").replaceChildren();
    ui("proposed-plans").textContent = "Sign in to inspect your persisted plans.";
    ui("operation-history").textContent = "No operation history loaded.";
    ui("knowledge-status").textContent = "Sign in to inspect knowledge.";
    ui("question").value = "";
    ui("question-count").textContent = "0 / 8000 characters";
    ui("department-name").value = "";
    ui("department-id").value = "";
    ui("skill-result").replaceChildren();
    ui("template-result").replaceChildren();
    renderSkills();
    updateControls();
  }

  function updateControls() {
    const authenticated = Boolean(state.token && state.context);
    ui("auth-status").textContent = authenticated ? "Signed in · tenant-bound" : "Not signed in";
    ui("sign-in").hidden = authenticated;
    ui("sign-out").hidden = !authenticated;
    ui("scope-selector").disabled = !authenticated || !state.context.scopes.length;
    ui("question").disabled = !authenticated || !permitted("knowledge.read") || state.busy;
    ui("ask").disabled = ui("question").disabled || !ui("question").value.trim();
    ui("refresh-status").disabled = !authenticated || state.refreshing;
    ui("ask").textContent = state.busy ? "Waiting for a completed answer…" : "Ask agent";
    const blocker = proposalBlocker();
    ui("department-name").disabled = Boolean(blocker) || state.proposalBusy;
    ui("department-id").disabled = Boolean(blocker) || state.proposalBusy;
    ui("propose").disabled = Boolean(blocker) || state.proposalBusy
      || (!ui("department-name").value.trim() && !ui("department-id").value.trim());
    ui("propose").textContent = state.proposalBusy
      ? "Waiting for a persisted pending plan…" : "Propose metadata plan · do not execute";
    ui("proposal-status").textContent = blocker || (state.proposalBusy
      ? "Preparing a scoped preview; no approval or execution has been requested."
      : state.proposalMessage || "Ready to request a pending plan. The server will verify the exact target and existing API/storage availability.");
    const skill = selectedSkill();
    ui("skill-selector").disabled = !authenticated || !state.skills.length || state.skillBusy;
    ui("discover-templates").disabled = !authenticated || !permitted("factory.read") || state.skillBusy;
    ui("run-skill").disabled = !skill || skill.available !== true || state.skillBusy;
    ui("run-skill").textContent = state.skillBusy ? "Waiting for the backend…"
      : !skill ? "Choose a skill" : skill.kind === "action" ? "Prepare plan · do not execute"
        : skill.kind === "diagnostic" ? "Read Factory status" : "Read cost report";
    for (const audience of ["platform", "project"]) {
      const selected = audience === state.audience;
      ui("view-" + audience).setAttribute("aria-pressed", String(selected));
      ui("view-" + audience).className = selected ? "" : "secondary";
    }
    ui("view-help").textContent = state.audience === "platform"
      ? "Platform guidance emphasizes shared architecture, governance and team responsibilities."
      : "Project guidance emphasizes use-case onboarding and self-service.";
  }

  function proposalBlocker() {
    if (!state.token || !state.context) {
      return "Blocked until approved Entra sign-in. Configuration writes and exact server target identifiers are also required; no API host is provisioned.";
    }
    if (!activeScope()) return "Choose an authorized factory/project/environment scope.";
    if (!permitted("factory.read") || !permitted("config.write")) {
      return "Blocked: this scope requires both factory.read and config.write grants.";
    }
    const blockers = state.context.capabilities?.proposal_blockers || [];
    const messages = [];
    if (!state.context.settings.writes_enabled || blockers.includes("writes_disabled")) {
      messages.push("configuration writes are disabled by the operator");
    }
    if (blockers.includes("factory_target_unconfigured")) {
      messages.push("exact factory/scale-set/project identifiers are not configured on the server");
    }
    if (messages.length) return "Blocked: " + messages.join("; ") + ".";
    if (state.context.capabilities?.proposal_creation !== true) return "User proposal preparation is not available on this deployment.";
    return "";
  }

  async function api(path, {method = "GET", body} = {}) {
    if (!state.token || Date.now() >= state.expiresAt) {
      clearSession();
      throw new Error("Your access token expired. Sign in again; no write was retried.");
    }
    const sessionVersion = state.sessionVersion;
    let response;
    try {
      response = await fetch(path, {
        method, credentials: "omit", cache: "no-store", redirect: "error",
        headers: {Authorization: "Bearer " + state.token, ...(body ? {"Content-Type": "application/json"} : {})},
        ...(body ? {body: JSON.stringify(body)} : {}),
      });
    } catch {
      throw new Error("The server could not be reached. Check connectivity. Inspect operation history before retrying any action.");
    }
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned an unexpected response. Check deployment health; do not replay writes.");
    }
    if (sessionVersion !== state.sessionVersion) {
      throw new Error("The session changed while the request was in progress. Its response was discarded.");
    }
    if (!response.ok) {
      if (response.status === 401) clearSession();
      const hints = {
        401: "Sign in again with the approved tenant account.",
        403: "This scope or permission is not granted. Choose an authorized scope or contact the operator.",
        409: "The plan changed, expired or was already used. Inspect history and prepare again if appropriate.",
        422: "Check the required question, scope and exact plan hash.",
        503: "Authentication, knowledge or an operation dependency is unavailable. Contact the deployment operator.",
      };
      const blockers = {
        writes_disabled: "Configuration writes are disabled. Ask the deployment operator; no plan was executed.",
        factory_target_unconfigured: "Exact factory/scale-set/project identifiers are missing on the server. Ask the operator to configure the scoped target.",
        factory_auth_unconfigured: "The existing Factory API credential is not configured. Contact the deployment operator.",
        factory_configuration: "The existing Factory API configuration or credential dependency is unavailable. Contact the operator.",
        factory_timeout: "The existing Factory API timed out. Check persisted plans before submitting again; no automatic retry occurred.",
        factory_api_error: "The existing Factory API request failed. Contact the operator; no separate API host is provisioned.",
      };
      const failure = new Error(blockers[data.error?.code] || hints[response.status]
        || "The request failed. Check health and operation history before retrying.");
      failure.operation = data.operation;
      throw failure;
    }
    return data;
  }

  function uuid(value) {
    return typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value)
      && !/^0{8}-0{4}-0{4}-0{4}-0{12}$/.test(value);
  }

  function configured(config) {
    if (!config || !uuid(config.tenant_id) || !uuid(config.client_id)
      || typeof config.audience !== "string" || !/^[A-Za-z0-9_.-]+$/.test(config.required_scope || "")) return false;
    if (uuid(config.audience)) return true;
    try {
      const url = new URL(config.audience);
      return ["api:", "https:"].includes(url.protocol) && Boolean(url.hostname)
        && !url.username && !url.password && !url.search && !url.hash;
    } catch {
      return false;
    }
  }

  function apiScope() {
    const audience = uuid(state.config.audience) ? "api://" + state.config.audience : state.config.audience;
    return audience.replace(/\/+$/, "") + "/" + state.config.required_scope;
  }

  function base64url(bytes) {
    return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  async function signIn() {
    showError("");
    if (!configured(state.config) || !crypto.subtle || !window.isSecureContext) {
      showError("Sign-in requires approved Entra configuration and HTTPS (or localhost). Ask the operator to finish setup.");
      return;
    }
    ui("sign-in").disabled = true;
    try {
      const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
      // Carry non-secret view preferences in the state transaction, not extra browser storage.
      const scopePreference = /^[A-Za-z0-9_-]{1,80}$/.test(state.scopeKey) ? state.scopeKey : "";
      const oauthState = base64url(crypto.getRandomValues(new Uint8Array(32))) + "." + state.audience + "." + scopePreference;
      const challenge = base64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
      sessionStorage.setItem(STATE_KEY, oauthState);
      sessionStorage.setItem(VERIFIER_KEY, verifier);
      const authorize = new URL("https://login.microsoftonline.com/" + state.config.tenant_id + "/oauth2/v2.0/authorize");
      authorize.search = new URLSearchParams({
        client_id: state.config.client_id, response_type: "code", response_mode: "query",
        redirect_uri: location.origin + "/", scope: apiScope(), state: oauthState,
        code_challenge: challenge, code_challenge_method: "S256",
      });
      location.assign(authorize.href);
    } catch {
      showError("The secure sign-in transaction could not be saved. Enable browser session storage and try again.");
      ui("sign-in").disabled = false;
    }
  }

  async function finishSignIn() {
    const expected = sessionStorage.getItem(STATE_KEY);
    const verifier = sessionStorage.getItem(VERIFIER_KEY);
    sessionStorage.removeItem(STATE_KEY);
    sessionStorage.removeItem(VERIFIER_KEY);
    if (!expected || !verifier || !callback.state || callback.state !== expected) {
      throw new Error("Sign-in state verification failed. Start a new sign-in from this page; no callback was accepted.");
    }
    if (callback.error || !callback.code) {
      throw new Error("Microsoft did not complete sign-in. Confirm registration approval, API consent and the exact SPA redirect URI.");
    }
    const preferences = expected.split(".");
    if (preferences.length === 3 && ["platform", "project"].includes(preferences[1])) {
      state.audience = preferences[1];
      if (/^[A-Za-z0-9_-]{1,80}$/.test(preferences[2])) state.scopeKey = preferences[2];
    }
    const response = await fetch(
      "https://login.microsoftonline.com/" + state.config.tenant_id + "/oauth2/v2.0/token",
      {
        method: "POST", credentials: "omit", cache: "no-store", redirect: "error",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: new URLSearchParams({
          client_id: state.config.client_id, grant_type: "authorization_code", code: callback.code,
          redirect_uri: location.origin + "/", code_verifier: verifier, scope: apiScope(),
        }),
      },
    );
    callback.code = null;
    const token = await response.json();
    if (!response.ok || token.token_type?.toLowerCase() !== "bearer" || typeof token.access_token !== "string"
      || !token.access_token || token.access_token.length > 32768
      || !Number.isFinite(token.expires_in) || token.expires_in <= 0 || token.expires_in > 86400) {
      throw new Error("The API access token could not be acquired. Check the Entra SPA platform, delegated scope and consent.");
    }
    state.token = token.access_token;
    state.expiresAt = Date.now() + token.expires_in * 1000 - 15000;
    state.context = await api("/api/context");
    const scopes = state.context.scopes;
    if (!scopes.some((scope) => scope.key === state.scopeKey)) state.scopeKey = scopes[0]?.key || "";
    ui("scope-selector").replaceChildren(...scopes.map((scope) => {
      const option = node("option", scope.label);
      option.value = scope.key;
      return option;
    }));
    if (!scopes.length) {
      ui("scope-selector").append(node("option", "No scopes granted to this account"));
      showError("Sign-in succeeded, but this account has no configured scope grants. Ask the deployment operator for access.");
    }
    ui("scope-selector").value = state.scopeKey;
    renderScope();
    saveSelection();
    updateControls();
    await refresh();
  }

  function renderScope() {
    ui("scope-details").replaceChildren();
    const selected = activeScope();
    if (!selected) return;
    for (const key of ["factory", "project", "environment", "tenant_id", "subscription_id", "resource_group"]) {
      ui("scope-details").append(node("dt", key.replace(/_/g, " ")), node("dd", selected.scope[key]));
    }
    ui("scope-details").append(node("dt", "Permissions"), node("dd", selected.permissions.join(", ")));
    ui("request-status").textContent = permitted("knowledge.read")
      ? "Ready to ask in the selected scope. Answers are not commands executed."
      : "Knowledge read is not granted in this scope.";
  }

  function renderSources(citations) {
    ui("citations").replaceChildren();
    for (const citation of citations || []) {
      const item = node("li");
      let label = "Evidence type not specified";
      if (citation.source_type === "live_observation") label = "LIVE OBSERVATION";
      else if (citation.is_history || citation.current_history === "history") label = "HISTORICAL RELEASE NOTE";
      else if (citation.is_current || citation.current_history === "current") label = "CURRENT GUIDANCE";
      item.append(node("span", label, "source-type"), node("strong", citation.citation_id || "Source"));
      item.append(node("div", citation.heading || citation.source_path || "Untitled source"));
      const metadata = ["source_type", "source_path", "version", "release", "source_revision", "ingested_at", "working_tree",
        "line_start", "line_end"].filter((key) => citation[key] !== undefined && citation[key] !== null)
        .map((key) => key.replace(/_/g, " ") + ": " + String(citation[key])).join(" · ");
      item.append(node("p", metadata, "muted"));
      if (citation.source_url) {
        let url;
        try { url = new URL(citation.source_url); } catch { url = null; }
        if (url && ["https:", "http:"].includes(url.protocol) && !url.username && !url.password) {
          const link = node("a", "Open source");
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          item.append(link);
        } else {
          item.append(node("p", "Source location: " + citation.source_url, "muted"));
        }
      }
      ui("citations").append(item);
    }
    if (!ui("citations").children.length) ui("citations").append(node("li", "No cited source was returned."));
  }

  async function ask(event) {
    event.preventDefault();
    if (state.busy || !permitted("knowledge.read")) return;
    const question = ui("question").value;
    if (!question.trim() || question.length > 8000) {
      showError("Enter a nonempty question of at most 8000 characters.");
      return;
    }
    const submittedScope = state.scopeKey;
    const submittedView = state.audience;
    state.busy = true;
    showError("");
    updateControls();
    ui("request-status").textContent = "Retrieving scoped evidence and waiting for a completed answer…";
    try {
      const result = await api("/api/chat", {method: "POST", body: {
        question, audience: submittedView, scope_key: submittedScope,
      }});
      ui("answer").textContent = result.answer;
      ui("answer-context").textContent = "Scope: " + result.scope_key + " · view: " + result.audience
        + " · correlation: " + result.correlation_id;
      renderSources(result.citations);
      const activity = result.tool_activity || [];
      ui("tool-activity").textContent = activity.length
        ? "Backend tool calls: " + activity.map((item) => item.name).join(", ")
          + ". Consult persisted plans below; a call is not proof of successful execution."
        : "No backend tool calls reported for this answer.";
      ui("request-status").textContent = "Answer received. Chat is read-only; existing persisted plans require separate approval and execution.";
      await refresh();
    } catch (error) {
      showError(error.message);
      ui("request-status").textContent = "No new completed answer confirmed.";
    } finally {
      state.busy = false;
      updateControls();
    }
  }

  async function propose(event) {
    event.preventDefault();
    if (state.proposalBusy || proposalBlocker()) return;
    const settings = {
      department_name: ui("department-name").value.trim() || null,
      department_id: ui("department-id").value.trim() || null,
    };
    if (settings.department_name === null && settings.department_id === null) return;
    const scopeKey = state.scopeKey;
    state.proposalBusy = true;
    state.proposalMessage = "";
    showError("");
    updateControls();
    try {
      const operation = await api("/api/operations/propose", {method: "POST", body: {scope_key: scopeKey, settings}});
      state.operations = state.operations.filter((item) => item.id !== operation.id).concat(operation);
      state.proposalMessage = "Pending plan created for " + operation.scope_key + ": " + operation.id
        + ". It is not approved or executed. Review its exact hash below.";
      ui("department-name").value = "";
      ui("department-id").value = "";
      renderOperations();
      try {
        await refresh();
      } catch (error) {
        showError("The pending plan was created, but history refresh failed. " + error.message);
      }
    } catch (error) {
      state.proposalMessage = "No new pending plan confirmed. Inspect persisted history before submitting again.";
      showError(error.message);
      try { await refresh(); } catch { /* Keep the proposal failure visible; never resubmit automatically. */ }
    } finally {
      state.proposalBusy = false;
      updateControls();
    }
  }

  function details(title, value) {
    const element = node("details");
    element.append(node("summary", title), node("pre", JSON.stringify(value, null, 2)));
    return element;
  }

  function selectedSkill() {
    return state.skills.find((skill) => skill.name === ui("skill-selector").value);
  }

  function renderSkills() {
    const selected = ui("skill-selector").value;
    ui("skill-selector").replaceChildren(...state.skills.map((skill) => {
      const option = node("option", skill.label);
      option.value = skill.name;
      return option;
    }));
    if (!state.skills.length) ui("skill-selector").append(node("option", "No skills loaded for this scope"));
    if (state.skills.some((skill) => skill.name === selected)) ui("skill-selector").value = selected;
    renderSkillArguments();
  }

  function renderSkillArguments() {
    ui("skill-arguments").replaceChildren();
    const skill = selectedSkill();
    ui("skill-description").textContent = skill ? skill.command : "";
    if (!skill) {
      ui("skill-status").textContent = "Sign in and select an authorized scope.";
      return;
    }
    const schema = skill.arguments_schema || {};
    for (const [key, definition] of Object.entries(schema.properties || {})) {
      const types = definition.anyOf || [definition];
      const typed = types.find((item) => item.type && item.type !== "null") || definition;
      let input;
      if (typed.enum) {
        input = node("select");
        for (const value of typed.enum) {
          const option = node("option", value);
          option.value = value;
          input.append(option);
        }
      } else {
        input = node("input");
        input.type = typed.type === "boolean" ? "checkbox"
          : ["integer", "number"].includes(typed.type) ? "number" : "text";
        if (typed.maxLength) input.maxLength = typed.maxLength;
        if (typed.minimum !== undefined) input.min = String(typed.minimum);
        if (typed.maximum !== undefined) input.max = String(typed.maximum);
        input.autocomplete = "off";
      }
      input.id = "skill-arg-" + key;
      input.dataset.argument = key;
      input.dataset.valueType = typed.type || "string";
      input.required = (schema.required || []).includes(key) && typed.type !== "boolean";
      input.disabled = skill.available !== true;
      if (definition.default !== undefined && definition.default !== null) {
        if (typed.type === "boolean") input.checked = definition.default;
        else input.value = String(definition.default);
      }
      const label = node("label", definition.title || key.replace(/_/g, " "));
      label.htmlFor = input.id;
      ui("skill-arguments").append(label, input);
      if (definition.description) ui("skill-arguments").append(node("p", definition.description, "muted"));
    }
    ui("skill-status").textContent = skill.available
      ? skill.kind === "action" ? "Ready to prepare a scoped plan. Approval and execution are separate."
        : skill.kind === "diagnostic" ? "Ready for a read-only Factory observation."
          : "Ready for read-only analysis. Unknown prices and missing billing data are not zero cost."
      : "Blocked: " + (skill.blockers || []).join(", ") + ". Ask the deployment operator to finish the scoped setup.";
  }

  async function runSkill(event) {
    event.preventDefault();
    const skill = selectedSkill();
    if (!skill || skill.available !== true || state.skillBusy) return;
    const args = {};
    for (const key of Object.keys(skill.arguments_schema?.properties || {})) {
      const input = ui("skill-arg-" + key);
      if (input.dataset.valueType === "boolean") args[key] = input.checked;
      else if (["integer", "number"].includes(input.dataset.valueType)) {
        if (input.value !== "") args[key] = Number(input.value);
      } else if (input.value.trim() !== "") args[key] = input.value.trim();
    }
    const scopeKey = state.scopeKey;
    state.skillBusy = true;
    showError("");
    ui("skill-result").replaceChildren();
    updateControls();
    try {
      const route = skill.kind === "action" ? "propose" : "run";
      const result = await api("/api/skills/" + encodeURIComponent(skill.name) + "/" + route, {
        method: "POST", body: {scope_key: scopeKey, arguments: args},
      });
      if (scopeKey !== state.scopeKey) return;
      if (skill.kind === "action") {
        state.operations = state.operations.filter((item) => item.id !== result.id).concat(result);
        ui("skill-status").textContent = "Pending plan saved: " + result.id + ". Review below; it is not approved or executed.";
        renderOperations();
      } else {
        ui("skill-status").textContent = skill.kind === "diagnostic" ? "Read-only Factory observation received."
          : "Read-only cost analysis received. Estimates, actual charges and forecasts have different bases.";
        ui("skill-result").append(details(skill.kind === "diagnostic" ? "Factory observation"
          : "Cost analysis, sources, assumptions and coverage", result.data || result));
      }
    } catch (error) {
      showError(error.message);
      ui("skill-status").textContent = "No new result confirmed. Inspect saved plans before submitting an action again.";
    } finally {
      state.skillBusy = false;
      updateControls();
    }
  }

  async function discoverTemplates() {
    if (!state.token || !permitted("factory.read") || state.skillBusy) return;
    const scopeKey = state.scopeKey;
    state.skillBusy = true;
    showError("");
    updateControls();
    try {
      const result = await api("/api/templates?scope_key=" + encodeURIComponent(scopeKey));
      if (scopeKey !== state.scopeKey) return;
      ui("template-result").replaceChildren(details("Source types, exact targets and creation blockers", result));
    } catch (error) {
      showError(error.message);
    } finally {
      state.skillBusy = false;
      updateControls();
    }
  }

  async function operate(operation, action, button, hash, confirmationPhrase) {
    button.disabled = true;
    showError("");
    try {
      await api("/api/operations/" + encodeURIComponent(operation.id) + "/" + action, {
        method: "POST", ...(action === "approve" ? {body: {plan_hash: hash,
          ...(confirmationPhrase ? {confirmation_phrase: confirmationPhrase} : {})}} : {}),
        ...(action === "continue" ? {body: {plan_hash: operation.plan_hash,
          observation_hash: operation.progress.observation_hash}} : {}),
      });
      await refresh();
    } catch (error) {
      if (error.operation) {
        state.operations = state.operations.filter((item) => item.id !== error.operation.id).concat(error.operation);
        renderOperations();
      }
      showError(error.message);
      // Read-only reconciliation is safe; never automatically replay approve/execute/cancel.
      try { await refresh(); } catch { /* The original actionable error remains visible. */ }
    } finally {
      button.disabled = false;
    }
  }

  function operationCard(operation, proposed) {
    const card = node("article", undefined, "operation");
    card.append(node("h3", operation.tool_name + " · " + operation.scope_key));
    const label = statusLabels[operation.status] || "Unknown status — no completion confirmed";
    const statusClass = operation.status === "succeeded" ? "status-good"
      : ["failed", "uncertain"].includes(operation.status) ? "status-bad" : "status-pending";
    card.append(node("p", label, statusClass));
    card.append(node("p", "Operation: " + operation.id + " · correlation: " + operation.correlation_id, "muted"));
    card.append(node("p", "Created: " + operation.created_at + " · expires: " + operation.expires_at, "muted"));
    card.append(node("p", "Exact plan hash: " + operation.plan_hash, "plan-hash"));
    card.append(details("Review target, proposed changes and affected resources", {
      scope: operation.scope, factory_api_url: operation.factory_api_url,
      request: operation.request, preview: operation.preview,
      affected_resources: operation.affected_resources,
    }));
    if (operation.progress) card.append(details("Persisted progress", operation.progress));
    if (operation.outcome) card.append(details("Backend execution result", operation.outcome));
    if (operation.observation) card.append(details("Latest read-only job observation", operation.observation));
    const actionPermission = {
      "delete-aifactory": "factory.delete", "add-project-to-aifactory": "project.add",
      "create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj": "factory.create",
      "create-agent-oftype-for-project": "agent.create",
      "create-ml-model-oftype-for-project": "model.create",
    }[operation.tool_name] || "config.write";
    if (operation.status === "awaiting_continuation" && operation.progress?.continuation_allowed
        && permitted("factory.create") && permitted("factory.read") && state.context.settings.writes_enabled) {
      card.append(node("p", "Continue only within the original approved plan and this exact paused-stage observation. New scope or recovery requires a new plan.", "muted"));
      const continuation = node("button", "Continue this approved workflow");
      continuation.type = "button";
      continuation.addEventListener("click", () => { void operate(operation, "continue", continuation); });
      card.append(continuation);
    }
    if (proposed && permitted(actionPermission) && permitted("factory.read")) {
      if (!state.context.settings.writes_enabled) {
        card.append(node("p", "Configuration writes are disabled. This unexecuted plan can still be cancelled.", "muted"));
      } else if (operation.status === "pending") {
        const form = node("form");
        const input = node("input");
        input.type = "text";
        input.required = true;
        input.autocomplete = "off";
        input.spellcheck = false;
        input.maxLength = 64;
        input.id = "hash-" + operation.id;
        const labelElement = node("label", "After reviewing, enter the exact 64-character plan hash to approve");
        labelElement.htmlFor = input.id;
        const approve = node("button", "Approve this exact plan");
        approve.type = "submit";
        approve.disabled = true;
        const phrase = operation.preview?.confirmation_phrase;
        let phraseInput;
        if (operation.tool_name === "delete-aifactory") {
          phraseInput = node("input");
          phraseInput.type = "text";
          phraseInput.required = true;
          phraseInput.autocomplete = "off";
          phraseInput.id = "phrase-" + operation.id;
          const phraseLabel = node("label", "To authorize deletion, type: " + (phrase || "Deletion phrase unavailable"));
          phraseLabel.htmlFor = phraseInput.id;
          form.append(phraseLabel, phraseInput);
        }
        const validApproval = () => input.value === operation.plan_hash
          && (!phraseInput || (typeof phrase === "string" && phraseInput.value === phrase));
        input.addEventListener("input", () => { approve.disabled = !validApproval(); });
        if (phraseInput) phraseInput.addEventListener("input", () => { approve.disabled = !validApproval(); });
        form.append(labelElement, input, approve);
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          if (validApproval()) void operate(operation, "approve", approve, input.value, phraseInput?.value);
        });
        card.append(form);
      } else if (operation.status === "approved") {
        const execute = node("button", operation.tool_name === "factory_prepare_settings"
          ? "Execute approved metadata change" : "Execute this approved Factory operation");
        execute.type = "button";
        execute.addEventListener("click", () => { void operate(operation, "execute", execute); });
        card.append(execute);
      }
      const cancel = node("button", "Cancel unexecuted plan", "secondary");
      cancel.type = "button";
      cancel.addEventListener("click", () => { void operate(operation, "cancel", cancel); });
      const controls = node("div", undefined, "operation-controls");
      controls.append(cancel);
      card.append(controls);
    }
    return card;
  }

  function renderOperations() {
    ui("proposed-plans").replaceChildren();
    ui("operation-history").replaceChildren();
    for (const operation of state.operations.filter((item) => item.scope_key === state.scopeKey)) {
      const proposed = ["pending", "approved"].includes(operation.status);
      ui(proposed ? "proposed-plans" : "operation-history").append(operationCard(operation, proposed));
    }
    if (!ui("proposed-plans").children.length) ui("proposed-plans").textContent = "No pending or approved plans in the active scope.";
    if (!ui("operation-history").children.length) ui("operation-history").textContent = "No executed or closed plans in the active scope.";
  }

  async function refresh() {
    if (!state.token || !state.context || state.refreshing) return;
    state.refreshing = true;
    const refreshedScope = state.scopeKey;
    updateControls();
    try {
      const jobs = [api("/api/operations").then(async (result) => {
        state.operations = result.operations;
        renderOperations();
        const observations = await Promise.allSettled(result.operations.filter((operation) =>
          operation.scope_key === refreshedScope && ["running", "awaiting_continuation"].includes(operation.status)
        ).map(async (operation) => {
          const observed = await api("/api/operations/" + encodeURIComponent(operation.id) + "/status");
          state.operations = state.operations.filter((item) => item.id !== observed.id).concat(observed);
          renderOperations();
        }));
        const failure = observations.find((observation) => observation.status === "rejected");
        if (failure) throw failure.reason;
      })];
      if (state.context.capabilities?.skills_supported && permitted("factory.read")) {
        const scopeKey = state.scopeKey;
        jobs.push(api("/api/skills?scope_key=" + encodeURIComponent(scopeKey)).then((result) => {
          if (scopeKey !== state.scopeKey) return;
          state.skills = result.skills;
          renderSkills();
        }));
      }
      if (permitted("knowledge.read")) {
        const scopeKey = state.scopeKey;
        jobs.push(api("/api/knowledge/status?scope_key=" + encodeURIComponent(scopeKey)).then((result) => {
          if (scopeKey !== state.scopeKey) return;
          const info = result.status;
          const reconciled = info.reconciliation_pending === false
            && (!Object.hasOwn(info, "search_document_count") || info.search_document_count === info.indexed_document_count);
          const ready = info.status === "ready" && info.stale === false
            && Number.isInteger(info.indexed_document_count) && info.indexed_document_count > 0 && reconciled;
          const label = info.status === "ready" && !ready
            ? "Not ready — freshness, population or reconciliation is unconfirmed"
            : knowledgeLabels[info.status] || "Unknown knowledge state — readiness is not confirmed";
          ui("knowledge-status").textContent = label + " (reported: " + info.status + ")"
            + " · corpus age: " + (info.stale === false ? "fresh" : "stale / unknown")
            + " · indexed: " + (info.indexed_document_count ?? "unknown")
            + " · Search confirms: " + (info.search_document_count ?? "not checked")
            + " · reconciliation: " + (info.reconciliation_pending === false ? "complete" : "pending / unknown")
            + " · refreshed: " + (info.refreshed_at || "not confirmed");
        }));
      } else {
        ui("knowledge-status").textContent = "Knowledge read is not granted in the active scope.";
      }
      const results = await Promise.allSettled(jobs);
      const failures = results.filter((result) => result.status === "rejected");
      if (failures.length) throw failures[0].reason;
    } finally {
      state.refreshing = false;
      updateControls();
      if (state.token && state.scopeKey !== refreshedScope) {
        void refresh().catch((error) => showError(error.message));
      }
    }
  }

  async function initialize() {
    updateControls();
    try {
      const response = await fetch("/api/public-config", {credentials: "omit", cache: "no-store", redirect: "error"});
      if (!response.ok) throw new Error("Public sign-in configuration is unavailable. Check the HTTP service.");
      state.config = await response.json();
      if (!configured(state.config)) {
        ui("setup-heading").textContent = "Setup blocked · Entra registration approval pending";
        ui("setup-message").textContent = "Sign-in is disabled. An approved operator must configure tenant/client ID, API audience and delegated scope, and register this exact SPA redirect URI: "
          + location.origin + "/. No identity is created by this page; tokens cannot be pasted as a workaround.";
        if (callback.present) {
          sessionStorage.removeItem(STATE_KEY);
          sessionStorage.removeItem(VERIFIER_KEY);
          callback.code = null;
        }
        return;
      }
      ui("setup-heading").textContent = "Entra sign-in configured";
      ui("setup-message").textContent = "Sign in to load only your authorized factory/project/environment scopes. Live execution readiness is checked separately.";
      ui("sign-in").disabled = !window.isSecureContext || !crypto.subtle;
      if (ui("sign-in").disabled) throw new Error("Secure browser cryptography is unavailable. Serve this frontend over HTTPS or localhost.");
      if (callback.present) await finishSignIn();
    } catch (error) {
      callback.code = null;
      if (state.token && !state.context) clearSession();
      showError(error.message || "Sign-in failed. Check browser connectivity and approved Entra setup.");
    }
  }

  ui("sign-in").addEventListener("click", () => { void signIn(); });
  ui("sign-out").addEventListener("click", clearSession);
  ui("question-form").addEventListener("submit", (event) => { void ask(event); });
  ui("proposal-form").addEventListener("submit", (event) => { void propose(event); });
  ui("skill-form").addEventListener("submit", (event) => { void runSkill(event); });
  ui("skill-selector").addEventListener("change", () => { renderSkillArguments(); updateControls(); });
  ui("discover-templates").addEventListener("click", () => { void discoverTemplates(); });
  for (const id of ["department-name", "department-id"]) {
    ui(id).addEventListener("input", updateControls);
  }
  ui("question").addEventListener("input", () => {
    ui("question-count").textContent = ui("question").value.length + " / 8000 characters";
    updateControls();
  });
  ui("scope-selector").addEventListener("change", () => {
    state.scopeKey = ui("scope-selector").value;
    state.proposalMessage = "";
    state.skills = [];
    renderSkills();
    ui("skill-result").replaceChildren();
    ui("template-result").replaceChildren();
    renderScope();
    saveSelection();
    renderOperations();
    ui("knowledge-status").textContent = "Checking the newly selected scope…";
    updateControls();
    void refresh().catch((error) => showError(error.message));
  });
  for (const audience of ["platform", "project"]) {
    ui("view-" + audience).addEventListener("click", () => {
      state.audience = audience;
      saveSelection();
      updateControls();
    });
  }
  ui("refresh-status").addEventListener("click", () => {
    showError("");
    void refresh().catch((error) => showError(error.message));
  });
  window.setInterval(() => {
    if (state.token && Date.now() >= state.expiresAt) {
      clearSession();
      showError("Your access token expired. Sign in again; tokens are not persisted or silently refreshed.");
    } else if (state.operations.some((operation) => ["executing", "continuing", "running"].includes(operation.status))) {
      void refresh().catch((error) => showError(error.message));
    }
  }, 10000);
  void initialize();
})();
