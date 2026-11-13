"""Quickstart 04 shows how to reach the internal chat app: the Factory's point-to-site VPN (video 10, 2026-11-13).

The page said only "Connect your VPN", so a reader with a new Factory had no gateway profile and no client, and the
chat address resolved to a public IP that closes the connection.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = Path(os.environ.get("ESAF_QUICKSTART04", ROOT / "documentation" / "v2" / "quickstarts" / "04-first-agent-chat.md"))


def section(text: str, heading: str) -> str:
    start = text.index("\n## " + heading + "\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else len(text)]


def test_connect_section_comes_before_the_first_question():
    text = PAGE.read_text(encoding="utf-8")
    assert text.index("\n## Connect to the private network\n") < text.index("\n## Ask your first question\n")


def test_connect_section_installs_the_client_downloads_the_profile_and_imports_it():
    vpn = section(PAGE.read_text(encoding="utf-8"), "Connect to the private network")
    assert "winget install --id 9NP355QT2SQB" in vpn            # Azure VPN Client (Microsoft Store)
    assert "az network vnet-gateway vpn-client generate" in vpn
    assert "azurevpnconfig.xml" in vpn
    assert "**Import**" in vpn and "**Connect**" in vpn
    assert "$HOME\\Downloads" in vpn                            # the profile stays out of the Factory repository


def test_first_question_points_to_the_connect_section():
    ask = section(PAGE.read_text(encoding="utf-8"), "Ask your first question")
    assert "(#connect-to-the-private-network)" in ask