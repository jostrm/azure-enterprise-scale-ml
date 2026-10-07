"""Azure CLI JSON transport, including the Windows CLI Python distribution."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit


class AzureCLIError(RuntimeError):
    """CLI failure with HTTP metadata when ``az rest`` supplies it explicitly."""

    def __init__(self, message, *, status_code=None, error_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def _http_error(stderr):
    text = stderr.strip().replace("\r\n", "\n")
    status_code = 404 if text.startswith(("ERROR: Not Found(", "ERROR: Not Found\n")) else None
    error_code = None
    start = text.find("{")
    if start != -1:
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error_code = payload["error"].get("code")
    return status_code, error_code


def azure_cli(*args):
    executable = shutil.which("az")
    if not executable:
        raise FileNotFoundError("Azure CLI must be installed and authenticated")
    command = [executable]
    if Path(executable).suffix.lower() in (".cmd", ".bat"):
        runtime = Path(executable).parent.parent / "python.exe"
        if not runtime.is_file():
            raise FileNotFoundError("Azure CLI Python runtime is missing")
        command = [str(runtime), "-X", "utf8", "-IBm", "azure.cli"]
    result = subprocess.run(
        [*command, *args, "--output", "json", "--only-show-errors"],
        text=True, encoding="utf-8", capture_output=True, timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode:
        status_code, error_code = _http_error(result.stderr)
        raise AzureCLIError(f"Azure CLI {' '.join(args[:3])} failed: {result.stderr.strip()}",
                            status_code=status_code, error_code=error_code)
    return json.loads(result.stdout) if result.stdout.strip() else None


def role_assignments(cli, scope, subscription, *, include_inherited=False):
    """Read every ARM page without CLI role/principal name backfilling."""
    endpoint = f"https://management.azure.com{scope}/providers/Microsoft.Authorization/roleAssignments"
    url = endpoint + "?api-version=2022-04-01"
    if include_inherited:
        url += "&$filter=atScope()"
    expected = urlsplit(endpoint)
    assignments, seen = [], set()
    while url is not None:
        if not isinstance(url, str):
            raise ValueError("Invalid role assignment inventory continuation")
        parsed = urlsplit(url)
        if (parsed.scheme != expected.scheme or parsed.netloc != expected.netloc
                or parsed.path.lower() != expected.path.lower() or parsed.fragment or url in seen):
            raise ValueError("Invalid or repeated role assignment inventory continuation")
        seen.add(url)
        page = cli("rest", "--method", "get", "--url", url, "--subscription", subscription)
        if not isinstance(page, dict) or not isinstance(page.get("value"), list):
            raise ValueError("Azure role assignment inventory did not return an array")
        for item in page["value"]:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not isinstance(item.get("properties"), dict)):
                raise ValueError("Invalid Azure role assignment inventory entry")
            assignments.append({**item["properties"], "id": item["id"]})
        url = page.get("nextLink")
    return assignments
