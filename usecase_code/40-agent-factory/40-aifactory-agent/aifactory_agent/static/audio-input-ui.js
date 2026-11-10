/* Optional DOM adapter. The controller owns device/permission state; voice.js owns capture and transport. */
(() => {
  "use strict";
  function mount({env = globalThis, controller, canAllow = () => false, isLive = () => false}) {
    const doc = env.document, text = env.AIFactoryAudioInputText;
    const get = id => doc && doc.getElementById(id);
    const details = get("voice-audio-settings"), select = get("voice-input-device");
    const refresh = get("voice-input-refresh"), allow = get("voice-input-allow"), status = get("voice-input-status");
    if (!text || !details || !select || !refresh || !allow || !status) return null;
    for (const [id, key] of [
      ["voice-input-heading", "heading"], ["voice-input-label", "microphone"],
      ["voice-input-explanation", "explanation"], ["voice-input-lifetime", "lifetime"],
      ["voice-input-refresh", "refresh"], ["voice-input-allow", "allow"],
    ]) {
      const node = get(id);
      if (node) node.textContent = text[key];
    }
    function render(state = controller.snapshot()) {
      select.replaceChildren();
      const option = (value, label, disabled = false) => {
        const node = doc.createElement("option");
        node.value = value;
        node.textContent = label;
        node.disabled = disabled;
        select.append(node);
      };
      option("", text.systemDefault);
      let number = 0;
      for (const device of state.devices) {
        if (device.deviceId === "default") continue;
        const label = device.label || (device.unavailable ? text.selectedDevice : text.generic.replace("{number}", String(++number)));
        // An anonymized device with no ID cannot be selected exactly before permission.
        option(device.deviceId, device.unavailable ? text.unavailableDevice.replace("{label}", label) : label,
          !device.deviceId || device.unavailable === true);
      }
      select.value = state.selectedId;
      select.disabled = state.busy;
      allow.disabled = !canAllow() || isLive() || state.busy;
      refresh.disabled = state.busy;
      status.textContent = text[state.code] || text.captureFailed;
      if (["missing", "denied", "restricted", "busy", "policy", "unsupported", "insecure",
        "enumerationFailed", "captureFailed", "ended"].includes(state.code)) details.open = true;
    }
    const onSelect = () => controller.select(select.value);
    const onRefresh = () => { void controller.refresh(); };
    const onAllow = event => {
      if (!canAllow() || isLive() || allow.disabled) return;
      if (event && event.isTrusted === false) {
        controller.reportError({audioInputCode: "gesture"});
        return;
      }
      void controller.allow();
    };
    select.addEventListener("change", onSelect);
    refresh.addEventListener("click", onRefresh);
    allow.addEventListener("click", onAllow);
    const unsubscribe = controller.subscribe(render);
    details.hidden = false;
    void controller.refresh();
    return {
      render,
      describe: code => text[code] || text.captureFailed,
      dispose() {
        unsubscribe();
        for (const [node, name, fn] of [[select, "change", onSelect], [refresh, "click", onRefresh], [allow, "click", onAllow]]) {
          node.removeEventListener(name, fn);
        }
      },
    };
  }
  const api = {mount};
  if (typeof module === "object" && module.exports) module.exports = api;
  else globalThis.AIFactoryAudioInputUI = api;
})();
