"""Opt-in, read-only negative authorization probes under real persona identities.

Supply PERSONA_AUTHORIZATION_CASES as a local JSON path. Each case contains
name, azure_config_dir (already authenticated), principal_id, tenant_id, subscription_id,
url, resource, expected_status and, for a 403, expected_error_code.
Never commit credentials, secret values or this tenant-specific case inventory.
"""

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytest


pytestmark = pytest.mark.integration


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError("Authorization probes must not redirect bearer tokens")


def _cases():
    if os.environ.get("LIVE_AZURE") != "1" or not os.environ.get("PERSONA_AUTHORIZATION_CASES"):
        return []
    return json.loads(Path(os.environ["PERSONA_AUTHORIZATION_CASES"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_real_persona_read_authorization(case):
    parsed = urlparse(case["url"])
    hosts = {
        "https://storage.azure.com/": r"[a-z0-9]{3,24}\.dfs\.core\.windows\.net",
        "https://vault.azure.net": r"[a-z0-9-]{3,24}\.vault\.azure\.net",
        "https://management.azure.com/": r"management\.azure\.com",
        "https://api.loganalytics.io": r"api\.loganalytics\.io",
    }
    assert case["resource"] in hosts and parsed.scheme == "https"
    assert re.fullmatch(hosts[case["resource"]], parsed.netloc)
    assert not parsed.username and not parsed.password and "sig=" not in parsed.query.lower()
    assert case["expected_status"] in (200, 403)
    executable = shutil.which("az")
    assert executable, "Azure CLI required"
    command = [executable]
    if Path(executable).suffix.lower() in (".cmd", ".bat"):
        command = [str(Path(executable).parent.parent / "python.exe"), "-X", "utf8", "-IBm", "azure.cli"]
    result = subprocess.run(
        [*command, "account", "get-access-token", "--subscription", case["subscription_id"],
         "--resource", case["resource"], "--output", "json", "--only-show-errors"],
        env={**os.environ, "AZURE_CONFIG_DIR": case["azure_config_dir"]},
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    assert result.returncode == 0, "Persona authentication failed; no token/error payload is logged"
    token = json.loads(result.stdout)
    assert token["tenant"].lower() == case["tenant_id"].lower()
    payload = token["accessToken"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["oid"].lower() == case["principal_id"].lower(), "Wrong test identity"
    request = Request(case["url"], method="GET", headers={
        "Authorization": "Bearer " + token["accessToken"], "x-ms-version": "2023-11-03",
    })
    try:
        with build_opener(NoRedirect).open(request, timeout=45) as response:
            status, error_code = response.status, ""
            # Deliberately discard content: authorization tests never log secrets or data.
    except HTTPError as error:
        status = error.code
        error_code = error.headers.get("x-ms-error-code", "")
        if status == 403 and not error_code:
            body = json.loads(error.read())
            detail = body.get("error", {})
            error_code = (detail.get("innererror") or {}).get("code") or detail.get("code", "")
    assert status == case["expected_status"], f"{case['name']}: unexpected HTTP {status}"
    if status == 403:
        assert case.get("expected_error_code"), "A network/firewall denial is not proof of persona authorization"
        assert error_code == case["expected_error_code"]
        assert error_code in {"AuthorizationPermissionMismatch", "ForbiddenByRbac", "AuthorizationFailed",
                              "InsufficientAccessError"}, "Generic/network denials are not authorization evidence"
