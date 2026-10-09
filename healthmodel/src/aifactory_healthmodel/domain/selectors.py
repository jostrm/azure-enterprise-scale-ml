"""Interpreter for the selector language of model definitions (Specification pattern).

Grammar (JSON)::

    expr := {"all": true}
          | {"profile": key | [keys]}           catalog profile key
          | {"origin": o | [o]}                 project | common | model (nested health model)
          | {"type": armType | [armTypes]}      case-insensitive
          | {"layer": key | [keys]}             catalog layer of the profile
          | {"tag": {name: value | [values] | true}}
          | {"name": "regex"}                   full, case-insensitive match on the resource name
          | {"nestedModel": definitionKey | [keys]}
          | {"allOf": [expr, ...]} | {"anyOf": [expr, ...]} | {"not": expr}

An object with several keys means all of them. Selectors compose with ``&``, ``|`` and ``~``.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Callable, Iterable

from .classification import ORIGINS, Candidate
from .signals import SignalCatalog


class SelectorError(ValueError):
    pass


class Selector(ABC):
    @abstractmethod
    def matches(self, candidate: Candidate) -> bool: ...

    @abstractmethod
    def describe(self) -> str: ...

    def __and__(self, other: "Selector") -> "Selector":
        return AllOf((self, other))

    def __or__(self, other: "Selector") -> "Selector":
        return AnyOf((self, other))

    def __invert__(self) -> "Selector":
        return Not(self)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.describe()}>"


class Everything(Selector):
    def matches(self, candidate):
        return True

    def describe(self):
        return "everything"


class ValueIn(Selector):
    def __init__(self, label: str, values: Iterable[str], getter: Callable[[Candidate], str | None],
                 normalize: Callable[[str], str] = str):
        self.label, self.values = label, tuple(values)
        self._getter, self._normalize = getter, normalize
        self._accepted = frozenset(normalize(v) for v in self.values)

    def matches(self, candidate):
        value = self._getter(candidate)
        return value is not None and self._normalize(value) in self._accepted

    def describe(self):
        if len(self.values) == 1:
            return f"{self.label} = {self.values[0]}"
        return f"{self.label} in ({', '.join(self.values)})"


class TagMatches(Selector):
    def __init__(self, name: str, values: tuple[str, ...] | None):
        self.name, self.values = name, values

    def matches(self, candidate):
        tags = {str(k).lower(): str(v) for k, v in (candidate.resource.tags or {}).items()}
        if self.name.lower() not in tags:
            return False
        return self.values is None or tags[self.name.lower()].lower() in {v.lower() for v in self.values}

    def describe(self):
        if self.values is None:
            return f"tag {self.name} present"
        if len(self.values) == 1:
            return f"tag {self.name} = {self.values[0]}"
        return f"tag {self.name} in ({', '.join(self.values)})"


class NameMatches(Selector):
    def __init__(self, pattern: str):
        try:
            self._regex = re.compile(pattern, re.IGNORECASE)
        except re.error as error:
            raise SelectorError(f"name selector is not a valid regular expression: {error}") from None
        self.pattern = pattern

    def matches(self, candidate):
        return bool(self._regex.fullmatch(candidate.resource.short_name))

    def describe(self):
        return f"name matches /{self.pattern}/"


class AllOf(Selector):
    def __init__(self, parts: Iterable[Selector]):
        self.parts = tuple(parts)

    def matches(self, candidate):
        return all(part.matches(candidate) for part in self.parts)

    def describe(self):
        return " and ".join(f"({p.describe()})" if isinstance(p, AnyOf) else p.describe() for p in self.parts)


class AnyOf(Selector):
    def __init__(self, parts: Iterable[Selector]):
        self.parts = tuple(parts)

    def matches(self, candidate):
        return any(part.matches(candidate) for part in self.parts)

    def describe(self):
        return " or ".join(f"({p.describe()})" if isinstance(p, (AllOf, AnyOf)) else p.describe()
                           for p in self.parts)


class Not(Selector):
    def __init__(self, inner: Selector):
        self.inner = inner

    def matches(self, candidate):
        return not self.inner.matches(candidate)

    def describe(self):
        return f"not ({self.inner.describe()})"


class SelectorParser:
    """Parses and validates selector expressions against the catalog and known definitions."""

    def __init__(self, catalog: SignalCatalog, definition_keys: Iterable[str] | None = None):
        self._catalog = catalog
        self._definition_keys = None if definition_keys is None else frozenset(definition_keys)

    def parse(self, expression) -> Selector:
        if not isinstance(expression, dict):
            raise SelectorError("A selector must be a JSON object, for example {\"profile\": \"search\"}.")
        if not expression:
            raise SelectorError("A selector must not be empty; use {\"all\": true} to select everything.")
        terms = [self._term(key, value) for key, value in expression.items()]
        return terms[0] if len(terms) == 1 else AllOf(terms)

    def _term(self, key: str, value) -> Selector:
        handler = getattr(self, f"_term_{key}", None) if key.isidentifier() else None
        if handler is None:
            raise SelectorError(f"Unknown selector term {key!r}. Use one of: all, profile, origin, type, layer, "
                                "tag, name, nestedModel, allOf, anyOf, not.")
        return handler(value)

    @staticmethod
    def _values(key: str, value) -> tuple[str, ...]:
        values = (value,) if isinstance(value, str) else tuple(value) if isinstance(value, list) else None
        if not values or not all(isinstance(v, str) and v for v in values):
            raise SelectorError(f"{key} selector needs a non-empty string or list of strings.")
        return values

    def _term_all(self, value):
        if value is not True:
            raise SelectorError("The all selector only accepts true.")
        return Everything()

    def _term_profile(self, value):
        values = self._values("profile", value)
        for key in values:
            if not self._catalog.has_profile(key):
                raise SelectorError(f"Unknown profile {key!r} in selector.")
        return ValueIn("profile", values, lambda c: c.profile.key)

    def _term_origin(self, value):
        values = self._values("origin", value)
        bad = [v for v in values if v not in ORIGINS]
        if bad:
            raise SelectorError(f"origin must be one of {', '.join(ORIGINS)}; got {', '.join(bad)}.")
        return ValueIn("origin", values, lambda c: c.origin)

    def _term_type(self, value):
        return ValueIn("type", self._values("type", value), lambda c: c.resource.type, str.lower)

    def _term_layer(self, value):
        values = self._values("layer", value)
        for key in values:
            if not self._catalog.has_layer(key):
                raise SelectorError(f"Unknown layer {key!r} in selector.")
        return ValueIn("layer", values, lambda c: c.profile.layer)

    def _term_tag(self, value):
        if not isinstance(value, dict) or not value:
            raise SelectorError("tag selector needs an object such as {\"workload\": \"agents\"}.")
        terms = []
        for name, expected in value.items():
            if expected is True:
                terms.append(TagMatches(name, None))
            else:
                terms.append(TagMatches(name, self._values(f"tag {name}", expected)))
        return terms[0] if len(terms) == 1 else AllOf(terms)

    def _term_name(self, value):
        if not isinstance(value, str) or not value:
            raise SelectorError("name selector needs a regular expression string.")
        return NameMatches(value)

    def _term_nestedModel(self, value):
        values = self._values("nestedModel", value)
        if self._definition_keys is not None:
            for key in values:
                if key not in self._definition_keys:
                    raise SelectorError(f"Unknown model definition {key!r} in nestedModel selector.")
        return ValueIn("nested model", values, lambda c: c.nested_definition)

    def _children(self, key, value) -> list[Selector]:
        if not isinstance(value, list) or not value:
            raise SelectorError(f"{key} needs at least one selector.")
        return [self.parse(item) for item in value]

    def _term_allOf(self, value):
        return AllOf(self._children("allOf", value))

    def _term_anyOf(self, value):
        return AnyOf(self._children("anyOf", value))

    def _term_not(self, value):
        return Not(self.parse(value))
