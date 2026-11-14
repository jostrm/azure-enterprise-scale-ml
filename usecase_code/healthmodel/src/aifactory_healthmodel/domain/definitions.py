"""Health model definitions: what a model contains and how it is laid out.

* ``ModelDefinition.plan`` is a Template Method: naming, overrides, classification,
  layer assignment, signal-source filtering, ordering, building, validation and coverage
  always run in the same order; subclasses override hooks such as ``assign``.
* ``LayeredModelDefinition`` is the declarative kind used by ``definitions/*.json``.
* ``ModelDefinitionFactory`` creates definitions by ``kind`` (parameterised Factory Method).
* ``DefinitionRegistry`` loads built-in and consumer definitions (External Configuration
  Store), validates cross references and orders deployments so nested models come first.
* Definitions are immutable Prototypes: ``clone(**changes)`` derives a variant.
"""
from __future__ import annotations

import dataclasses
import json
import re
import string
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .. import catalog as raw
from ..naming import TOKEN_TEMPLATE, FactoryScope
from .builder import HealthModelBuilder
from .classification import Candidate, ClassificationContext, ClassificationHandler, Unclassified, default_chain
from .coverage import CoverageAnalyzer
from .layout import LayoutStrategy, TieredLayout
from .model import breadth_first
from .overrides import OverrideSet
from .plan import ModelPlan, PlannedEntity
from .policy import validate_alert_policy, validate_health_objective
from .resources import DiscoveredResource
from .selectors import SelectorParser, Selector
from .signals import Layer, SignalCatalog
from .visitors import PayloadVisitor, ValidationVisitor, relationships

DEFINITIONS_DIR = raw.HEALTHMODEL_ROOT / "definitions"
DEFINITION_FIELDS = frozenset({
    "$schema", "key", "kind", "description", "nameToken", "home", "rootDisplayName", "reportCoverage",
    "layers", "overrides", "alertPolicy", "healthObjective",
})
KEY_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,30}")
# Layer entities are named layer-<key>; entity names must end with a letter or digit.
LAYER_KEY_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,39}[a-z0-9]")
HOMES = ("project", "common")
PLACEHOLDERS = frozenset({"project", "env"})
WORKSPACE_ID = re.compile(r"/subscriptions/[0-9a-f-]{36}/resourceGroups/([\w().-]{1,90})/providers/"
                          r"Microsoft\.OperationalInsights/workspaces/[\w-]{4,63}", re.I)


class DefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class LayerSpec:
    selector: Selector
    layer: Layer | None = None  # None: the catalog layer of the selected profile

    @property
    def from_catalog(self) -> bool:
        return self.layer is None


@dataclass(frozen=True)
class DefinitionSpec:
    key: str
    name_token: str
    home: str
    root_display_name: str
    layers: tuple[LayerSpec, ...]
    kind: str = "layered"
    description: str = ""
    report_coverage: bool = False
    overrides: dict = field(default_factory=dict)
    alert_policy: dict = field(default_factory=dict)
    health_objective: int | None = None
    nests: frozenset[str] = frozenset()
    source: str = "<memory>"


@dataclass(frozen=True)
class PlanningRequest:
    scope: FactoryScope
    resources: tuple[DiscoveredResource, ...]
    overrides: OverrideSet | None = None
    workspace: str | None = None
    model_name: str | None = None
    siblings: Mapping[str, tuple[re.Pattern, str]] = field(default_factory=dict)


def parse_definition(document, catalog: SignalCatalog, source: str = "<memory>") -> DefinitionSpec:
    """Validate a JSON definition document strictly and return its immutable spec."""
    try:
        return _parse(document, catalog, source)
    except DefinitionError:
        raise
    except ValueError as error:
        raise DefinitionError(f"{source}: {error}") from None


def validate_spec(spec: DefinitionSpec, catalog: SignalCatalog) -> DefinitionSpec:
    """The one validation of a definition, whether parsed from JSON, cloned or created in code."""
    try:
        _validate(spec, catalog)
    except DefinitionError:
        raise
    except ValueError as error:
        raise DefinitionError(f"{spec.source}: {error}") from None
    return spec


