/* Voice orb: a pulsing, ambient circular light that shows whether the agent is idle, listening, thinking or speaking.
 * `describe` is a pure model (testable without a browser); `createOrb` draws it on a canvas using theme colours. */
(() => {
  "use strict";

  const TAU = Math.PI * 2;
  const DEFAULT_PALETTE = {
    accent: "#6750A4", action: "#006B75", danger: "#C42B1C", muted: "#686370", surface: "#FFFFFF",
  };
  const THEME_VARIABLES = {
    accent: "--cp-accent", action: "--cp-action", danger: "--cp-danger", muted: "--cp-text-muted", surface: "--cp-bg-elevated",
  };
  const STATES = ["off", "connecting", "listening", "thinking", "speaking", "error"];
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const phase = (time, period, offset = 0) => (((time / period) + offset) % 1 + 1) % 1;

  function ripples(time, level, period, spread, base, gain, reduced) {
    return [0, 1, 2].map((index) => {
      const progress = reduced ? (index + 1) / 4 : phase(time, period, index / 3);
      return {
        radius: 1.05 + (spread + 1.2 * level) * progress,
        alpha: (base + gain * level) * Math.pow(1 - progress, 1.4),
        width: 2,
      };
    });
  }

  function describe(state, time, level = 0, reducedMotion = false) {
    const sound = reducedMotion ? 0 : clamp(Number.isFinite(level) ? level : 0, 0, 1);
    const breath = (period, size) => (reducedMotion ? 0 : size * Math.sin(TAU * phase(time, period)));
    switch (state) {
      case "connecting": {
        const progress = reducedMotion ? 0.5 : phase(time, 1.6);
        return {
          tone: "accent", core: {radius: 0.95 + breath(1.6, 0.02), alpha: 0.55},
          glow: {radius: 1.7, alpha: 0.16}, arcs: [],
          rings: [{radius: 1 + 0.8 * progress, alpha: 0.5 * (1 - progress), width: 2}],
        };
      }
      case "listening":
        return {
          tone: "action", core: {radius: 1 + 0.12 * sound + breath(3.2, 0.02), alpha: 0.85},
          glow: {radius: 1.8 + 0.5 * sound, alpha: 0.2 + 0.3 * sound}, arcs: [],
          rings: ripples(time, sound, 2.4, 0.9, 0.12, 0.55, reducedMotion),
        };
      case "thinking": {
        const angle = reducedMotion ? 0 : time * 1.8;
        return {
          tone: "accent", core: {radius: 0.98 + breath(1.2, 0.05), alpha: 0.85},
          glow: {radius: 1.8, alpha: 0.24},
          rings: [{radius: 1.38, alpha: 0.2, width: 2}],
          arcs: [0, 1, 2].map((index) => ({start: angle + index * (TAU / 3), length: 1.0, alpha: 0.9 - 0.22 * index, radius: 1.38})),
        };
      }
      case "speaking":
        return {
          tone: "accent", core: {radius: 1 + 0.16 * sound + breath(0.8, 0.03), alpha: 0.95},
          glow: {radius: 1.9 + 0.6 * sound, alpha: 0.35 + 0.3 * sound}, arcs: [],
          rings: ripples(time, sound, 1.4, 0.8, 0.25, 0.6, reducedMotion),
        };
      case "error":
        return {
          tone: "danger", core: {radius: 1, alpha: 0.85}, glow: {radius: 1.6, alpha: 0.2}, arcs: [],
          rings: [{radius: 1.3, alpha: 0.5, width: 2}],
        };
      default:
        return {
          tone: "muted", core: {radius: 0.9 + breath(6, 0.015), alpha: 0.4}, glow: {radius: 1.5, alpha: 0.1},
          arcs: [], rings: [{radius: 1.2, alpha: 0.18, width: 1.5}],
        };
    }
  }

  function needsAnimation(state, reducedMotion) {
    return !reducedMotion && state !== "off" && state !== "error";
  }

  function parseColor(value, fallback) {
    const text = String(value || "").trim();
    let match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
    if (match) {
      const hex = match[1].length === 3 ? match[1].replace(/./g, (c) => c + c) : match[1];
      return [0, 2, 4].map((index) => parseInt(hex.slice(index, index + 2), 16));
    }
    match = /^rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})/i.exec(text);
    if (match) return [1, 2, 3].map((index) => clamp(Number(match[index]), 0, 255));
    return fallback ? parseColor(fallback) : [103, 80, 164];
  }

  function readPalette(root, computeStyle) {
    const style = computeStyle ? computeStyle(root) : null;
    const palette = {};
    for (const key of Object.keys(DEFAULT_PALETTE)) {
      const value = style ? style.getPropertyValue(THEME_VARIABLES[key]) : "";
      palette[key] = parseColor(value, DEFAULT_PALETTE[key]);
    }
    return palette;
  }

  const rgba = (color, alpha) => `rgba(${color[0]},${color[1]},${color[2]},${clamp(alpha, 0, 1).toFixed(3)})`;
  const mix = (color, other, amount) => color.map((channel, index) => Math.round(channel + (other[index] - channel) * amount));

  function draw(context, size, frame, palette) {
    const center = size / 2;
    const unit = size * 0.14; // the widest ripple (3.2 units) and glow (3.4 units) must stay inside the canvas
    const color = palette[frame.tone] || palette.accent;
    context.clearRect(0, 0, size, size);
    const glowRadius = unit * frame.glow.radius * 1.35;
    const glow = context.createRadialGradient(center, center, unit * 0.4, center, center, glowRadius);
    glow.addColorStop(0, rgba(color, frame.glow.alpha));
    glow.addColorStop(1, rgba(color, 0));
    context.fillStyle = glow;
    context.beginPath();
    context.arc(center, center, glowRadius, 0, TAU);
    context.fill();
    for (const ring of frame.rings) {
      context.beginPath();
      context.arc(center, center, unit * ring.radius, 0, TAU);
      context.lineWidth = Math.max(1, ring.width * (size / 320));
      context.strokeStyle = rgba(color, ring.alpha);
      context.stroke();
    }
    context.lineCap = "round";
    for (const arc of frame.arcs) {
      context.beginPath();
      context.arc(center, center, unit * arc.radius, arc.start, arc.start + arc.length);
      context.lineWidth = Math.max(2, 5 * (size / 320));
      context.strokeStyle = rgba(color, arc.alpha);
      context.stroke();
    }
    const radius = unit * frame.core.radius;
    const core = context.createRadialGradient(center - radius * 0.25, center - radius * 0.3, radius * 0.1, center, center, radius);
    core.addColorStop(0, rgba(mix(color, [255, 255, 255], 0.55), frame.core.alpha));
    core.addColorStop(0.65, rgba(color, frame.core.alpha));
    core.addColorStop(1, rgba(mix(color, [0, 0, 0], 0.25), frame.core.alpha * 0.9));
    context.fillStyle = core;
    context.beginPath();
    context.arc(center, center, radius, 0, TAU);
    context.fill();
  }

  function createOrb(canvas, options = {}) {
    const environment = options.environment || globalThis;
    const reducedQuery = environment.matchMedia ? environment.matchMedia("(prefers-reduced-motion: reduce)") : null;
    const context = canvas.getContext("2d");
    const orb = {state: "off", level: 0, target: 0, palette: readPalette(null), frame: 0, running: false, last: 0, paletteAt: -Infinity};
    const reduced = () => Boolean(options.reducedMotion ?? (reducedQuery && reducedQuery.matches));
    const root = environment.document && environment.document.documentElement;

    function resize() {
      const ratio = clamp(environment.devicePixelRatio || 1, 1, 2);
      const css = canvas.clientWidth || 220;
      const pixels = Math.round(css * ratio);
      if (canvas.width !== pixels) {
        canvas.width = pixels;
        canvas.height = pixels;
      }
      return pixels;
    }

    function refreshPalette() {
      const compute = environment.getComputedStyle ? environment.getComputedStyle.bind(environment) : null;
      orb.palette = readPalette(root, compute);
    }

    function render(time) {
      const size = resize();
      const seconds = time / 1000;
      if (seconds - orb.paletteAt > 1) {
        refreshPalette();
        orb.paletteAt = seconds;
      }
      const delta = orb.last ? Math.min(0.1, seconds - orb.last) : 0.016;
      orb.last = seconds;
      const rate = orb.target > orb.level ? 14 : 4;
      orb.level += (orb.target - orb.level) * (1 - Math.exp(-rate * delta));
      draw(context, size, describe(orb.state, seconds, orb.level, reduced()), orb.palette);
    }

    function loop(time) {
      if (!orb.running) return;
      render(time);
      if (needsAnimation(orb.state, reduced()) && !(environment.document && environment.document.hidden)) {
        orb.frame = environment.requestAnimationFrame(loop);
      } else {
        orb.frame = 0;
      }
    }

    function kick() {
      if (orb.frame || !orb.running) return;
      orb.frame = environment.requestAnimationFrame(loop);
    }

    const api = {
      setState(next) {
        if (!STATES.includes(next)) throw new Error("Unknown orb state: " + next);
        orb.state = next;
        refreshPalette();
        kick();
        if (orb.running && orb.frame === 0) render(environment.performance ? environment.performance.now() : 0);
      },
      setLevel(value) {
        orb.target = clamp(Number(value) || 0, 0, 1);
      },
      start() {
        orb.running = true;
        refreshPalette();
        kick();
      },
      stop() {
        orb.running = false;
        if (orb.frame && environment.cancelAnimationFrame) environment.cancelAnimationFrame(orb.frame);
        orb.frame = 0;
      },
      get state() {
        return orb.state;
      },
    };
    if (environment.document && environment.document.addEventListener) {
      environment.document.addEventListener("visibilitychange", () => {
        if (!environment.document.hidden) kick();
      });
    }
    return api;
  }

  const exported = {STATES, describe, needsAnimation, parseColor, readPalette, draw, createOrb};
  if (typeof module === "object" && module.exports) module.exports = exported;
  else globalThis.AIFactoryVoiceOrb = exported;
})();
