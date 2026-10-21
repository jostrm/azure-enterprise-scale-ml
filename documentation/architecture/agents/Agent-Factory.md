---
id: agent-factory
status: observed
sources:
  - usecase_code/40-agent-factory/readme.md
  - usecase_code/40-agent-factory/agent_factory/readme.md
  - usecase_code/40-agent-factory/agent_factory/cli.py
  - usecase_code/40-agent-factory/agent_factory/catalog.py
  - usecase_code/40-agent-factory/agent_factory/prompt.py
  - usecase_code/40-agent-factory/agent_factory/hosted.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py
  - usecase_code/40-agent-factory/agent_factory/factory_chat_agent.py
  - usecase_code/40-agent-factory/46-factory-chat-agent/deploy.py
  - usecase_code/40-agent-factory/agent_factory/agent_live_voice.py
  - usecase_code/40-agent-factory/47-aifactory-agent-live-voice/deploy.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/readme.md
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/main.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/runtime.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/search.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/chunks.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/arithmetic.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/dataset.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/agent.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/identity.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/images.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/deployment.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/preview.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/operator_preview.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sync.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/webhook.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/sync_state.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/sync_publication.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/graph_publication.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/graph_delta.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/graph_webhooks.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/retrieval_only.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/retrieval_experiment.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/check_sum.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/sum_evaluation.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/readme.md
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/main.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/hosted_main.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/runtime.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/plan.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/usecases.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/factory.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/esml.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/lake.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/agent.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/hosted.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/hosted_package.py
  - environment_setup/aifactory/bicep/README.md
tests:
  - usecase_code/40-agent-factory/tests/test_prompt.py
  - usecase_code/40-agent-factory/tests/test_hosted.py
  - usecase_code/40-agent-factory/tests/test_cli.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_services.py
  - usecase_code/40-agent-factory/tests/test_factory_chat_agent.py
  - usecase_code/40-agent-factory/tests/test_agent_live_voice.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_chat_agent_flag.py
  - environment_setup/unit-tests/test-bicep/unit/test_agent_live_voice_pipeline.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_search.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_runtime.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_deployment.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_images.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_operator_preview.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_graph_webhooks.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_sync_state.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_sync_cli.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_retrieval_experiment.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/tests/test_sum_evaluation.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_agent.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_plan.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_runtime.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_attempts.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_hosted.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_usecases.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_offline.py
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/tests/test_cli.py
graph_symbols:
  - usecase_code/40-agent-factory/agent_factory/cli.py::function:run
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py::class:AgentServiceFactory
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/runtime.py::class:SalesRuntime
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/runtime.py::class:MLRuntime
  - usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/ml_agent/hosted.py::class:HostedAgent
reviewed_source: 'af75afe9; observed 2026-10-21; no live deployment asserted'
---
# Agent Factory

## Observed responsibilities

| Component | Responsibility |
|---|---|
| Shared `agent_factory` operator | Explicit target/storage discovery, private-network checks, ingestion/Foundry IQ, prompt and hosted deployment/invocation. |
| Prompt agents | Persistent versioned Foundry definitions with catalogued roles and allowed tools. |
| Hosted examples | Framework-specific runtime and package construction; they are not independent factory provisioning engines. |
| Multi-agent examples | Knowledge/reviewer collaboration pattern; role names alone do not grant additional tools or permissions. |
| `40-aifactory-agent` application | Grounded Factory Chat, exact-scope authorization, existing API adapters and durable human-approved operations. |
| Backend functions | Execute client-side tool implementations. Creating a Foundry definition alone does not host those functions. |
| Factory Chat Agent step (`46-factory-chat-agent`, task `70-factory-chat-agent`, `enableFactoryChatAgent`) | Opt-in late project-pipeline step that creates or versions the owned Foundry prompt agent from the canonical definition; idempotent by definition hash, never deletes, refuses a foreign owner. A delete-all flag conflicts with it and fails validation. |
| AI Factory MCP step (`45-aifactory-mcp-gateway`, task `71-aifactory-mcp-ai-gateway`) | Opt-in late step between the chat and live voice steps; its boundary is described in [[MCP-Boundary]]. |
| Live voice step (`47-aifactory-agent-live-voice`, task `72-aifactory-agent-live-voice`, `enableAIFactoryAgentLiveVoice`) | Opt-in late project-pipeline step for project001 Dev: verifies that owned agent (never creates it), builds the knowledge index and deploys the private chat application with Azure Voice Live using the application's own ownership-checked commands. Voice without the chat flag fails, as does a delete-all flag; other environments are skipped; an app deployed by hand is never replaced; false never deletes. |