def _parse(document, catalog: SignalCatalog, source: str) -> DefinitionSpec:
    if not isinstance(document, dict):
        raise ValueError("A model definition must be a JSON object.")
    unknown = set(document) - DEFINITION_FIELDS
    if unknown:
        raise ValueError(f"Unknown definition field(s): {sorted(unknown)}")
    _check_identity(document.get("key"), document.get("nameToken"), document.get("home"),
                    document.get("rootDisplayName"))
    parser = _ReferenceCollectingParser(catalog)
    layers = _parse_layers(document.get("layers"), catalog, parser)
    if parser.selects_models and not parser.references:
        raise ValueError("Selecting nested health models (origin 'model' or profile 'health-model') needs a "
                         "nestedModel selector that names the definitions whose models to nest.")
    spec = DefinitionSpec(
        key=document.get("key"), name_token=document.get("nameToken"), home=document.get("home"),
        root_display_name=document.get("rootDisplayName"), layers=layers, kind=document.get("kind", "layered"),
        description=document.get("description", ""), report_coverage=document.get("reportCoverage", False),
        overrides=document.get("overrides") or {}, alert_policy=document.get("alertPolicy") or {},
        health_objective=document.get("healthObjective"), nests=frozenset(parser.references), source=source)
    _validate(spec, catalog)
    return spec


def _check_identity(key, token, home, display) -> None:
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise ValueError("Definition key must be 2-31 lowercase letters, digits or dashes, starting with a letter.")
    if not isinstance(token, str) or not TOKEN_TEMPLATE.fullmatch(token):
        raise ValueError(f"Invalid model name token {token!r}: use 2-8 lowercase letters or digits, "
                         "optionally followed by {project}.")
    if home not in HOMES:
        raise ValueError(f"home must be one of {', '.join(HOMES)} (the resource group the model is deployed to).")
    _check_display_name(display)


def _validate(spec: DefinitionSpec, catalog: SignalCatalog) -> None:
    _check_identity(spec.key, spec.name_token, spec.home, spec.root_display_name)
    if not isinstance(spec.kind, str) or not spec.kind:
        raise ValueError("kind must be a non-empty string.")
    if not isinstance(spec.report_coverage, bool):
        raise ValueError("reportCoverage must be true or false.")
    if not isinstance(spec.description, str):
        raise ValueError("description must be a string.")
    if not isinstance(spec.layers, tuple) or not spec.layers or not all(isinstance(l, LayerSpec) for l in spec.layers):
        raise ValueError("layers must be a non-empty list.")
    named = [item.layer for item in spec.layers if item.layer is not None]
    for layer in named:
        _check_layer(layer)
    duplicates = sorted({layer.key for layer in named if sum(other.key == layer.key for other in named) > 1})
    if duplicates:
        raise ValueError(f"Layer {duplicates[0]!r} is defined twice.")
    if spec.key in spec.nests:
        raise ValueError("A definition cannot nest itself.")
    OverrideSet.parse(spec.overrides, catalog).resolve(catalog)
    validate_alert_policy(spec.alert_policy)
    if spec.health_objective is not None:
        validate_health_objective(spec.health_objective)


def _check_display_name(display) -> None:
    """Only {project} and {env}, without format specs or conversions, so rendering can never fail."""
    if not isinstance(display, str) or not display.strip() or len(display) > 200:
        raise ValueError("rootDisplayName must be a non-empty string of at most 200 characters.")
    try:
        fields = list(string.Formatter().parse(display))
    except ValueError as error:
        raise ValueError(f"rootDisplayName is not a valid template ({error}); write literal braces as "
                         "{{ and }}.") from None
    for _, name, spec, conversion in fields:
        if name is None:
            continue
        if name not in PLACEHOLDERS:
            raise ValueError(f"Unknown placeholder {{{name}}} in rootDisplayName; use {{project}} and {{env}}.")
        if spec or conversion:
            raise ValueError("rootDisplayName placeholders take no format spec or conversion; "
                             "write {project} or {env}.")


def _check_layer(layer: Layer) -> None:
    if not isinstance(layer.key, str) or not LAYER_KEY_PATTERN.fullmatch(layer.key):
        raise ValueError("Layer key must be 2-41 lowercase letters, digits or dashes, starting with a letter "
                         "and ending with a letter or digit.")
    if layer.impact not in raw.IMPACTS:
        raise ValueError(f"Layer {layer.key!r} impact must be one of {sorted(raw.IMPACTS)}.")
    if not isinstance(layer.display_name, str) or not 0 < len(layer.display_name) <= 120:
        raise ValueError(f"Layer {layer.key!r} displayName must be 1-120 characters.")


