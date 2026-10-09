---
id: bootstrap-and-layouts
status: observed
sources:
  - 00-start.sh
  - 01-start-v125-and-above.sh
  - bootstrap/01-aif-copy-aifactory-templates.sh
  - bootstrap/lib/layout_router.sh
  - bootstrap/lib/bootstrap_no_delete.py
  - bootstrap/lib/registered_setup.py
  - bootstrap/lib/registered_creation.py
  - bootstrap/lib/runner_bootstrap.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_registered_creation.py
  - environment_setup/unit-tests/test-bicep/unit/test_registered_prerequisites.py
  - environment_setup/unit-tests/test-bicep/unit/test_runner_bootstrap.py
graph_symbols:
  - bootstrap/lib/registered_creation.py::function:prepare
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Bootstrap and layouts

## Observed entry points

`00-start.sh` is intended to install a control bundle into the parent consumer repository. It routes by layout and has an explicit `--no-delete` bundle-refresh path that avoids legacy cleanup, prompts and dispatch. Ordinary invocation is not equivalent to that safer path.

`01-start-v125-and-above.sh` delegates to `registered_setup.py`: registered-layout onboarding, not a download, source-version change or cloud deployment. `registered_creation.py` maps Simple/Full launcher inputs into the API-owned prepare/review/confirm workflow and does not write factory records or execute cloud bootstrap itself.

| Layout | Meaning |
|---|---|
| `aifactory` | Legacy copied consumer configuration and provider templates. Retained compatibility route. |
| `azurefactory/register.json` | Registered catalog with explicit factory/scale-set/project projections. Empty register is not deployed infrastructure. |
| `copy_to_local_settings`, `copy_my_subfolders_to_my_grandparent` | Canonical sources copied into consumers; do not edit generated consumer projections as if they were upstream source. |

Changing the requested release does **not** migrate layouts. Registered roots reject ordinary legacy update/copy operations; migration requires separate API review and confirmation.

Full bootstrap coordinates prerequisites, identity/provider setup, common infrastructure and selected project stages. Enrollment, runner readiness, network readiness and deployment are distinct milestones. `runner_bootstrap.py` provides a separate plan/ensure route for the exact existing common resource group/subnet; it is not whole-factory creation or permission to change OS/ownership of existing VMs.

## Intended constraints

`00-aif-add-submodule.sh` acquires/initializes the library; it does not merge
configuration. `01-aif-copy-aifactory-templates.sh` copies canonical provider
templates into `aifactory-templates`; the `02a`/`02b` and non-overwriting
`03a`/`03b` provider scripts establish active/template files. The ordinary
ADO/GHA update launchers then merge JSON and YAML/environment assignments,
preserving existing values and legacy keys. Their JSON merge and scale-set
bootstrap share `preserve_template_configuration`: canonical names outrank
duplicate `acrIpWhitelist`/`admin_username` aliases, and adding the default-off
`enablePersonas` flag cannot silently downgrade an existing mode-only opt-in.
Stage/Prod overlays are checked independently. Explicit false is authoritative;
the separate resource-group marker guard still prevents unsafe downgrades.
The exporter, mandatory persona bridge, registered worker and merge guard
normalize flag/mode/manifest aliases inside each section before overlaying it.
A later section's alias overrides an earlier section's canonical value;
canonical spelling wins only among duplicates within the same section.

The canonical JSON, ADO YAML and GHA environment templates expose the project VM,
AKS tier, RBAC-update and seven per-service diagnostic switches using existing
Bicep defaults. Diagnostic values are passed to cognitive-service deployments;
the isolated AI Search capacity runner reads its declared parameter from the
environment. Tests retain only the two reference projects' key inventories,
never customer values. Provider-specific identity, ownership metadata and
connection fields are not invented as cross-provider deployment flags.

Do not bypass blocked registered setup with legacy scripts. Template refresh can modify files; some update routes also commit, push and dispatch. This vault describes those paths but runs none.

See [[Repository-Boundaries]], [[IaC-and-Private-Networking]], [[Lifecycle-and-Recovery]], [[Factory-API-and-SDK]], [[Orchestration-and-Updates]] and [[Index]].

Authority: [setup and migration](../../v2/20-29/24-end-2-end-setup.md), [runner contract](../../../README.md), [API quickstart](../../../environment_setup/azurefactory-cli/readme.md).
