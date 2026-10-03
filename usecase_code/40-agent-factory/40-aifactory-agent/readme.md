# Enterprise Scale AI Factory Agent

A versioned Microsoft Foundry prompt agent with Azure AI Search grounding,
backend-enforced scope/authorization, existing Factory API/CLI adapters, and a
private web frontend. Selecting Platform or Project changes explanations, not
permissions. Configuration persistence, agent deployment and Azure provisioning
are distinct operations.

## Boundaries

- Use existing Foundry, Search, project data storage and internal Container Apps
  resources. No separate Factory API host is required to deploy this solution.
- The existing Factory HTTP API is required **only** for Factory operations that
  use it. Its clients are real `AzureFactoryClient` / `azurefactory` integrations,
  not another provisioning engine. An unavailable endpoint is reported as a
  blocker, never mocked into success.
- The initial deployment enables one explicit DEV scope. No subscription-wide
  write, arbitrary shell or audience-based elevation. Factory actions stay
  disabled until their dedicated grants and reviewed server-side targets exist.
- The application managed identity has no Azure Contributor or Owner grant.
  Search read and Foundry inference use their supported service-level roles;
  application scope filters and user grants remain mandatory.
- The private network and existing service tiers are not changed. The shared
  Container Apps environment references a common-group subnet; this deployment
  does not modify it or its DNS.
- A dedicated Entra registration or an approved existing one is needed for web
  sign-in. Unconfigured sign-in fails closed. Operator CLI questions use the
  actual signed-in user's object ID and the same configured authorization.

## Configuration and installation

All Azure identifiers, endpoints, model deployment, Search/storage choices,
Factory API URL, project scopes, users and corpus paths live in configuration,
not application code. `config.example.json` contains the initial target and no
credentials. Copy it to `config.local.json`, which is ignored by Git.

```powershell
Set-Location C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory\40-aifactory-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e ..\..\..\environment_setup\azurefactory-cli
Copy-Item config.example.json config.local.json
```

Use `credential: "cli"` only for operator deployment. Cached Azure sign-in must
belong to the configured tenant. Production configuration is generated with
`managed_identity`, never user token caches or CLI passwords. No automatic
interactive login, subscription switching, secret fallback or device-code login.

For another tenant/subscription, replace configuration values and supply existing
private service resources. Paths resolve relative to the configuration file.
The packaged cloud snapshot uses a Linux-native repository path automatically.

## Model and agent

The initial Azure catalog advertised `gpt-6.1-sol`, version `2026-09-29`, with
Agents v2 and Responses support in Sweden Central. The initial deployment is
`aifactory-agent-gpt-6-1-sol`, EU `DataZoneStandard`, capacity 10. Verify catalog,
quota, capabilities and project compatibility again for a different target.
Do not replace an unavailable requested model without approval.

```powershell
.\.venv\Scripts\python.exe -m aifactory_agent --config config.local.json deploy-agent
```

The name is ownership-checked. A changed definition creates a new agent version;
an identical definition reuses the existing version. Set `agent_version` to pin
invocations or roll back. Foundry instructions and function definitions are in
`aifactory_agent\foundry.py`. The backend executes client-side functions; creating
an agent alone does not host those functions in the Foundry portal.

## Grounding, refresh and citations

```powershell
.\.venv\Scripts\python.exe -m aifactory_agent --config config.local.json ingest
.\.venv\Scripts\python.exe -m aifactory_agent --config config.local.json knowledge-status
```

The initial corpus includes the setup/ITSM guides, Foundry examples, substantive
ML documentation, API/CLI references and **all** `RELEASE_*.md` files, including
future files. The original `30-machine-learning` directory has only an empty
README; that is a source coverage gap, not machine-learning evidence.

Inclusion/exclusion rules are configurable. Credentials/environment files,
dependencies, generated output, tests/evaluations and unrelated formats are
excluded. Fenced commands, heading context and source lines are retained.
Chunks carry source path/type, headings, content hash, version/release metadata,
scope access and citations. Release notes remain historical information.

