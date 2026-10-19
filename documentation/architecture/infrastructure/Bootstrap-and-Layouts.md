---
id: bootstrap-and-layouts
status: observed
sources:
  - 00-start.sh
  - 01-start-v125-and-above.sh
  - bootstrap/01-aif-copy-aifactory-templates.sh
  - bootstrap/lib/layout_router.sh
  - bootstrap/.gitignore.template
  - bootstrap/lib/bootstrap_no_delete.py
  - bootstrap/lib/registered_setup.py
  - bootstrap/lib/registered_creation.py
  - bootstrap/lib/runner_bootstrap.py
  - bootstrap/lib/runner-prerequisites.sh
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_registered_creation.py
  - environment_setup/unit-tests/test-bicep/unit/test_registered_prerequisites.py
  - environment_setup/unit-tests/test-bicep/unit/test_runner_bootstrap.py
  - environment_setup/unit-tests/test-bicep/unit/test_bootstrap_scoped_creation_guard.py
graph_symbols:
  - bootstrap/lib/registered_creation.py::function:prepare
reviewed_source: 'aecd686a + runner apt-source change; observed 2026-10-19'
---
# Bootstrap and layouts

## Observed entry points

`00-start.sh` is intended to install a control bundle into the parent consumer repository. It routes by layout and has an explicit `--no-delete` bundle-refresh path that avoids legacy cleanup, prompts and dispatch. Ordinary invocation is not equivalent to that safer path.

The bundle includes `registered_personas.py`. Runtime Git ignore exceptions are
derived from the same library inventory used for copying, while the checked-in
ignore template is covered by the round-trip contract. Unlisted local library
files and credentials remain ignored.

`01-start-v125-and-above.sh` delegates to `registered_setup.py`: registered-layout onboarding, not a download, source-version change or cloud deployment. `registered_creation.py` maps Simple/Full launcher inputs into the API-owned prepare/review/confirm workflow and does not write factory records or execute cloud bootstrap itself.

| Layout | Meaning |
|---|---|
| `aifactory` | Legacy copied consumer configuration and provider templates. Retained compatibility route. |
| `azurefactory/register.json` | Registered catalog with explicit factory/scale-set/project projections. Empty register is not deployed infrastructure. |
| `copy_to_local_settings`, `copy_my_subfolders_to_my_grandparent` | Canonical sources copied into consumers; do not edit generated consumer projections as if they were upstream source. |

Changing the requested release does **not** migrate layouts. Registered roots reject ordinary legacy update/copy operations; migration requires separate API review and confirmation.

Full bootstrap coordinates prerequisites, identity/provider setup, common infrastructure and selected project stages. Enrollment, runner readiness, network readiness and deployment are distinct milestones. `runner_bootstrap.py` provides a separate plan/ensure route for the exact existing common resource group/subnet; it is not whole-factory creation or permission to change OS/ownership of existing VMs.

On Linux runners, `runner-prerequisites.sh` installs Azure CLI and PowerShell only from signed Microsoft apt repositories. apt rejects one repository (URL and suite) with two different `signed-by` keyrings, and Defender for Endpoint (`MDE.Linux`, often installed by governance automation) already configures `packages.microsoft.com/ubuntu/<version>/prod` with its own keyring. Before writing `aifactory-<kind>.list`, the script scans `sources.list`, `sources.list.d/*.list` and deb822 `*.sources` for enabled entries of that URL and suite. It reuses them only when their single `signed-by` keyring holds only the Microsoft key `BC528686B50D79E339D3721CEB3E94ADBE1229CF` (the same check its own download must pass). A missing or non-path `signed-by`, other or extra keys, differing keyrings or a differing own source next to them fail closed and name the file. It never edits or deletes files it did not create.

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

For normal legacy ADO updates with JSON override selected, an absent
`aifactory/variables.json` is initialized before tenant lookup from the active,
literal `variables.yaml` mapping. `initialize_json_from_ado_yaml` reuses the
configuration parser's assignment/comment rules, preserves YAML identities and
explicit empty settings, and creates the JSON exclusively without overwriting
existing files. Invalid, duplicate or unsupported YAML fails before creation.
The later template merge adds missing defaults. Project-only, reviewed and
registered routes retain their existing configuration requirements; no template
identity, tenant fallback or deployment authorization is inferred.

The canonical JSON, ADO YAML and GHA environment templates expose the project VM,
AKS tier, RBAC-update and seven per-service diagnostic switches using existing
Bicep defaults. Diagnostic values are passed to cognitive-service deployments;
the isolated AI Search capacity runner reads its declared parameter from the
environment. Tests retain only the two reference projects' key inventories,
never customer values. Provider-specific identity, ownership metadata and
connection fields are not invented as cross-provider deployment flags.

The canonical templates now expose `aiSearchFallbackLocationArrayDev` and
`aiSearchFallbackLocationArrayStageProd`, both defaulting in order to
`["francecentral","denmarkeast","italynorth","norwayeast","germanywestcentral"]`
(Germany last), as native JSON arrays and serialized ADO/GHA arrays.
GHA's explicit registration routes
`AI_SEARCH_FALLBACK_LOCATION_ARRAY_DEV` and
`AI_SEARCH_FALLBACK_LOCATION_ARRAY_STAGEPROD` as repository variables; project
job bindings and JSON overrides forward them into preflight and the shared
Search runner. Up to five fallback regions plus the primary permit at most
18 region/SKU combinations. The defaults affect only new Search provisioning,
not runtime failover or index migration; review residency before deployment.
Denmark East is intentionally retained based on portal availability despite
its omission from the Microsoft AI Search region list; Germany's capacity
warning is known, not an availability guarantee. Refreshing templates does not
alter source pins.
Registration serializes an explicitly empty region-array value as `[]` to clear
prior opt-ins; explicit `[]`/blank disables regional fallback. Missing runtime
fields and undefined GHA variables retain `[]`, and unrelated empty settings
retain existing behavior. A normalized per-environment CI gate skips the separate
regional-fallback task for empty values; ordinary Search/networking and SKU-only
retries remain enabled under their existing service/deletion/debug/phase gates.

Do not bypass blocked registered setup with legacy scripts. Template refresh can modify files; some update routes also commit, push and dispatch. This vault describes those paths but runs none.

See [[Repository-Boundaries]], [[IaC-and-Private-Networking]], [[Lifecycle-and-Recovery]], [[Factory-API-and-SDK]], [[Orchestration-and-Updates]] and [[Index]].

Authority: [setup and migration](../../v2/20-29/24-end-2-end-setup.md), [runner contract](../../../README.md), [API quickstart](../../../environment_setup/azurefactory-cli/readme.md).
