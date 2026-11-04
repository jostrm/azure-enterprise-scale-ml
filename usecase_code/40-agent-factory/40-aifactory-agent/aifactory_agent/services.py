from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import RLock
from typing import Callable, Mapping

from .config import Settings
from .ports import ConversationPort, CostPort, DualGraphPort, FactoryToolPort, KnowledgePort, OperationStorePort, WorkloadPort
from .security import Principal, principal_from_token


def _knowledge(settings: Settings) -> KnowledgePort:
    from .knowledge import Knowledge
    return Knowledge(settings)


def _dual_graph(settings: Settings) -> DualGraphPort:
    from .graph_service import GraphQueryService
    return GraphQueryService(settings)


def _store(settings: Settings) -> OperationStorePort:
    from .operations import OperationStore
    return OperationStore(settings, namespace=settings.agent_name)


def _costs(settings: Settings, principal: Principal, scope_key: str) -> CostPort:
    from .costs import CostSkills
    return CostSkills(settings, principal, scope_key)


def _workloads(settings: Settings, principal: Principal, scope_key: str,
               store: OperationStorePort) -> WorkloadPort:
    from .workloads import WorkloadSkills
    return WorkloadSkills(settings, principal, scope_key, store)


def _conversation(settings: Settings, knowledge: KnowledgePort,
                  tools: Callable[[Principal, str], FactoryToolPort],
                  dual_graph: DualGraphPort | None = None) -> ConversationPort:
    from .foundry import Conversation
    return Conversation(settings, knowledge, tool_factory=tools, dual_graph=dual_graph)


@dataclass(frozen=True)
class AgentDependencies:
    knowledge_factory: Callable[[Settings], KnowledgePort] = _knowledge
    operation_store_factory: Callable[[Settings], OperationStorePort] = _store
    tool_factory: Callable[[Settings, Principal, str, OperationStorePort], FactoryToolPort] | None = None
    cost_factory: Callable[[Settings, Principal, str], CostPort] = _costs
    workload_factory: Callable[[Settings, Principal, str, OperationStorePort], WorkloadPort] = _workloads
    conversation_factory: Callable[
        [Settings, KnowledgePort, Callable[[Principal, str], FactoryToolPort]], ConversationPort
    ] = _conversation
    authenticate: Callable[[Settings, str], Principal] = principal_from_token
    dual_graph_factory: Callable[[Settings], DualGraphPort] = _dual_graph
    graph_conversation_factory: Callable[
        [Settings, KnowledgePort, Callable[[Principal, str], FactoryToolPort], DualGraphPort], ConversationPort
    ] | None = None


class AgentServices:
    """Per-agent composition root; shared services never hold a requesting principal."""

    def __init__(self, settings: Settings, *, dependencies: AgentDependencies | None = None):
        self.settings = Settings.model_validate(settings.model_dump(mode="python"))
        self.dependencies = dependencies if dependencies is not None else AgentDependencies()
        self._knowledge: KnowledgePort | None = None
        self._dual_graph: DualGraphPort | None = None
        self._store: OperationStorePort | None = None
        self._lock = RLock()

    def knowledge(self) -> KnowledgePort:
        with self._lock:
            if self._knowledge is None:
                self._knowledge = self.dependencies.knowledge_factory(self.settings)
            return self._knowledge

    def operation_store(self) -> OperationStorePort:
        with self._lock:
            if self._store is None:
                self._store = self.dependencies.operation_store_factory(self.settings)
            return self._store

    def dual_graph(self) -> DualGraphPort:
        with self._lock:
            if self._dual_graph is None:
                self._dual_graph = self.dependencies.dual_graph_factory(self.settings)
            return self._dual_graph

    def tools(self, principal: Principal, scope_key: str, *,
              store: OperationStorePort | None = None) -> FactoryToolPort:
        store = store if store is not None else self.operation_store()
        if self.dependencies.tool_factory is not None:
            return self.dependencies.tool_factory(self.settings, principal, scope_key, store)
        from .tools import FactoryTools
        return FactoryTools(
            self.settings, principal, scope_key, operation_store=store,
            cost_factory=lambda settings, caller, scope, cred:
                self.dependencies.cost_factory(settings, caller, scope),
            workload_factory=self.dependencies.workload_factory,
        )

    def costs(self, principal: Principal, scope_key: str) -> CostPort:
        return self.dependencies.cost_factory(self.settings, principal, scope_key)

    def workloads(self, principal: Principal, scope_key: str, *,
                  store: OperationStorePort | None = None) -> WorkloadPort:
        return self.dependencies.workload_factory(
            self.settings, principal, scope_key, store if store is not None else self.operation_store(),
        )

    def conversation(self, knowledge: KnowledgePort | None = None) -> ConversationPort:
        knowledge = knowledge if knowledge is not None else self.knowledge()
        factory = self.dependencies.graph_conversation_factory
        if factory is not None:
            return factory(self.settings, knowledge, self.tools, self.dual_graph())
        if self.dependencies.conversation_factory is _conversation:
            return _conversation(self.settings, knowledge, self.tools, self.dual_graph())
        return self.dependencies.conversation_factory(self.settings, knowledge, self.tools)

    def authenticate(self, token: str) -> Principal:
        return self.dependencies.authenticate(self.settings, token)


class AgentServiceFactory(ABC):
    @abstractmethod
    def create(self, profile: str) -> AgentServices:
        """Create an independent composition for an explicitly configured agent."""


class AgentFactory(AgentServiceFactory):
    def __init__(self, profiles: Mapping[str, Settings], *,
                 dependencies: Mapping[str, AgentDependencies] | None = None):
        if not profiles:
            raise ValueError("Configure at least one agent profile.")
        self._profiles = {key: Settings.model_validate(value.model_dump(mode="python")) for key, value in profiles.items()}
        identities = [
            (settings.tenant_id, settings.azure.storage_endpoint, settings.azure.storage_container, settings.agent_name)
            for settings in self._profiles.values()
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Agent profiles sharing storage must have distinct agent names.")
        self._dependencies = dict(dependencies or {})
        if self._dependencies.keys() - self._profiles.keys():
            raise ValueError("Dependencies reference an unknown agent profile.")

    def create(self, profile: str) -> AgentServices:
        if profile not in self._profiles:
            raise ValueError(f"Unknown agent profile: {profile}")
        return AgentServices(self._profiles[profile], dependencies=self._dependencies.get(profile))