class _ReferenceCollectingParser(SelectorParser):
    """Selector parser that records nestedModel references and positive selections of health models."""

    def __init__(self, catalog: SignalCatalog):
        super().__init__(catalog)
        self.references: set[str] = set()
        self.selects_models = False
        self._negations = 0

    def _term_nestedModel(self, value):
        selector = super()._term_nestedModel(value)
        self.references.update(selector.values)
        return selector

    def _term_origin(self, value):
        selector = super()._term_origin(value)
        self._note_model_selection("model" in selector.values)
        return selector

    def _term_profile(self, value):
        selector = super()._term_profile(value)
        self._note_model_selection(any(self._catalog.profile(key).nested_model for key in selector.values))
        return selector

    def _term_not(self, value):
        self._negations += 1
        try:
            return super()._term_not(value)
        finally:
            self._negations -= 1

    def _note_model_selection(self, selects: bool) -> None:
        if selects and self._negations % 2 == 0:
            self.selects_models = True


def _parse_layers(items, catalog: SignalCatalog, parser: SelectorParser) -> tuple[LayerSpec, ...]:
    if not isinstance(items, list) or not items:
        raise ValueError("layers must be a non-empty list.")
    specs, keys = [], set()
    for item in items:
        if not isinstance(item, dict) or "select" not in item:
            raise ValueError("Every layer needs a select expression.")
        selector = parser.parse(item["select"])
        if "fromCatalog" in item:
            if item["fromCatalog"] is not True or set(item) != {"fromCatalog", "select"}:
                raise ValueError("A fromCatalog layer only takes fromCatalog: true and select.")
            specs.append(LayerSpec(selector))
            continue
        bad = set(item) - {"key", "displayName", "impact", "description", "select"}
        if bad:
            raise ValueError(f"Unknown layer field(s): {sorted(bad)}")
        key = item.get("key")
        if not isinstance(key, str):
            raise ValueError("Every named layer needs a key.")
        if key in keys:
            raise ValueError(f"Layer {key!r} is defined twice.")
        keys.add(key)
        base = catalog.layer(key) if catalog.has_layer(key) else None
        display, impact = item.get("displayName"), item.get("impact")
        if base is None and (not display or not impact):
            raise ValueError(f"Custom layer {key!r} needs displayName and impact.")
        layer = base or Layer(key, display, impact, item.get("description", ""))
        changes = {name: value for name, value in (("display_name", display), ("impact", impact),
                                                     ("description", item.get("description"))) if value}
        layer = layer.clone(**changes) if changes else layer
        _check_layer(layer)
        specs.append(LayerSpec(selector, layer))
    return tuple(specs)


