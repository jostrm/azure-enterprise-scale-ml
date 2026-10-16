# Split tables: native ADLS permissions, multi-index RAG and exact sales

This example combines a Microsoft Foundry prompt agent with two **different,
nonempty partitions** of one synthetic car-sales dataset. It is not an example of
an LLM adding a handful of search snippets. Search supplies cited evidence;
a deterministic tool reads the complete authorized structured sources and
calculates the answer in integer USD cents.

**Execution status:** local implementation and approval-gated cloud runner.
No deployment, real Text Split results, live ACL/revocation result, paid agent
evaluation or image-serving success is implied by the source code or unit tests.
The cloud acceptance criteria below must pass before claiming the complete demo.

## Architecture and boundaries

```text
Fixed-seed generator --> master publication --> hash-verified project copy
                          |                         |
                          |        +----------------+----------------+
                          |        |                                 |
                          |   whole JSON                    whole Excel-derived text
                          |        |                                 |
                          |   ADLS native permission indexers (no custom skills)
                          |        |                                 |
                          |   Text Split --> embedding          Text Split --> embedding
                          |        |                                 |
                          |   JSON chunk index                  Excel chunk index
                          |        +-------------+-------------------+
                          |                      |
                          |          end-user native authorization
                          |                      |
                          |          hybrid + semantic evidence
                          |
                          +--> structured row files, pinned per partition
                                    |
                             delegated user Storage reads
                                    |
                        exhaustive authorized calculator --> exact cents

Independent evaluator/oracle (not indexed; not an agent tool)

Separate synthetic-only image source --> agentic knowledge source + asset store
                                     --> answer synthesis + image-use activity
```

`Text Split` is **not row-aware**. It controls model-input size, not spreadsheet
semantics. A JSON fragment cut through an object is not a valid standalone table.
Exported parts are valid JSON **envelopes** with `chunk_text` and measured
metadata, not falsely repaired source records.

The calculator uses the **authoritative structured-row method**. It does not
reconstruct arithmetic from top-k search hits. Full chunk reconstruction is
checked as an ingestion acceptance test, independently of arithmetic. This
demonstrates RAG plus a calculator, not exhaustive vector aggregation.

## Prerequisites and pins

- Python 3.13, PowerShell, Azure CLI OAuth and the existing factory consumer
  configuration. Root operator pins are retained: `azure-ai-projects==2.6.0`,
  `azure-identity==1.25.3`, `openai==3.0.0`.
- Example-only pins: `tiktoken==0.11.0`, `openpyxl==3.1.5`, `Pillow==11.3.0`.
  The minimal DOCX is deterministic standard-library OOXML, validated as an
  actual document rather than relying on a platform-specific Office generator.
- Search REST **`2026-08-01-preview`** for native permission ingestion/querying,
  index projections and the separate agentic image branch. This is a preview
  demonstration, not a GA compatibility promise.
- `text-embedding-3-large`, 3,072 dimensions, `cl100k_base` tokenizer. The actual
  selected model deployment is checked, not inferred from a friendly name.
- Existing private ADLS Gen2 account and explicitly configured filesystem.
  Public access and account keys are not enabled by this example.
- Private network connectivity to Storage **blob and DFS**, Search and Foundry.
  Private DNS alone does not establish that traffic can reach those addresses.
- Search outbound shared private links must separately be approved for the
  source account's `blob` and `dfs` subresources and Foundry's `openai_account`.
  Indexers explicitly select `executionEnvironment: private`; the runner's VPN
  cannot supply connectivity to Search's managed execution environment.
- A read-only retrieval backend managed identity on an Azure host reachable over
  that private network; separately authenticated delegated end users. Do not run
  a managed-identity backend on a laptop and expect implicit operator fallback.

| Identity | Required purpose |
| --- | --- |
| Publication operator | Task-path creation, immutable file copy and explicit task-path ACL setup |
| Search ingestion identity | Read approved source files; call the embedding deployment |
| Retrieval backend identity | Search Index Data Reader plus a service-scoped custom role granting `Microsoft.Search/searchServices/indexers/read` in **Actions** (or built-in Reader); never a substitute for user source authorization |
| End user | Delegated Search and Storage tokens, group-derived partition policy and native source access |
| Evaluator | Separate access to the oracle; never expose that access as an agent tool |
| Image pipeline identity | Approved isolated synthetic source/asset boundary and relevant model permissions |

No role assignment, group creation, SharePoint provisioning, public networking
change or shared-resource deletion is automatic. Selecting identities does not
grant them permissions. Existing broad Storage data roles for test users/groups
can bypass ACL restrictions; preflight reports them, including custom wildcard
roles and conditional assignments requiring review. Include all transitive group
principals of test users in that review.
Live evaluation additionally resolves both real test users' transitive groups
and checks their effective direct/group assignments before making paid calls.
Conditional data grants are flagged for review, not assumed harmless.

