"""Azure CLI JSON transport, including the Windows CLI Python distribution."""

import json
import os
from pathlib import Path
import shutil
import subprocess


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
