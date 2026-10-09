---
id: factory-api-and-sdk
status: observed
sources:
  - environment_setup/azurefactory-cli/src/azurefactory/client.py
  - environment_setup/azurefactory-cli/src/azurefactory/cli.py
  - environment_setup/azurefactory-cli/src/azurefactory/review.py
  - environment_setup/azurefactory-cli/src/azurefactory/operation_results.py
  - environment_setup/azurefactory-cli/src/azurefactory/preflight.py
  - environment_setup/azurefactory-cli/src/azurefactory/workflow_events.py
  - environment_setup/azurefactory-cli/readme.md
  - environment_setup/install_config_wizard/readme.md
  - environment_setup/install_config_wizard/api-usage-examples/readme.md
tests:
  - environment_setup/azurefactory-cli/tests/test_client.py
  - environment_setup/azurefactory-cli/tests/test_cli.py
  - environment_setup/azurefactory-cli/tests/test_reviews.py
  - environment_setup/azurefactory-cli/tests/test_operation_results.py
  - environment_setup/azurefactory-cli/tests/test_preflight.py
  - environment_setup/azurefactory-cli/tests/test_quickstart_examples.py
  - environment_setup/azurefactory-cli/tests/test_workflow_events.py
graph_symbols:
  - environment_setup/azurefactory-cli/src/azurefactory/client.py::class:AzureFactoryClient
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Factory API and SDK

## Observed consumer contract

`AzureFactoryClient` is a standard-library-only HTTP SDK for the existing local Factory API. It exposes health/capability inspection, configuration/catalog prepare/confirm, parameter changes, registered creation workflows, runtime jobs, monitoring and named factory-deletion routes.

The canonical Tkinter API implementation is external. The documented MAUI build packages that API executable; MAUI is not described as a second REST/provisioning backend. Installed binaries may lag this source. Use the actual host URL/key and capability checks rather than assuming a default listening port or feature version.

Transport validation permits plaintext HTTP only on loopback, rejects URL credentials, redirects and endpoint escapes, and sends the API key in `X-API-Key`. Transport/API authentication is independent from the host's Azure/provider identity and approval to save or deploy.

## Modes and observations

- Catalog/configuration confirmation can return a saved catalog with no runtime job.
- Scoped settings have thin convenience entry points:
  `AzureFactoryClient.catalog_settings_prepare` and CLI
  `catalog configure-settings`. Both use the existing `configure-settings`
  catalog action and separate catalog confirmation; they do not copy server
  editable-key/default rules or provision resources. Successful previews must
  acknowledge configuration-only mode, exact factory/scale/project selectors
  and source revision. The `catalog-settings` review receipt retains the exact
  supplied replacements. Omitted fields remain unchanged; selecting a scale
  with a project does not make shared project settings environment-specific.
  Disabling flags does not authorize deletion. Unknown installed-host fields
  are rejected by that host, without translating names or falling back.
- Project preparation can explicitly request `scale_set_id: latest-successful`
  per environment. The shared API resolves and freezes the exact UUID using
  recorded verified runtime evidence and eligibility constraints; SDK/CLI never
  sort local catalog entries or infer success from saved configuration. The
  selector creates neither infrastructure nor a promotion snapshot. Explicit
  UUID placement behavior is unchanged; old APIs reject unsupported selectors.
  Client review checks bind `resolved_placements` to the exact factory, scale
  scope and project placements before accepting an automatic-selection receipt.
  They do not reproduce server eligibility/ranking or verify live Azure state.
- Registered Full bootstrap is server-owned; clients prepare, approve, observe and explicitly continue supported paused stages.
- Runtime prepare is not runtime execution.
- Poll/watch status is observation; a timeout does not cancel the underlying job or justify reconfirmation.
- Legacy `execution_result` explicitly limits completion to the local script:
  `submitted` is a zero script exit, not provider success; `deployment_verified`
  remains false. The SDK conservatively interprets older status-only replies
  but rejects contradictory acknowledgements. `--wait` and exit code zero do
  not turn local completion into deployed-state evidence.
- Review receipts bind request/preview/scope and expiry; they are not signed
  approvals, provider success receipts or permission to retry uncertain writes.
- Named deletion capability and `can_execute`/retention evidence are required; no fallback to direct shell deletion.
- Named whole-factory reviews must declare a server-owned retention policy
  matching the frozen ordered-pipeline plan. The SDK validator and CLI reject
  missing/conflicting policy or selective retention that the whole-group runtime
  cannot execute. External retained inventory does not prove live preservation.

Agent and MCP adapters consume this client. They do not start or silently upgrade an unavailable API and must report missing endpoints/capabilities as blockers.

External Tkinter/MAUI implementation details are documentation-backed boundaries only in this review. No external checkout or running desktop application was verified.

See [[System-Context]], [[Reviewed-Operations]], [[Packaging-and-Release]], [[MCP-Boundary]], [[Bootstrap-and-Layouts]] and [[Index]].

Authority: [SDK and commands](../../../environment_setup/azurefactory-cli/readme.md), [runnable API scenarios](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md), [desktop distribution](../../../environment_setup/install_config_wizard/readme.md).
