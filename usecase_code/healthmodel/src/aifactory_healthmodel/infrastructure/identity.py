"""ARM transport with an azure-identity style credential (managed identity, workload identity, ...)."""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ..client import ARM
from .azure_cli import arm_error


class TokenTransport:
    """Calls ARM with a bearer token from any credential exposing ``get_token(scope)``."""

    def __init__(self, credential, timeout: int = 60):
        self.credential = credential
        self.timeout = timeout

    def request(self, method: str, url: str, body: dict | None = None):
        if not url.startswith(f"{ARM}/"):
            raise ValueError("Only Azure Resource Manager URLs are allowed.")
        token = self.credential.get_token(f"{ARM}/.default").token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method.upper(), headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            raise arm_error(subprocess.CompletedProcess([], 1, "", raw), f"{method.upper()} {urlsplit(url).path}",
                            status=error.code) from None
        return json.loads(payload) if payload else None