class ModelDefinition(ABC):
    """Template Method for planning one health model from discovered resources."""

    def __init__(self, spec: DefinitionSpec, catalog: SignalCatalog, *,
                 chain: ClassificationHandler | None = None, layout: LayoutStrategy | None = None,
                 coverage: CoverageAnalyzer | None = None):
        self.spec = validate_spec(spec, catalog)
        self.catalog = catalog
        self._chain = chain or default_chain()
        self._layout = layout or TieredLayout()
        self._coverage = coverage or CoverageAnalyzer(catalog)
        self._overrides = OverrideSet.parse(spec.overrides, catalog)

    # -- identity -------------------------------------------------------------------------
    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def home(self) -> str:
        return self.spec.home

    @property
    def nests(self) -> frozenset[str]:
        return self.spec.nests

    @property
    def defaults(self) -> dict:
        """Bicep defaults of this definition; deployment options given at run time win."""
        defaults = {}
        if self.spec.health_objective is not None:
            defaults["healthObjective"] = self.spec.health_objective
        if self.spec.alert_policy:
            defaults["alertPolicy"] = dict(self.spec.alert_policy)
        return defaults

    def clone(self, **changes) -> "ModelDefinition":
        """Prototype: a variant of this definition (for example with extra overrides)."""
        return type(self)(dataclasses.replace(self.spec, **changes), self.catalog, chain=self._chain,
                          layout=self._layout, coverage=self._coverage)

    def model_name(self, scope: FactoryScope) -> str:
        return scope.model_name_for(scope.render_token(self.spec.name_token))

    def root_display_name(self, scope: FactoryScope) -> str:
        return self.spec.root_display_name.format(project=scope.project_number, env=scope.environment)

    def check_home(self, scope: FactoryScope) -> None:
        if self.home == "common" and not scope.common_resource_group:
            raise ValueError(f"The {self.key} model is deployed to the common resource group, "
                             "but no common resource group is configured.")

    def resolve_profiles(self, overrides: OverrideSet | None = None) -> dict:
        """Effective profiles: catalog, then this definition's overrides, then the run's overrides."""
        return self._overrides.merge(overrides).resolve(self.catalog)

    def preflight(self, scope: FactoryScope, overrides: OverrideSet | None = None) -> None:
        """Every check that needs no Azure call, so a run can fail before its first Azure request."""
        self.check_home(scope)
        self.model_name(scope)
        self.root_display_name(scope)
        self.resolve_profiles(overrides)

    # -- template method ------------------------------------------------------------------
    def plan_for(self, scope: FactoryScope, resources: Iterable[DiscoveredResource], *, overrides=None,
                 workspace: str | None = None, model_name: str | None = None,
                 siblings: Mapping | None = None) -> ModelPlan:
        extra = OverrideSet.parse(overrides, self.catalog) if overrides else None
        return self.plan(PlanningRequest(scope, tuple(resources), extra, workspace or None, model_name,
                                         dict(siblings or {})))

    def plan(self, request: PlanningRequest) -> ModelPlan:
        scope = request.scope
        workspace = self.validate_workspace(request.workspace)
        self.check_home(scope)
        model_name = request.model_name or self.model_name(scope)
        if not raw.MODEL_NAME_PATTERN.fullmatch(model_name):
            raise ValueError(f"Invalid health model name {model_name!r}.")
        resolved = self.resolve_profiles(request.overrides)
        # Only models of the definitions this one names are nested, so the result never depends on
        # which other definitions happen to be part of the same run.
        siblings = {key: value for key, value in request.siblings.items() if key in self.nests}
        context = ClassificationContext(scope, self.catalog, model_name, siblings)
        classified = [self.classify(resource, context) for resource in request.resources]

        assigned: list[tuple[Candidate, Layer]] = []
        for item in classified:
            if isinstance(item, Candidate):
                layer = self.assign(item)
                if layer is not None:
                    assigned.append((item, layer))
        enabled = [(c, layer) for c, layer in assigned if resolved[c.profile.key] is not None]
        monitored = [(c, layer) for c, layer in enabled if resolved[c.profile.key].has_signal_source(workspace)]
        report = self.spec.report_coverage
        unmodelled = [i.resource for i in classified
                      if report and isinstance(i, Unclassified) and i.origin == self.home and i.reason == "unmodelled"]
        not_monitorable = [i.resource for i in classified if report and isinstance(i, Unclassified)
                           and i.origin == self.home and i.reason == "not-monitorable"]
        hints: list[str] = []
        for candidate, _ in enabled:
            profile = resolved[candidate.profile.key]
            if not profile.has_signal_source(workspace):
                not_monitorable.append(candidate.resource)
                hint = profile.no_source_hint or f"{profile.key} has no signal source."
                if hint not in hints:
                    hints.append(hint)

        monitored.sort(key=self.order_key)
        builder = HealthModelBuilder(model_name, self.root_display_name(scope), self._layout).with_workspace(workspace)
        for candidate, layer in monitored:
            builder.add_resource(layer, resolved[candidate.profile.key], candidate)
        root = builder.build()
        self.validate_model(root)

        entities = self.render_entities(root)
        coverage, warnings = (self._coverage.analyze(
            scope.flags, self.home, (c for c, _ in assigned),
            {key for key, value in resolved.items() if value is None}) if report else ([], []))
        warnings.extend(hints)
        if not monitored:
            warnings.append("No modelled resources were found; only the root entity will be created.")
        return ModelPlan(
            definition=self.key, model_name=model_name, model_scope=self.home, scope=scope,
            root_display_name=root.display_name, entities=entities, relationships=relationships(root),
            reader_resource_groups=self.reader_resource_groups(scope, root, workspace), coverage=coverage,
            warnings=warnings, unmodelled=unmodelled, not_monitorable=not_monitorable, root=root,
            defaults=self.defaults, nests=self.nests)

    # -- hooks ----------------------------------------------------------------------------
    def classify(self, resource: DiscoveredResource, context: ClassificationContext):
        return self._chain.handle(resource, context)

    @abstractmethod
    def assign(self, candidate: Candidate) -> Layer | None:
        """The layer a candidate belongs to in this model, or None when it is not part of it."""

    def layer_rank(self, layer_key: str) -> int:
        order = self.catalog.layer_order
        return order.index(layer_key) if layer_key in order else len(order)

    def order_key(self, item: tuple[Candidate, Layer]):
        candidate, layer = item
        return self.layer_rank(layer.key), candidate.profile.key, candidate.resource.id.lower()

    @staticmethod
    def validate_workspace(workspace: str | None) -> str | None:
        if workspace and not WORKSPACE_ID.fullmatch(workspace):
            raise ValueError("log_analytics_workspace_id must be a Log Analytics workspace resource ID.")
        return workspace or None

    @staticmethod
    def validate_model(root) -> None:
        validator = ValidationVisitor()
        for entity in breadth_first(root):
            entity.accept(validator)
        validator.raise_if_invalid()

    @staticmethod
    def render_entities(root) -> list[PlannedEntity]:
        visitor, entities = PayloadVisitor(), []
        for entity in breadth_first(root):
            properties = entity.accept(visitor)
            if properties is None:
                continue
            if entity.role == "layer":
                entities.append(PlannedEntity(entity.name, "layer", entity.layer.key, entity.display_name, properties))
            else:
                entities.append(PlannedEntity(
                    entity.name, "resource", entity.layer.key, properties["displayName"], properties,
                    profile=entity.profile.key, resource_id=entity.resource.id,
                    scope=entity.candidate.aifactory_scope))
        return entities

    def reader_resource_groups(self, scope: FactoryScope, root, workspace: str | None) -> list[str]:
        """Groups where the model identity needs Monitoring Reader: home, monitored resources, workspace."""
        groups = [scope.project_resource_group if self.home == "project" else scope.common_resource_group]
        resources = [entity for entity in breadth_first(root) if entity.role == "resource"]
        for entity in resources:
            if entity.resource.resource_group not in groups:
                groups.append(entity.resource.resource_group)
        if workspace and any(entity.profile.log_signals for entity in resources):
            workspace_group = WORKSPACE_ID.fullmatch(workspace).group(1)
            if workspace_group.lower() not in {g.lower() for g in groups}:
                groups.append(workspace_group)
        return groups

    def describe(self) -> dict:
        return {"key": self.key, "kind": self.spec.kind, "description": self.spec.description,
                "home": self.home, "nameToken": self.spec.name_token, "nests": sorted(self.nests),
                "reportCoverage": self.spec.report_coverage, "source": self.spec.source}