Refresh reconciles changed and removed source chunks against a Blob manifest.
Only task-owned index documents are reconciled. Partial indexing failures do not
advance the committed manifest. The status endpoint distinguishes unavailable,
stale and successful ingestion. Refreshing an immutable cloud source snapshot
does not fetch newer repository content: package/deploy an updated approved
snapshot first, then refresh it.

Hybrid text/vector retrieval uses configured semantic reranking. The initial
Search service has free semantic ranking; its quota is shared. Errors are
surfaced, not silently downgraded. Approve a service change separately if a larger
semantic quota or Search tier is needed.

Documentation is intended behavior. Authenticated SDK/API observations are live
state. Installed factory version is explicitly unknown until authoritative
environment evidence establishes it; repository HEAD or newest release notes are
not installation evidence.

## Operator questions

```powershell
.\.venv\Scripts\python.exe -m aifactory_agent --config config.local.json ask `
  --scope project001-dev --audience platform `
  --question "Does saving configuration deploy resources, and how does Full bootstrap differ?"

.\.venv\Scripts\python.exe -m aifactory_agent --config config.local.json ask `
  --scope project001-dev --audience project `
  --question "How can a project team start using Foundry agents in an existing AI Factory?"
```

Both commands use the persisted Foundry agent and real Search retrieval. Model
answers must cite supplied evidence. Tool calls are bounded, errors propagate,
and inference/writes are not blindly retried.

## Private application deployment

Infrastructure definitions are `infra\identity.bicep` and
`infra\application.bicep`. The latter creates a new application in the existing
internal environment. It does not configure public networking or a new registry.

The digest-pinned Microsoft Azure CLI image downloads an integrity-pinned code
bundle from the task-owned private Blob container using its managed identity.
Dependencies are installed **offline** from locked Linux wheels. No code is
downloaded from GitHub or dependencies from package feeds during startup.
This source-bundle approach avoids creating a public registry or changing a
shared private registry/network. Treat the bundle as executable deployment
content and protect its container and deployment permissions.

```powershell
.\.venv\Scripts\python.exe -m pip download --dest .build\wheels `
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 `
  --python-version 312 --implementation cp --abi cp312 --only-binary ":all:" `
  -r requirements.lock.txt pip==25.3

# Read-only deployment plan:
.\.venv\Scripts\python.exe deploy.py --config config.local.json `
  --environment aif-mcp-project001-dev-env

# Only after approval of the printed scope and grants:
.\.venv\Scripts\python.exe deploy.py --config config.local.json `
  --environment aif-mcp-project001-dev-env --apply
```

Application resources are tagged `managed-by: enterprise-scale-ai-factory-agent`.
The bootstrap needs Blob-role propagation and private DNS. The startup probe
allows bounded initialization time. `/health/live` means process alive;
`/health/ready` includes prerequisites and must not be interpreted as operational
readiness while sign-in or knowledge is blocked.

## Authentication, tools and approvals

### OOAD and dependency injection

`aifactory_agent\ports.py` defines structural interfaces for knowledge,
model sessions, Factory API/tools, cost reporting, audit and operation storage.
`AgentServices` is the per-agent composition root. `AgentDependencies` supplies
constructor-injected factories and authentication; HTTP handlers and operator
CLI use these services rather than constructing cloud clients themselves.
`AgentServiceFactory` is an abstract factory interface, with `AgentFactory`
creating independent compositions from explicit configuration profiles.

```python
from aifactory_agent.config import load_settings
from aifactory_agent.services import AgentFactory
from aifactory_agent.web import create_app

