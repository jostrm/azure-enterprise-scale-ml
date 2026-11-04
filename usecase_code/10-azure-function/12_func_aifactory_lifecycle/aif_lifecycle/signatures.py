"""GitHub-style `X-Hub-Signature-256` HMAC signatures (the relay signs the same way GitHub does)."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable

_PREFIX = "sha256="


def sign(secret: bytes, body: bytes) -> str:
    return _PREFIX + hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify(secrets: Iterable[bytes], body: bytes, header: str | None) -> bool:
    """Constant-time check against every configured secret, so a secret can be rotated."""
    if not header or not header.startswith(_PREFIX):
        return False
    supplied = header[len(_PREFIX):].encode("ascii", "replace")
    matched = False
    for secret in secrets:
        if secret:
            matched |= hmac.compare_digest(sign(secret, body)[len(_PREFIX):].encode("ascii"), supplied)
    return matched
