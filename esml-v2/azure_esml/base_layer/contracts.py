"""Customer-independent contracts for workspace operations and folder discovery."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
from uuid import UUID


@dataclass(frozen=True)
class WorkspaceTarget:
    tenant_id: str
    subscription_id: str
    resource_group: str
    workspace_name: str

    def __post_init__(self):
        for field in ("tenant_id", "subscription_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
            ):
                raise ValueError(f"{field} must be a hyphenated UUID")
            object.__setattr__(self, field, str(UUID(value)))
        for field in ("resource_group", "workspace_name"):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}", value)
                or value.endswith(".")
            ):
                raise ValueError(f"{field} must be a nonempty, safe resource identifier")


class MLBackend(ABC):
    @abstractmethod
    def submit(self, document: dict, base_path: Path) -> dict:
        """Submit an explicit job document; resolve local paths against base_path."""

    @abstractmethod
    def get_job(self, name: str) -> dict:
        """Read a job's small, serializable metadata record."""

    @abstractmethod
    def list_jobs(self, limit: int = 100) -> list[dict]:
        """Read at most limit recent jobs, without an experiment server filter."""

    @abstractmethod
    def download_job(self, name: str, destination: Path, output_name: str) -> None:
        """Download one named output into a new destination; never overwrite one."""

    @abstractmethod
    def ensure_datastore(self, definition: dict) -> dict:
        """Create a missing credentialless store or verify an identical existing one."""

    @abstractmethod
    def get_datastore(self, name: str) -> dict:
        """Read datastore binding metadata without provisioning or changing it."""

    @abstractmethod
    def register_data(self, definition: dict) -> dict:
        """Register an explicit immutable data version, or reuse matching metadata."""

    @abstractmethod
    def get_data(self, name: str, version: str) -> dict:
        """Read an explicit data version, never a label."""

    @abstractmethod
    def get_model(self, name: str, version: str) -> dict:
        """Read an explicit model version, never a label."""

    @abstractmethod
    def register_model(self, definition: dict) -> dict:
        """Register a model; omit version to let Azure assign a candidate version."""

    @abstractmethod
    def publish(
        self, component: dict, endpoint: dict, deployment: dict, base_path: Path, *,
        reuse_component: bool = False,
    ) -> dict:
        """Publish without changing endpoint defaults.

        Existing component versions fail unless reuse_component explicitly selects
        the registered version instead of the supplied component implementation.
        """

    @abstractmethod
    def invoke(self, endpoint_name: str, deployment_name: str, inputs: dict, outputs: dict) -> dict:
        """Invoke a named deployment with typed path bindings or scalar inputs.

        Local input paths are relative to the current working directory. Typed
        literals use {"type": "integer", "default": 1}, for example.
        """


class IFolderCatalog(ABC):
    @abstractmethod
    def list_folders(self, prefix: str) -> tuple[str, ...]:
        """Return sorted direct child folder names, not files or recursive paths."""
