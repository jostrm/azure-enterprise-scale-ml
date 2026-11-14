"""Small, credential-free readiness probe for the co-located Factory API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from .client import validate_http_url


class ReadinessProbe(Protocol):
    def ready(self) -> bool: ...


@dataclass(frozen=True)
class ApiReadinessProbe:
    api_url: str
    transport: httpx.BaseTransport | None = None

    def __post_init__(self):
        url = validate_http_url(self.api_url)
        object.__setattr__(self, "api_url", url)

    def ready(self) -> bool:
        try:
            with httpx.Client(
                timeout=2.0, follow_redirects=False, trust_env=False, transport=self.transport,
            ) as client:
                with client.stream("GET", self.api_url + "/health") as response:
                    if response.status_code != 200:
                        return False
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            return False
            data = json.loads(body)
            return isinstance(data, dict) and data.get("status") == "ok"
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
            return False