## Local setup and deterministic generation

Use a component-specific environment; do not change the shared operator's pins.
For a consumer copy, replace `$Demo` with its `aifactory-usecase-code` location.
All generated files and consumer settings live **outside** the replaceable code.

```powershell
$Demo = "C:\path\to\azure-enterprise-scale-ml\usecase_code\40-agent-factory\48-rag-with-splitted-tables-acl-adlsgen2"
$Consumer = "C:\path\to\orange-repo"
$State = Join-Path $Consumer "aifactory\agent-factory\sales-demo"
$Data = Join-Path $State "data\v1"
$Config = Join-Path $State "config.json"
Set-Location $Demo
py -3.13 -m venv .venv
$Python = Join-Path $Demo ".venv\Scripts\python.exe"
& $Python -m pip install -r requirements.txt
$env:TIKTOKEN_CACHE_DIR = Join-Path $Demo ".venv\tiktoken-cache"
& $Python main.py generate --output $Data --version v1 --seed 48
& $Python -m unittest discover -s tests
```

Generation creates the required `car-sales-xyz.json`,
`car-calculator-tool.xlsx` and `car-random-image.docx`, plus the normalized
whole-workbook text, structured rows and original PNG derivative. JSON and Excel
contribute disjoint business IDs. A **separate, nonindexed** overlapping fixture
exercises mirrored-record deduplication. Additional simulated libraries do not
duplicate sales merely to make the layout look populated.

`publication.json` contains integrity metadata, not totals. The independent
`evaluation\expected.json` contains the oracle, IDs, row counts, hashes and
expected exact amounts. It is outside `master` and `project` ingestion and is
only opened by the evaluator. The generator copies master files to the local
project tree and checks byte hashes; the publisher independently copies pinned
master bytes to the Azure project publication.

The **actual whole input strings** are tokenized: the serialized JSON and text
extracted back from the workbook. Workbook XML and file size are not token
measurements. Generation targets approximately 13,500-14,500 tokens per input;
both must exceed 9,000. These counts do not prove three Azure chunks.
The first tokenizer use downloads its public vocabulary if not already cached;
an offline machine needs an already populated, verified tokenizer cache.

Measured locally for seed **48**, version **v1**:

| Partition | Rows | Actual input tokens | Independent expected net sales |
| --- | ---: | ---: | ---: |
| JSON | 109 | 13,618 | USD 16,768,818.26 |
| Excel | 153 | 13,572 | USD 22,767,114.36 |
| Combined, disjoint IDs | 262 | Not a shared embedding input | USD 39,535,932.62 |

These are evaluator expectations, not values supplied to the agent. The local
DOCX passed OOXML schema validation and was rendered with installed Microsoft
Word for visual inspection. That establishes the local embedded image, **not**
Azure's DOCX image extraction or image-serving compatibility.

## Arithmetic and coverage contract

Sales means **net merchandise revenue excluding tax**, in USD cents:

```text
completed/refunded row = quantity * unit_price_minor - discount_minor - refund_minor
cancelled row          = 0
tax_minor              = recorded but excluded from sales
```

Discounts and refunds apply to the entire row, not each unit. Values and
quantities are validated integers, never binary floats or booleans. Refunds
cannot exceed the discounted merchandise amount. Cancelled records remain
auditable but contribute zero.

The stable identity is `(dataset, version, sale_id)`. Identical mirrored rows
contribute once; conflicting payloads for the same identity fail. Source
breakdowns use deterministic first-source attribution so they reconcile to the
deduplicated grand total; they are not independent double-counted source sums.
This rule is immaterial to the primary disjoint-partition scenario but essential
to the overlap fixture.

The backend selects partitions from trusted configuration and current validated
identity, not model-supplied index names, paths, groups or arbitrary scope. It
must check the publication version, source hashes, complete row pages and
complete ingested chunk coverage. Missing partitions/chunks, inconsistent
duplicates, unfinished publication, wrong version, unreadable authorized
sources or incomplete pagination are errors, not a smaller plausible total.

## Resolve the actual lake and plan

Do not derive a container from a portal account URL. Select an existing
consumer-owned common-lake binding and resolve its explicit account/container.
The following command does not provision anything:

```powershell
& $Python main.py init-config `
  --factory-config "$Consumer\aifactory\agent-factory\config.json" `
  --target "<existing target key>" `
  --source-bindings "$Consumer\aifactory\agent-factory\rag-sources.json" `
  --source-key "<existing common-lake binding key>" `
  --artifacts-root $Data --output $Config
