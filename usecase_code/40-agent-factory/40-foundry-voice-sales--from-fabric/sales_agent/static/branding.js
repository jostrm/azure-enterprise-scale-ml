/* Cosmetic preferences only; never store conversations, audio, identity or credentials. */
(() => {
  "use strict";
  const allowed = new Set(["gray", "swedish-retail"]);
  const key = "foundry-sales.brand";
  const storageUnavailable = (error) => error instanceof DOMException
    && ["SecurityError", "QuotaExceededError"].includes(error.name);
  let storage = null, saved = null, persistent = true;
  try {
    storage = window.localStorage;
    saved = storage.getItem(key);
  } catch (error) {
    if (!storageUnavailable(error)) throw error;
    storage = null;
    persistent = false;
  }
  let value = allowed.has(saved) ? saved : "gray";
  document.documentElement.setAttribute("data-brand", value);
  window.salesBranding = Object.freeze({
    get value() { return value; },
    get persistent() { return persistent; },
    select(next) {
      if (!allowed.has(next)) throw new RangeError("Unknown brand theme");
      value = next;
      document.documentElement.setAttribute("data-brand", value);
      if (!storage) return false;
      try {
        storage.setItem(key, value);
        persistent = true;
      } catch (error) {
        if (!storageUnavailable(error)) throw error;
        persistent = false;
      }
      return persistent;
    },
  });
})();
