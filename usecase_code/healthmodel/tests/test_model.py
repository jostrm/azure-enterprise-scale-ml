"""Composite model, Iterator traversal, Builder, layout Strategy and Visitors."""
from __future__ import annotations

import pytest

from aifactory_healthmodel.domain.builder import HealthModelBuilder
from aifactory_healthmodel.domain.classification import Candidate
from aifactory_healthmodel.domain.layout import TieredLayout
from aifactory_healthmodel.domain.model import breadth_first, depth_first, edges
from aifactory_healthmodel.domain.resources import DiscoveredResource
from aifactory_healthmodel.domain.signals import SignalCatalog
from aifactory_healthmodel.domain.visitors import (MANAGED_BY, PayloadVisitor, SignalCountVisitor,
                                                    ValidationVisitor, relationships)

SUB = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture(scope="module")
def catalog():
    return SignalCatalog.from_file()


def candidate(catalog, profile_key, name, origin="project"):
    profile = catalog.profile(profile_key)
    resource = DiscoveredResource(
        id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/{profile.resource_type}/{name}", name=name,
        type=profile.resource_type, kind="AIServices" if profile_key == "foundry" else "", resource_group="rg")
    return Candidate(resource, profile, origin)


@pytest.fixture()
def root(catalog):
    builder = HealthModelBuilder("hm-test-prj001", "Test model")
    for key, name in (("foundry", "aif1"), ("search", "srch1"), ("keyvault", "kv1")):
        item = candidate(catalog, key, name)
        builder.add_resource(catalog.layer(item.profile.layer), item.profile, item)
    return builder.build()


def test_builder_produces_a_composite_tree(root):
    assert root.name == "hm-test-prj001" and root.display_name == "Test model"
    assert [layer.name for layer in root.children()] == ["layer-genai", "layer-security"]
    assert [len(layer.children()) for layer in root.children()] == [2, 1]
    assert all(resource.children() == () for layer in root.children() for resource in layer.children())


def test_iterators_walk_breadth_and_depth_first(root):
    assert [e.role for e in breadth_first(root)] == ["root", "layer", "layer", "resource", "resource", "resource"]
    assert [e.role for e in depth_first(root)] == ["root", "layer", "resource", "resource", "layer", "resource"]
    pairs = [(parent.role, child.role) for parent, child in edges(root)]
    assert pairs == [("root", "layer"), ("root", "layer"), ("layer", "resource"), ("layer", "resource"),
                     ("layer", "resource")]


def test_tiered_layout_strategy():
    layout = TieredLayout()
    assert [layout.layer_position(i, 3) for i in range(3)] == [
        {"x": -360, "y": 220}, {"x": 0, "y": 220}, {"x": 360, "y": 220}]
    assert layout.resource_position({"x": 0, "y": 220}, 0, 1) == {"x": 0, "y": 440}
    assert [layout.resource_position({"x": 0, "y": 220}, i, 3) for i in range(3)] == [
        {"x": -90, "y": 440}, {"x": 90, "y": 440}, {"x": -90, "y": 580}]


def test_layout_strategy_is_replaceable(catalog):
    class Grid(TieredLayout):
        def layer_position(self, index, count):
            return {"x": index * 1000, "y": 0}

    item = candidate(catalog, "keyvault", "kv1")
    root = HealthModelBuilder("hm-test", "T", layout=Grid()).add_resource(
        catalog.layer("security"), item.profile, item).build()
    assert root.children()[0].position == {"x": 0, "y": 0}


def test_payload_visitor_renders_api_shaped_properties(root, catalog):
    visitor = PayloadVisitor()
    layer, resource = root.children()[0], root.children()[0].children()[0]
    layer_props = layer.accept(visitor)
    assert layer_props["signalGroups"] == {"dependencies": {"aggregationType": "WorstOf", "ignoreUnknown": True}}
    assert layer_props["tags"] == {"managedBy": MANAGED_BY, "role": "layer", "layer": "genai"}
    props = resource.accept(visitor)
    assert props["displayName"] == "Microsoft Foundry: aif1" or props["displayName"].endswith(": aif1")
    assert props["tags"]["profile"] == "foundry" and props["tags"]["aifactoryScope"] == "project"
    group = props["signalGroups"]["azureResource"]
    assert group["signals"] == [s.to_api() for s in catalog.profile("foundry").signals]
    assert props["signalAggregationGroups"] == catalog.profile("foundry").aggregation_groups_api()
    assert root.accept(visitor) is None, "the root entity is created by Bicep"


def test_relationships_and_signal_counts(root):
    rels = relationships(root)
    assert rels[0] == {"name": "hm-test-prj001-to-layer-genai", "parentEntityName": "hm-test-prj001",
                       "childEntityName": "layer-genai"}
    assert len(rels) == 5
    counter = SignalCountVisitor()
    for entity in breadth_first(root):
        entity.accept(counter)
    assert counter.total == sum(len(r.profile.signals) for l in root.children() for r in l.children())


def test_validation_visitor_rejects_duplicates(catalog):
    item = candidate(catalog, "keyvault", "kv1")
    builder = HealthModelBuilder("hm-test", "T")
    builder.add_resource(catalog.layer("security"), item.profile, item)
    builder.add_resource(catalog.layer("security"), item.profile, item)
    root = builder.build()
    validator = ValidationVisitor()
    for entity in breadth_first(root):
        entity.accept(validator)
    assert any("Duplicate entity name" in error for error in validator.errors)
    with pytest.raises(ValueError, match="Duplicate entity name"):
        validator.raise_if_invalid()