& $Python main.py plan --config $Config --output "$State\deployment-plan.json"
& $Python main.py discover --config $Config --update-config `
  --output "$State\preflight.json"
```

`discover` is read-only in Azure; `--update-config` only records discovered
endpoints/identity in the local consumer configuration. It never approves paths
or selects reader identities on your behalf. Fill the explicit group policies,
allowed/denied test principals and backend identity, then review the plan.

The generated candidate preserves repository lineage:

```text
mlops/v1/master/environments/<env>/datasets/car-sales/versions/<version>/
mlops/v1/projects/projectNNN/environments/<env>/usecases/car-sales/rag/corpora/car-sales/versions/<version>/
```

These paths are **candidates until approved**. The shared `datasets` and
project `usecases` parents must already exist and provide necessary traversal.
The plan lists every directory to create, starting at the two task-owned
`car-sales` roots and ending at this version's source directories. After
approval the publisher can create missing task-owned parents; it never changes
the shared parents. Existing task ancestors retain their ACLs, and insufficient
traversal blocks the operation rather than silently broadening those ACLs.
Foreign-owned directories are never replaced. Oracle data,
debug chunks and images are excluded from protected sales ingestion.

## Approved cloud execution

The following commands are instructions, **not a record of executed approval**.
Review the exact resource names, paths, identities and cost-bearing operations
first. Set `paths_approved` only after that review. `--apply` gates mutations;
`--allow-paid` separately gates indexing/inference where model calls may occur.

```powershell
& $Python main.py plan --config $Config
& $Python main.py discover --config $Config --output "$State\preflight.json"
& $Python main.py publish --config $Config --apply
& $Python main.py configure --config $Config --apply --allow-paid
& $Python main.py ingest --config $Config --apply --allow-paid --timeout-seconds 1800
& $Python main.py verify --config $Config --output "$State\chunk-evidence"
& $Python main.py deploy --config $Config --apply --allow-paid
& $Python main.py ask --config $Config --allow-paid `
  --input "Give me the sum of all sales."
& $Python main.py evaluate --config $Config --allow-paid `
  --oracle "$Data\evaluation\expected.json" `
  --restricted-profile "$State\auth\restricted" --output "$State\live-evaluation.json"