class LayeredModelDefinition(ModelDefinition):
    """Declarative definition: the first layer whose selector matches a candidate wins."""

    def assign(self, candidate: Candidate) -> Layer | None:
        for spec in self.spec.layers:
            if spec.selector.matches(candidate):
                return self.catalog.layer(candidate.profile.layer) if spec.from_catalog else spec.layer
        return None

    def layer_rank(self, layer_key: str) -> int:
        """Catalog layers keep the catalog order; custom layers follow in definition order."""
        order = self.catalog.layer_order
        if layer_key in order:
            return order.index(layer_key)
        custom = [s.layer.key for s in self.spec.layers if not s.from_catalog and s.layer.key not in order]
        return len(order) + (custom.index(layer_key) if layer_key in custom else len(custom))

    def describe(self) -> dict:
        layers = []
        for spec in self.spec.layers:
            layers.append({"layer": "(catalog layer of each profile)" if spec.from_catalog else spec.layer.key,
                           "select": spec.selector.describe()})
        return {**super().describe(), "layers": layers}


class ModelDefinitionFactory:
    """Creates definitions by kind; register new kinds to plug in coded definitions."""

    def __init__(self):
        self._creators: dict[str, type[ModelDefinition]] = {"layered": LayeredModelDefinition}

    def register(self, kind: str, creator) -> "ModelDefinitionFactory":
        self._creators[kind] = creator
        return self

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._creators))

    def create(self, spec: DefinitionSpec, catalog: SignalCatalog) -> ModelDefinition:
        creator = self._creators.get(spec.kind)
        if creator is None:
            raise DefinitionError(f"{spec.source}: Unknown definition kind {spec.kind!r}. "
                                  f"Registered kinds: {', '.join(self.kinds())}.")
        return creator(spec, catalog)


