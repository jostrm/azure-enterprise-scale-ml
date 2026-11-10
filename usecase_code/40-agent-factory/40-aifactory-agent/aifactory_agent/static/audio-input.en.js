/* English microphone-settings resource; loaded synchronously with the optional UI, never during a gesture. */
(() => {
  "use strict";
  const text = Object.freeze({
    heading: "Audio settings",
    microphone: "Microphone",
    systemDefault: "System default",
    generic: "Microphone {number}",
    unavailableDevice: "{label} (unavailable)",
    selectedDevice: "Previously selected microphone",
    refresh: "Refresh devices",
    allow: "Allow microphone",
    explanation: "Allow microphone briefly opens the selected microphone locally to request permission and reveal device names, then immediately closes it. No audio from this check is sent or stored. Refresh devices never opens the microphone.",
    lifetime: "Your microphone choice lasts only for this page. Changing it stops voice; press Start talking to use the new input.",
    idle: "Choose an input, or allow microphone access to see device names.",
    ready: "Microphone settings ready. Press Start talking when you want to speak.",
    changed: "Input changed. Voice is stopped; press Start talking to use this microphone.",
    missing: "The selected microphone is unavailable. Reconnect it or choose another input, then press Start talking. No other microphone will be selected automatically.",
    noDevices: "No microphone is visible. Connect a microphone, or use Allow microphone if permission has not been granted.",
    denied: "Microphone permission was denied by the browser, app or operating system. This page cannot tell which one blocked it. Check site/app permission and system microphone privacy settings, then try Allow microphone again.",
    restricted: "Microphone access is disabled by a security restriction. Check browser/app and operating-system privacy policies, or contact your administrator.",
    busy: "The microphone could not be read. Another app may be using it, or the device or operating system may be blocking access. Close other audio apps and check the device, then try again.",
    policy: "This document's Permissions-Policy blocks microphone access. Changing its address after loading does not change that policy. Reopen or reload the voice-enabled page, then try Allow microphone. If it remains blocked, contact the deployment administrator. A device choice or permission prompt cannot override this policy.",
    insecure: "Microphone access requires HTTPS or localhost.",
    unsupported: "Microphone capture is not supported in this browser or app.",
    enumerationUnsupported: "This browser cannot list microphones. System default and explicit microphone permission may still work.",
    enumerationFailed: "Microphones could not be listed. Refresh devices to try again; your input choice has been kept.",
    gesture: "Use Allow microphone or Start talking directly to request microphone access.",
    permissionPending: "Waiting for microphone permission. Complete the browser/app prompt before starting voice.",
    captureFailed: "Microphone capture could not start. Check the selected input and try again.",
    ended: "The microphone stopped or was disconnected. Voice is stopped; check the input and press Start talking to reconnect.",
    unavailable: "Microphone settings are no longer active on this page.",
  });
  if (typeof module === "object" && module.exports) module.exports = text;
  else globalThis.AIFactoryAudioInputText = text;
})();
