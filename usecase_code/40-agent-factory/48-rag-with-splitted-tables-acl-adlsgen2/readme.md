# Split tables: native ADLS permissions, multi-index RAG and exact sales

Can an LLM add up every sale when the data spans two search indexes? What happens
when a table is too large to embed in one piece?

This demo explores both questions with Microsoft Foundry and synthetic car-sales
data. The JSON file and Excel workbook hold **different, nonempty partitions** of
the same dataset, so neither source alone can answer "Give me the sum of all sales."
There are three ways to run it:

| Path | Arithmetic | What it demonstrates |
| --- | --- | --- |
| Native-ACL pipeline (`main.py`) | Deterministic calculator over complete authorized sources | Exact totals independent of top-k evidence; strict split/ACL acceptance gates |
| Playground experiment (`retrieval_only.py ask`) | LLM only, native multi-index MCP retrieval | Retrieval from both indexes; full summation still fails in the observed runs |
| Full-text control (`retrieval_only.py full-text-sum`) | Same model, **no tools** | Exact LLM summation succeeded twice when both complete texts were supplied directly |

**Where things stand:** the code and cloud runner are implemented; cloud writes
and paid calls require approval. The full-text LLM test worked twice, but the
Playground agent did not produce a complete total. The original native-ACL
pipeline is still blocked by Text Split completeness checks. These are separate
results, not a claim that the full split/ACL/image demo has passed. Source code
and unit tests alone cannot establish that.

## Retrieval-only Playground experiment: no calculator

Use `retrieval_only.py` when you want the **LLM itself** to attempt the arithmetic.
This separate experiment needs explicit approval. The Foundry prompt agent gets
one native MCP tool, `knowledge_base_retrieve`, backed by a knowledge base with
**both JSON and Excel indexes**. The agent decides whether to search and how often;
one minimal-reasoning knowledge-base call can query both sources.

There is no calculator, Code Interpreter, custom function executor or Container
App in this path. The answer is the model's own attempt. An oracle does not supply
or correct it.

The deployed setup uses `native-whole-table`. Native Blob indexers read the two
already-approved immutable files into **separate indexes**: one complete JSON
table and one complete Excel-derived text table. This avoids giving the operator
document-upload rights or adding Storage permissions. Retrieval uses keyword
search and semantic ranking, with no Text Split or embedding skill. The schema
still has a vector field for compatibility, but it contains no vectors and has
no query-time vectorizer.

There is also a row-aware push option for operators who have separately approved
data-write permissions. It packs complete rows into three valid JSON documents
per partition, each embedded below 6,000 tokens. If a push fails, the CLI does not
grant itself contributor access. Neither option changes the protected pipeline
or its recorded failures. Having every row in an index does not mean every search
or model answer will use every row.

**Use synthetic data only here.** Native Search document authorization requires
a separate user-token header. This setup has not established that Playground
forwards it automatically. Instead, the experiment creates separately named
**synthetic project-corpus indexes** and retrieves through the project's managed
identity, without personal file-ACL filtering.

Project/agent users and service readers may access that approved corpus. Do not
put protected Graph or customer content in it, or treat it as a per-user ACL test.
The existing native-ACL indexes, permission filters, source files and sync state
stay untouched.

Before making cloud changes, add this setting to your consumer configuration:

```json
"retrieval_experiment": {
  "synthetic_project_corpus_approved": true,
  "authorization": "project-managed-identity",
  "ingestion": "native-whole-table",
  "model_deployment": "<existing model deployment with enough token-rate capacity>"
}
```

Review the plan before setting the approval flag: check the new index names,
Foundry project managed-identity reader grant, MCP connection and agent
instructions. The identity receives Search Index Data Reader on the selected
demo service. Agent definitions contain no personal bearer tokens or API keys.
Existing service readers keep their access, and the agent needs no additional
Storage access.

The knowledge base allows 40,000 tokens and six documents per retrieval so the
tables fit. MCP can repeat table content in citation payloads, though, so size
your model choice around the **actual tool response**, not just the source files.
The existing `gpt-5.1` deployment in this demo had only 30,000 TPM. The experiment
therefore uses the existing `aifactory-agent-gpt-6-1-sol` deployment at 200,000 TPM.
Neither model's capacity nor the primary Factory Agent was changed. Rate limits
can still apply.

