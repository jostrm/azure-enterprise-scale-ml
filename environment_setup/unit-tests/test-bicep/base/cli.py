"""Base layer: thin wrappers around external CLIs used for verification.

Strategy: prefer bash + CLIs (az, nslookup) over PowerShell. Every command
runs through ``run`` so tests can mock a single seam. Nothing here knows about
AI Factory; it only shells out and returns structured results.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class CmdResult:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run(args: list[str], timeout: int = 120) -> CmdResult:
    """Run a command and capture output. Single mock seam for all CLI calls."""
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CmdResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def az(args: list[str], timeout: int = 180) -> CmdResult:
    """Run `az ...`. Add `-o json` at call sites when JSON is expected."""
    return run(["az", *args], timeout=timeout)


def az_json(args: list[str], timeout: int = 180):
    res = az([*args, "-o", "json"], timeout=timeout)
    if not res.ok or not res.stdout:
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return None


def nslookup(host: str, timeout: int = 30) -> CmdResult:
    """Resolve a hostname; used to assert private-endpoint DNS resolution."""
    return run(["nslookup", host], timeout=timeout)


def resolves_to_private_ip(host: str) -> bool:
    """True when host resolves to RFC1918 space (private endpoint in effect)."""
    res = nslookup(host)
    if not res.ok:
        return False
    out = res.stdout
    return any(p in out for p in ("10.", "172.16.", "172.17.", "192.168."))
