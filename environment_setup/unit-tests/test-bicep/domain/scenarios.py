"""Domain layer: AI Factory deployment concepts shared across all tests.

Once-and-only-once definitions of network modes, BYO modes, the service
enable-flag matrix, and named scenarios. Tests reference these instead of
duplicating flag lists. Pure data + builders, no Azure calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NetworkMode(str, Enum):
    PRIVATE = "private"   # fully private endpoints, no public access
    HYBRID = "hybrid"     # private data plane, public control plane / UI
    PUBLIC = "public"     # public access enabled (dev/test)


class ByoMode(str, Enum):
    NONE = "none"            # AI Factory creates vNet + subnets
    VNET_ONLY = "byo_vnet"   # bring vNet, AI Factory creates subnets
    SUBNETS = "byo_subnets"  # bring vNet + subnets
    ASE = "byo_ase"          # bring App Service Environment v3


# Every ENABLE_* service flag exposed in .env.template / variables.yaml.
SERVICE_FLAGS: tuple[str, ...] = (
    "ENABLE_AI_FOUNDRY",
    "ENABLE_AI_SEARCH",
    "ENABLE_AZURE_OPENAI",
    "ENABLE_AZURE_AI_VISION",
    "ENABLE_AZURE_SPEECH",
    "ENABLE_AI_DOC_INTELLIGENCE",
    "ENABLE_CONTENT_SAFETY",
    "ENABLE_BING",
    "ENABLE_AZURE_MACHINE_LEARNING",
    "ENABLE_AKS_FOR_AZURE_ML",
    "ENABLE_AKS",
    "ENABLE_DATABRICKS",
    "ENABLE_DATAFACTORY",
    "ENABLE_COSMOS_DB",
    "ENABLE_POSTGRESQL",
    "ENABLE_REDIS_CACHE",
    "ENABLE_SQL_DATABASE",
    "ENABLE_ELASTICSEARCH",
    "ENABLE_FUNCTION",
    "ENABLE_WEBAPP",
    "ENABLE_CONTAINER_APPS",
    "ENABLE_LOGIC_APPS",
    "ENABLE_EVENT_HUBS",
    "ENABLE_BOT_SERVICE",
)

# Networking flags toggled by NetworkMode.
NETWORK_FLAGS: tuple[str, ...] = (
    "ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET",
    "ENABLE_PUBLIC_GENAI_ACCESS",
    "ENABLE_PUBLIC_ACCESS_WITH_PERIMETER",
)


@dataclass
class Scenario:
    name: str
    network: NetworkMode = NetworkMode.PRIVATE
    byo: ByoMode = ByoMode.NONE
    services: dict[str, bool] = field(default_factory=dict)

    def env_overrides(self) -> dict[str, str]:
        """Materialize this scenario as .env-style overrides for a deploy."""
        public = self.network in (NetworkMode.HYBRID, NetworkMode.PUBLIC)
        out = {f: ("true" if public else "false") for f in NETWORK_FLAGS}
        out["BYO_SUBNETS"] = "true" if self.byo == ByoMode.SUBNETS else "false"
        out.update({k: ("true" if v else "false") for k, v in self.services.items()})
        return out


def all_enabled() -> Scenario:
    return Scenario("all_enabled", services={f: True for f in SERVICE_FLAGS})


def all_disabled() -> Scenario:
    return Scenario("all_disabled", services={f: False for f in SERVICE_FLAGS})


def matrix() -> list[Scenario]:
    """Named scenarios covering the IaC paths requested for unit testing."""
    return [
        all_enabled(),
        all_disabled(),
        *(Scenario(f"net_{m.value}", network=m) for m in NetworkMode),
        *(Scenario(f"byo_{b.value}", byo=b) for b in ByoMode),
    ]