```powershell
& $Python retrieval_only.py plan --config $Config --output "$State\retrieval-only-plan.json"
# Only after the synthetic project-corpus scope and paid-call approval:
& $Python retrieval_only.py configure --config $Config --apply --allow-paid
& $Python retrieval_only.py verify --config $Config
& $Python retrieval_only.py probe --config $Config --allow-paid `
  --input "Find evidence from both the JSON and Excel car-sales sources."
& $Python retrieval_only.py deploy --config $Config --apply
& $Python retrieval_only.py ask --config $Config --allow-paid `
  --input "Give me the sum of all sales."
```

The probe saves knowledge-base activity and references; agent calls save the
native MCP trace. Those server-executed calls must succeed before the agent can
be described as usable in Playground. A successful retrieval still says nothing
about the accuracy of its arithmetic. This path does not apply the calculator's
numeric-answer check or copy protected content from the Graph delta/security
extension into project-readable indexes.

In the live run, both indexes held exact copies of their source text. The agent
returned car-model values found in both sources and cited them, without a calculator.
Asked for the full sum, it searched twice and declined to give a complete total,
saying the results were truncated. That response is kept as a result of the
experiment, not replaced with a calculated answer.

### Reproduce the successful no-tools summation control

**This test bypasses the Playground agent; it does not fix it.** `full-text-sum`
reads both complete documents from the live experiment indexes, checks their
content and provenance against the approved publication, and sends the original
text directly to the **same model deployment**. It does not invoke the saved agent
or its MCP tool. The only transformation is decoding the transport JSON: no rows
are pre-calculated, summarized, split or replaced with evaluator answers.

First complete the local setup, consumer configuration, synthetic publication
and approved `native-whole-table` experiment deployment described in this README.
You will need your own private-network access, Entra identity and consumer
configuration. Sharing the code does not share the original operator's Azure
resources.

`$Python`, `$Config` and `$State` refer to the variables in **Local setup and
deterministic generation** below. A compatible reasoning model with adequate
context, output and token-rate capacity must already be deployed and selected by
`retrieval_experiment.model_deployment`. This command creates no Azure resources.

```powershell
# Optional comparison: existing native MCP/Playground route.
& $Python retrieval_only.py ask --config $Config --allow-paid `
  --input "Give me the sum of all sales." --output "$State\sum-agent.json"

# Paid full-text control: no calculator, retrieval or code-execution tools.
& $Python retrieval_only.py full-text-sum --config $Config --allow-paid `
  --output "$State\sum-full-text-1.json"

# Independent fresh response; no previous answer is supplied.
& $Python retrieval_only.py full-text-sum --config $Config --allow-paid `
  --output "$State\sum-full-text-2.json"