```

Creating an indexer can start indexing automatically. Consequently `configure`
also requires paid-call approval and waits for completion; `ingest` explicitly
runs an already configured pipeline. No source changes are silently retried.

Authenticate the restricted user in a separate existing CLI profile first.
Use the same tenant, `az login --allow-no-subscriptions`, and a temporary
`AZURE_CONFIG_DIR` pointing to that profile; restore the previous environment
after sign-in. The delegated token provider deliberately does not require that
user to have an Azure subscription role. The current/default profile remains
the full reader/operator. `--user-profile` can explicitly select a separate full
reader as well. Never commit or share either profile's authentication cache.

The Foundry agent definition is persisted and version-pinned. Its functions
execute in the approved local/private runner; creating a prompt-agent definition
does **not** host those functions as a web service. Every invocation preserves
the exact user prompt and inspects actual function calls.

## Real Text Split acceptance evidence

Both native ADLS indexers read whole text with `parsingMode: text`. The split
skill precedes the embedding skill:

| Setting | Value |
| --- | --- |
| `textSplitMode` | `pages` |
| `unit` / tokenizer | `azureOpenAITokens` / `cl100k_base` |
| `maximumPageLength` | `6000` |
| `pageOverlapLength` | `0` |
| `maximumPagesToTake` | **`0`** (all pages, never truncate to three) |
| Embedding limit | Each final input must be **below 8,000 tokens** |

A separate native-authorized parent audit index retains the service's actual
page strings, ordinal positions, offsets and lengths. This avoids unsupported
custom skills, knowledge stores or debug sessions. Verification correlates audit
pages with the derived chunk index, validates complete source coverage and checks
that at least one boundary crosses a row/serialized record.

Exactly three chunks are an **assertion on actual service output**, not a
configuration guarantee. If the real service produces a different number,
adjust deterministic fixture generation, choose a new version and rerun. Never
truncate, pre-split the source or manufacture cloud evidence.

After a successful real run, the verifier exports:

```text
car-sales-xyz-part-1.json
car-sales-xyz-part-2.json
car-sales-xyz-part-3.json
```

Each envelope records source/parent identity, ordinal, exact chunk text, token
count, offsets, lengths and hashes. Exports must be outside ingestion prefixes.
No such files are generated by the offline generator.

## Native permissions and revocation

The ADLS data source uses `indexerPermissionOptions` for `userIds`, `groupIds`
and `rbacScope`; secured indexes enable `permissionFilterOption`. Every projected
chunk receives the indexer-emitted native permission metadata. Group permissions
are preferred; this is not a flattened document-level user-membership list.
Both indexes retain the native `metadata_storage_path` field as well as the
shared `source_uri` alias: the preview service requires the original field for
ADLS permission ingestion. Text Split language (`en`) and semantic ranking order
(`BoostedRerankerScore`) are explicit so service-default round trips do not look
like foreign definition changes.

Each secured query carries the end user's Search-scoped token in
`x-ms-query-source-authorization`, independently of backend Search RBAC
authentication. Missing user identity is rejected before querying. The
calculator's Storage token must represent the same validated delegated user;
there is no operator/account-key fallback.
This is a trusted local CLI boundary, not an HTTP token-validation service:
tokens originate in Azure CLI OAuth, authenticated Graph `/me` establishes the
user, and Search/Storage validate their own tokens. Local JWT decoding only
checks consistency. Do not expose these injectable adapters as a network API.
Graph transitive-group casts use `$count=true` and `ConsistencyLevel: eventual`;
their directory replication delay remains a revocation consideration.

The trusted partition policy is an additional scope/integrity control, **not a
replacement for native enforcement**. Source reads and citations are authorized
before returning data. No shared authorization/result cache is used. A user
with only one authorized partition sees only that partition's total and
provenance, not hidden totals, counts, IDs or a list of excluded sources.

Native authorization is file-level, not row-level within a workbook. Different
entitlements require different files. Copying a file does not transfer
SharePoint permissions, and POSIX ACLs are not a perfect SharePoint permission
model. This example simulates site/library lineage; real SharePoint provisioning
is optional and not performed.
Native ingestion also reads permission metadata on the filesystem root and
every ancestor directory. A reader role restricted to the two source files and
their list prefixes may therefore be insufficient even when content reads work.
Do not replace that condition with account-wide access. Inspect the failing
operations and separately review exact ancestor-object permissions; the source
selection is not itself a permission boundary.

ACL-only changes might not update blob last-modified timestamps. Refresh
permissions explicitly and rerun the native indexers:

```powershell
& $Python main.py resync --config $Config --apply
```

This queues `resync` with `options: ["permissions"]`, then runs the indexers.
Recheck allowed and revoked identities on every projected chunk and delegated
source read. Native Search permission refresh, Entra group/token changes and
client authentication have separate delays; no instantaneous-revocation SLA is
claimed. Disable access while a required resync is incomplete rather than
serving a cached answer.

## Separate image-serving branch

The DOCX contains an original car illustration with a distinctive visual fact
absent from surrounding document text. Only explicitly non-sensitive synthetic
content belongs in this branch.

**`assetStore` cannot be combined with `ingestionPermissionOptions`.** Never
upload protected sales data into the image branch to get around this limitation.
An approved isolated source/asset storage boundary is required; do not grant
account-wide image-pipeline write access on the shared master lake.

Use agentic retrieval's asset store, `enableImageServing: true` and
`outputMode: answerSynthesis`. Extractive mode is not the demonstration.
Success requires real retrieval activity with `imagesSentToModel > 0`; an answer
that merely guesses the image fact is not evidence of visual grounding.

Direct DOCX embedded-image extraction depends on the chosen extraction path and
is **not assumed supported**. Test DOCX separately. The original PNG derivative
can demonstrate image serving if clearly labelled as a derivative; it must not
be reported as direct DOCX success. Image assets remain private to the approved
branch even though their synthetic content is non-sensitive.

Copy `image.example.json` into consumer configuration's `image` object and
replace all placeholders. The protected account list must include the selected
sales lake. Use a separate prefix for each input format; never mix a DOCX and
its derivative in one direct-DOCX experiment. After separate approval of the
isolated account/containers, permissions and content upload:

```powershell
# This write is optional and requires approval. Use only the generated synthetic PNG.
az storage blob upload --auth-mode login --account-name "<isolated-source-account>" `
  --container-name synthetic-documents --name "synthetic/images/v1/png-derivative/car-random-image.png" `
  --file "$Data\master\images\car-random-image.png" --overwrite false
& $Python main.py images-plan --config $Config
& $Python main.py images-configure --config $Config --apply --allow-paid
& $Python main.py images-ask --config $Config --allow-paid `
  --input "What shape, color and number are on the car door?"
```

The result retains activity and `imagesSentToModel`; it does not turn a declared
`input_kind: docx` into proof of direct DOCX extraction. `docx_pass` remains false
without an independently established source-to-image extraction provenance.
Aggregate image counters alone cannot establish that provenance.

## Optional Graph delta and security-webhook extension