The shared operator and Factory Chat application have separate Python/dependency/configuration boundaries. Parent operator `--apply` conventions are not portable to Chat's immediate `ingest`/`deploy-agent` commands. Offline plans/help do not imply live connectivity; invocation and ingestion can incur model/service charges.

Storage selection is explicit common/project data storage. Changing it does not move the Foundry target, create permission, infer an account by first-match discovery or rewrite historical lake paths.

## Authority boundary

The model can propose or explain; backend authorization determines scope. Platform/Project audience changes explanation, not permissions. A source/knowledge agent and a reviewer cannot approve an infrastructure change merely by agreeing with each other.

The application has a compatibility speech shell and an opt-in native Voice Live realtime engine. Both reuse the common prepared-turn grounding/read-tool policy; native streaming is not another privileged agent or an external full-text answer chain. Language profiles and voice mode are operator-owned configuration, not deployment intent from a spoken request. Voice-only failure must not invalidate authenticated text chat. Native streamed speech is provisional until final citation checks (see [[Chat-and-Grounding]]); local tests do not establish the installed live revision.

Private Azure MCP in `44-azure-mcp` is a separate narrow Azure resource-read integration from this repository's `mcp` Factory API adapter. Neither name implies arbitrary shell access or unrestricted Azure writes.

## Split-table sales example

`48-rag-with-splitted-tables-acl-adlsgen2` is a separately configured demonstration,
not a change to the project-wide permissions of example `45-rag-agent`. Whole JSON
and normalized workbook text enter Search Text Split before embedding; the workbook
file itself is not indexed. Native ADLS permission metadata is projected onto every
derived chunk. End-user Search authorization and delegated structured-source reads
remain separate from the Search/backend service identities.

Exact totals come from complete hash-pinned structured rows, not semantic top-k
results or model arithmetic. Consumer-owned policy selects authorized partitions;
native Search authorization and source access still have to succeed. A total is
produced only after verification of each partition reports successful ingestion,
the expected chunk count and the pinned input hash; otherwise the sales tool is
unavailable. Independent evaluation answers are excluded from ingestion and agent
tools. A separate synthetic image-serving branch is necessary because asset stores
cannot be combined with native permission ingestion; it never reuses the sales
storage or its permissions.

The publisher plans missing parents only inside its two owned `car-sales` roots.
Shared `datasets`/`usecases` parents are never modified. Existing task ancestors
retain their ACLs and require sufficient traversal; an ownership or access
mismatch blocks rather than rewriting permissions for earlier publications.

The separate `preview.py` entry point binds one existing operator to both
partitions for authorized-access demonstrations. It retains native Search
authorization and delegated source reads, but identifies its CLI backend as
operator-authenticated rather than managed identity. Strict `main.py` behavior
is unchanged; preview results cannot count as denied-user or revocation proof.
Foundry Playground does not execute the example's local function implementations.
Native permission ingestion retains `metadata_storage_path` on parent and chunk
indexes. The README documents that ingestion also reads root/ancestor permission
metadata, not only file bytes, so exact-file grants do not establish ancestor
access. The code never broadens shared ancestors or common-lake permissions to
close that gap; it surfaces as an indexer failure.
The parent audit index also retains the actual pre-split input; verification
compares that pinned source with all returned chunks and never repairs missing
text or accepts inconsistent offsets merely because three chunks were returned.
Deferred primary/regional/additional-service RBAC and network parity work is
tracked in the [Bicep README](../../../environment_setup/aifactory/bicep/README.md)'s
project-creation TODO list, not silently implemented through use-case deployment scripts.

