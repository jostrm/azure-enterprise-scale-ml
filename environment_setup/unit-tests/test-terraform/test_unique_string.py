"""ARM uniqueString() in Terraform (modules/arm-unique-string) equals the ARM engine's own result.

The expected values come from the Bicep compiler (`bicep build-params` evaluates uniqueString with the ARM
expression engine). The suite's Python oracle (harness.unique_string) is checked against the same values,
because the naming tests use it to evaluate Bicep variables.
"""
from __future__ import annotations

import json
import random
import string

from harness import terraform, unique_string, unique_strings_from_bicep


def vectors() -> list[list[str]]:
    rng = random.Random(1144)
    alphabet = string.ascii_letters + string.digits + "-_./() "
    cases = [[""], ["a"], ["aaaaa"], ["fubar"], ["fu", "bar"], ["x" * 256],
             ["/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"],
             ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/mrvel-1-esml-common-eus2-test-001"],
             ["esml-common-weu-prod-002"], ["snet-esml-cmn-pbi-001"], ["dsvm-cmn-weu-dev-001"]]
    for length in range(1, 41):  # every length class modulo 8, several times
        cases.append(["".join(rng.choice(alphabet) for _ in range(length))])
    for _ in range(30):
        cases.append(["".join(rng.choice(alphabet) for _ in range(rng.randint(40, 200)))])
    cases.append(["/subscriptions/x", "Microsoft.Storage/storageAccounts"])
    return cases


def test_real_deployment_matches():
    # aif-138 deployed acrcommon6hc2hsdc001dev in this resource group (see test-bicep unit/test_nic_detach_churn.py).
    rg = "/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
    assert unique_string(rg)[:5] == "6hc2h"


def test_python_oracle_matches_the_arm_engine():
    cases = vectors()
    expected = unique_strings_from_bicep(cases)
    assert [unique_string(*case) for case in cases] == expected


def test_terraform_module_matches_the_arm_engine(terraform_copy):
    cases = vectors()
    expected = unique_strings_from_bicep(cases)
    work = terraform_copy["base"] / "unique-string"
    work.mkdir()
    (work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    module = "../terraform/modules/arm-unique-string"  # relative: an absolute Windows path is not a local source
    (work / "main.tf").write_text(
        'module "u" {\n'
        '  for_each = { for index, values in jsondecode(file("${path.module}/cases.json")) : tostring(index) => values }\n'
        f'  source   = "{module}"\n'
        "  values   = each.value\n}\n", encoding="utf-8")
    result = terraform("init", "-backend=false", "-input=false", "-no-color", cwd=work)
    assert result.returncode == 0, result.stdout + result.stderr
    result = terraform("console", "-no-color", cwd=work,
                       stdin="jsonencode({ for key, m in module.u : key => m.value })\n")
    assert result.returncode == 0, result.stderr
    actual = json.loads(json.loads(result.stdout.strip().splitlines()[-1]))
    mismatches = [(cases[i], actual[str(i)], expected[i]) for i in range(len(cases)) if actual[str(i)] != expected[i]]
    assert not mismatches, mismatches[:5]
