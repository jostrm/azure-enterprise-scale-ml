#!/usr/bin/env python3
"""Install the pinned Bicep CLI (the version test-bicep/ci/install-bicep.sh pins) on Linux or Windows x64.

Usage: python install_bicep.py <directory>   -> <directory>/bicep or <directory>/bicep.exe, checksum verified.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import sys
import urllib.request

VERSION = "0.44.1"
ASSETS = {
    "Linux": ("bicep-linux-x64", "bicep", "e17dc9a9888184886bb0c0051a3230b83b19f342749999f707bc571c3dfd2f45"),
    "Windows": ("bicep-win-x64.exe", "bicep.exe", "5153ab5898e70f1f822e0b844ae902a5acc5692f5a6303814af7b202e1072160"),
}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    system = platform.system()
    if system not in ASSETS or platform.machine().lower() not in ("x86_64", "amd64"):
        print(f"Unsupported platform {system} {platform.machine()}", file=sys.stderr)
        return 1
    asset, name, checksum = ASSETS[system]
    target = Path(sys.argv[1]) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/Azure/bicep/releases/download/v{VERSION}/{asset}"
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != checksum:
        print(f"Checksum mismatch for {url}: {digest}", file=sys.stderr)
        return 1
    target.write_bytes(data)
    os.chmod(target, 0o755)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