The synthetic `<site>/<library>` folder layout is not a SharePoint site.
`graph-sync.example.json` must be bound to an explicitly approved **real**
SharePoint document-library or OneDrive for Business drive and the stable IDs of
the two sales files. Consumer OneDrive is rejected. No source site, user,
Container App, subscription, public callback or Graph consent is created by
enabling the local code.

Use the full root delta enumeration for bootstrap, then preserve Graph's opaque
`@odata.deltaLink`. Every initial, continuation and incremental request sends:

```http
Prefer: hierarchicalsharing, deltashowremovedasdeleted, deltatraversepermissiongaps, deltashowsharingchanges
```

This includes the required companion preferences for
`@microsoft.graph.sharedChanged` (documented as the string `"True"`). The feed
represents latest state, not an event log: the last occurrence of a repeated
item wins; empty pages with `@odata.nextLink` are still followed. Items are
identified by tenant/drive/item ID, never just filename. Folder moves/renames
affect descendants even when those descendants are not repeated in delta.
Tombstones and `410 Gone` trigger reconciliation, not a partial-data total or an
upload back to Graph. `token=latest` is not used to skip the initial inventory.

Security subscription creation uses the exact business-drive contract:

```http
POST https://graph.microsoft.com/v1.0/subscriptions
Prefer: includesecuritywebhooks
Content-Type: application/json

{
  "changeType": "updated",
  "resource": "/drives/<drive-id>/root",
  "notificationUrl": "https://<approved-host>/notifications",
  "expirationDateTime": "<future-UTC-time>",
  "clientState": "<secret-from-approved-secret-store>"
}
```

`includesecuritywebhooks` is sent on creation/recreation, not claimed to upgrade
an old content-only subscription through renewal. The default lifetime is one
day; the currently documented driveItem maximum is **42,300 minutes**. Renew
before expiry. A 404 requires explicit recreation with a new secret; a lost
creation response is an uncertain operation, not permission to blindly POST
again.

### Permission changes and durable invalidation

The ASGI callback returns a decoded validation token as plain text within the
Graph handshake contract. Normal batches validate every subscription,
tenant/resource and `clientState` using constant-time hash comparison, then
atomically mark the bound drive dirty in SQLite **before** returning 202. The
receiver does no Graph, Storage, Search or model work before acknowledgement.
An unavailable durable store returns a retryable failure instead of losing the
event. Tokens and client-state secrets are not stored in reports; the database
stores only the secret hash.

A root notification does not reliably identify the changed file or distinguish
content from permissions. All configured source permissions are therefore
re-read during reconciliation. Unknown permissions, incomplete responses or
unresolved identities leave the drive unavailable. Absence of `sharedChanged`
does not mean permissions were unchanged.
Retired subscription notifications are authenticated but disregarded. Activity
is rechecked inside the durable signal transaction, so an event being validated
during subscription recreation cannot put the healthy replacement on hold.

With `graph_sync` enabled in the demo configuration, retrieval and aggregation
require a fresh, complete synchronized publication. The agent checks the same
generation before model calls and before returning an answer. A notification
arriving during calculation or generation discards that result. There is no
cross-user answer cache. Expired reconciliation evidence or subscriptions fail
closed; a successful delta fetch alone does not reopen the gate.

Content changes stage a new immutable publication, including the entire
normalized workbook text and structured rows. Real Text Split, embedding,
source hashes and complete calculator coverage must be verified again.
Permission-only changes update all owned mirrored file ACLs, then call native
Search `/resync` with `{"options":["permissions"]}`, run and await completion.
If content also needs processing on an existing pipeline, its normal indexer
run is separate and follows the completed permission run. The delta checkpoint
advances only when the corresponding publication is durable and verified.
An arriving notification invalidates the in-flight reconciliation epoch.
External publication/ACL writes are serialized with a separate per-scope
process lock; webhook invalidation never waits on a long-running indexing
transaction. Partial writes retain a repair marker, so restoring a quarantined
source forces ACL restoration/resync rather than incorrectly selecting a
read-only recheck.

Deleting either required sales source quarantines the publication. Named
readers are removed from its owned mirrored files and native permissions are
refreshed; the remaining partition is never described as a complete dataset.
Existing broad Storage RBAC still cannot be revoked by removing a named ACL.

### Graph permissions and deployment prerequisites

Microsoft's permission-scanning guidance requires **`Sites.FullControl.All`**;
ordinary `Files.Read`/`Files.Read.All` is not proof of a complete authorization
snapshot. Subscription creation and renewal have their own permission
requirements; current reference tables differ on the minimum renewal scope.
No broad permission is granted automatically. An administrator must review the
actual source scope, consent, reader projection and callback before live use.

