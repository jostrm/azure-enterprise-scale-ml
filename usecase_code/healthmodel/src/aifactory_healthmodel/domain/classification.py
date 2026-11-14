"""Chain of Responsibility that turns discovered resources into model candidates.

Each handler either decides (returns a classification) or passes the resource to its
successor. The default chain mirrors the AI Factory rules: subscription guard, system
databases, nested health models, factory resource groups, catalog profiles, known
not-monitorable types, excluded plumbing types and finally "unmodelled".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Union

from ..naming import FactoryScope
from .resources import DiscoveredResource
from .signals import Profile, SignalCatalog

ORIGINS = ("project", "common", "model")


@dataclass(frozen=True)
class Candidate:
    """A resource a model definition may select: catalog profile plus where it lives."""

    resource: DiscoveredResource
    profile: Profile
    origin: str  # project | common | model (a nested health model)
    nested_definition: str | None = None
    nested_home: str | None = None

    @property
    def aifactory_scope(self) -> str:
        """Value of the ``aifactoryScope`` tag: the factory scope the resource belongs to."""
        return self.nested_home or self.origin


@dataclass(frozen=True)
class Unclassified:
    """A resource without a usable catalog profile (reported, never modelled)."""

    resource: DiscoveredResource
    origin: str
    reason: str  # unmodelled | not-monitorable


@dataclass(frozen=True)
class Dropped:
    resource: DiscoveredResource
    reason: str


Classification = Union[Candidate, Unclassified, Dropped]


@dataclass(frozen=True)
class ClassificationContext:
    scope: FactoryScope
    catalog: SignalCatalog
    model_name: str
    # definition key -> (model name pattern for every project, home of that definition)
    siblings: Mapping[str, tuple[re.Pattern, str]] = field(default_factory=dict)

    def origin_of(self, resource: DiscoveredResource) -> str | None:
        group = resource.resource_group.lower()
        if group == self.scope.project_resource_group.lower():
            return "project"
        if self.scope.common_resource_group and group == self.scope.common_resource_group.lower():
            return "common"
        return None

    def profile_of(self, resource: DiscoveredResource) -> Profile | None:
        return self.catalog.classify(resource.type, resource.kind, resource.hns)


class ClassificationHandler:
    """Base handler: delegates to the successor; the end of the chain drops the resource."""

    def __init__(self, successor: "ClassificationHandler | None" = None):
        self._successor = successor

    def handle(self, resource: DiscoveredResource, context: ClassificationContext) -> Classification:
        if self._successor is None:
            return Dropped(resource, "unhandled")
        return self._successor.handle(resource, context)


class SubscriptionGuard(ClassificationHandler):
    def handle(self, resource, context):
        if resource.subscription_id != context.scope.subscription_id.lower():
            return Dropped(resource, "other-subscription")
        return super().handle(resource, context)


class SystemDatabaseFilter(ClassificationHandler):
    def handle(self, resource, context):
        if resource.type == "microsoft.sql/servers/databases" and resource.short_name.lower() == "master":
            return Dropped(resource, "system-database")
        return super().handle(resource, context)


class NestedModelHandler(ClassificationHandler):
    """Health models of sibling definitions (for example every project model) become nestable."""

    def handle(self, resource, context):
        profile = context.profile_of(resource)
        if not (profile and profile.nested_model):
            return super().handle(resource, context)
        name = resource.name.lower()
        if name == context.model_name:
            return Dropped(resource, "self")
        for key, (pattern, home) in context.siblings.items():
            if pattern.fullmatch(name):
                return Candidate(resource, profile, "model", nested_definition=key, nested_home=home)
        return Dropped(resource, "unrelated-model")


class FactoryBoundary(ClassificationHandler):
    def handle(self, resource, context):
        if context.origin_of(resource) is None:
            return Dropped(resource, "outside-factory")
        return super().handle(resource, context)


class CatalogProfileHandler(ClassificationHandler):
    def handle(self, resource, context):
        profile = context.profile_of(resource)
        if profile is not None:
            return Candidate(resource, profile, context.origin_of(resource))
        return super().handle(resource, context)


class NotMonitorableHandler(ClassificationHandler):
    def handle(self, resource, context):
        if resource.type in context.catalog.not_monitorable:
            return Unclassified(resource, context.origin_of(resource), "not-monitorable")
        return super().handle(resource, context)


class ExcludedTypeHandler(ClassificationHandler):
    def handle(self, resource, context):
        if context.catalog.is_excluded(resource.type):
            return Dropped(resource, "excluded-type")
        return super().handle(resource, context)


class UnmodelledHandler(ClassificationHandler):
    def handle(self, resource, context):
        return Unclassified(resource, context.origin_of(resource), "unmodelled")


DEFAULT_HANDLERS = (SubscriptionGuard, SystemDatabaseFilter, NestedModelHandler, FactoryBoundary,
                    CatalogProfileHandler, NotMonitorableHandler, ExcludedTypeHandler, UnmodelledHandler)


def build_chain(*handler_types: type[ClassificationHandler]) -> ClassificationHandler:
    chain = None
    for handler_type in reversed(handler_types):
        chain = handler_type(chain)
    return chain


def default_chain() -> ClassificationHandler:
    return build_chain(*DEFAULT_HANDLERS)