The optional Graph extension uses stable tenant/drive/item IDs and permission-aware
root delta, with `Prefer: includesecuritywebhooks` on business security-subscription
creation. Notifications durably invalidate a scope before acknowledgement; they
are triggers, not permissions or complete change records. Explicit source reads
stage immutable content or reviewed named-principal ACL changes, with native
Search resync and complete verification before committing the delta checkpoint.
Process-level publication serialization and generation checks prevent stale
workers/results from reopening revoked access. This local SQLite reference is
single-host, not a distributed coordinator or an instantaneous-revocation SLA.
Graph-bound publications change only through `sync.py`'s serialized
reconciliation: `main.py` refuses `publish`, `configure`, `ingest` and `resync` for
them. A source deletion or a permission the index cannot represent quarantines the
publication, and a binding change requires redeploying the agent. `webhook.py` is
an ASGI application factory configured through `AIF48_GRAPH_SYNC_CONFIG`; it starts
no server. Real source consent (the example configuration names
`Sites.FullControl.All` for permission reads), callback hosting and notification
delivery are separate deployment evidence; synthetic library folders do not
establish SharePoint setup.

Local fixtures or passing unit tests do not establish three real service chunks,
successful revocation, image use, or a deployed Foundry agent. The example's
README distinguishes measured local results from approval-gated cloud evidence;
it records that the protected publication failed its chunk completeness and offset
checks, remains blocked, and that no protected-pipeline agent was deployed.

The optional `retrieval_only.py` path tests the model without a calculator or
client-side function executor; its only tool is the native Foundry IQ MCP
`knowledge_base_retrieve`. One knowledge base is configured over two separately
named synthetic indexes, and the probe accepts an answer only when it cites
references from both. This path requires explicit project-corpus approval, refuses
Graph-bound configurations and does not claim per-user native file-ACL enforcement
in Playground: its indexes do not use permission filtering. Its `deploy` step
grants the Foundry project's managed identity Search Index Data Reader on the
Search service and creates a secretless MCP project connection; retrieval is
bounded to 40,000 output tokens and six documents. Whole-table native ingestion,
or the default row-aware push variant (which needs Search write access), replaces
Text Split only for this isolated experiment; protected indexes and their
integrity gates remain unchanged. Model arithmetic and retrieval exhaustiveness
remain unverified until evaluated, and no oracle is supplied as a tool or prompt.

The separate `retrieval_only.py full-text-sum` control reads and hash-verifies both
complete live whole-table index documents, then submits their original text to
the experiment's existing model with no tools, no agent reference and high
reasoning. It retains exact requests/raw responses for independent evaluation;
it never reads the oracle or computes row amounts before inference. The README
records (16 October 2026) that two synthetic-fixture controls produced the exact
full total, while two persisted MCP-agent trials did not. This is not a
Playground-path fix, Text Split acceptance, per-user authorization proof or
general guarantee of LLM arithmetic. The README keeps the dated results and
reproducible commands without tenant bindings.

`check_sum.py` and `sales_demo.sum_evaluation` provide a separate offline,
post-inference check of saved answers. They validate fixture integrity and
independent Decimal expectations, then score reported audit ranges, exact source
and combined totals, coverage, currency conversion and available response/tool
metadata. Missing or ambiguous evidence fails rather than accepting a matching
number in prose. This checker is not imported by inference or exposed as a tool,
refuses to overwrite its inputs, and marks every report `live_execution_verified:
false`; a passing local report is not proof of authenticated live execution.

The README records 17 October copying diagnostics that locate the reported cutoffs
near 16,384 `cl100k_base` tokens in the wrapped document representation. In one
recorded control, the same model with medium reasoning copied all eight selected
records from that exact payload when given it directly. This supports a hosted MCP
delivery-path cutoff hypothesis, not a proven public token-limit contract; the
diagnostic scripts are not kept in the repository. SourceDataFields adds metadata
rather than excluding semantic content. Smaller indexed documents or an explicitly
paged read-only tool remain remediation candidates; the README records that
neither was deployed and that no cloud resource or permission was changed.