```

The fixed prompt asks the model to add all sales from both texts in integer USD
cents. Cancelled rows count as zero; discounts and refunds are deducted, and tax
is excluded. It asks for deduplication by `(dataset, version, sale_id)`, subtotals
for groups of at most 20 consecutive IDs per source, and then each source's count
and subtotal plus the grand total.
The exact prompt is `FULL_TEXT_SUM_QUESTION` in
[`sales_demo/retrieval_experiment.py`](sales_demo/retrieval_experiment.py).
Because this is a fixed comparison, the command rejects `--input`.

Inference uses `tools=[]`, `tool_choice="none"`, `reasoning.effort="high"`,
`max_output_tokens=24000`, `store=false`, no previous response and no automatic
retry. It leaves out `agent_reference` because the service rejects per-request
reasoning overrides when an agent reference is present. If the model is
incompatible or a rate limit is reached, the command reports the error. It does
not switch models or add a tool.

Each run saves its exact input and settings, source hashes and raw response under
`$State\retrieval-only-experiment\full-text-sum-runs\<run-id>`. The result also
contains token usage, duration and the raw model answer. An incomplete response
or unexpected tool call fails the run; the response is kept for inspection.
Keep these artifacts and all consumer configuration outside Git.

For a blind comparison, **do not give the model the README, expected amounts or
`evaluation\expected.json`**. Only after inference, compare the returned source
counts, subtotals, grand total and audit groups with the independent expected
results (the oracle) and structured rows. The command returns
`arithmetic_verified:false` on purpose: a completed model response is not proof
of correct arithmetic or complete coverage.

### Observed results: 16 October 2026

The original test runner used the same request format now available through
`full-text-sum`. It used synthetic `car-sales/v1` data with seed 48. The model
received no expected total, computed row amount or calculator.

| Route | Completed trials | Exact full totals |
| --- | ---: | ---: |
| Persisted native-MCP agent: original and stronger audit prompts | 2 | 0 |
| Same `gpt-6.1-sol` model: full-text, high-reasoning, no-tools control | 2 | 2 |

Both successful controls returned **262 records and USD 39,535,932.62**, including
109 JSON records / USD 16,768,818.26 and 153 Excel records / USD 22,767,114.36.
After each response, an independent Decimal calculation matched **all 14
audit-group subtotals**, source totals, row counts and currency conversions.
The runs took approximately 241 and 288 seconds (about 4-5 minutes).

The agent baseline declined a full total. The stronger prompt reported only
61 JSON and 114 Excel records and also introduced a USD 100 arithmetic error.
Yet every recorded MCP response contained both complete source texts with
matching hashes. The content may be cut off between the hosted tool and the
model's context, but the exact cause and token limit are still unknown. A complete
tool trace does not prove the model received that same text.

**What this tells us:** the LLM can calculate the full total for this fixture
without a calculator. Two correct runs do not guarantee future accuracy. The
controls use different input delivery and reasoning settings; they do not fix
Playground or prove Text Split reconstruction or personal file-ACL enforcement.
The original native-ACL splitter returned three chunks but failed content and
offset checks. Those checks were kept, rather than relaxed to make the demo pass.

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

`Text Split` is **not row-aware**. It keeps model inputs small enough; it does not
understand spreadsheet rows. A chunk that ends halfway through a JSON object is
not a valid table on its own. The exported parts are valid JSON **envelopes**
containing `chunk_text` and measured metadata, not repaired versions of the rows.

The calculator takes a different route: it reads the **complete authoritative
structured rows**, rather than trying to total top-k search hits. A separate
ingestion check verifies that the chunks reconstruct the full source. This path
demonstrates RAG plus a calculator, not exhaustive aggregation through vector
search.

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

Selecting an identity does not grant it permissions. Role assignments, new
groups, SharePoint provisioning, public-network changes and shared-resource
deletion are not automatic.

Check the test users' existing Storage roles carefully: broad data roles can
bypass ACL restrictions. Preflight reports these, including custom wildcard roles
and conditional assignments that need review. Include every transitive group
principal for each user. Before paid calls, live evaluation also resolves both
test users' transitive groups and checks their effective direct and group grants.
Conditional grants are flagged for review, not assumed safe.

## Local setup and deterministic generation

Use a separate environment for this example so the shared operator's dependency
pins stay unchanged. If you are working from a consumer copy, point `$Demo` at
its `aifactory-usecase-code` folder. Keep generated files and consumer settings
**outside** the template code, where an update will not overwrite them.

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

The generator creates `car-sales-xyz.json`,
`car-calculator-tool.xlsx` and `car-random-image.docx`, plus the normalized
whole-workbook text, structured rows and original PNG derivative. JSON and Excel
contain different business IDs. A **separate, nonindexed** fixture contains
overlapping records to test deduplication. The simulated libraries do not add
duplicate sales just to fill out the folder layout.

`publication.json` holds integrity metadata, not answers.
`evaluation\expected.json` holds the independent oracle: IDs, row counts, hashes
and exact expected amounts. It stays outside `master` and `project` ingestion;
only the evaluator opens it. The generator copies master files to the local
project tree and checks their byte hashes. The publisher separately copies the
hash-pinned master files to the Azure project publication.

Token counts come from the **actual text entering Text Split**: the serialized
JSON and the text extracted back from the workbook, not workbook XML or file
size. The generator targets about 13,500-14,500 tokens per input, and both must
exceed 9,000. Only a real Azure run can establish whether that produces three
chunks.

The tokenizer downloads its public vocabulary on first use unless it is cached.
An offline machine needs a populated, verified tokenizer cache.

Measured locally for seed **48**, version **v1**:

| Partition | Rows | Actual input tokens | Independent expected net sales |
| --- | ---: | ---: | ---: |
| JSON | 109 | 13,618 | USD 16,768,818.26 |
| Excel | 153 | 13,572 | USD 22,767,114.36 |
| Combined, disjoint IDs | 262 | Not a shared embedding input | USD 39,535,932.62 |

These amounts are for evaluation, not for the agent's prompt. The local DOCX
passed OOXML schema validation and was opened in installed Microsoft Word for
visual inspection. That confirms the embedded image in the file, **not** Azure's
ability to extract or serve it.

## Arithmetic and coverage contract

Sales means **net merchandise revenue excluding tax**, in USD cents:

```text
completed/refunded row = quantity * unit_price_minor - discount_minor - refund_minor
cancelled row          = 0
tax_minor              = recorded but excluded from sales
```

Discounts and refunds apply to the whole row, not to each unit. Amounts and
quantities must be valid integers, not binary floats or booleans. A refund cannot
exceed the discounted merchandise amount. Cancelled records stay in the audit
trail but contribute zero.

Each record is identified by `(dataset, version, sale_id)`. Identical copies count
once; different row contents with the same identity cause an error. For source
breakdowns, a duplicate is assigned deterministically to the first source. That
keeps the breakdown consistent with the deduplicated grand total. The main
partitions do not overlap, but the separate overlap fixture needs this rule.

The backend chooses partitions from trusted configuration and the validated
current identity. The model cannot choose arbitrary index names, paths, groups
or scope. Before calculating, the backend checks the publication version, source
hashes, all row pages and all ingested chunks.

A missing partition or chunk, conflicting duplicate, unfinished publication,
wrong version, unreadable authorized source or incomplete page sequence is an
error. The backend must not turn any of these into a plausible-looking subtotal.

## Resolve the actual lake and plan

Use an existing common-lake binding from your consumer configuration to resolve
the account and container. Do not guess the container from a portal account URL.
These commands do not provision Azure resources:

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

`discover` only reads Azure. With `--update-config`, it records the discovered
endpoints and identity in your local consumer configuration. It does not approve
paths or choose readers for you. Fill in the group policies, allowed and denied
test principals, and backend identity, then review the plan.

The proposed paths follow the repository's master/project layout:

```text
mlops/v1/master/environments/<env>/datasets/car-sales/versions/<version>/
mlops/v1/projects/projectNNN/environments/<env>/usecases/car-sales/rag/corpora/car-sales/versions/<version>/
```

These paths are **candidates until approved**. The shared `datasets` and project
`usecases` parents must already exist and allow traversal. The plan lists every
directory it would create, from the two task-owned `car-sales` roots down to this
version's source folders.

After approval, the publisher can create missing task-owned parents. It leaves
shared parents and existing ancestor ACLs alone. If traversal is insufficient,
the operation stops instead of widening permissions. It never replaces a
directory owned by something else. Oracle data, debug chunks and images are
excluded from protected sales ingestion.

## Approved cloud execution

Review the exact resource names, paths, identities and billable operations before
running these commands. Their presence in this README is **not approval to run
them**. Set `paths_approved` only after review. `--apply` allows changes;
`--allow-paid` separately allows indexing and inference that may call models.

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

Creating an indexer can start indexing straight away. That is why `configure`
requires paid-call approval and waits for completion. Use `ingest` to run a
pipeline that is already configured. Source changes are not silently retried.

Sign in the restricted user through a separate existing CLI profile before
testing. Use the same tenant and `az login --allow-no-subscriptions`, with a
temporary `AZURE_CONFIG_DIR` pointing to that profile. Restore the previous
environment after sign-in. The delegated token provider does not require the
restricted user to have an Azure subscription role.

The current/default profile stays the full reader/operator. You can also select
a separate full reader with `--user-profile`. Never commit or share either
profile's authentication cache.

The Foundry agent definition is saved and pinned to a version. Its functions run
in the approved local/private runner. Creating that definition does **not** host
the functions as a web service. Each invocation keeps the exact user prompt and
inspects the function calls that actually ran.

## Real Text Split acceptance evidence

Both native ADLS indexers read the whole text with `parsingMode: text`. Text Split
runs before the embedding skill:

| Setting | Value |
| --- | --- |
| `textSplitMode` | `pages` |
| `unit` / tokenizer | `azureOpenAITokens` / `cl100k_base` |
| `maximumPageLength` | `6000` |
| `pageOverlapLength` | `0` |
| `maximumPagesToTake` | **`0`** (all pages, never truncate to three) |
| Embedding limit | Each final input must be **below 8,000 tokens** |

For the audit, a separate parent index with native authorization keeps the exact
`/document/content` input as `split_input_text`, plus the service's actual
page strings, ordinal positions, offsets and lengths. This avoids unsupported
custom skills, knowledge stores and debug sessions. The verifier matches those
pages to the derived chunk index, checks that all source text is present, and
confirms that at least one boundary cuts through a row or serialized record.

The target is exactly three chunks, but **only the service output can confirm
that**. It is not guaranteed by configuration. If Azure returns a different
number, adjust the deterministic fixture generation, choose a new version and
rerun. Do not truncate, pre-split the source or manufacture cloud evidence.

After a successful real run, the verifier exports:

```text
car-sales-xyz-part-1.json
car-sales-xyz-part-2.json
car-sales-xyz-part-3.json
```

Each envelope records the source and parent identity, ordinal, exact chunk text,
token count, offsets, lengths and hashes. Keep exports outside ingestion prefixes
so they are not indexed again. The offline generator does not create these files.

## Native permissions and revocation

The ADLS data source uses `indexerPermissionOptions` for `userIds`, `groupIds`
and `rbacScope`. Secured indexes enable `permissionFilterOption`, and every
projected chunk receives the native permission metadata emitted by the indexer.
Prefer group permissions over expanding group membership into per-document
user lists.

Both indexes keep `metadata_storage_path` alongside the shared `source_uri`
alias because the preview service needs the original field for ADLS permission
ingestion. Text Split language (`en`) and semantic ranking order
(`BoostedRerankerScore`) are set explicitly, so defaults returned by the service
are not mistaken for changes to the owned definition.

Each secured query sends the end user's Search-scoped token in
`x-ms-query-source-authorization`. This is separate from the backend's Search
RBAC authentication. A query without a user identity is rejected. The calculator
must use a Storage token for that same validated delegated user; it cannot fall
back to the operator or an account key.

These adapters are for a trusted local CLI, not an HTTP token-validation service.
Tokens come from Azure CLI OAuth, authenticated Graph `/me` establishes the user,
and Search and Storage validate their own tokens. Local JWT decoding checks
consistency only. Do not expose the injectable adapters as a network API. Graph
transitive-group casts use `$count=true` and `ConsistencyLevel: eventual`, so
directory replication delay also matters when testing revocation.

The trusted partition policy adds scope and integrity checks; it **does not
replace native enforcement**. Source reads and citations must be authorized
before data is returned. There is no shared authorization or result cache.
Someone who can read only one partition sees its total and provenance, not
hidden totals, counts, IDs or a list of excluded sources.

Native authorization applies to files, not individual workbook rows. Different
entitlements need different files. Copying a file does not carry over SharePoint
permissions, and POSIX ACLs cannot represent every SharePoint permission. The
demo simulates site/library lineage; actual SharePoint provisioning is optional
and has not been performed.

The indexer also reads permission metadata on the filesystem root and every
ancestor directory. A reader role limited to the two source files and their list
prefixes may therefore fail even when content reads work. Do not solve that by
granting account-wide access. Inspect the failed operations and review the exact
ancestor-object permissions separately. Selecting a source path does not, by
itself, restrict what an identity is allowed to read.

ACL-only changes might not update blob last-modified timestamps. Refresh
permissions explicitly and rerun the native indexers:

```powershell
& $Python main.py resync --config $Config --apply
```

This queues `resync` with `options: ["permissions"]`, then runs the indexers.
Afterwards, test allowed and revoked identities against every projected chunk
and delegated source read. Search permission refresh, Entra group/token changes
and client authentication each have their own delays, so this is not an
instantaneous-revocation SLA. Keep access disabled while a required resync is
unfinished rather than serving a cached answer.

## Separate image-serving branch

The DOCX contains an original car illustration with a visual detail that is not
described in the surrounding text. This branch is for explicitly non-sensitive,
synthetic content only.

**`assetStore` cannot be combined with `ingestionPermissionOptions`.** Never
upload protected sales data into the image branch to get around this limitation.
Use an approved, isolated area for image sources and assets. Do not give the
image pipeline account-wide write access to the shared master lake.

Use agentic retrieval's asset store with `enableImageServing: true` and
`outputMode: answerSynthesis`, not extractive mode. To pass, the real retrieval
activity must show `imagesSentToModel > 0`. Guessing the detail correctly is not
evidence that the model saw the image.

**Do not assume direct DOCX image extraction works.** Support depends on the
extraction path, so test DOCX separately. You can use the original PNG derivative
to demonstrate image serving, provided it is clearly labelled as a derivative,
not as successful extraction from DOCX. Keep image assets private to the approved
branch even though the synthetic content is non-sensitive.

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

The result saves activity and `imagesSentToModel`. Setting `input_kind: docx` does
not prove that the image came from DOCX. `docx_pass` stays false unless the
source-to-image extraction is independently established; aggregate image counts
are not enough.

## Optional Graph delta and security-webhook extension

The synthetic `<site>/<library>` folders are not a SharePoint site. To use this
extension, bind `graph-sync.example.json` to an explicitly approved **real**
SharePoint document-library or OneDrive for Business drive, using stable IDs for
the two sales files. Consumer OneDrive is rejected. Enabling the local code does
not create a source site, user, Container App, subscription or public callback,
or grant Graph consent.

Start by enumerating the full drive-root delta, then keep Graph's opaque
`@odata.deltaLink` for later requests. Every initial, continuation and incremental
request sends:

```http
Prefer: hierarchicalsharing, deltashowremovedasdeleted, deltatraversepermissiongaps, deltashowsharingchanges
```

These include the companion preferences required for
`@microsoft.graph.sharedChanged`, which is documented as the string `"True"`.
Delta gives the latest state, not a complete event log. If an item appears more
than once, the last occurrence wins. An empty page with `@odata.nextLink` still
has to be followed.

Identify items by tenant/drive/item ID, not filename. Folder moves and renames
affect descendants even if delta does not list those descendants again.
Tombstones and `410 Gone` trigger reconciliation, never a partial-data total or
an upload back to Graph. The initial inventory is not skipped with `token=latest`.

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

Send `includesecuritywebhooks` when creating or recreating the subscription.
Renewing an old content-only subscription is not treated as an upgrade to
security notifications. The default lifetime is one day; the documented
driveItem maximum is **42,300 minutes**. Renew before expiry.

A 404 needs explicit recreation with a new secret. If a creation response is
lost, first establish what happened; do not blindly repeat the POST.

### Permission changes and durable invalidation

The ASGI callback returns the decoded validation token as plain text, as required
by the Graph handshake. For normal batches, it validates each subscription,
tenant/resource and `clientState`, using constant-time hash comparison for the
secret. It then atomically marks the bound drive dirty in SQLite **before**
returning 202.

The receiver does no Graph, Storage, Search or model work before acknowledging
the event. If the durable store is unavailable, it returns a retryable failure
instead of losing the notification. Reports contain no tokens or client-state
secrets; the database stores only the secret hash.

A root notification does not reliably say which file changed or whether the
change affected content or permissions. Reconciliation therefore re-reads
permissions for every configured source. Unknown permissions, incomplete
responses or unresolved identities keep the drive unavailable. An absent
`sharedChanged` field does not rule out a permission change.

Notifications for retired subscriptions are authenticated, then disregarded.
The callback rechecks whether a subscription is active inside the durable signal
transaction. This prevents a notification being validated during recreation from
putting the healthy replacement on hold.

With `graph_sync` enabled, retrieval and aggregation need a fresh, complete
synchronized publication. The agent checks the same generation before calling
the model and before returning the answer. If a notification arrives during
calculation or answer generation, that result is discarded. There is no
cross-user answer cache. Expired reconciliation evidence or subscriptions block
serving; a successful delta fetch alone does not make it safe to resume.

A content change stages a new immutable publication, including the whole
normalized workbook text and structured rows. Text Split, embedding, source
hashes and complete calculator coverage must all be verified again.

A permission-only change updates the ACLs on every owned mirrored file, calls
native Search `/resync` with `{"options":["permissions"]}`, runs the indexer and
waits for completion. If the existing pipeline also has content to process, a
separate normal indexer run follows the permission run. The delta checkpoint
advances only after the corresponding publication is durable and verified.

A new notification invalidates reconciliation already in progress. A separate
per-scope process lock serializes publication and ACL writes, so webhook
invalidation never waits for a long indexing transaction. Partial writes leave
a repair marker. Restoring a quarantined source therefore forces ACL restoration
and resync, rather than taking the read-only recheck path.

Deleting either required sales file quarantines the publication. Named readers
are removed from its owned mirrored files and native permissions are refreshed.
The remaining partition is not presented as the whole dataset. Removing a named
ACL still cannot revoke access granted by broader Storage RBAC.

### Graph permissions and deployment prerequisites

Microsoft's permission-scanning guidance requires **`Sites.FullControl.All`**.
Ordinary `Files.Read`/`Files.Read.All` access does not establish a complete
authorization snapshot. Subscription creation and renewal have separate permission
requirements, and the current reference tables differ on the minimum renewal
scope. No broad permission is granted automatically. An administrator must review
the actual source scope, consent, reader mapping and callback before live use.

Graph permission JSON is **not** a POSIX ACL export. The extension supports only
explicitly approved Entra user/group mappings. Sharing links, invitations,
SharePoint-local groups, unknown roles and incomplete permission snapshots cause
quarantine, not public access. Nor does a missing `inheritedFrom` prove a grant
is explicit: SharePoint/Business responses do not reliably include that property.

Before reading source data, the Graph transport checks the trusted OAuth token's
tenant, audience, expiry and permission-scanning grant. This is a claim check,
not a validator for arbitrary external bearer tokens; Graph validates the token
itself. An opaque, unverifiable or insufficiently scoped token is rejected.

Webhooks need an externally reachable **HTTPS receiver**. Having private ADLS,
Search and workers does not make a private-only callback reachable by Graph.
The code provides a handler, not a deployed host or a public-network change.
It supports `reauthorizationRequired`, but driveItem documentation does not
guarantee the `missed` or `subscriptionRemoved` lifecycle events. Monitor expiry
and reconcile delta periodically rather than relying on those events.

Revocation is not instantaneous. Graph notification and directory replication
take time; the documented driveItem maximum notification latency can reach six
hours. Serving stops when a change becomes known or freshness expires, but the
system cannot react to a notification it has not received. Delegated source
reads and live native authorization are still required.

### Reproducible extension commands

Keep source configuration, SQLite state and staged candidates outside the
template. Before requesting source data, fill in the real drive/item IDs,
approved download host, permission-scan authorization and explicit `principal_map`.
For example, `{"group:<Entra-group-id>": {"type":"group","id":"<same-id>"}}`
keeps a group as a group instead of expanding its members into a user list.

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

`poll` always reconciles delta and reads fresh permissions for the selected
items. Content changes produce a new local candidate and native pipeline.
Permission-only changes keep the existing bytes and version. If neither changed,
the extension only rechecks the result; it does not write ACLs or re-embed data.
A failed, deleted or unrepresentable source keeps serving blocked.

After activating a changed binding, explicitly redeploy the pinned prompt-agent
definition. Reconciliation does not deploy models or agents behind the scenes.
The full evaluator is separate, and changed source data needs an updated
independent oracle.

The worker uses approved managed-identity compute to read native Search. It
still reads source content with the selected end user's delegated Storage
identity, never an operator fallback.

For an approved externally reachable ASGI host, mount
`webhook:create_app` with factory mode and set `AIF48_GRAPH_SYNC_CONFIG` to the
consumer configuration. `webhook.py` does not start a server. This is a
**single-host** reference implementation: the callback and worker must share a
durable local SQLite database and process-lock filesystem. Do not scale out
instances with separate local databases. A distributed deployment needs an
equivalent durable queue, shared epoch store and write-serialization adapter.

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

Once a subscription is confirmed missing, use
`recreate --subscription-id <old-id>` with explicit `--apply` and a new secret.
Other subscriptions are not deleted. A normal delta reconciliation cannot clear
a lifecycle hold; both subscription repair and fresh reconciliation are required.
Schedule renewal and polling outside the callback, more often than the configured
`max_age_seconds`. The extension does not create a scheduled job.

## Evaluation and completion

There are three different things to check: offline code behavior, service
integration, and answers from a live deployed agent. Mocked service or model
responses test the client logic. They do not prove a deployment works.

### Explicit single-user operator preview

If you have only one existing user, use `preview.py` for a **separate local
operator preview**. It does not relax the full ACL checks in `main.py`.
In the consumer configuration, set `evaluation_mode` to `operator-preview`,
`operator_preview_user_id` to the verified user's object ID, both partitions'
`allowed_user_ids` to exactly that one ID, and `allowed_group_ids` plus
`denied_test_user_ids` to empty lists. This creates no user or group.

Every online command checks the configured user against authenticated Graph
`/me` in the selected tenant. The CLI Search backend also uses the operator's
cached, subscription-bound OAuth credentials. That means this preview does
**not** validate a managed-identity backend, and it is never an automatic fallback
for the normal runtime.

The read-only transport guard, native `x-ms-query-source-authorization`, delegated
Storage reads, complete chunk/row coverage and exact arithmetic checks still
apply. No elevated-read header is used.

An operator with broad Storage RBAC can show that authorized retrieval and
calculation work, but not that restrictive ACLs or revocation work. The evaluator
therefore reports `authorized_cases_passed` separately and always leaves `passed`
and `complete_acl_acceptance` false. It does not reuse the same user as a pretend
denied identity. The independent oracle remains evaluator-only.

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

You can inspect the saved prompt agent in Foundry Playground, but its custom
functions still run in this CLI. Playground does **not** automatically host
`aggregate_sales`. An interactive Playground calculator would need a separately
approved remote tool host and supported per-user delegation. Copying protected
tables into Code Interpreter does not preserve the same permission model.
`preview.py` creates no Container App, external tool host or new user.

Service and live unittest entry points are skipped unless you enable them:

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

Only the evaluator opens the independent oracle. It compares the deployed
agent's exact numeric answers and tool traces. Do not put expected totals in
instructions, search content or calculator code, or present model mocks as live
results.

The offline suite covers the original pipeline, delta handling, webhook
validation and lifecycle, concurrent invalidation, immutable content staging,
permission-only refresh and deletion quarantine. Three service/live entry points
need explicit opt-in. Local checks also cover generating and reading back the
workbook, the exact independent oracle, both >9,000-token inputs, master/project
hashes, the original embedded image and the rendered DOCX.

For the **protected sales pipeline**, complete live chunk coverage, group-based
allow/deny and revocation, deployed-agent answers, destructive missing-chunk
fault injection and image serving have not passed live acceptance. The evaluator's
pass flag covers the protected sales agent, not the separate image branch or
cloud fault injection. The calculator-free experiments earlier in this README
have their own results.

The approved live attempt published the immutable synthetic files and created
the native indexes, data sources, skillsets and indexers. It revealed the required
native path field and explicit defaults described above. Ingestion then failed
before processing documents: Storage metrics showed denied `GetPathAccessControl`
calls even though content reads and listing worked.

After separately approved reads of the exact ancestor objects, both indexers
reported success with one source processed each. The known path-key rename
advisory is kept for these immutable publications; unknown warnings still fail.
With a separately approved service-scoped reader grant, queries returned three
chunks per source. **The chunks did not pass the completeness check.**

The token-based output had zero-based ordinals and inconsistent offsets. JSON
chunks lost text at a boundary; Excel chunks exceeded the requested 6,000-token
page size, though they stayed below 8,000. A bounded 5,000-token experiment also
lost text. The audited input to Text Split matched the original source exactly.
The verifier therefore did not repair or accept the fragments. The default
6,000-token settings were restored, but this publication remains blocked and
no protected-pipeline agent was deployed.

That is what happened in this preview deployment, not a claim about every Text
Split deployment. Identity-specific evidence stays in consumer-owned state,
outside the indexed corpus and source template.

The Graph extension has not been registered against a real drive or public
webhook. Simulated callbacks do not prove delivery of a real Microsoft
permission-change notification. The opt-in source test additionally requires
`AIF48_GRAPH_SERVICE_TESTS=1`, `AIF48_GRAPH_SOURCE_READ_APPROVED=1`,
`AIF48_GRAPH_SYNC_CONFIG`, and `AIF48_CONFIG` before real Graph reads.

## Costs, troubleshooting and cleanup

Deferred project-creation fixes are tracked in the
[IaC Search RBAC and regional-parity TODO list](../../../environment_setup/aifactory/bicep/README.md#todo-project-creation-search-rbac-and-regional-parity).
Additional or regional Search instances should get the same correct roles for
each identity and the same private-connectivity setup as the primary task. The
manual recovery used here should not become an undocumented prerequisite for
future deployments.

- In the split-and-embed pipeline, indexing invokes embeddings for all produced
  chunks. Semantic ranking, vectorization, agent inference, image
  extraction/synthesis and storage consume
  service capacity or incur charges. This README does not give an unverified
  price estimate.
- A missing managed-identity endpoint means the backend is running in the wrong
  host context. Do not replace it with a broadly privileged user token.
- `403`, unknown membership, hash mismatch or failed indexer status are blockers,
  not a reason to enable public access or omit a partition.
- Missing task-owned source parents are included in the publication plan.
  Missing shared parents or traversal require a separately reviewed change,
  never recursive ACL broadening of the shared lake.
- If a Search object or directory with the chosen name belongs to something else,
  stop. Use a new task/version prefix rather than overwriting it.
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

The repository's dual graph helps explain the code and architecture. It is not
evidence of a live deployment. For what actually ran, use the source, tests and
recorded responses from approved service calls.
