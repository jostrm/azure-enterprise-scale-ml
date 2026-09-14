# AI Factory IaC test suite

Automated, credential-free tests for AI Factory Bicep, Azure DevOps and GitHub
Actions configuration. CI never logs into Azure, deploys, runs ARM what-if, or
deletes resources. Separate live integration tests remain explicitly opt-in.

## Visual guide

[Open the interactive VisualLearner guide](docs/ci-visual-guide.html) for the
push-to-results flow, flag-pair coverage explorer, CI activation checklist and
reproduction commands. Download/open the HTML locally when browsing GitHub;
GitHub's source viewer does not execute interactive HTML.

![VisualLearner schematic: push and PR, configuration contracts, unit and syntax checks, Bicep matrix, evidence review](docs/ci-flow.svg)

The guide is generated using the actual portable **AsomRecordsAB.VisualLearner**
scene and motion library. Its nodes represent CI stages, **not Azure locations**.
The HTML is self-contained, supports keyboard navigation and reduced motion,
and includes a static SVG/no-JavaScript fallback. The embedded matrix numbers
are a labelled report snapshot; the current CI artifacts are authoritative.

`docs/ci-scene.json` records library provenance, deterministic flow samples and
the source report hash. `docs/generator/VisualGuide.csproj` can regenerate the
documents using an explicitly supplied `VisualLearnerProject` path; see the
guide's reproduction section. Normal CI and reading the documentation do not
require that external project or .NET.

## Automatic checks after a push or pull request

`.github/workflows/infrastructure-tests.yml` runs on every push, pull request and
manual dispatch. A local commit alone does not start remote CI; push it first.
The checks are **IaC / unit / ubuntu-22.04**, **IaC / unit / windows-2022**,
**IaC / syntax / ubuntu-22.04** and **IaC / bicep / ubuntu-22.04**.

- **Unit:** all `unit/test_*.py` and root-level `test_*.py`, including the existing
  parity, bootstrap, project-only, exact-version, DNS and resource-discovery
  regressions. The new contracts inventory every exposed `ENABLE_*` setting and
  reject an unreviewed new flag, missing mapping, cross-wiring, wrong boolean
  conversion or missing deployment-parameter forwarding.
- **Syntax:** parse YAML without silently accepting duplicate keys, compile Python
  syntax without executing it, and run Bash `-n` without executing scripts.
- **Bicep:** discover active deployment entrypoints from the pipeline templates,
  compile their real referenced modules, then validate a generated boolean
  parameter matrix against the emitted ARM schemas. Reports distinguish
  entrypoint flags from nested modules, required-default differences and matrix
  coverage. Adding a flag changes the generated matrix automatically.

Both CI providers run unit tests on Linux and Windows, so Windows-only DPAPI,
command-shim and junction regressions are not lost behind Linux skips. Linux
hosts must include Bash, Git and PowerShell Core; the specified hosted images
provide them. CI passes `--require-ci-tools` and fails if a required tool is
missing rather than silently skipping those tests. Platform-specific skips
remain visible in JUnit.

Both CI providers use Python 3.12 and standalone Bicep 0.44.1. The compiler
download is checksum-verified. An explicit dependency preparation step restores
declared public Bicep registry modules; the subsequent compiler checks use
`--no-restore`. Downloads install test tools/modules, not Azure resources.
GitHub Actions are pinned to immutable commits; checkout credentials are not
persisted, and no Azure service connection or repository secret is required.

GitHub publishes JSON and JUnit artifacts for each phase, even when checks fail.
To **block merging** on regressions, add these four checks to the main/release
branch ruleset. Workflow files alone do not enable branch protection.

### Azure DevOps setup

Create a pipeline once using **Existing Azure Pipelines YAML file**, pointing to:

`environment_setup/unit-tests/test-bicep/azure-pipelines.yml`

It runs the same phases/operating-system matrix and publishes JUnit results plus JSON artifacts.
For a GitHub-backed ADO pipeline, the YAML PR trigger applies. For **Azure Repos**,
configure a **Build validation** branch policy for PRs; Azure Repos does not use
the YAML `pr` trigger. Also confirm the pipeline UI has not overridden YAML CI
triggers. This repository change does not register a pipeline or modify branch
policies automatically.

These checks belong in the PURPLE repository. GREEN consumers pinned to a
submodule commit are not changed or deployed by the tests.

## What the matrix proves (and does not)

The matrix exercises baseline, individual flag values and pairwise boolean
combinations, not the exponential Cartesian product of every flag, SKU, region,
tenant and network setting. Compiler/schema acceptance does not execute ARM
resource conditions or prove that a combination can deploy. Parsed pipeline
gates cover specific dependencies; they do not emulate the complete Azure
Pipelines template-expansion service.

`feature-contract-coverage.json` explicitly reports known exceptions:
`ENABLE_AI_FACTORY_HUB` is configuration intent, while `ENABLE_AMPLS` and
`ENABLE_RETRIES` currently lack GHA forwarding. They are inventoried and their
disabled defaults are guarded, **not claimed as tested deployable features**.
Existing ADO/GHA AML-AKS and hybrid-benefit default differences are retained and
reported rather than silently changing customer deployment behavior.

Live Azure validation is still needed for RBAC/policy, private endpoints,
capacity, quotas, provider APIs, runtime provisioning and actual pipeline
execution. A green offline run is not a production-deployment certification.

## Layers (once-and-only-once)

```
tests/
  base/        # no domain knowledge: paths, config parsing, az/nslookup wrappers
  domain/      # AI Factory concepts: scenarios, common/project deploy, PaaS checks
  app/         # lifecycle context managers (deploy -> verify -> guaranteed cleanup)
  unit/        # offline, fast, mocked (no Azure)
  integration/ # live Azure; skipped unless LIVE_AZURE=1
  test_env_parity.py        # existing ADO <-> GitHub var parity
  test_workflow_parity.py   # existing workflow parity
```

## Run

Install the existing requirements in an isolated Python environment:

```bash
cd environment_setup/unit-tests/test-bicep
python -m pip install -r requirements.txt
python run_ci.py --phase unit
python run_ci.py --phase syntax
python run_bicep_matrix.py --bicep bicep --prepare-cache --report test-results/bicep-dependencies.json
python run_ci.py --phase bicep --bicep bicep
# Or, after tools/cache are ready:
python run_ci.py --bicep bicep
```

On Windows, install Git Bash and pass the full installed `bicep.exe` path to
`--bicep`. No `az login` is needed. `test-results/` is ignored by Git; use
`--results-dir` to put CI reports elsewhere. The runner fails if a required tool,
compilation or test fails; it never silently switches to mocked compiler output.

`python -m pytest -q` now includes root-level regressions and excludes the live
`integration/` directory by default. CI additionally supplies explicit offline
test paths and forces `LIVE_AZURE=0`, so an inherited environment cannot opt it
into deployment tests.

To run live tests separately, review the target subscriptions and cleanup logic,
authenticate explicitly, then run `LIVE_AZURE=1 python -m pytest integration -q`.
Some live cases remain placeholders and may create/delete resource groups.

## Idempotency
Integration tests deploy through `app/lifecycle.py` context managers that always
run cleanup (delete resource groups) in `finally`, so the suite re-runs cleanly.

## Implementation status
Offline unit, pipeline-contract, syntax and real compiler/matrix checks are
implemented. Live deploy/cleanup and PaaS coverage remain incomplete; see
SUGGESTED_TESTS.md. Do not infer live coverage from the offline test count.