## Agent-driven ML training example

`49-agent-training-ml-churn-prediction` has two entry points. `main.py` deploys a
prompt agent whose client-side tools run in the operator's CLI process.
`hosted_main.py` serves a code-based hosted agent whose tools run inside the Foundry
sandbox with the hosted agent's own Entra identity (CLI and developer credentials
are excluded), so the Foundry Playground can execute them. Both expose the same
plan-bound `MLRuntime` tools; the hosted agent adds `plan_run` and
`get_approval_status`. Both call the ESML v2 SDK (`azure_esml`) and the
`ml_model_factory` engines, which the hosted package vendors. The agent can create
the M49 churn use case from the model-factory churn template, using only
deterministic synthetic data from `ml_model_factory.synthetic`; the template's
dataset reference is not copied. It can also train M49, retrain the existing M05
air-passengers model and run `GOLD_INFERENCE` batch scoring through
`AzureMLRollout` receipts. M49 is never trained before its data version is
recorded as published.

Every create, train, retrain or inference tool call is checked against an offline
plan bound by SHA-256 to its bytes, schema and configuration fingerprint. A plan
covers only the use cases requested; an unselected use case has no operations. In
the CLI the operator approves that plan and passes `--apply`; training, retraining,
scoring, deployment and `ask` also need `--allow-paid`. In the hosted agent the
model can only propose a plan through `plan_run`. Only the same platform user's own
`approve <code>` message approves it; the code is a 12-character prefix of the hash
and the host re-checks the full hash, never model output. A pending plan expires
after 30 minutes and the approver's write permission after 12 hours; the plan stays
readable for status. A host note states the active plan, its expiry and the runs it
covers on every turn. New work can be planned while a plan is active: the active
plan stays in effect until the new one is approved, and because there is one shared
approval record, a newer approval (by any user) replaces it. Tools for use cases
outside the active plan are refused, so the model cannot widen the write scope.

Hosted state (plans, approvals, publications and both M49 and M05 receipts) is
mirrored below `<M49 use-case root>/agent-state/<owner>/<version>` in the shared
lake, the only lake area the hosted agent rewrites. A renewed blob lease serializes
turns and uploads are ETag-conditional, so a later Playground session resumes a
recorded job instead of resubmitting it. CLI status reads receipts only; hosted
status also reads the Azure ML status of a recorded, unfinished job and returns the
next action, and falls back to receipts when Azure ML cannot be read. A failed
scoring job starts a new bounded attempt (at most five, each with its own
create-only lake paths); a failed training job needs a new plan. Hosted tool waits
are bounded and return `running` instead of holding a turn. GUIDs and ARM IDs are
redacted from tool results before they reach the model. Tools accept only the two enumerated use cases (create and train
M49, retrain M05), never take paths or identifiers from the model, and expose no
delete operation. `hosted-deploy` refuses an agent it does not own; the example
assigns no roles.

Retraining runs only when the operator, or in the hosted agent the approving
Playground user, requests it. It is not an autonomous drift-to-retraining loop.
For M05 the selection policy may keep the champion, and scoring then uses the
retained champion (see [[Monitoring-and-Retraining]]); an M49 candidate that was not
promoted cannot be scored. Local tests and the offline reproduction do not establish
a live lake publication, an Azure ML job, a registered model or a deployed agent;
the README's "What to expect" section describes intended outcomes, not observations.

See [[Chat-and-Grounding]], [[MCP-Boundary]], [[Retrieval-Provenance]], [[Dependency-Injection]], [[System-Context]] and [[Index]].

Authority: [Agent Factory quickstart](../../../usecase_code/40-agent-factory/readme.md), [operator responsibilities](../../../usecase_code/40-agent-factory/agent_factory/readme.md), [agent catalog guide](../../v2/30-39/agent-factory.md).
