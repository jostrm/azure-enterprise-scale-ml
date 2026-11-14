"""Discovered Azure resources (value objects) and stable entity naming."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

HEALTH_MODEL_TYPE = "microsoft.cloudhealth/healthmodels"


@dataclass(frozen=True)
class DiscoveredResource:
    id: str
    name: str
    type: str
    kind: str
    resource_group: str
    location: str = ""
    hns: bool | None = None
    tags: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def subscription_id(self) -> str:
        parts = self.id.split("/")
        return parts[2].lower() if len(parts) > 2 else ""

    @property
    def short_name(self) -> str:
        return self.name.split("/")[-1]


def parse_resources(rows: list[dict] | None) -> list[DiscoveredResource]:
    """Resource Graph rows (id, name, type, kind, resourceGroup, location, hns, tags) to value objects."""
    resources = []
    for row in rows or []:
        hns = row.get("hns")
        resources.append(DiscoveredResource(
            id=str(row["id"]), name=str(row["name"]), type=str(row["type"]).lower(),
            kind=str(row.get("kind") or ""), resource_group=str(row.get("resourceGroup") or ""),
            location=str(row.get("location") or ""), hns=None if hns is None else bool(hns),
            tags=dict(row.get("tags") or {}),
        ))
    return resources


def health_model_resource(model_id: str, name: str, resource_group: str) -> DiscoveredResource:
    """A health model deployed in this run, before Resource Graph has indexed it."""
    return DiscoveredResource(id=model_id, name=name, type=HEALTH_MODEL_TYPE, kind="", resource_group=resource_group)


def sanitize(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower())
    return re.sub(r"-{2,}", "-", value).strip("-")


def entity_name(profile_key: str, resource: DiscoveredResource) -> str:
    """Stable, unique entity name: profile, readable resource name and a digest of the resource ID."""
    base = sanitize(resource.name.replace("/", "-"))[:50].strip("-") or "resource"
    digest = hashlib.sha1(resource.id.lower().encode("utf-8")).hexdigest()[:6]
    return f"{profile_key}-{base}-{digest}"