Graph permission JSON is **not** a POSIX ACL export. Only explicitly approved
Entra user/group mappings are supported; sharing links, invitations,
SharePoint-local groups, unknown roles or incomplete permission snapshots must
be quarantined rather than interpreted as public access. Missing
`inheritedFrom` is not proof of an explicit grant: SharePoint/Business responses
do not reliably return that property.
The native Graph transport also checks the trusted OAuth token's tenant,
audience, expiry and permission-scanning grant before requesting source data.
This claim check is not an external bearer-token validator; Graph validates the
token itself. An opaque/unverifiable or insufficiently scoped token fails closed.

Webhooks require an externally reachable **HTTPS receiver**. Private ADLS,
Search and workers do not make a private-only callback reachable by Graph.
The handler is provided without deploying a host or changing public networking.
`reauthorizationRequired` is supported; driveItem is not documented to guarantee
the `missed` or `subscriptionRemoved` lifecycle events. Expiry monitoring and
periodic delta reconciliation are therefore required independently.

This is not instantaneous revocation: Graph notification/directory replication
latency exists (the documented driveItem maximum notification latency can reach
six hours). The gate closes when a change is known and when freshness expires;
it cannot react to an event not yet delivered. Delegated source reads and live
native authorization remain mandatory.

### Reproducible extension commands

Keep the source configuration, SQLite state and staged candidates outside the
template. Fill the real drive/item IDs, approved download host, permission-scan
authorization and explicit `principal_map` before any source request. For
example, `{"group:<Entra-group-id>": {"type":"group","id":"<same-id>"}}` preserves
the group rather than expanding its members into user lists.

```powershell
$SyncConfig = Join-Path $State "graph-sync.json"
# Copy graph-sync.example.json there and resolve/review its fields first.
& $Python sync.py plan --sync-config $SyncConfig --config $Config
# Local write: attach the initially closed serving gate to this demo.
& $Python sync.py init --sync-config $SyncConfig --config $Config --apply
# Approved source reads only; downloads the two bound files and stages local work.
& $Python sync.py poll --sync-config $SyncConfig --config $Config `
  --output "$State\candidate-review.json"

# Review the candidate's exact version paths and principal changes before applying.
# Its new version may need separately approved, equally narrow indexer read rights.
$Review = Get-Content "$State\candidate-review.json" -Raw | ConvertFrom-Json
& $Python sync.py reconcile --sync-config $SyncConfig --config $Config `
  --epoch $Review.epoch --approved-candidate $Review.candidate_sha256 `
  --apply --allow-paid
& $Python sync.py status --sync-config $SyncConfig --config $Config
```

`poll` always performs delta reconciliation and fresh selected-item permission
reads. Content changes produce a new local candidate and native pipeline;
permission-only changes retain the existing bytes and version. Unchanged
content/permissions use a verification-only recheck, without ACL writes or
re-embedding. Failed/deleted/unrepresentable sources keep serving blocked.
After a changed binding is activated, redeploy the pinned prompt-agent
definition explicitly; no model/agent deployment is hidden in reconciliation.
The full evaluator remains separate and an updated independent oracle is
required for changed source data.

The worker runs on approved managed-identity compute for native Search reads;
the source content is still read using the selected end user's delegated
Storage identity. No operator fallback is introduced by this extension.

For an approved externally reachable ASGI host, mount
`webhook:create_app` with factory mode and set `AIF48_GRAPH_SYNC_CONFIG` to the
consumer configuration. `webhook.py` does not start a server. This reference
implementation is **single-host**: callback and worker must share the same
durable local SQLite database and process-lock filesystem. Do not independently
scale instances with separate local databases. A distributed deployment needs
an equivalent durable queue, shared epoch store and write-serialization adapter.

Only after the callback, consent and source scope are approved:

```powershell
# Keep the generated secret in memory; do not print it or log notification bodies.
$env:AIF48_GRAPH_CLIENT_STATE = & $Python -c "from sales_demo.graph_webhooks import generate_client_state; print(generate_client_state())"
& $Python sync.py subscribe --sync-config $SyncConfig --config $Config
& $Python sync.py subscribe --sync-config $SyncConfig --config $Config --apply
Remove-Item Env:AIF48_GRAPH_CLIENT_STATE

# Use the actual returned subscription ID; renew before expiry.
& $Python sync.py renew --sync-config $SyncConfig --config $Config `
  --subscription-id "<registered-id>" --apply
# Repair reauthorizationRequired even outside the normal renewal window:
& $Python sync.py renew --sync-config $SyncConfig --config $Config `
  --subscription-id "<registered-id>" --force-renew --apply
