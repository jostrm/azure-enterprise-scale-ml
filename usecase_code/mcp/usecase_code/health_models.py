"""Register an additional health strategy without changing MCP dispatch or transport."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from aifactory_mcp.health import HealthDefinition, HealthModel, HealthProbe, default_health_models
from aifactory_mcp.runtime import load_runtime
from aifactory_mcp.server import create_server, run_stdio


class VersionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: str = Field(min_length=1, max_length=80)


@dataclass(frozen=True)
class ApiVersionHealthModel:
    probe: HealthProbe
    definition: HealthDefinition = HealthDefinition(
        "health_api_version",
        "Compare the observed Factory API version with an expected version. This is not deployment readiness.",
        VersionArguments,
    )

    def evaluate(self, arguments: Mapping[str, object]) -> dict[str, object]:
        observation = self.probe.api_health()
        if observation.get("ok") is not True:
            return observation
        data = observation.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("version"), str):
            return {"ok": False, "error": {
                "code": "invalid_factory_contract",
                "message": "The API did not provide a version observation.", "status_code": 502,
            }}
        version = data["version"]
        return {"ok": True, "data": {
            "status": "healthy" if version == arguments["expected_version"] else "degraded",
            "observed_version": version, "expected_version": arguments["expected_version"],
            "coverage": "API version compatibility only; not Azure deployment readiness.",
        }}


def health_models(probe: HealthProbe) -> tuple[HealthModel, ...]:
    return (*default_health_models(probe), ApiVersionHealthModel(probe))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--repository-root")
    options = parser.parse_args(argv)
    runtime = load_runtime(
        options.config, options.repository_root, health_models_factory=health_models,
    )
    asyncio.run(run_stdio(create_server(runtime, options.scope, object_id=options.object_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
