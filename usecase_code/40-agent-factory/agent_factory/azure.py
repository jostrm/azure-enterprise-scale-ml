"""Small OAuth-only Azure transport; never changes the Azure CLI's active account."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ARM = "https://management.azure.com"
ARM_API = "2025-06-01"


class AzureError(RuntimeError):
    def __init__(self, status: int, method: str, url: str, detail: str):
        self.status = status
        super().__init__(f"{method} {url}: HTTP {status}: {detail}")


class _NoOAuthRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError("Azure redirected an authenticated request; refusing to forward its bearer token.")


class AzureSession:
    def __init__(self, subscription_id: str, tenant_id: str):
        self.subscription_id = subscription_id
        self.tenant_id = tenant_id
        self._tokens: dict[str, tuple[float, str]] = {}

    def token(self, audience: str) -> str:
        cached = self._tokens.get(audience)
        if cached and cached[0] > time.time() + 120:
            return cached[1]
        executable = shutil.which("az")
        if not executable:
            raise RuntimeError("Azure CLI is required. Install it, then use browser-based az login.")
        result = subprocess.run(
            [executable, "account", "get-access-token", "--subscription", self.subscription_id,
             "--resource", audience, "--output", "json", "--only-show-errors"],
            capture_output=True, text=True, check=False, timeout=90,
        )
        if result.returncode:
            raise RuntimeError(
                f"OAuth unavailable for tenant {self.tenant_id}. Use browser-based "
                f"'az login --tenant {self.tenant_id}' (not device-code login).\n{result.stderr.strip()}"
            )
        document = json.loads(result.stdout)
        if document["tenant"].lower() != self.tenant_id.lower():
            raise RuntimeError("Azure CLI returned a token for a different tenant; refusing the request.")
        self._tokens[audience] = (float(document["expires_on"]), document["accessToken"])
        return document["accessToken"]

    def request(
        self, method: str, url: str, body: dict | None = None, *,
        audience: str = ARM, headers: dict[str, str] | None = None,
    ) -> dict:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("Azure requests require an HTTPS endpoint without embedded credentials.")
        request_headers = {
            "Authorization": f"Bearer {self.token(audience)}", "Accept": "application/json",
            "Content-Type": "application/json", **(headers or {}),
        }
        payload = None if body is None else json.dumps(body).encode("utf-8")
        # Retrying creates can duplicate agent versions or charge for inference.
        attempts = 4 if method.upper() in {"GET", "PUT", "HEAD"} else 1
        for attempt in range(attempts):
            request = Request(url, data=payload, headers=request_headers, method=method)
            try:
                with build_opener(_NoOAuthRedirects()).open(request, timeout=90) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else {}
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 502, 503, 504} and attempt + 1 < attempts:
                    delay = exc.headers.get("Retry-After", "")
                    time.sleep(min(float(delay), 30) if delay.isdecimal() else 2 ** attempt)
                    continue
                raise AzureError(exc.code, method, url, detail) from exc
        raise RuntimeError("Azure retry budget exhausted.")

    def arm(self, method: str, resource_id: str, body: dict | None = None,
            api_version: str = ARM_API) -> dict:
        return self.request(method, f"{ARM}{resource_id}?{urlencode({'api-version': api_version})}", body)

    def pages(self, url: str, *, audience: str = ARM, field: str = "value") -> list[dict]:
        origin = urlsplit(url).netloc
        seen: set[str] = set()
        items: list[dict] = []
        while url:
            if url in seen or urlsplit(url).netloc != origin or urlsplit(url).scheme != "https":
                raise RuntimeError("Invalid Azure continuation URL; refusing to forward credentials.")
            seen.add(url)
            page = self.request("GET", url, audience=audience)
            items.extend(page[field])
            url = page.get("nextLink") or page.get("next_link") or ""
        return items