```

For a confirmed missing subscription, `recreate --subscription-id <old-id>`
requires explicit `--apply` and a newly generated secret. It does not delete
other subscriptions. Ordinary delta reconciliation cannot clear a lifecycle
hold; subscription repair and a fresh reconciliation are both required.
Schedule renewal and polling outside the callback, more frequently than the
configured `max_age_seconds`; no scheduled job is created automatically.

## Evaluation and completion

Offline unit tests, service integration acceptance and live deployed-agent
prompt evaluations are different layers. Mocked service/model responses test
client logic; they never establish an actual successful deployment.

### Explicit single-user operator preview

If only one existing user is available, `preview.py` offers a **separate local
operator path**, not a relaxation of `main.py`'s full ACL acceptance gates.
In consumer configuration, set `evaluation_mode` to `operator-preview`,
`operator_preview_user_id` to the verified user's object ID, both partitions'
`allowed_user_ids` to exactly that one ID, and `allowed_group_ids` plus
`denied_test_user_ids` to empty lists. This creates no user or group.

Every online command confirms the configured user against authenticated Graph
`/me` in the selected tenant. The operator's cached subscription-bound OAuth is
also the CLI Search backend credential; this is **not** managed-identity backend
validation and is never an automatic fallback for the normal runtime. The
read-only transport guard, native `x-ms-query-source-authorization`, delegated
Storage reads, complete chunk/row coverage and exact arithmetic remain intact.
No elevated-read header is used.

An operator with broad Storage RBAC can demonstrate authorized retrieval and
calculation, but cannot demonstrate restrictive ACLs or revocation. The
evaluation reports `authorized_cases_passed` separately and always leaves
`passed` and `complete_acl_acceptance` false. It never reuses the same user as a
pretend denied identity. The independent oracle stays evaluator-only.

```powershell
# Offline plan; reviewed paths must still be approved before publication.
& $Python preview.py plan --config $Config --output "$State\single-user-plan.json"
# Only after explicit publication and paid-call approval:
& $Python preview.py publish --config $Config --apply
& $Python preview.py configure --config $Config --apply --allow-paid
& $Python preview.py verify --config $Config --output "$State\chunk-evidence"
& $Python preview.py deploy --config $Config --apply --allow-paid
& $Python preview.py ask --config $Config --allow-paid `
  --input "Give me the sum of all sales."
& $Python preview.py evaluate --config $Config --allow-paid `
  --oracle "$Data\evaluation\expected.json" --output "$State\single-user-evaluation.json"
