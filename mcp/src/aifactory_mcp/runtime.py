"""Load the checkout's governed agent and SDK without ambient identity selection."""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from uuid import UUID

from .health import HealthModelFactory, default_health_models
from .auth import (
    ApplicationPrincipal, ApplicationTokenVerifier, AudienceTokenVerifier,
    DelegatedTokenVerifier, TokenVerifier, load_application_auth,
)


_AGENT = Path("usecase_code") / "40-agent-factory" / "40-aifactory-agent"
_SDK = Path("environment_setup") / "azurefactory-cli" / "src"
_IMPORT_LOCK = threading.RLock()


def _repository(root: str | Path | None) -> Path:
    candidates = [Path(root).expanduser().resolve()] if root is not None else Path(__file__).resolve().parents
    for candidate in candidates:
        if ((candidate / _AGENT / "aifactory_agent" / "config.py").is_file()
                and (candidate / _SDK / "azurefactory" / "client.py").is_file()):
            return candidate
    raise RuntimeError(
        "A repository checkout containing the actual AI Factory agent and AzureFactory SDK is required; "
        "set repository_root explicitly when installed away from the checkout."
    )


def _trusted_package(name: str, source: Path) -> None:
    package = (source / name).resolve()
    for loaded_name, module in tuple(sys.modules.items()):
        if loaded_name == name or loaded_name.startswith(name + "."):
            filename = getattr(module, "__file__", None)
            if filename is None or not Path(filename).resolve().is_relative_to(package):
                raise RuntimeError("An agent or SDK module was loaded from outside the configured repository.")
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, package / "__init__.py", submodule_search_locations=[str(package)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("The configured repository package cannot be loaded.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        loaded = False
        try:
            spec.loader.exec_module(module)
            loaded = True
        finally:
            if not loaded:
                sys.modules.pop(name, None)
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


@dataclass(frozen=True)
class Runtime:
    settings: object
    repository_root: Path
    tools: ModuleType
    operations: ModuleType
    skills: ModuleType
    security: ModuleType
    costs: ModuleType
    sdk: ModuleType
    health_models_factory: HealthModelFactory = default_health_models
    token_verifier: TokenVerifier | None = None
    graph_only: bool = False

    def local_principal(self, object_id: str):
        """Trusted local stdio/approval CLI only; never use this for network callers."""
        try:
            if not isinstance(object_id, str):
                raise ValueError
            identity = UUID(object_id)
            if not identity.int:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("An explicit, nonzero operator object UUID is required.") from None
        return self.security.Principal(tenant_id=self.settings.tenant_id, object_id=str(identity))

    def principal_from_token(self, token: str):
        if self.token_verifier is not None:
            return self.token_verifier.verify(token)
        return self.security.principal_from_token(self.settings, token)

    def backend(self, principal, scope_key: str):
        from .backend import AgentBackend
        from .access import ReadOnlyApplicationBackend
        from .graph import GraphOnlyBackend

        backend_type = GraphOnlyBackend if self.graph_only else AgentBackend
        if isinstance(principal, ApplicationPrincipal):
            if scope_key not in principal.scope_keys:
                raise PermissionError("The application identity is not permitted in this scope.")
            return ReadOnlyApplicationBackend(
                backend_type(self, principal.principal, scope_key), principal.allowed_tools,
            )
        return backend_type(self, principal, scope_key)


def load_runtime(
    agent_config: str | Path, repository_root: str | Path | None = None, *,
    health_models_factory: HealthModelFactory = default_health_models,
    application_auth: str | Path | None = None,
    graph_only: bool = False,
) -> Runtime:
    root = _repository(repository_root)
    try:
        with _IMPORT_LOCK:
            _trusted_package("azurefactory", root / _SDK)
            _trusted_package("aifactory_agent", root / _AGENT)
            config = importlib.import_module("aifactory_agent.config")
            modules = {name: importlib.import_module(f"aifactory_agent.{name}") for name in
                       ("tools", "operations", "skills", "security", "costs")}
            sdk = importlib.import_module("azurefactory.client")
            # FactoryTools' fixed CLI subprocess inherits PYTHONPATH, not this process's sys.path.
            sdk_source = str(root / _SDK)
            inherited = [value for value in os.environ.get("PYTHONPATH", "").split(os.pathsep)
                         if value and value != sdk_source]
            os.environ["PYTHONPATH"] = os.pathsep.join([sdk_source, *inherited])
        # An explicit filename avoids load_settings' environment-config fallback.
        settings = config.load_settings(Path(agent_config).expanduser().resolve())
    except (ImportError, OSError, ValueError, TypeError):
        raise RuntimeError(
            "The agent runtime could not be loaded. Check the explicit configuration, repository, "
            "and installed shared agent dependencies."
        ) from None
    runtime = Runtime(settings=settings, repository_root=root, sdk=sdk,
                      health_models_factory=health_models_factory, graph_only=graph_only, **modules)
    if application_auth is None:
        return runtime
    policy = load_application_auth(application_auth)
    from .policy import GRAPH_APPLICATION_TOOLS

    for identity in policy.identities:
        grants = [grant for grant in settings.auth.grants if grant.object_id == identity.object_id]
        if any(set(grant.permissions) - {"factory.read", "cost.read", "graph.read"} for grant in grants):
            raise ValueError("Application identity grants must contain read-only permissions only.")
        required = {"graph.read"} if graph_only else {"factory.read"}
        if graph_only and not set(identity.allowed_tools) <= GRAPH_APPLICATION_TOOLS:
            raise ValueError("Graph-only application identities may allow only explicit graph tools.")
        if any(tool.startswith("cost_") for tool in identity.allowed_tools):
            required.add("cost.read")
        if GRAPH_APPLICATION_TOOLS.intersection(identity.allowed_tools):
            required.add("graph.read")
            graph = getattr(settings, "dual_graph", None)
            if not graph or not set(identity.scope_keys) <= set(graph.allowed_scopes):
                raise ValueError("Application graph tools require explicit enabled graph scope configuration.")
        for scope in identity.scope_keys:
            permissions = {
                permission for grant in grants if scope in grant.scopes for permission in grant.permissions
            }
            if scope not in settings.scopes or not required <= permissions:
                raise ValueError("Application identities require explicit matching read-only scope grants.")
    verifier = AudienceTokenVerifier(
        DelegatedTokenVerifier(lambda token: modules["security"].principal_from_token(settings, token)),
        settings.auth.audience,
        ApplicationTokenVerifier(
            settings.tenant_id, policy,
            lambda tenant, caller: modules["security"].Principal(tenant_id=tenant, object_id=caller),
        ),
    )
    return replace(runtime, token_verifier=verifier)
