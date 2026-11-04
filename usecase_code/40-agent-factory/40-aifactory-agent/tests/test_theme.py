import re
import subprocess
from pathlib import Path

import pytest


STATIC = Path(__file__).parents[1] / "aifactory_agent" / "static"
PALETTES = {
    "light": {
        "--cp-bg": "#F7F6FA", "--cp-surface": "#FFFFFF", "--cp-surface-soft": "#F0EEF4",
        "--cp-border": "#E1DDE7", "--cp-text": "#24212A", "--cp-text-muted": "#686370",
        "--cp-accent": "#6750A4", "--cp-accent-hover": "#4F378B", "--cp-accent-soft": "#EEE8FF",
        "--cp-link": "#0F6CBD", "--cp-success": "#0F7B55", "--cp-danger": "#C42B1C",
        "--cp-warning": "#9A6700",
    },
    "dark": {
        "--cp-bg": "#121016", "--cp-surface": "#1B1820", "--cp-surface-soft": "#27232D",
        "--cp-border": "#403A48", "--cp-text": "#F5F1F7", "--cp-text-muted": "#BDB5C5",
        "--cp-accent": "#B9A7FF", "--cp-accent-hover": "#D8CEFF", "--cp-accent-soft": "#382E50",
        "--cp-link": "#78B9F4", "--cp-success": "#69D3A6", "--cp-danger": "#FF8A7E",
        "--cp-warning": "#F3C969",
    },
}
# ConfigWizard ThemePaletteCatalog.GrayAndBlue is dark only; the page's light Gray and Blue has no app counterpart.
GRAY_BLUE_DARK = {
    "--cp-bg": "#1F1F1F", "--cp-surface": "#141414", "--cp-surface-soft": "#2E2E2E", "--cp-border": "#404040",
    "--cp-text": "#F2F2F2", "--cp-text-muted": "#A6A6A6", "--cp-accent": "#3B7DD8", "--cp-accent-hover": "#8DB4E2",
    "--cp-accent-soft": "#24384F", "--cp-link": "#7FA7D4", "--cp-action": "#7FC8D9", "--cp-success": "#6CC497",
    "--cp-danger": "#F28B82", "--cp-warning": "#E08A1E",
}
SELECTORS = {
    ("purple", "light"): [":root"],
    ("purple", "dark"): [":root", 'html[data-theme="dark"]'],
    ("gray-blue", "light"): [":root", 'html[data-palette="gray-blue"]'],
    ("gray-blue", "dark"): [":root", 'html[data-theme="dark"]', 'html[data-palette="gray-blue"]',
                            'html[data-palette="gray-blue"][data-theme="dark"]'],
}
COMBINATIONS = list(SELECTORS)


def variables(theme, palette="purple"):
    """Resolve the custom properties for one palette and mode, applying matching blocks in cascade order."""
    source = (STATIC / "theme.css").read_text("utf-8")
    tokens = source[:source.index("* {")]
    blocks = re.findall(r"([^{}]+)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", tokens, flags=re.S))
    selected = {}
    for selector, body in blocks:
        if selector.strip() in SELECTORS[(palette, theme)]:
            selected.update(re.findall(r"(--cp-[\w-]+):\s*([^;]+);", body))
    return selected


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_palette_matches_maui_theme_palette_catalog(theme):
    selected = variables(theme)
    for key, value in PALETTES[theme].items():
        assert selected[key].upper() == value


def test_gray_blue_dark_matches_maui_gray_and_blue_palette():
    selected = variables("dark", "gray-blue")
    for key, value in GRAY_BLUE_DARK.items():
        assert selected[key].upper() == value


def test_gray_blue_light_drops_the_purple_accent():
    light = variables("light", "gray-blue")
    assert light["--cp-accent"].upper() != PALETTES["light"]["--cp-accent"]
    assert set(light) == set(variables("light"))


def luminance(value):
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return sum(channel * factor for channel, factor in zip(linear, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize("palette,theme", COMBINATIONS)
def test_primary_button_label_contrast_is_readable(palette, theme):
    selected = variables(theme, palette)
    foreground = luminance(selected["--cp-accent-fg"])
    for key in ("--cp-accent", "--cp-accent-hover"):
        background = luminance(selected[key])
        assert (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05) >= 4.5


@pytest.mark.parametrize("theme,matches,expected", [
    ("light", True, "light"), ("dark", False, "dark"),
    ("invalid", True, "dark"), ("", False, "light"), ("", True, "dark"),
])
def test_explicit_and_system_theme_selection(theme, matches, expected):
    html = (STATIC / "index.html").read_text("utf-8")
    inline = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    script = r"""
const vm = require("node:vm");
const assert = require("node:assert/strict");
const selected = {};
const sandbox = {
  URLSearchParams,
  window: {
    location: {search: process.argv[2] ? "?scoutTheme=" + process.argv[2] : ""},
    matchMedia: () => ({matches: process.argv[3] === "true", addEventListener() {}}),
  },
  document: {documentElement: {setAttribute(name, value) {selected[name] = value;}}},
};
vm.runInNewContext(process.argv[5], sandbox);
assert.equal(selected["data-theme"], process.argv[4]);
assert.equal(selected["data-palette"], "gray-blue");
"""
    result = subprocess.run(
        ["node", "-", theme, str(matches).lower(), expected, inline],
        input=script, text=True, capture_output=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("search,hash,expected", [
    ("", "", "gray-blue"),
    ("?scoutPalette=purple", "", "purple"),
    ("?scoutPalette=gray-blue", "", "gray-blue"),
    ("?scoutPalette=<script>", "", "gray-blue"),
    ("", "#view=project&palette=purple", "purple"),
    ("?scoutPalette=gray-blue", "#palette=purple", "purple"),
    ("?scoutPalette=purple", "#palette=invalid", "purple"),
])
def test_color_theme_defaults_to_gray_and_blue_and_honors_fragment_then_app(search, hash, expected):
    html = (STATIC / "index.html").read_text("utf-8")
    inline = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    script = r"""
const vm = require("node:vm");
const assert = require("node:assert/strict");
const selected = {};
const sandbox = {
  URLSearchParams,
  window: {
    location: {search: process.argv[2], hash: process.argv[3]},
    matchMedia: () => ({matches: false, addEventListener() {}}),
  },
  document: {documentElement: {setAttribute(name, value) {selected[name] = value;}}},
};
vm.runInNewContext(process.argv[5], sandbox);
assert.equal(selected["data-palette"], process.argv[4]);
"""
    result = subprocess.run(
        ["node", "-", search, hash, expected, inline],
        input=script, text=True, capture_output=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_color_theme_selector_sits_below_sign_in_with_both_choices():
    html = (STATIC / "index.html").read_text("utf-8")
    controls = html[html.index('<div class="auth-controls">'):html.index("</header>")]
    assert controls.index('id="sign-in"') < controls.index('<label for="color-theme">Color theme</label>')
    select = re.search(r'<select id="color-theme">(.*?)</select>', controls, re.S).group(1)
    assert re.findall(r'<option value="([^"]+)">([^<]+)</option>', select) == [
        ("gray-blue", "Gray and Blue"), ("purple", "Purple"),
    ]
    css = (STATIC / "theme.css").read_text("utf-8")
    assert ".theme-control { flex-basis: 100%;" in css