class DefinitionRegistry:
    """All known model definitions: built-in ones plus consumer files (later sources win)."""

    def __init__(self, catalog: SignalCatalog, factory: ModelDefinitionFactory | None = None):
        self.catalog = catalog
        self._factory = factory or ModelDefinitionFactory()
        self._definitions: dict[str, ModelDefinition] = {}

    @classmethod
    def builtin(cls, catalog: SignalCatalog | None = None,
                factory: ModelDefinitionFactory | None = None) -> "DefinitionRegistry":
        return cls(catalog or SignalCatalog.from_file(), factory).load_directory(DEFINITIONS_DIR)

    def load_directory(self, path: str | Path) -> "DefinitionRegistry":
        folder = Path(path)
        if not folder.is_dir():
            raise DefinitionError(f"Definitions folder not found: {path}")
        for file in sorted(folder.glob("*.json")):
            if file.name.endswith(".schema.json"):
                continue
            self.load_file(file, validate=False)
        self.validate()
        return self

    def load_file(self, path: str | Path, validate: bool = True) -> ModelDefinition:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise DefinitionError(f"Cannot read the model definition {Path(path).name} as JSON.") from None
        return self.add_document(document, source=str(path), validate=validate)

    def add_document(self, document, source: str = "<memory>", validate: bool = True) -> ModelDefinition:
        definition = self._factory.create(parse_definition(document, self.catalog, source), self.catalog)
        return self.add(definition, validate=validate)

    def add(self, definition: ModelDefinition, validate: bool = True) -> ModelDefinition:
        previous = self._definitions.get(definition.key)
        self._definitions[definition.key] = definition
        if validate:
            try:
                self.validate()
            except DefinitionError:
                if previous is None:
                    del self._definitions[definition.key]
                else:
                    self._definitions[definition.key] = previous
                raise
        return definition

    def validate(self) -> None:
        tokens: dict[str, str] = {}
        for key, definition in sorted(self._definitions.items()):
            token = definition.spec.name_token
            if token in tokens:
                raise DefinitionError(f"Model name token {token!r} of {key!r} is already used by {tokens[token]!r}.")
            tokens[token] = key
            for nested in sorted(definition.nests):
                if nested not in self._definitions:
                    raise DefinitionError(f"Definition {key!r} nests unknown model definition {nested!r}.")
        self.deployment_order(self._definitions)

    def get(self, key: str) -> ModelDefinition:
        try:
            return self._definitions[key]
        except KeyError:
            raise DefinitionError(f"Unknown model definition {key!r}. Known: {', '.join(self.keys())}.") from None

    def __contains__(self, key: str) -> bool:
        return key in self._definitions

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def definitions(self) -> tuple[ModelDefinition, ...]:
        return tuple(self._definitions[key] for key in self.keys())

    def sibling_patterns(self, scope: FactoryScope) -> dict[str, tuple[re.Pattern, str]]:
        return {d.key: (scope.sibling_model_pattern(d.spec.name_token), d.home) for d in self.definitions()}

    def deployment_order(self, keys: Iterable[str]) -> list[str]:
        """Requested keys with nested definitions before the definitions that nest them."""
        pending, order = list(dict.fromkeys(keys)), []
        while pending:
            ready = [k for k in pending if all(n in order or n not in pending for n in self.get(k).nests)]
            if not ready:
                raise DefinitionError("Model definitions form a nesting cycle: " + " -> ".join(pending + pending[:1]))
            order.extend(ready)
            pending = [k for k in pending if k not in ready]
        return order

    def plan(self, key: str, scope: FactoryScope, resources: Iterable[DiscoveredResource], *, overrides=None,
             workspace: str | None = None, model_name: str | None = None) -> ModelPlan:
        return self.get(key).plan_for(scope, resources, overrides=overrides, workspace=workspace,
                                      model_name=model_name, siblings=self.sibling_patterns(scope))