factory = AgentFactory({
    "platform": load_settings("platform.config.json"),
    "reviewer": load_settings("reviewer.config.json"),
})
platform = factory.create("platform")
reviewer = factory.create("reviewer")
platform_app = create_app(platform.settings, services=platform)
reviewer_app = create_app(reviewer.settings, services=reviewer)
```

Each configuration specifies its own agent name/model, scopes, grants and
knowledge ownership. Use separate owned indexes/containers where corpus policies
differ. Knowledge and approval services have a per-agent lazy lifetime; caller
and scope-bound tool/cost adapters are created per request. There is no global
singleton that stores a principal, credential-bearing API session, approval or
conversation history. Operation records are isolated in an agent namespace,
and that namespace is covered by the plan hash and record signature. Old
unnamespaced approvals are not migrated or replayed automatically; prepare anew.

New capabilities are developed with failing interface tests first, then real
adapters and green tests. Fakes implement the same interfaces without cloud
construction or monkeypatching production authorization. Use Factory/Strategy
for selecting implementations, Adapter for SDK boundaries, and Command/State
for persisted operations. Do not add every pattern speculatively.

This follows the [Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/)
and [cloud design patterns](https://learn.microsoft.com/en-us/azure/architecture/patterns/):
least privilege and signed approvals (security), explicit uncertain outcomes and
bounded retries (reliability), async job observations (performance), sourced
cost coverage (cost optimization), and immutable bundles/tests/audit
(operational excellence). This is design alignment, not a claim of a completed
Well-Architected production assessment.

Configure `auth.client_id`, `auth.audience`, `required_scope` and exact object-ID
grants before web use. Entra tokens are checked for the configured tenant,
issuer, audience, validity and delegated scope. No browser-provided user ID,
audience toggle, model argument or managed identity establishes user authority.
Tokens stay in browser memory; the frontend uses authorization-code PKCE.

Factory adapter inputs are closed typed schemas and server-side selected IDs.
`factory_cli_health` uses an allowlisted argument array and never model-generated
shell text. Prefer direct API tools for capabilities supported by both.
Unavoidable API keys use a configured Key Vault secret URL or an explicitly
supplied process secret; they never appear in command arguments or receipts.

Factory writes are disabled in the example until the actual endpoint, exact
catalog identifiers and supported contract have been confirmed. Supported
configuration changes require a persisted, caller/scope/revision-bound plan,
expiry, explicit approval of the exact plan hash, and a one-use execution state.
The model cannot approve. Drift or uncertain execution stops the workflow;
lost replies are not permission to replay a non-idempotent write.

### Factory skills

The authenticated **Factory actions and cost monitoring** panel exposes eleven
named skills. These are agent capabilities, not shell aliases or automatic
permissions:

| Command | Behavior |
| --- | --- |
| `/create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj` | Prepare Full bootstrap from an approved server-side private hub/VPN/default-project profile. |
| `/delete-aifactory` | Prepare whole-factory deletion against an explicitly authorized resource manifest; preserve Entra security groups. |
| `/add-project-to-aifactory` | Prepare a new project in the configured factory and scale set. Configuration persistence and Azure deployment are reported separately. |
| `/get-default-project-estimated-azure-idle-running-cost` | Estimate provisioned project baseline from the canonical default `variables.json`, including enabled services and selected SKUs, and compare with Azure Cost Analysis. |
| `/get-aifactory-common-estimated-azure-idle-running-cost` | Analyze a supplied common resource group only when it is explicitly authorized for the active scope. |
| `/get-monthtly-forecasted-project-estimated-azure-cost` | Read actual and forecast monthly project costs for the active project's resource group. The correctly spelled `monthly` alias is also accepted. |
| `/get-aifactory-health` | Read the existing Factory API health without changing configuration. |
| `/get-aifactory-settings` | Read only the exact server-selected factory/project/environment settings. |
| `/get-aifactory-operation-status` | Observe an operation owned by the requesting user in the active scope; never accept an arbitrary backend job or folder. |
| `/create-agent-oftype-for-project` | Select an immediate agent-template folder and the exact approved Foundry project resource ID; prepare one version without changing routing. |
| `/create-ml-model-oftype-for-project` | Select an immediate ML template folder, `batch`/`online`/`streaming` mode, and the exact approved workspace or project resource group ID; prepare asynchronous training without implicit registration or serving promotion. |

Action permissions are distinct: `factory.create`, `factory.delete` and
`project.add`, `agent.create` and `model.create`. Department `config.write`
does **not** grant any of them.
Monitoring requires `cost.read` and `factory.read`. All grants are checked
against the requesting caller and exact active scope; selecting the Platform
view grants nothing.

`GET /api/skills?scope_key=...` returns closed argument schemas and setup
blockers. Read-only reports use `POST /api/skills/{name}/run`. Actions use
`POST /api/skills/{name}/propose` to create a pending signed Blob record, then
the existing separate hash approval and one-use execution endpoints. There is
no raw-plan execution endpoint and no action preparation from model chat.
Deletion additionally requires the exact backend-provided confirmation phrase.
Unknown, running and paused jobs are never presented as completed. Status
observation does not retry, re-confirm or automatically continue a write.
An interrupted approved Full bootstrap can be explicitly continued through
`POST /api/operations/{id}/continue` with the original `plan_hash` and the
current paused-stage `observation_hash`. The store claims that observation once
with Blob CAS. Continuation preserves the initial approval and job binding,
validates the original whole-workflow authorization and expiry, and refuses
changed scope, recovery, stale observations and uncertain write replay.

Configure `actions.enabled_skills` explicitly, keyed
`actions.bootstrap_profiles` for creation, and
`actions.deletion_resource_groups` for whole-factory deletion. A bootstrap
profile must pin the backend program, source assets and normalized workflow
input hash, identify every approved resource group/deployment identity, and
specify the private hub, nonoverlapping VPN pool and provider repository bounds.
An existing project grant is not permission to create or delete an entire factory.
`factory.operation_signing_secret_url` must identify a dedicated Key Vault
HMAC secret, separate from the Factory API credential. Deployment profiles are
server configuration, never model-supplied JSON.

`costs.common_resource_groups` is an explicit resource-group name allowlist
keyed by authorized scope. `costs.currency` defaults to USD; estimates never
convert or combine currencies. The checked-in default template is
`environment_setup\aifactory\variables.json`, pinned by SHA-256 and included
in the offline application bundle. A template override additionally requires
`costs.default_variables_sha256`; a changed/unpinned template fails closed.
Grant the execution identity resource Reader and the appropriate Azure Cost
Management read access only on approved billing targets. The skills do not
grant roles or elevate the caller.

### Project-template workload strategies

`GET /api/templates?scope_key=...` discovers actual immediate source-folder types,
with exact configured targets and explicit blockers. Agent templates come from
`usecase_code\40-agent-factory`; shared helpers, generated folders and empty
placeholders are not deployable agent types. ML templates come from
`usecase_code\50-ml-model-factory\batch`, `online` and `streaming`. The same
type name can appear in more than one mode, so `serving_mode` is required.

```json
{
  "scope_key": "project001-dev",
  "arguments": {
    "type": "41-single-agent",
    "project_resource_id": "/subscriptions/<subscription>/resourceGroups/<project-rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>"
  }
}
```

```json
{
  "scope_key": "project001-dev",
  "arguments": {
    "type": "regression",
    "serving_mode": "batch",
    "project_resource_id": "/subscriptions/<subscription>/resourceGroups/<project-rg>/providers/Microsoft.MachineLearningServices/workspaces/<workspace>"
  }
}
```

Send these to the corresponding `/api/skills/{name}/propose` endpoint, not
directly to execution. Every selection requires a server-approved
`workloads.profiles[scope_key]` entry and `workloads.enabled_skills`.
Profiles specify `profile_id`, `kind`, `type`, `family`,
`project_resource_id`, and a credential-free repository-relative `config_path`.
Agent profiles select one `catalog_selection` and `agent_prefix`; hosted
profiles also select explicit runtime/source and output bounds. Model profiles
select `serving_mode`, canonical `scenario_path`, `training_mode` and
`output_directory`. Neither caller text nor folder names select an arbitrary
module, command, repository path, compute or deployment identity.

`TemplateCatalog` is an interface and `WorkloadAdapter` an abstract Strategy
with typed plans/results. Constructor-injected `WorkloadRegistry` instances
select real prompt/hosted/AML adapters; they reuse the purple factories rather
than introduce another provisioning engine. Source/config manifests and exact
project IDs are hash-bound to the signed approval and revalidated before use.
Creation uses the purple SDK directly and does not require a Factory API key.

The thin cloud bundle includes only approved-profile source types and their
required code/configuration; it does not copy datasets, private/generated
files or the entire checkout. Unconfigured types are discoverable only when
the full approved source tree is separately available. Missing SDKs, profiles,
source/configuration or permissions are blockers, never placeholder success.
Agent version creation is not endpoint routing. Training submission is not a
completed/registered model or an online deployment; these phases remain explicit.

Idle running cost means the provisioned baseline with no workload traffic; it
does not assert measured inactivity. Retail/template estimates, Cost Analysis
actual charges and Azure forecasts remain separate, with currency, period,
source, assumptions and missing-price/data coverage surfaced explicitly.
An unpriced enabled resource or unavailable billing data is **unknown**, not
zero cost. Do not infer a price from a similar SKU or mix currencies.

Operation history/audit data lives in the owned private Blob container. Record
the requester, scope, operation, correlation ID, timestamps and observed outcome,
not secret values or entire conversations. Pending plans can be cancelled;
underlying jobs can be cancelled only if the Factory interface supports it.
Closing a progress feed does not cancel a job.

## Operations, updates, rollback and teardown

- Refresh the approved corpus after documentation/release changes. Rebuild the
  immutable bundle after application or dependency changes.
- Keep the previous agent version, bundle hash and Container Apps revision.
  Revert `agent_version` and shift traffic to the known-good revision for an
  application rollback. This does not roll back a Factory operation.
- Application Insights integration can be configured using
  `azure.application_insights_connection_string`. Capture health, retrieval/tool
  errors, latency and model token usage without prompt bodies or credentials.
  Container Apps startup/application logs remain available in Azure.
- For access failures, inspect the exact requesting user grant, token audience,
  service-role propagation, private DNS and the active scope. Do not enable
  public access or grant Contributor as a shortcut.
- Teardown requires a separately approved exact manifest: this application's
  revisions, its managed identity/role assignments, task-owned index/container
  contents, owned agent versions and owned model deployment if no other workload
  uses it. Preserve Foundry, Search, storage, Cosmos, Key Vault, Container Apps
  environment, networking, Entra groups and all unrelated resources. Deleting
  the resource group is never an appropriate teardown command.

## Costs and service tiers

Pricing assumptions: USD retail, Sweden Central, 730 hours/month, before free
grants, discounts and taxes. Azure Retail Prices API observed active Container
Apps rates of $0.000024/vCPU-second and $0.000003/GiB-second. One continuously
active 0.5-vCPU/1-GiB app is approximately **$39.42/month** for compute alone.
Replica counts are configurable; scale-to-zero reduces compute but introduces
cold starts. Private access still requires the factory's private connectivity.

Existing Basic Search is reused unchanged. A separate Basic unit was priced at
$0.101/hour ($73.73/month); three S1 units at $0.336/unit-hour would be
$735.84/month, **not** a change authorized or performed by this implementation.
Production availability/isolation may require separately approved replicas,
partitions or dedicated services.

Model/embedding usage, storage, monitoring, requests and existing environment
charges are additional. GPT 6.1 prices were not present in the queried retail
records; the public pricing page exposed placeholders. No total model price is
invented. Use your verified agreement/calculator rates and actual usage.

## Automated tests and evaluations

Use the repository's existing pytest runner; live evaluations are separate from
mocked unit tests. `evaluations.json` covers both audiences, release/current/live
distinctions, unsupported instructions, injection, unauthorized scope, unapproved
writes, arbitrary shell and live state. Tests cover schema/authorization, approval
replay/concurrency, corpus changes/deletions, failure-safe manifests and portability.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

See `deployment-status.json` for observed deployment/evaluation evidence and the
explicit separation between demonstrated, unexercised and blocked capabilities.