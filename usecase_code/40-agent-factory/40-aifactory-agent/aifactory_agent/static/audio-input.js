/* Page-lifetime input preference and local permission probe. No transport, storage or PCM processing. */
(() => {
  "use strict";

  function createAudioInput({env = globalThis, onInputChange = () => {}} = {}) {
    const media = env.navigator && env.navigator.mediaDevices;
    const listeners = new Set();
    let devices = [], selectedId = "", selectedLabel = "", enumerated = false;
    let issue = "", notice = "idle", busy = false, pending = false, disposed = false;
    let permissionGeneration = 0, refreshGeneration = 0;

    function preflight(gesture = false) {
      if (env.isSecureContext !== true) return "insecure";
      const policy = env.document && (env.document.permissionsPolicy || env.document.featurePolicy);
      if (policy && typeof policy.allowsFeature === "function" && !policy.allowsFeature("microphone")) return "policy";
      if (!media || typeof media.getUserMedia !== "function") return "unsupported";
      if (gesture && env.navigator.userActivation && env.navigator.userActivation.isActive === false) return "gesture";
      return "";
    }

    const missing = () => Boolean(selectedId && enumerated && !devices.some(d => d.deviceId === selectedId));
    function snapshot() {
      const unavailable = missing();
      const listed = devices.map(d => ({...d}));
      if (unavailable) listed.push({deviceId: selectedId, label: selectedLabel, unavailable: true});
      return {selectedId, devices: listed, busy,
        code: preflight() || issue || (unavailable ? "missing" : enumerated && !devices.length ? "noDevices" : notice)};
    }
    function emit() {
      if (!disposed) for (const listener of listeners) listener(snapshot());
    }
    function failure(code) {
      return Object.assign(new Error(code), {audioInputCode: code});
    }
    function classify(error) {
      if (preflight()) return preflight();
      if (error && error.audioInputCode) return error.audioInputCode;
      switch (error && error.name) {
        case "NotAllowedError": return "denied";
        case "SecurityError": return "restricted";
        case "NotReadableError":
        case "AbortError": return "busy";
        case "NotFoundError": return selectedId ? "missing" : "noDevices";
        case "OverconstrainedError": return "missing";
        default: return "captureFailed";
      }
    }
    function reportError(error) {
      const code = classify(error);
      issue = code;
      emit();
      return code;
    }
    function constraints() {
      const code = preflight(true);
      if (disposed || code || pending || missing()) throw failure(disposed ? "unavailable" : code || (pending ? "permissionPending" : "missing"));
      return {audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
        ...(selectedId ? {deviceId: {exact: selectedId}} : {})}};
    }

    async function refresh(reason = "refresh") {
      if (disposed) return;
      const generation = ++refreshGeneration;
      const blocked = preflight();
      if (blocked) { issue = blocked; emit(); return; }
      if (typeof media.enumerateDevices !== "function") { issue = "enumerationUnsupported"; emit(); return; }
      try {
        const found = await media.enumerateDevices();
        if (disposed || generation !== refreshGeneration) return;
        const wasMissing = missing();
        const previousDefault = devices.find(d => d.deviceId === "default");
        const next = found.filter(d => d.kind === "audioinput").map(d => ({
          deviceId: d.deviceId, label: d.label || "", groupId: d.groupId || "",
        }));
        const nextDefault = next.find(d => d.deviceId === "default");
        // A permission grant can itself emit devicechange when anonymous entries gain names/IDs.
        // That is not an input switch. Once identities are visible, stop on a changed/unknown default route.
        const defaultChanged = reason === "devicechange" && enumerated && !selectedId
          && ((devices.length > 0 && !next.length) || (devices.some(d => d.label || d.groupId)
            && (!previousDefault || !nextDefault || !previousDefault.groupId
              || previousDefault.groupId !== nextDefault.groupId)));
        devices = next;
        enumerated = true;
        const current = devices.find(d => d.deviceId === selectedId);
        if (current && current.label) selectedLabel = current.label;
        if (["enumerationFailed", "enumerationUnsupported", "missing", "noDevices"].includes(issue)) issue = "";
        if ((missing() && !wasMissing) || defaultChanged) {
          cancelPermission();
          onInputChange(missing() ? "missing" : "changed");
          notice = "changed";
        } else if (wasMissing || notice !== "changed") notice = "ready";
        emit();
      } catch {
        if (!disposed && generation === refreshGeneration) { issue = "enumerationFailed"; emit(); }
      }
    }

    function cancelPermission() {
      permissionGeneration++;
      busy = false;
      if (notice === "permissionPending") notice = "idle";
      emit();
    }
    function select(value) {
      if (disposed || value === selectedId) return;
      // Stop the existing voice synchronously before applying another input. Never restart it here.
      cancelPermission();
      onInputChange("changed");
      selectedId = value || "";
      selectedLabel = (devices.find(d => d.deviceId === selectedId) || {}).label || "";
      issue = "";
      notice = "changed";
      emit();
    }
    async function allow() {
      if (disposed || pending) return;
      const generation = ++permissionGeneration;
      let stream, succeeded = false;
      try {
        const requested = constraints();
        busy = true;
        pending = true;
        issue = "";
        notice = "permissionPending";
        emit();
        // No await before this call: native/browser consent belongs to the explicit button gesture.
        stream = await media.getUserMedia(requested);
        succeeded = true;
      } catch (error) {
        if (!disposed && generation === permissionGeneration) reportError(error);
      } finally {
        if (stream) for (const track of stream.getTracks()) {
          try { track.stop(); } catch { /* still release every other track */ }
        }
        pending = false;
        if (!disposed && generation === permissionGeneration) {
          busy = false;
          if (succeeded) { issue = ""; notice = "ready"; }
          emit();
        }
      }
      if (succeeded && !disposed && generation === permissionGeneration) await refresh();
    }
    function captured() {
      if (disposed) return;
      issue = "";
      notice = "ready";
      emit();
      void refresh();
    }
    const devicechange = () => { void refresh("devicechange"); };
    if (media && media.addEventListener) media.addEventListener("devicechange", devicechange);
    return {
      snapshot, constraints, refresh, select, allow, reportError, captured, cancelPermission,
      subscribe(listener) { listeners.add(listener); listener(snapshot()); return () => listeners.delete(listener); },
      dispose() {
        disposed = true;
        permissionGeneration++;
        refreshGeneration++;
        listeners.clear();
        if (media && media.removeEventListener) media.removeEventListener("devicechange", devicechange);
      },
    };
  }
  const api = {createAudioInput};
  if (typeof module === "object" && module.exports) module.exports = api;
  else globalThis.AIFactoryAudioInput = api;
})();
