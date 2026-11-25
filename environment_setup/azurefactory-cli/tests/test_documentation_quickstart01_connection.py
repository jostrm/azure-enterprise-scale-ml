"""Quickstart 01 connects the CLI to the Factory API the way each option really starts it (video 10, 2026-11-12).

The ESAF Tutorial Guide (option A) starts its API on a new port every time and its Type connection button types the
address and the key into PowerShell, while the AIFactory Config Wizard (option B) listens on 8765 with a key the
reader chose. A single fixed 8765 + Read-Host block sent option A readers to a port where nothing listens.
"""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = Path(os.environ.get("ESAF_QUICKSTART01", ROOT / "documentation" / "v2" / "quickstarts" / "01-install-esaf.md"))


def tab(text: str, name: str) -> str:
    match = re.search(r'<details markdown="1" data-factory-tool="' + re.escape(name) + r'"[^>]*>(.*?)</details>',
                      text, re.S)
    assert match, name
    return match.group(1)


def test_powershell_tab_connects_option_a_with_type_connection_and_keeps_8765_for_option_b():
    text = PAGE.read_text(encoding="utf-8")
    powershell = tab(text, "CLI (PowerShell)")
    option_a = powershell.index("Option A")
    option_b = powershell.index("Option B")
    assert "Type connection" in powershell[option_a:option_b]
    assert powershell.index("'http://127.0.0.1:8765'") > option_b
    assert "If you forgot to save key" not in text


def test_option_a_says_the_port_changes_and_how_to_connect():
    text = PAGE.read_text(encoding="utf-8")
    start = text.index("Option A) Windows")
    section = text[start:text.index("</details>", start)]
    assert "new port every time" in section
    assert "Type connection" in section

def test_option_c_starts_the_packaged_api_host_from_the_command_line():
    """Videos 20a-c (2026-11-25): the Factory API starts without a window, from PowerShell, with a key the
    reader never sees (aifactory-config.exe --api-host, pink v0.47.107+)."""
    text = PAGE.read_text(encoding="utf-8")
    start = text.index("Option C) Windows - Start from the command line")
    section = text[start:text.index("</details>", start)]
    for needle in ("v0.47.107", "aifactory-config-windows.zip", "Expand-Archive", "RandomNumberGenerator",
                   "$env:AIFACTORY_API_KEY", "'--api-host', '--port', '8765'", "-PassThru",
                   "Invoke-RestMethod http://127.0.0.1:8765/health", "Stop-Process -Id $api.Id"):
        assert needle in section, needle
    assert "Write-Host $env:AIFACTORY_API_KEY" not in section and "echo $env:AIFACTORY_API_KEY" not in section


def test_powershell_tab_connects_option_c_in_the_same_window():
    powershell = tab(PAGE.read_text(encoding="utf-8"), "CLI (PowerShell)")
    option_c = powershell.index("Option C")
    assert "same PowerShell window" in powershell[option_c:]
    assert "$env:AIFACTORY_API_URL = 'http://127.0.0.1:8765'" in powershell[option_c:]