```

The persisted prompt agent can be inspected in Foundry Playground, but its
custom functions still execute in this CLI. Playground does **not** automatically
host `aggregate_sales`. A fully interactive Playground calculator requires a
separately approved remote tool host and supported per-user delegation; copying
protected tables into Code Interpreter is not an equivalent permission model.
No Container App, external tool host, or new user is created by `preview.py`.

The service/live unittest entry points are skipped unless explicitly enabled:

```powershell
$env:AIF48_CONFIG = $Config
$env:AIF48_SERVICE_TESTS = "1"
& $Python -m unittest discover -s tests\service
Remove-Item Env:AIF48_SERVICE_TESTS
# Only after explicit approval of paid live evaluations:
$env:AIF48_ORACLE = "$Data\evaluation\expected.json"
$env:AIF48_RESTRICTED_PROFILE = "$State\auth\restricted"
$env:AIF48_LIVE_EVALUATIONS = "1"
$env:AIF48_ALLOW_PAID = "1"
& $Python -m unittest discover -s tests\live
Remove-Item Env:AIF48_LIVE_EVALUATIONS,Env:AIF48_ALLOW_PAID
```

| Prompt/scenario | Required result |
| --- | --- |
| `Give me the sum of all sales.` | Exact authorized grand total; both primary indexes/sources for a fully authorized user |
| `Give me the sum of sales in the JSON dataset.` | Exact JSON partition subtotal; complete three-chunk coverage |
| `Give me the sum of sales in the Excel workbook.` | Exact Excel partition subtotal; complete three-chunk coverage |
| `Give me the total and break it down by source.` | Exact reconciled source breakdown |
| Cross-index fact question | One agent invocation uses evidence from both authorized indexes |
| Split-row and overlapping-record fixtures | No lost amount; identical business identity counted once |
| Restricted/denied identity | Only authorized data; no hidden-source disclosure |
| Missing chunk/partition or unfinished publication | Explicit incomplete-data error, never partial success |
| Image-dependent question | Supported extraction path plus actual positive image-use statistics |

Only the evaluator opens the independent oracle. It compares exact numeric
answers and tool traces from the deployed agent. Do not put expected totals in
instructions, search content, calculator code, or model mocks presented as live
results.

Locally exercised: the offline suite covers the original pipeline plus delta,
webhook validation/lifecycle, concurrent invalidation, immutable content staging,
permission-only refresh and deletion quarantine. Three service/live entry
points are skipped without explicit opt-in. The original local coverage includes
a generated/read-back workbook, exact independent oracle, both >9,000-token
inputs, master/project hashes, original embedded image and rendered DOCX.
Live Search chunk output, group-based allow/deny and revocation, deployed agent
responses, destructive missing-chunk fault injection, and image serving remain
unverified. The live evaluator's pass flag covers the protected sales agent, not
the separate image branch or cloud fault injection.

A subsequent authorized live attempt exercised immutable synthetic publication
and native index/data-source/skillset/indexer creation. It exposed the required
native path field and explicit defaults above. Ingestion then failed before
processing documents: existing Storage metrics showed denied
`GetPathAccessControl` operations alongside successful content/list operations.
After separately approved exact ancestor-object reads, both indexers reported
success with one source processed each. The documented path-key rename advisory
is retained for these immutable publications; unknown warnings remain failures.
Query verification then returned 403: the current operator lacks Search Index
Data Reader on the new service. No real three-chunk or live-agent success is
claimed from that attempt. Its
identity-specific deployment evidence remains in consumer-owned state, not in
the indexed corpus or source template.
The Graph extension has not been registered against a real drive or public
webhook. Its simulated callback tests are not proof of Microsoft delivering a
real permission-change notification. Real Graph reads additionally require
`AIF48_GRAPH_SERVICE_TESTS=1`, `AIF48_GRAPH_SOURCE_READ_APPROVED=1`,
`AIF48_GRAPH_SYNC_CONFIG`, and `AIF48_CONFIG` for the opt-in source test.

## Costs, troubleshooting and cleanup

- Indexing invokes embeddings for all produced chunks. Semantic ranking,
  vectorization, agent inference, image extraction/synthesis and storage consume
  service capacity or incur charges. No unverified price estimate is supplied.
- A missing managed-identity endpoint means the backend is running in the wrong
  host context. Do not replace it with a broadly privileged user token.
- `403`, unknown membership, hash mismatch or failed indexer status are blockers,
  not a reason to enable public access or omit a partition.
- Missing task-owned source parents are included in the publication plan.
  Missing shared parents or traversal require a separately reviewed change,
  never recursive ACL broadening of the shared lake.
- A collision with a foreign-owned Search object or directory is an error. Use a
  new task/version prefix rather than overwriting it.
- No destructive cleanup command is implemented. Retire only resources listed
  in the reviewed task plan and owned by this exact example/version. Never delete
  the Search service, Foundry project, shared account/container, master lake,
  unrelated indexes or another publication. Keep independent evaluation
  artifacts private and outside any future ingestion scope.

## Authoritative compatibility references

- [Text Split skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-textsplit)
- [Embedding skill and 8,000-token limit](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-azure-openai-embedding)
- [Document-level access overview](https://learn.microsoft.com/en-us/azure/search/search-document-level-access-overview)
- [Native ADLS permissions and limitations](https://learn.microsoft.com/en-us/azure/search/search-indexer-access-control-lists-and-role-based-access)
- [Query-time native authorization](https://learn.microsoft.com/en-us/azure/search/search-query-access-control-rbac-enforcement)
- [Index projections](https://learn.microsoft.com/en-us/azure/search/search-how-to-define-index-projections)
- [Agentic retrieval](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Image serving and asset-store incompatibility](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-image-serving)
- [Permission resync](https://learn.microsoft.com/en-us/azure/search/search-howto-run-reset-indexers)
- [Private indexer execution and shared private links](https://learn.microsoft.com/en-us/azure/search/search-indexer-howto-access-private)
- [Graph transitive membership query requirements](https://learn.microsoft.com/en-us/graph/api/user-list-transitivememberof?view=graph-rest-1.0)
- [Pinned Foundry agent-reference contract](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.6.0/sdk/ai/azure-ai-projects/tests/agents/test_agent_responses_crud.py)
- [Graph driveItem delta and sharing-change preferences](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)
- [Graph security-webhook subscription header](https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0)
- [Webhook validation, delivery and retries](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks)
- [Subscription lifetime limits](https://learn.microsoft.com/en-us/graph/change-notifications-overview#subscription-lifetime)
- [Resource-specific lifecycle notifications](https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events)
- [Permission scanning guidance](https://learn.microsoft.com/en-us/onedrive/developer/rest-api/concepts/scan-guidance?view=odsp-graph-online)

The repository's dual graph supplies structural/architecture context, not live
deployment evidence. Source, tests and the actual approved service responses are
the authority for this example's exercised behavior.
