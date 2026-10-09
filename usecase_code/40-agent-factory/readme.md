# Agent Factory implementation

This directory is a factory-neutral starter for persistent Foundry prompt agents,
framework-based hosted agents, and a hosted multi-agent team. The operator runs
Python locally; Foundry runs the deployed agents. **There is no single
`python main.py` command that runs every folder.** Use the shared operator for
`41`/`42`, the dedicated entry points for `43`/`44`/`45`, and the separate
application environment for `40-aifactory-agent`.

Start with [prerequisites](#prerequisites),
[Python setup](#how-to-set-up-the-python-environment), and
[how to run the code](#how-to-run-the-code). Each folder's README then gives its
own commands, required inputs and expected results.

## Folder layout

```text
40-agent-factory\
  readme.md                    Start here: shared setup and execution workflow
  requirements.txt             Local operator SDK pins, not every runtime's packages
  config.example.json          Template for consumer-owned target configuration
  40-aifactory-agent\           Separate documentation-grounded agent and private web app
  40-aifactory-agent-v2\        Placeholder only; no runnable implementation yet
  41-single-agent\
    prompt-agent\              Declarative agents deployed by the shared operator
    hosted-agent\              Shared runtime helper and framework-specific main.py files
      agent-framework\
      langgraph\
      openai-agent-sdk\
      github-copilot-sdk\
      custom\
      anthropic-agents\
  42-multi-agent\              Hosted knowledge -> reviewer -> synthesis team
  43-data\                     Managed-identity ingestion and optional Azure-hosted worker
  44-azure-mcp\                Private, read-only Azure inventory service setup
  45-rag-agent\                Explicit source-bound common/project storage RAG
  agent_factory\              Shared Python operator/library; python -m agent_factory
  tests\                      Offline regressions; fixtures\ contains synthetic JSON
```

| Folder | How it runs |
| --- | --- |
| [40-aifactory-agent](40-aifactory-agent/readme.md) | Its own environment/configuration and `python -m aifactory_agent`; optional private web service. |
| [40-aifactory-agent-v2](40-aifactory-agent-v2/readme.txt) | Not runnable; use the implemented sibling above. |
| [41-single-agent](41-single-agent/readme.md) | Choose a [prompt agent](41-single-agent/prompt-agent/readme.md) or [hosted framework](41-single-agent/hosted-agent/readme.md), then shared `plan`, `deploy`, `invoke`. |
| [42-multi-agent](42-multi-agent/readme.md) | Deploy knowledge/reviewer participants, then the hosted team; invoke its persisted name. |
| [43-data](43-data/readme.md) | Shared `*-datafactory` commands; optional `worker.py` runs only on approved managed-identity compute. |
| [44-azure-mcp](44-azure-mcp/readme.md) | `44-azure-mcp\deploy.py` for infrastructure planning; shared commands configure/verify the connection. |
| [45-rag-agent](45-rag-agent/readme.md) | `45-rag-agent\main.py` with one explicit `--source`; its own prepare/deploy/ask lifecycle. |
| [agent_factory](agent_factory/readme.md) | Shared library/CLI, not another agent to deploy. |
| [tests](tests/readme.md) / [fixtures](tests/fixtures/readme.md) | `unittest` from this directory; no agent, Azure login or live dataset needed. |

Keep three kinds of files separate: **consumer configuration** outside the copied
code, **maintainer-owned code/templates** in this tree, and **generated local
artifacts** such as `.venv`, target exports and journals. Deployment journals and
ZIPs are stored beside the selected configuration under
`.agent-factory\<account>\<project>`, not in framework source folders. Do not
commit credentials, local environments or generated journals.

## AI Factory shared lake RAG example

[45-rag-agent](45-rag-agent/readme.md) is the explicit end-to-end example for
reading a pinned corpus from either common ADLS Gen2 or project Blob Storage.
It preserves the existing `mlops/v1/master` and `mlops/v1/projects` physical
paths, describing them as the **AI Factory shared lake**. ADF copies only the
selected source into an isolated retrieval folder; Search and Foundry IQ serve
separate, source-bound RAG agents. All examples inherit the storage selection
below. Omitting it preserves existing `43-data` behavior. No per-user ACL
filtering, binary extraction or lake rename is implied.

The hosted multi-agent team calls separately persisted knowledge and reviewer
agents. Target names are discovered from ARM in
the selected project resource group; Bicep's generated resource-name salts are not
guessed.

Grounded answers must preserve the scope of their evidence. A generic procedure
is not proof that it applies to a named product or feature. When that applicability
is undocumented, the knowledge agent reports the gap instead of supplying generic
steps as a workaround; reviewers and hosted workers retain that limitation.

## Separation and template copying

- Make shared changes here in the purple repository, never in a consumer's submodule.
- `bootstrap/01-aif-copy-aifactory-templates.sh` already copies this entire directory
  to `aifactory-usecase-code/40-agent-factory` in a consumer repository.
- Keep project configuration at `aifactory/agent-factory/config.json`, outside that
  generated directory. The full bootstrap replaces generated use-case code.
- Copy `config.example.json` to that configuration location. Its `variables_file`
  is resolved relative to the config file, not the current working directory.
- Multiple named targets are supported in configuration. Every mutation selects
  exactly one target; there is deliberately no implicit subscription/fleet-wide write.
  Ambiguous accounts/projects require an explicit `selection`.

## Prerequisites

| Requirement | When it is needed |
| --- | --- |
| Python **3.13** with `venv`/`pip` and PowerShell | Shared operator and the hosted examples. Use `py -3.13` on Windows; if the launcher is absent, use the full path to that Python installation. |
| A checkout or generated consumer copy of this tree | Run shared commands from the directory containing `agent_factory`, not inside a framework folder. |
| Package-feed access during environment setup | Install the checked-in dependency pins. Do not install every framework into the operator environment. |
| Azure CLI (`az`) and browser-based Entra sign-in for the target tenant | Live discovery, preflight, deployment and invocation; not CLI help, offline plans or ordinary unit tests. |
| Existing AI Factory `aifactory\variables.json` and a resolved Agent Factory config | Offline plans validate real configuration, not the unresolved placeholders in `config.example.json`. |
| Existing Foundry account/project, compatible model deployment, Search, data storage and project identity | These examples use existing infrastructure; they do not bootstrap an entire factory. |
| VPN/private DNS and network reachability | The operator must reach the selected private data endpoints. No public-network fallback. |
| Scope-appropriate Azure permissions | Operator discovery/deployment access, data-plane access, and separately approved managed-identity permissions for ingestion/retrieval. Contributor alone does not imply data access. |

If the local tools are missing, install
[Python for Windows](https://www.python.org/downloads/windows/) with the
requested Python version and `py` launcher, and
[Azure CLI for Windows](https://learn.microsoft.com/cli/azure/install-azure-cli-windows).
Open a new PowerShell window after installation. `py -3.13 --version` and
`az version` should work before starting the shared live workflow.

For default grounded examples, finish [43-data](43-data/readme.md) and
`configure-knowledge` first. Hosted agents additionally need supported regional
hosting, private network injection, capability-host/model access and permitted
build egress. The optional expanded tool profile needs
[44-azure-mcp](44-azure-mcp/readme.md); the default profile does not.
Anthropic requires a separately approved compatible Foundry Claude deployment.

`40-aifactory-agent` is a **separate application** using Python 3.12 and its own
locked dependencies/configuration; follow its README instead of this shared
environment. The optional managed-identity data worker also has its own
requirements. No API keys, PATs, device-code sign-in or globally installed SDKs
are required by the shared operator workflow.

## How to set up the Python environment

Use PowerShell. Change the checkout path below for your machine. If using a
consumer copy, select `<consumer>\aifactory-usecase-code\40-agent-factory`
instead; **do not edit the consumer's purple submodule**.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m agent_factory --help
```

Create the environment once, then reuse it. The explicit interpreter avoids
PowerShell activation/execution-policy issues and accidental global installs.
In a fresh terminal, return to this directory and use the same interpreter;
there is no need to recreate the environment. If already using a different
Python version in `.venv`, create a separately named 3.13 environment rather
than overwriting it, and adjust subsequent interpreter paths.

The root manifest installs the **operator** SDKs. Hosted `requirements.txt`
files are packaged with their respective runtimes and installed by Foundry.
Installing only a framework manifest locally does not generate
`agent_spec.json`, supply hosted credentials or deploy an agent. These are not
independent workstation chat scripts.

## One storage selection for every example

`config.example.json` defaults **new** configurations to
`"use_common_datalake_storage": false`. Replace its unresolved account/group
placeholders with existing resources before running `plan`:

```json
{
  "use_common_datalake_storage": false,
  "storage_targets": {
    "common": {
      "account_name": "yourcommonlake",
      "resource_group": "your-common-rg",
      "container": "lake3"
    },
    "project": {
      "account_name": "yourprojectdata",
      "resource_group": "your-project-rg",
      "container": "agent-factory"
    }
  }
}
```

- `true` selects the explicit existing common-RG data account, with default
  container `lake3`; `false` selects the explicit project-RG **data** account,
  with default container `agent-factory`. Neither means local disk, Foundry
  `1001` metadata storage, or AML workspace artifact storage.
- Use actual JSON booleans. Strings such as `"false"`, numbers and `null` fail.
  Account name and resource group are mandatory in the selected profile. The
  group must match the corresponding group derived from `variables.json` or
  overridden in the target's `selection`. No first-account/prefix guessing:
  e.g. common accounts for multiple factories must be selected explicitly.
- All targets inherit these root fields. Override under
  `targets[i].selection.use_common_datalake_storage` and/or
  `targets[i].selection.storage_targets`. Profiles merge **by field**, root
  first, target second; other targets remain unchanged. For example,
  `"selection": {"use_common_datalake_storage": true, "storage_targets":
  {"common": {"container": "reviewed-data"}}}` inherits the common account/group.
  Conflicting flat `storage_name`, `storage_resource_group` or
  `storage_container` values are rejected.
- Omitting the flag preserves legacy `2001` project discovery and legacy route
  containers (`agent-factory`, `agent-factory-adf`, `agent-factory-rag`). Old
  credential-free `target.json` files still load; regenerate them with
  `discover --output target.json` to propagate a new selection to `43-data`.
  A worker `--container` override must match the selected profile, never silently
  redirect its writes. Custom profile containers apply to every route.
- `41-single-agent` prompt/hosted frameworks and `42-multi-agent` consume the
  selected ingestion/Foundry IQ path; no runtime-specific storage paths change.
  `43-data` uploads, ADF linked services/datasets/private links and Search data
  sources use the same account/group/container. `44-azure-mcp` inherits discovery
  but its inventory/identity scope remains the **project** RG. Foundry, Search,
  ADF and the project UAMI are never moved to the common RG.
- `45-rag-agent/sources.example.json` omits storage location/account/container
  so sources and isolated materializations inherit this selection. An explicit
  source storage field must match the selected profile. Source formats, pinned
  hashes, manifests and project audience checks still apply: selecting common
  storage does not convert a knowledge array into a shared-lake snapshot.
  Without the flag, retain all three explicit source storage fields as described
  in the legacy RAG guide. Existing source paths are not renamed or migrated.

This setting does not provision accounts, grant write permissions, change runtime
cloud settings, or enable public access. In selected mode the private container
must already exist; its metadata/ownership is not changed. Operators must arrange
private connectivity, project-UAMI data permissions and Search MI read access on
the **selected** account/container. Existing explicit `--apply` operations still
configure owned ingestion/retrieval artifacts; incompatible old artifacts fail
rather than being silently repointed. Re-run discovery, ingestion and knowledge
verification after changing profiles; do not reuse old grounding journals.
`plan` is offline; discovery and data/network verification are read-only cloud
operations. Plans, target exports and storage results expose resource names,
groups and containers, never credentials.

After changing storage selection, reconfigure and verify ingestion/knowledge and
redeploy the affected agents. Invocation checks the stored deployment and knowledge
selection rather than reporting a new account while retrieving from an old one.
Index provenance checks cover the complete bounded corpus, not just one document.
With explicit storage profiles, the ADF ingestion prefix includes a target-specific
route suffix so its metadata writes cannot collide with the standalone worker or
another project's ADF route in the shared container.

## How to run the code

### 1. Prepare consumer-owned configuration

Stay in the `40-agent-factory` directory used during Python setup. Replace
`C:\code\my-aifactory` with your actual consumer repository. This absolute config
path works whether the executing code is in purple or in the generated consumer
copy. **Do not copy over an existing configuration.**

```powershell
$ConsumerRoot = "C:\code\my-aifactory"
$Config = Join-Path $ConsumerRoot "aifactory\agent-factory\config.json"
$Target = "project001-dev"
New-Item -ItemType Directory -Force (Split-Path $Config) | Out-Null
if (-not (Test-Path $Config)) {
    Copy-Item .\config.example.json $Config
}
```

Edit the new config before proceeding: select the existing storage
account/resource group/container, target key and environment. Its
`variables_file` is relative to the config file (`../variables.json` in the
template), so it must point to the consumer's existing, resolved infrastructure
variables. Use `selection` for an explicit Foundry account/project/model when
discovery would otherwise be ambiguous. `model_overrides` is keyed by framework.
The default agent prefix is `aif`; adjust all sample agent names if you change it.
This configuration is **not** `40-aifactory-agent\config.local.json`.

### 2. Plan offline, then check the selected Azure target

```powershell
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target
```

The plan prints the resolved target configuration and catalog with
`"mutations": false`. It does not authenticate, discover resources or prove that
Azure prerequisites are present. Stop and fix unresolved values or wrong scope.
Use `--agent aif-knowledge` (or another exact catalog name) to plan a subset.

For the following live, read-only steps, use cached OAuth first. If unavailable,
run `az login --tenant "<target-tenant-id>"` and complete browser sign-in. Never
print/store access tokens or switch the global subscription to make examples
work. Connect the approved VPN/private network before preflight.

```powershell
.\.venv\Scripts\python.exe -m agent_factory discover --config $Config --target $Target
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
```

Discovery returns actual resource IDs/endpoints. Preflight checks private
DNS/TCP plus Foundry/Search access; failures are blockers, not permission to
enable public access. To save a credential-free target for the optional worker,
add `--output` with an explicit local path as shown in [43-data](43-data/readme.md).

### 3. Prepare dependencies for the selected use case

For a new grounded target, complete the [data and Foundry IQ](#data-and-foundry-iq)
steps below once. Reuse verified ingestion and knowledge journals for an
unchanged target; do not start new copies just to ask another question.
For the team, deploy its knowledge and reviewer participants before the team.
For a source-bound corpus use [45-rag-agent](45-rag-agent/readme.md), whose
`main.py` and `--sources`/`--source` options replace the shared deployment flow.

### 4. Deploy one selected example, then ask it a question

The following is the smallest prompt-agent example **after knowledge setup**.
`deploy --apply` is an Azure write that creates/reuses an owned agent version;
only run it after reviewing the target and permissions. `invoke` is a billed
model/tool request even though it has no `--apply` flag.

```powershell
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-knowledge --input "How do I reset my password?"
```

Deployment returns agent/version records; invocation returns JSON including
answer text and successful grounding tool calls. A successful deployment alone
does not establish answer quality. To choose a hosted framework, follow its
linked README in [41-single-agent](41-single-agent/readme.md): deploy required
participants first, then replace the selected agent name. Do not run a hosted
`main.py` directly or use `--include-hosted` as a first-run shortcut.

### Returning to an existing deployment

Reopen PowerShell, select the same code directory, set `$Config` and `$Target`,
and run preflight and the relevant `invoke`/`ask` command. Keep the same config
and journals. Resume existing jobs with their poll commands instead of
re-ingesting or recreating infrastructure. Use [tests](tests/readme.md) for
offline development without cloud access.

Private endpoint DNS and TCP reachability are checked before data-plane work.
`repair-dns` produces a read-only plan; adding `--apply` adds missing Foundry
zones to the existing approved endpoint's DNS zone group while preserving its
name, other zone associations, and ETag concurrency protection. It never changes
`centralDnsZoneByPolicyInHub` or enables public access. In policy-owned mode the
hub policy owner must retain all three Foundry zones in future remediations.

## Data and Foundry IQ

The example configuration selects Data Factory ingestion. Enable Data Factory
through the existing project pipeline first; its project UAMI and managed-VNet
integration runtime must be present. Configure task-owned copy artifacts and
approve only their two Blob private links (ADF and Search) on the selected storage:

```powershell
.\.venv\Scripts\python.exe -m agent_factory configure-datafactory --config $Config --target $Target --apply
# Approve the specifically reported ADF and Search Blob connections on storage.
.\.venv\Scripts\python.exe -m agent_factory configure-datafactory --config $Config --target $Target --apply
.\.venv\Scripts\python.exe -m agent_factory start-datafactory --config $Config --target $Target --apply
.\.venv\Scripts\python.exe -m agent_factory poll-datafactory --config $Config --target $Target --apply --timeout-seconds 3600
```

Start once, then resume the saved run ID with `poll-datafactory`; do not create
another run while one is active. ADF verifies raw byte count/Content-MD5, projects
knowledge and evaluation columns into separate blobs, and validates row counts.
The private Search indexer reads only the published knowledge directory using
Search's managed identity. Verification compares all indexed knowledge against
the pinned corpus SHA-256 reference; Copy does not pretend to calculate SHA-256
or silently deduplicate. See `43-data/datafactory-guide.txt`.

Alternatively, run `43-data/worker.py` on already-approved Azure compute with the
selected project UAMI attached. Local operator OAuth cannot impersonate a managed
identity. This optional worker refuses unavailable UAMI authentication instead
of falling back to your user account. It uses a separate index and artifact
subfolders from ADF (also a separate container in legacy mode). Select a non-ADF
ingestion mode only when intentionally using that path.

The pinned, public MIT Kaggle dataset is downloaded directly on that Azure host.
It writes only to the selected data storage (legacy: project `2001`), never the
`1001` Foundry metadata account. It preserves attribution and hashes, parses multiline CSV,
deduplicates knowledge documents, and keeps evaluation questions/ground truth
separate from the searchable knowledge.

The initial Foundry IQ path uses a semantic text index and an existing-index
knowledge source. This works with an appropriately configured Basic Search
service without embeddings or an automatic paid SKU upgrade. Private
`azureBlob` knowledge-source ingestion is a different capability that currently
requires S2 or above; this starter does not silently select it.

After managed-identity ingestion completes:

```powershell
.\.venv\Scripts\python.exe -m agent_factory configure-knowledge --config $Config --target $Target --apply
```

This writes the knowledge configuration and verifies retrieval. Continue with
the selected folder's deployment instructions; the
[team](42-multi-agent/readme.md) needs its participants deployed first.
`deploy` without selectors creates the three prompt agents. Use `--agent` to
select a hosted runtime, or `--include-hosted` for all catalog entries after
checking their prerequisites. Anthropic requires a separately configured,
compatible Foundry-hosted Claude deployment; it never falls back to a public
Anthropic endpoint. Hosted source deployment requires the account's supported
private network injection, regional availability, model permissions and allowed
build egress. See the hosted-agent readme for runtime details.

Versions and endpoint routes remain in Foundry; the scripts never delete agents
as sample cleanup. Matching owned definitions are reused; collisions with
unowned agents fail. Generated packages and per-project deployment records live
beside configuration under `.agent-factory`, not inside the replaceable templates.
An error after a partial deployment leaves the completed records for diagnosis.

## Agent Map / Map Agents To Departments

### Offline Monitoring ML reports

`monitoring-export` projects **recorded** results into `aifactory.monitoring/v1`.
It makes no Azure calls, writes only the requested local report/tag files, and
never deploys agents, publishes artifacts, or updates Azure tags. The standalone
entry point `python -m agent_factory.monitoring` accepts the same flags.

```powershell
.\.venv\Scripts\python.exe -m agent_factory monitoring-export `
  --input .\knowledge-result.json --source-format knowledge `
  --output .\monitoring-agent.json --tags-output .\monitoring-agent-tags.json `
  --aifactory my-factory --project 001 --environment dev `
  --subject aif-knowledge --version 1 `
  --window-start 2026-09-11T10:00:00Z --window-end 2026-09-11T10:05:00Z
```

Supply the actual factory identifier, three-digit project, environment, agent
name/version and **observation** window from your explicitly selected target.
These are never inferred from endpoints, resource names, ambient Azure context,
or an arbitrary first configured target. Existing `FactoryConfig` exposes
`project_number` and `environment`, but no authoritative factory identifier;
provide that explicitly. `stage` normalizes to `test`; `stage_prod` is a variables
section, not a valid environment. All three environments are supported.
If the input includes `scope`/`subject`, they must match the explicit selection.
Shared-service observations are attributed by the operator, not automatically
represented as per-agent measurements.

Supported source formats select narrow allowlists from existing JSON outputs:

| `--source-format` | Exported observations |
| --- | --- |
| `preflight` | `agent_count_on_page`, observed endpoint check/private/reachable counts, `foundry_access` and private endpoint check result |
| `knowledge` | `document_count`, `reference_count`, `retrieval_verified` |
| `ingestion` | `row_count`, `document_count`, `evaluation_count`, `blob_integrity.{raw,knowledge,evaluation}.bytes`, `corpus_sha256_verified` |
| `invocation` | Count of recorded `tool_calls`; never answer text, response IDs, or tool arguments |
| `deployment` | No measured agent metrics: lifecycle states such as active/created are not health checks |
| `metrics-only` | Every numeric/null leaf in a deliberately curated aggregate `metrics` object, with stable dotted names |

Example `metrics-only` input shape (illustrative values, **not live telemetry**):

```json
{
  "metrics": {
    "sample_count": 12,
    "error_count": 1,
    "latency": {"p95_ms": 420},
    "usage": {"input_tokens": 1200, "output_tokens": 300}
  },
  "units": {
    "sample_count": "count",
    "error_count": "count",
    "latency.p95_ms": "ms",
    "usage.input_tokens": "tokens",
    "usage.output_tokens": "tokens"
  },
  "checks": {"invocation_completed": true}
}
```

Only supply measurements already produced by your evaluation/usage/performance
collector. Current invocation/hosted summaries do **not** persist token usage or
latency, and ingestion evaluation counts are corpus sizes, not quality scores.
No sample counts, errors, durations, costs or scores are invented. Infrastructure
MCP/deployment details and raw SDK/tracing/billing payloads are not automatically
flattened: first select aggregate numeric fields into `metrics-only`. This
explicit coverage boundary avoids exporting prompts, responses, credentials,
user data, identifiers and arbitrary dimensions. Its only allowed top-level
keys are `metrics`, `units`, `checks`, and optional matching `scope`/`subject`.
Use stable aggregate names without embedded identifiers; do not put sensitive
numeric data into the curated metrics object.

Checks must be recorded booleans named `invocation_completed`,
`grounding_verified`, `retrieval_verified`, `foundry_access`,
`private_endpoints`, or `corpus_sha256_verified`. No checks means health
`unknown`, including when error count is zero. Failed checks mean `warning`,
never concept drift. Data drift and concept drift are always `not_supported`.
Metric status is `unknown` without a metric-specific assessment; null means
`insufficient_data`. Missing units are `unknown`; accepted units are `count`,
`ms`, `s`, `tokens`, `bytes`, `percent`, `ratio`, `USD`, `unitless`, `unknown`.

Inputs are bounded to 1 MiB, 128 metrics, six nested levels, and numeric/null
leaves only. Invalid names, duplicate keys, non-finite values and unsafe integers
are rejected rather than silently dropped. `details` contains only the projected
numeric aggregates and allowlisted checks. The report never copies raw input.
Timestamps require timezones and serialize to UTC `Z`; future observations and
inverted windows are rejected. `--generated-at` is optional; expiration is based
on **window end**, using `--ttl-hours` (default 24, maximum 720), not regeneration
time. Old observations remain `stale`.

`--tags-output` creates compact `mon_*` tags plus explicit
`aifactory`/`project`/`environment` identity. Optionally add `--report-uri` for an
**already published** credential-free Azure Blob or
`azureml://jobs/<job>/outputs/<output>/paths/<report>` artifact URI. Signed links,
queries, fragments and userinfo are rejected; no upload/tag write is performed.
The local contract fixture `tests/fixtures/monitoring-agent-v1.json` is generated
from fixture data, not Azure measurements. Run offline tests with
`python -m unittest discover -s tests -p test_monitoring.py`.

Every independently mappable participant is a persisted Foundry agent with a
stable name. Register the factory scope in the Config Wizard and refresh live
inventory in "Map Agents To Departments"; these examples do not alter local
department assignments or force the map out of mock mode.

String metadata records framework, execution kind, solution, participant role,
and an IT department hint. The current Wizard discovers these agents but does
not consume custom framework/solution metadata or draw true inter-agent edges.
Hosted tool discovery can therefore remain incomplete. Runtime orchestration
does not fabricate connected-agent tools to make the map look connected.

## Scope and prerequisites

The optional `expanded-readonly` tool profile adds a private, project-scoped
Azure MCP inventory service and role-appropriate evidence tools. See
[the Agent Factory tool reference](../../documentation/v2/30-39/agent-factory.md#optional-expanded-read-only-profile)
for the identity boundary, pinned image, MCP-only pipeline and approval behavior.
Use `44-azure-mcp/deploy.py plan` before identity preparation or deployment;
`configure-azure-mcp` must verify live private infrastructure before agent rollout.

No infrastructure SKU, model deployment, service-enable flag, shared VM identity,
or role assignment is changed implicitly. If infrastructure is missing, update
the consumer's reviewed `enable...` values and use its
`ADO-update-aifactory-and-run-project.sh` project pipeline. Do not run its broad
commit/copy path over unrelated dirty files. Any reusable infrastructure fixes
belong in the central purple templates.

API baseline: `azure-ai-projects==2.6.0`, Foundry API `v1`; hosted protocol and
framework dependencies are isolated per runtime. Search knowledge operations use
`2026-08-01-preview`. Preview region, quota, policy, and capability-host failures
are surfaced rather than presented as successful agent creation.

## Original design brief

The material below is historical design context, **not additional implemented
features or first-run instructions**. Use the folder guides and workflows above
for supported entry points and prerequisites.

### Original agent authoring goals

- Single agents. And both prompt agents, and single agents
    - Foundry Agent Service will be used: https://learn.microsoft.com/en-us/azure/foundry/agents/overview
        -  Agent runtime: Hosts and scales prompt agents and Hosted agents. Manages conversations, tool calls, and agent lifecycle.
        -  Toolboxes: Curate a set of tools once, such as: web search, file search, code interpreter, MCP servers, and custom functions. Then share them across agents through a single managed MCP endpoint with centralized authentication, governance, and versioning.
        - Models: Works with many models from the Foundry model catalog, such as GPT-5.4, Llama, and DeepSeek. Swap models without changing your agent code.
        - Observability: End-to-end tracing, metrics, evaluations, and Application Insights integration. See every decision your agent makes and measure its quality.
        - Optimization:Agent optimizer (preview) evaluates agent behavior and automatically generates better instructions, skills, tool descriptions, and model selections for prompt agents and Hosted agents.
        - Identity and security: Microsoft Entra identity, RBAC, content filters, and virtual network isolation. Enterprise-grade trust built in.
        - Publishing: Version agents, create stable endpoints, and share through Microsoft Teams, Microsoft 365 Copilot, and the Entra Agent Registry.
        - Docs: https://learn.microsoft.com/en-us/azure/foundry/agents/overview
    - Types of agents: 
        - Prompt agents: You define prompt agents entirely through configuration, including instructions, model selection, and tools. Author them in the Foundry portal for a quick start, or define them programmatically with the SDKs or REST API to integrate with your CI/CD workflows. Either way, Foundry runs the agent for you. There's no application code to maintain, and no containers or packages to optimize, scale, or monitor for security.
            - Code first approach. using the SDK or REST API in your deployment pipeline, enabling version control, code review, and automated rollout.
        - Hosted agents: Hosted agents are code-based agents you build with Agent Framework, LangGraph, the OpenAI Agents SDK, the Anthropic Agent SDK, the GitHub Copilot SDK, or your own code. Ship your agent as either a container image or a .zip file of your source code (Foundry builds the image for you when you bring a .zip file), and Foundry runs it with a managed endpoint, automatic scaling, a dedicated Microsoft Entra identity, session-level state persistence, and end-to-end observability.
            - https://github.com/microsoft/agent-framework
            - https://github.com/openai/openai-agents-python
            - https://github.com/anthropics/anthropic-sdk-python
            - https://github.com/langchain-ai/langgraph
- Multi-agent scenarios, that uses the single agents created. 

### Original data defaults
- Kaggle data right as demo, copied to Azure projects storage account with "2001" in its name. Not "1001", since dedicated for Foundry and its meta data
    - https://www.kaggle.com/datasets/dkhundley/sample-rag-knowledge-item-dataset

### Original RAG tool defaults
- The AI Search resource in each project resource group, next to Foundry

### Original MCP tool defaults
- Foundry Agent service contains toolbox for: web search, file search, code interpreter, MCP servers, and custom functions
- 
