"""Late project-pipeline step for the opt-in live voice of the AI Factory Agent chat application (project001 Dev).

Reads the pipeline variables by their exact names from the environment, validates them offline, and then plans
(Azure GET only) or applies (the agent's own ownership-checked operator commands). Disabled flags and Stage/Prod
runs exit cleanly without contacting Azure; invalid combinations fail instead of being ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_factory.agent_live_voice import (  # noqa: E402
    LiveVoiceIntegration, LiveVoiceRequest, decide, subprocess_runner)
from agent_factory.azure import AzureSession  # noqa: E402

INPUTS = (
    "enableFactoryChatAgent", "enableAIFactoryAgentLiveVoice",
    "enableContainerApps", "enableAIFoundry", "enableAISearch", "deleteAllServicesForProject", "deleteAllForProject",
    "dev_test_prod_sub_id", "tenantId", "dev_test_prod", "project_number_000", "admin_location",
    "admin_aifactoryPrefixRG", "projectPrefix", "admin_locationSuffix", "admin_aifactorySuffixRG",
    "projectSuffix", "projectResourceGroup", "modelGPTXName", "aifactoryAgentEntraAppId",
    "aifactoryAgentContainerAppsEnvironment", "aifactoryAgentReaderObjectIds", "aifactoryAgentVoiceName",
    "aifactoryAgentVoiceLanguages",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def work_directory(environ) -> Path:
    """Generated configuration and the isolated virtual environment live outside the repository checkout."""
    base = environ.get("RUNNER_TEMP") or environ.get("AGENT_TEMPDIRECTORY") or tempfile.gettempdir()
    return Path(base) / "aifactory-agent-live-voice"


def run(args, environ=os.environ, session_factory=AzureSession, runner=subprocess_runner) -> dict:
    request = LiveVoiceRequest.from_values({name: environ.get(name) for name in INPUTS})
    decision = decide(request)
    if args.command == "apply" and not args.apply:
        raise ValueError("apply requires --apply.")
    if not decision.act:
        return {"mode": "skipped", "reason": decision.reason, "mutations": False}
    if args.command == "validate":
        return {"mode": "validated", "reason": decision.reason, "voice": decision.voice, "mutations": False}
    session = session_factory(request.subscription_id, request.tenant_id)
    engine = LiveVoiceIntegration(session, runner, work_dir=work_directory(environ), repository_root=REPOSITORY_ROOT)
    return engine.run(request, apply=args.command == "apply")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "plan", "apply"])
    parser.add_argument("--apply", action="store_true", help="Required with apply; plan and validate never write.")
    try:
        result = run(parser.parse_args())
    except (ValueError, RuntimeError) as error:
        print(f"AI Factory Agent live voice configuration error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
