"""Shipped result renderer against real cost contracts and a text-only injected DOM."""

import json
import subprocess
from pathlib import Path

import pytest

from test_costs import COMMON, COST_SKILLS, FakeAzure, principal, run, settings


ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const request = JSON.parse(fs.readFileSync(0, "utf8"));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this._text = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ""; this.children = items; }
  setAttribute(name, value) { assert(!/^on/i.test(name)); this.attrs[name] = String(value); }
  set innerHTML(_) { throw Error("HTML sink is forbidden"); }
  insertAdjacentHTML() { throw Error("HTML sink is forbidden"); }
}
const document = {createElement: tag => new Element(tag)};
const context = vm.createContext({window: {}});
vm.runInContext(fs.readFileSync("aifactory_agent/static/skill-results.js", "utf8"), context);
const renderer = new context.window.FactorySkillResultRenderer({document});
const target = new Element("div");
if (request.previous) target.textContent = request.previous;
const before = JSON.stringify(request.data);
let error = null;
try { renderer[request.method](request.data, target); }
catch (exception) { error = exception.message; }
assert.equal(JSON.stringify(request.data), before, "Presentation must not mutate reviewed records");
function snapshot(node) {
  return {tag: node.tag, text: node.textContent, attrs: node.attrs, children: node.children.map(snapshot)};
}
console.log(JSON.stringify({error, tree: snapshot(target)}));
"""


def render(data, method="renderCost", previous=None):
    result = subprocess.run(
        ["node", "-e", DRIVER], cwd=ROOT, input=json.dumps({"data": data, "method": method, "previous": previous}),
        text=True, encoding="utf-8", capture_output=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def elements(tree, tag):
    result = [tree] if tree["tag"] == tag else []
    for child in tree["children"]:
        result.extend(elements(child, tag))
    return result


@pytest.mark.parametrize("skill,args", [
    (COST_SKILLS[0], {}),
    (COST_SKILLS[1], {"resource_group": COMMON}),
    (COST_SKILLS[2], {"resource_group": "factory-project001-dev-rg"}),
])
def test_real_cost_contract_has_visible_amounts_and_collapsed_raw_details(settings, principal, skill, args):
    data, _ = run(settings, principal, FakeAzure(), skill, args)
    result = render(data)
    assert result["error"] is None
    tree = result["tree"]
    assert "Actual month-to-date" in tree["text"] and "USD 2" in tree["text"]
    assert data["resource_group"] in tree["text"]
    assert elements(tree, "table")
    assert any("Raw response" in item["text"] for item in elements(tree, "details"))
    assert all("open" not in item["attrs"] for item in elements(tree, "details"))
    if "idle_baseline" in data:
        assert "Partial estimate" in tree["text"] or "Estimate unavailable" in tree["text"]
        assert "Full idle total" in tree["text"] and "Unknown" in tree["text"]
        assert "Usage requirements" in tree["text"] and "Assumptions" in tree["text"]
    else:
        assert "Azure full-month forecast" in tree["text"] and "USD 50" in tree["text"]
        assert "Already includes actual costs" in tree["text"]
        assert "Actual cutoff" in tree["text"]
        assert any(len([child for child in item["children"] if child["tag"] == "article"]) == 2
                   for item in elements(tree, "div"))


def test_currency_values_remain_separate_and_decimal_strings_are_not_rounded():
    data = {
        "actual_mtd": {
            "totals_by_currency": {"USD": "900719925474099.1234", "EUR": "-0.125"},
            "services": [], "period": {"from": "2026-10-01", "to": "2026-10-03"},
        },
    }
    result = render(data)
    assert result["error"] is None
    assert "USD 900719925474099.1234" in result["tree"]["text"]
    assert "EUR -0.125" in result["tree"]["text"]
    assert len(elements(result["tree"], "article")) == 2


@pytest.mark.parametrize("amount", [None, True, "NaN", "Infinity", {}, "not-a-price"])
def test_invalid_billing_amount_never_displays_as_zero(amount):
    result = render({"actual_mtd": {"totals_by_currency": {"USD": amount}}})
    assert result["error"] and "cost" in result["error"].lower()
    assert not result["tree"]["children"]


def test_empty_billing_totals_are_not_a_zero_spend_report():
    result = render({"actual_mtd": {"totals_by_currency": {}}})
    assert result["error"]
    assert not result["tree"]["children"]


def test_confirmed_zero_remains_distinct_from_missing_cost():
    result = render({"actual_mtd": {"totals_by_currency": {"USD": "0"}, "services": []}})
    assert result["error"] is None
    assert "USD 0" in result["tree"]["text"]


def test_invalid_new_report_does_not_partially_replace_previous_display():
    result = render({
        "actual_mtd": {"totals_by_currency": {"USD": "12.50"}},
        "azure_forecast_full_month": {"totals_by_currency": {"USD": None}},
    }, previous="Previous completed report")
    assert result["error"]
    assert result["tree"]["text"] == "Previous completed report"


def test_diagnostic_objects_and_arrays_are_readable_without_html_execution():
    payload = {"health": {"status": "unavailable"}, "warnings": ["<img src=x onerror=steal()>"],
               "resources_deployed": False}
    result = render(payload, "renderObservation")
    assert result["error"] is None
    tree = result["tree"]
    assert elements(tree, "dl") and elements(tree, "ul")
    assert "Resources deployed" in tree["text"] and "No" in tree["text"]
    assert "<img src=x onerror=steal()>" in tree["text"]
    assert not elements(tree, "img") and not elements(tree, "script")


@pytest.mark.parametrize("status", ["running", "awaiting_continuation", "failed", "uncertain"])
def test_operation_summary_preserves_completion_state_and_exact_resources(status):
    operation = {
        "status": status, "scope": {"project": "001", "environment": "dev"},
        "preview": {"summary": "Prepare project", "effects": ["Save settings, not Azure resources"]},
        "affected_resources": ["/subscriptions/exact/resourceGroups/project001"],
        "progress": {"phase": status, "completion_known": False, "retry_allowed": False},
        "observation": {"data": {"model_created": False, "registration_status": "not_requested"}},
    }
    result = render(operation, "appendOperation")
    assert result["error"] is None
    tree = result["tree"]
    assert "Not confirmed" in tree["text"]
    assert "/subscriptions/exact/resourceGroups/project001" in tree["text"]
    assert "Model created" in tree["text"] and "No" in tree["text"]
    assert "Registration status" in tree["text"] and "Not requested" in tree["text"]


def test_renderer_is_loaded_before_app_and_has_no_transport_or_html_sinks():
    html = (ROOT / "aifactory_agent" / "static" / "index.html").read_text("utf-8")
    assert html.index("/static/skill-results.js") < html.index("/static/app.js")
    source = (ROOT / "aifactory_agent" / "static" / "skill-results.js").read_text("utf-8")
    for forbidden in ("innerHTML", "insertAdjacentHTML", "fetch(", "localStorage", "eval("):
        assert forbidden not in source
