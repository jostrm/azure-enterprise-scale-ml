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


def variables(theme):
    source = (STATIC / "theme.css").read_text("utf-8")
    block = source.split('html[data-theme="dark"]', 1)[0] if theme == "light" else source.split(
        'html[data-theme="dark"]', 1,
    )[1].split("}", 1)[0]
    return dict(re.findall(r"(--cp-[\w-]+):\s*([^;]+);", block))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_palette_matches_maui_theme_palette_catalog(theme):
    selected = variables(theme)
    for key, value in PALETTES[theme].items():
        assert selected[key].upper() == value


def luminance(value):
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return sum(channel * factor for channel, factor in zip(linear, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_primary_button_label_contrast_is_readable(theme):
    selected = variables(theme)
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
let selected;
const sandbox = {
  URLSearchParams,
  window: {
    location: {search: process.argv[2] ? "?scoutTheme=" + process.argv[2] : ""},
    matchMedia: () => ({matches: process.argv[3] === "true", addEventListener() {}}),
  },
  document: {documentElement: {setAttribute(name, value) {selected = value;}}},
};
vm.runInNewContext(process.argv[5], sandbox);
assert.equal(selected, process.argv[4]);
"""
    result = subprocess.run(
        ["node", "-", theme, str(matches).lower(), expected, inline],
        input=script, text=True, capture_output=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
