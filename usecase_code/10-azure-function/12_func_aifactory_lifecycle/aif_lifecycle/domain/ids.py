"""Readable IDs for factories, scale sets and projects, in one place.

- FactoryId  = prefix-region-env                      aif-121-sdc-dev
- ScalesetId = FactoryId-suffix                        aif-121-sdc-dev-001
- ProjectId  = the project resource group name        aif-121-esml-project001-sdc-dev-001-rg

The tokens are purple's resource-group naming: `{prefixRG}{projectPrefix}project{NNN}-{loc}-{env}{suffixRG}{projectSuffix}`
with `projectPrefix='esml-'` and `projectSuffix='-rg'` by default. Azure names use the env tokens dev/test/prod; the
catalog says stage for test. Parsing works from the right because suffix, env and region code never contain dashes,
while the prefix can. There is no salt: an ID only has to be unique within one consumer repo's catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

from . import regions
from .errors import InvalidId

DEFAULT_PROJECT_PREFIX = "esml-"
DEFAULT_PROJECT_SUFFIX = "-rg"
COMMON_GROUP_BASE = "esml-common"

_CATALOG_ENV = {"dev": "dev", "test": "stage", "prod": "prod"}
_PHYSICAL_ENV = {"dev": "dev", "stage": "test", "test": "test", "prod": "prod"}
_PREFIX = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_THREE_DIGITS = re.compile(r"\d{3}")


def physical_environment(environment: str) -> str:
    """Catalog env (dev/stage/prod) or physical token -> the token used in Azure names."""
    try:
        return _PHYSICAL_ENV[environment]
    except (KeyError, TypeError):
        raise InvalidId(f"Environment '{environment}' must be dev, stage (test) or prod.") from None


def catalog_environment(token: str) -> str:
    try:
        return _CATALOG_ENV[token]
    except (KeyError, TypeError):
        raise InvalidId(f"Environment token '{token}' must be dev, test or prod.") from None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidId(message)


@dataclass(frozen=True)
class FactoryId:
    prefix: str
    region_code: str
    env: str

    def __post_init__(self):
        _require(isinstance(self.prefix, str) and bool(_PREFIX.fullmatch(self.prefix)),
                 f"Prefix '{self.prefix}' must be lowercase letters and digits separated by single dashes.")
        regions.region_for(self.region_code)
        _require(self.env in _CATALOG_ENV, f"Environment token '{self.env}' must be dev, test or prod (stage is test).")

    @classmethod
    def parse(cls, text: str) -> "FactoryId":
        _require(isinstance(text, str) and text.count("-") >= 2, f"'{text}' is not a FactoryId (prefix-region-env).")
        rest, code, env = text.rsplit("-", 2)
        return cls(rest, code, env)

    def __str__(self) -> str:
        return f"{self.prefix}-{self.region_code}-{self.env}"

    @property
    def region(self) -> str:
        return regions.region_for(self.region_code)

    @property
    def catalog_env(self) -> str:
        return catalog_environment(self.env)

    @property
    def factory(self) -> "FactoryId":
        return self

    def contains(self, other: "AnyId") -> bool:
        return other.factory == self


@dataclass(frozen=True)
class ScalesetId:
    factory: FactoryId
    suffix: str

    def __post_init__(self):
        _require(isinstance(self.suffix, str) and bool(_THREE_DIGITS.fullmatch(self.suffix)),
                 f"Scale set suffix '{self.suffix}' must be three digits, for example 001.")

    @classmethod
    def parse(cls, text: str) -> "ScalesetId":
        _require(isinstance(text, str) and "-" in text, f"'{text}' is not a ScalesetId (FactoryId-suffix).")
        rest, suffix = text.rsplit("-", 1)
        return cls(FactoryId.parse(rest), suffix)

    def __str__(self) -> str:
        return f"{self.factory}-{self.suffix}"

    @property
    def common_resource_group(self) -> str:
        f = self.factory
        return f"{f.prefix}-{COMMON_GROUP_BASE}-{f.region_code}-{f.env}-{self.suffix}"

    @property
    def scaleset(self) -> "ScalesetId":
        return self

    def contains(self, other: "AnyId") -> bool:
        return isinstance(other, (ScalesetId, ProjectId)) and other.scaleset == self


@dataclass(frozen=True)
class ProjectId:
    scaleset: ScalesetId
    number: str
    project_prefix: str = DEFAULT_PROJECT_PREFIX
    project_suffix: str = DEFAULT_PROJECT_SUFFIX

    def __post_init__(self):
        _require(isinstance(self.number, str) and bool(_THREE_DIGITS.fullmatch(self.number)),
                 f"Project number '{self.number}' must be three digits, for example 002.")

    @classmethod
    def parse(cls, text: str, *, project_prefix: str = DEFAULT_PROJECT_PREFIX,
              project_suffix: str = DEFAULT_PROJECT_SUFFIX) -> "ProjectId":
        _require(isinstance(text, str) and text.endswith(project_suffix) and len(text) > len(project_suffix),
                 f"'{text}' is not a project resource group ending in '{project_suffix}'.")
        core = text[: len(text) - len(project_suffix)] if project_suffix else text
        _require(core.count("-") >= 3, f"'{text}' is not a project resource group name.")
        head, code, env, suffix = core.rsplit("-", 3)
        match = re.fullmatch(rf"(?P<prefix>.+)-{re.escape(project_prefix)}project(?P<number>\d{{3}})", head)
        _require(match is not None, f"'{text}' does not contain '-{project_prefix}projectNNN'.")
        scaleset = ScalesetId(FactoryId(match["prefix"], code, env), suffix)
        return cls(scaleset, match["number"], project_prefix, project_suffix)

    def __str__(self) -> str:
        f = self.scaleset.factory
        return (f"{f.prefix}-{self.project_prefix}project{self.number}-{f.region_code}-{f.env}-"
                f"{self.scaleset.suffix}{self.project_suffix}")

    @property
    def resource_group(self) -> str:
        return str(self)

    @property
    def factory(self) -> FactoryId:
        return self.scaleset.factory

    def contains(self, other: "AnyId") -> bool:
        return other == self


AnyId = Union[FactoryId, ScalesetId, ProjectId]


def parse_any(text: str) -> AnyId:
    """Parse a protected-list entry of any kind: project, then scale set, then factory."""
    for parser in (ProjectId.parse, ScalesetId.parse, FactoryId.parse):
        try:
            return parser(text)
        except InvalidId:
            continue
    raise InvalidId(f"'{text}' is not a FactoryId, ScalesetId or ProjectId.")
