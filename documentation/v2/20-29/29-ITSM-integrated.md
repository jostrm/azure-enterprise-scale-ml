# AI Factory workflow events and ITSM integration

AI Factory can monitor an **exact GitHub Actions workflow run** and expose its
observed state through a common API. The CLI, configuration tools, a cloud portal,
and an ITSM integration can subscribe to the same updates instead of each
implementing their own GitHub polling.

Monitoring is read-only. Starting or stopping a subscription does **not** dispatch,
retry, cancel, approve, or redeploy a workflow. Workflow monitoring also does not
replace the separate factory setup, deployment approval, or distributed-lock
requirements.

## Prerequisites and scope

The Python examples need **both** the `azurefactory-cli` package (which provides
the `azurefactory` Python SDK) and a separately running AI Factory API. Installing
the package does not install/start the backend, generate an API key, or sign in
to GitHub. `AzureFactoryClient()` only reads the client's connection settings.

### 1. Install the Python SDK and CLI

Use **Python 3.10 or newer** and an updated checkout of this repository containing
`environment_setup\azurefactory-cli`, from `main` or `release/v.1.25`.
The commands below use **PowerShell 7 or newer**; replace the checkout path with
your own:

```powershell
Set-Location "C:\path\to\azure-enterprise-scale-ml"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .\environment_setup\azurefactory-cli
python -c "from azurefactory.client import AzureFactoryClient; print('SDK import OK')"
```

Install from this repository's package directory, not an assumed PyPI package
named `azurefactory`. The editable install above provides both the
`from azurefactory.client import AzureFactoryClient` import and the
`azurefactory` command. See the [CLI/SDK installation guide](../../../environment_setup/azurefactory-cli/readme.md#install).

Run your Python script with this same activated environment. In an IDE or
notebook, select this virtual environment as the interpreter/kernel; installing
into a different Python environment will still leave the import unavailable.
The import check does not need an API server or credentials.

### 2. Start or obtain access to the API backend

Use an updated API containing `/api/v1/workflow-runs/status` and
`/api/v1/workflow-runs/events`. The canonical backend is in the separate
`008_aifactory_admin_ux_tkinter` repository, not this SDK package.

**If you run the standalone source backend:** install that repository's
documented prerequisites in its own Python environment. Create a strong random
API secret using your approved secret manager, then supply it to the server
before startup. In a separate server terminal, with the backend environment
activated:

```powershell
Set-Location "C:\path\to\008_aifactory_admin_ux_tkinter"
$env:AIFACTORY_API_KEY = Read-Host "API secret from your secret manager" -MaskInput
gh auth status --hostname github.com
python -m src.api
```

Keep the server terminal running. The standalone source server defaults to
`http://127.0.0.1:8765`; use its actual address if the operator changed the port.
`gh auth status` checks existing authentication, not sign-in. Before monitoring,
the API host's GitHub CLI (`gh`) must be installed and authenticated as an account
or approved automation identity that can read the selected repository's Actions
runs. If needed, complete `gh auth login --hostname github.com` interactively on
the API host before starting it. Monitoring never launches sign-in for you.

**If you use the packaged MAUI app or an operator-managed API:** obtain the
authorized URL and key from the host/operator instead of generating a new client
key. MAUI starts its bundled API on a dynamically selected loopback port with a
per-process key. Neither `8765` nor the example port `64979` is a guaranteed MAUI
port, and connection settings may change after restart. This guide does not
provide a MAUI key-export UI or command; do not scrape another process's
environment. For a standalone integration without an operator-provided
connection, use the source-backend setup above.

See [API host and connection guidance](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md#which-api)
for the relationship between the source backend and packaged desktop API.

### 3. Configure the client's API URL and key

| Variable | What to set |
|---|---|
| `AIFACTORY_API_URL` | The running backend's **base URL**, for example `http://127.0.0.1:8765` for the default standalone server. Do not append `/api/v1`, `/docs`, or a workflow endpoint. |
| `AIFACTORY_API_KEY` | The **same secret accepted by that server**: the secret you configured before standalone startup, or the authorized key supplied by its operator. |

These values are not an Azure resource endpoint/key, an Azure access token, or a
GitHub token. Setting an arbitrary secret only in the client will not authorize
it. If the URL is omitted, the SDK defaults to `http://127.0.0.1:8765`; the key
has no usable default for authenticated calls.

In the **client terminal** from step 1:

```powershell
$env:AIFACTORY_API_URL = "http://127.0.0.1:8765" # Replace if your API uses another address.
$env:AIFACTORY_API_KEY = Read-Host "Enter the same API secret accepted by the server" -MaskInput
azurefactory health
azurefactory doctor
```

The masked prompts keep the secret out of the visible command and shell history.
For unattended clients, inject it through your approved secret-management
mechanism instead. Never commit it to a script, notebook, `.env` file, or
repository. The SDK sends it as the `X-API-Key` header, not in the URL.
Environment variables set here apply to this terminal and processes launched
from it; configure them separately for an already-running IDE or another shell.

`health` checks reachability without a key; success does **not** prove
authentication or GitHub access. `doctor` checks API compatibility; the exact-run
status call below checks workflow monitoring. An old API missing the workflow
routes must be upgraded, not worked around by changing credentials.

`127.0.0.1` refers to the machine running the client. For a remote ITSM service,
obtain an authorized, secured integration endpoint from its operator; do not
expose a desktop loopback listener publicly. The SDK permits plain HTTP only for
loopback hosts and requires HTTPS for non-loopback hosts.

### 4. Identify the exact GitHub run

Supply the exact repository and numeric GitHub run ID. For
`https://github.com/contoso/ai-factory/actions/runs/123456789`, use repository
`contoso/ai-factory` and run ID `123456789`. Replace these illustrative values with
a real run that the API host's identity is authorized to read:

```powershell
azurefactory workflow status --repository contoso/ai-factory --run-id 123456789
```

Never identify a deployment by asking for the repository's "latest run." Another
person or workflow can start a run concurrently. Retain the verified remote run
ID returned or recorded by the deployment process. The GitHub run ID is not the
AI Factory's local job UUID.

The current provider is GitHub.com. Azure DevOps, arbitrary GitHub Enterprise
hosts, and custom callback URLs are not implicitly supported by these routes.
Using the same event contract for another provider requires a separate adapter.

## Integration architecture

```text
GitHub Actions REST API
          ↓
Shared backend run monitor
          ↓
API event subscriptions
          ↓
AIF CLI / AIF Config Wiz UX / Your Cloud Portal or ITSM
```

| Consumer | Integration |
|---|---|
| AI Factory API | Current run status plus a Server-Sent Events subscription. |
| AI Factory CLI | A watch command, with optional JSON events. |
| AI Factory Config Wizard UX | An asynchronous subscription updating status, result, and **Open in GitHub**. |
| AI Factory Tkinter app | The same observed-event contract, with background work handed to the Tkinter UI thread. |
| Your Cloud portal / ITSM | The same API subscription as AI Factory Config Wizard UX; update the portal's UI safely or process events in an authenticated server-side integration. |

The backend owns GitHub authentication and monitoring. Consumers authenticate to
the AI Factory API; they do not need to copy GitHub credentials into each UI.
The shared monitor avoids a separate GitHub polling loop for every subscriber
within the same running backend. Separate API processes are not a distributed
leader election service: deploy a single monitoring backend per integration
unless you explicitly coordinate multiple instances.

## Does GitHub already have callbacks?

Yes. GitHub supports `workflow_run` webhooks, including these actions:

| Event/action | Meaning |
|---|---|
| `requested` | A workflow run was requested. |
| `in_progress` | Execution started. |
| `completed` | Execution finished, not necessarily successfully. |

GitHub also has `workflow_job` webhooks for individual jobs within a workflow.
These are not a live stream of every Bash command or output line.

A webhook requires an HTTPS receiver that GitHub can reach. GitHub cannot call a
normal laptop's `localhost` API. The desktop-friendly implementation therefore
reads GitHub's REST API and publishes **observed changes** to subscribers through
Server-Sent Events (SSE). No public listener, inbound firewall exception, tunnel,
or custom callback step in every workflow is needed.

This is not a GitHub webhook receiver. A future signed-webhook adapter can feed
the same event model, but webhook registration and delivery are not required by
the implementation described here.

### Status is not the result

Keep `status`, `conclusion`, and monitoring health separate.

| Example | Interpretation |
|---|---|
| `status = queued`, `conclusion = null` | GitHub has queued the run; it has not finished. |
| `status = waiting`, `conclusion = null` | The run is waiting, for example for an environment approval. Monitoring does not approve it. |
| `status = in_progress`, `conclusion = null` | The run is executing. |
| `status = completed`, `conclusion = success` | GitHub reports successful completion. |
| `status = completed`, `conclusion = failure` | GitHub reports failure; inspect the run's jobs and logs. |
| `status = completed`, `conclusion = cancelled` | The run was cancelled. |
| `status = completed`, `conclusion = timed_out` | The run exceeded a time limit. |
| `conclusion = neutral`, `skipped`, or another non-success value | Preserve the actual conclusion; do not silently convert it to success. |
| Monitoring connection failed | The observer cannot currently confirm new state. This does not mean the workflow failed or stopped. |

A successful workflow conclusion is not, by itself, independent evidence that
every Azure resource is healthy. Retain deployment verification and any
application-specific acceptance checks.

## API: current status and SSE

Both endpoints use the API's existing authentication and access policy:

```http
GET /api/v1/workflow-runs/status?repository=contoso%2Fai-factory&run_id=123456789
X-API-Key: <your-api-key>
Accept: application/json
```

```http
GET /api/v1/workflow-runs/events?repository=contoso%2Fai-factory&run_id=123456789
X-API-Key: <your-api-key>
Accept: text/event-stream
```

The event envelope identifies the repository, `run_id`, `run_attempt`, observed
`status`, nullable `conclusion`, verified `html_url`, commit `head_sha`, and UTC
`observed_at`. `schema_version` versions the envelope. `event_id` is an opaque
resume cursor, not a GitHub run ID. Repository identity is normalized to lowercase.
`monitor_status` (`ok` or `error`) and `stale` describe observation health.

If no GitHub observation has succeeded yet, an unavailable observation has
`run_attempt = 0`, `status = null`, `head_sha = null`, and `conclusion = null`.
An initial SSE `snapshot` can carry this unavailable state, with
`monitor_status = error` and `stale = true`. **Snapshot does not mean healthy.**
After an observation succeeds, errors preserve its last known workflow fields.

An illustrative completion frame is:

```text
id: <opaque-event-id>
event: completed
data: {"schema_version":1,"event_id":"<opaque-event-id>","event_type":"completed","repository":"contoso/ai-factory","run_id":123456789,"run_attempt":1,"status":"completed","conclusion":"success","html_url":"https://github.com/contoso/ai-factory/actions/runs/123456789","head_sha":"0123456789abcdef0123456789abcdef01234567","observed_at":"2026-09-24T07:30:00Z","monitor_status":"ok","stale":false}

```

The example IDs and SHA above are placeholders, not a real deployment.

### Subscription events

| Event | Consumer behavior |
|---|---|
| `snapshot` | Initialize from the current observed state. The first observation may already be completed. |
| `requested` | Show an observed `requested` status without claiming execution has started. |
| `in_progress` | Show that GitHub reports execution in progress. |
| `completed` | Read `conclusion` before presenting success or failure. |
| `status_changed` | Render another observed GitHub state without losing its original status. |
| `monitor_error` | Show degraded monitoring and preserve the last known workflow outcome. |
| `monitor_recovered` | Clear the monitoring warning after a successful observation. |

Polling can miss brief intermediate states. If the monitor first sees
`completed`, it must not invent a preceding `requested` or `in_progress` event.
Observed `queued`, `pending`, and `waiting` changes use `status_changed`, retaining
the exact GitHub status rather than mislabelling them as webhook deliveries.
Heartbeat comments keep the SSE connection alive; they do not represent workflow
progress.

Reconnect with the last processed cursor using `Last-Event-ID`, or the `after`
query parameter. A cursor belongs to its exact run stream: do not reuse it for a
different repository/run. Invalid or unavailable cursors must be handled as an
explicit resynchronization condition, not silently treated as a complete history.
Use `follow=false` to request the available snapshot/replay without waiting for
future observations.
If a resumed subscription is already caught up and complete, it may close with no
new frames. The CLI confirms the current status without emitting the same cursor
twice. An empty stream or disconnected connection alone is not proof of success.

The normal watch ends when the observed run attempt completes. A later GitHub
rerun has another `run_attempt`; start/reconnect monitoring to observe it.
Persisting the attempt prevents a completed first attempt from being mistaken
for the result of a later rerun.
Replayed completion events are history, not an instruction to stop consuming.
The clients finish only after reconciling the caught-up stream with the current
healthy run state. A newer monitoring error or run attempt must not be hidden
by an earlier successful completion.

### Browser and portal authentication

Do not put the API key in a URL, HTML file, browser local storage, or client-side
source shipped to other users. A browser's native `EventSource` constructor does
not let you add an arbitrary `X-API-Key` header.

For a portal, prefer an authenticated server-side proxy that keeps the AI Factory
API key private and relays only authorized run events. An authorized client that
already manages the credential can use a streaming HTTP client with headers.
Do not disable the desktop API's access checks or expose its loopback listener
publicly just to make a browser example work.

## CLI examples

Complete the [prerequisites](#prerequisites-and-scope) first, including SDK/CLI
installation and private API URL/key configuration. These commands read one exact run:

```bash
azurefactory workflow status --repository contoso/ai-factory --run-id 123456789
azurefactory workflow watch --repository contoso/ai-factory --run-id 123456789
azurefactory workflow watch --repository contoso/ai-factory --run-id 123456789 --json
azurefactory workflow watch --repository contoso/ai-factory --run-id 123456789 --json --timeout 1800
azurefactory workflow watch --repository contoso/ai-factory --run-id 123456789 --after "<opaque-event-id>" --no-follow
```

JSON watch output is newline-delimited JSON, suitable for a program consuming one
event at a time. Diagnostics belong on stderr, not mixed into the JSON stream.
Pressing Ctrl+C stops the local observer; it does not cancel the GitHub run.
Resume with the last event cursor when continuing the same stream.
The default overall watch deadline is 300 seconds. `--timeout` after `watch`
changes that deadline; the global `--timeout` before `workflow` controls individual
HTTP requests. Read-only reconnects are bounded by `--max-retries` (default 3).
Timeouts stop observation, not the workflow.

| CLI exit code | Meaning |
|---|---|
| `0` | A healthy observation; for a completed run, conclusion is `success`. A successful `status` or `--no-follow` read can still describe an unfinished run. |
| `2` | Monitoring/protocol/configuration error; workflow outcome is not inferred. |
| `4` | Observation/request timeout. |
| `5` | Completed with a conclusion other than `success`, including cancellation, neutral, or skipped. |
| `6` | AI Factory API authentication failure. |

### Python callback subscription

First complete the [prerequisites](#prerequisites-and-scope). Save the example as
`watch_workflow.py`, replace the sample repository/run ID with your actual run,
and execute `python .\watch_workflow.py` from the configured client terminal.

The SDK exposes `get_workflow_run_status`, `watch_workflow_run` (an event
generator), and `subscribe_workflow_run` (a synchronous callback adapter).
The callback runs on the caller's thread: desktop callers should use a worker
and dispatch UI updates to the main thread.

```python
from azurefactory.client import AzureFactoryClient

client = AzureFactoryClient()  # Uses AIFACTORY_API_URL and AIFACTORY_API_KEY.

def on_workflow_event(event):
    unavailable = event.get("monitor_status") == "error" or event.get("stale") is True
    if unavailable:
        print("Monitoring unavailable; workflow outcome is not inferred.")
    else:
        print(event["run_id"], event["run_attempt"], event["status"], event["conclusion"])
    # Returning False stops this subscription; it does not cancel the workflow.

client.subscribe_workflow_run(
    "contoso/ai-factory",
    123456789,
    on_workflow_event,
    timeout=1800,
)
```

For explicit lifetime management, iterate `watch_workflow_run(...)` and close
the generator in the worker's `finally` block. Do not close a Python generator
concurrently from a UI thread while it is executing.

## Configuration Wizard and Tkinter

In MAUI, open **GitHub Actions** from the navigation menu. In Tkinter's Quick
setup menu, choose **GitHub Actions - watch exact run**. Paste the exact GitHub run
URL, or enter its repository and run ID, then start watching. These views do not
automatically attach a local deployment-job UUID to a GitHub run. Display the
workflow status and conclusion separately from
connection health. **Open in GitHub** opens the verified run URL so the user can
inspect jobs, annotations, and logs.

The Windows MAUI consumer applies asynchronous updates through its UI dispatcher.
Tkinter uses a background subscription and a queued handoff through its main
event loop. Neither consumer should perform blocking GitHub requests on the UI
thread. Changing scope or leaving the view must cancel the obsolete subscription
and ignore its late callbacks.

## ITSM processing example

For an incident/change-management integration:

1. Associate the approved change record with the exact repository, run ID, and
   expected deployment scope.
2. Subscribe and persist each processed event cursor.
3. Update progress for the observed states. Treat duplicate deliveries
   idempotently; do not create another incident for the same run attempt/event.
4. On `completed`, record that attempt's observed `conclusion`. Before declaring
   the current change finished, consume replay and confirm the current healthy
   run state; an older successful attempt must not hide a newer rerun or
   monitoring error. Link the GitHub run rather than copying secrets or whole
   deployment logs into the ticket.
5. On `monitor_error`, flag observation as unavailable. Do not mark the change
   failed, restart the workflow, or release deployment locks based on that event.

Monitoring does not execute an ITSM change automatically. Any outbound ticket
updates, approvals, cancellations, or reruns require their own authorization and
integration logic.

## Delivery and reliability boundaries

- Observations are periodic, not instant. GitHub throttling and transient network
  failures can delay updates; the monitor honors backoff rather than increasing
  polling when more clients connect.
- Persisted state and event cursors support reconnect/restart recovery. Delivery
  is not an exactly-once distributed transaction; consumers must deduplicate.
- The stream reports run-level state. Downloading job logs, live terminal
  streaming, Azure resource health, and job/step-level subscriptions are separate
  capabilities.
- Read-only monitoring never retries a deployment. A lost connection is not
  evidence that dispatch failed.

## Source and release locations

The purple repository carries the shared monitor in
`bootstrap/lib/workflow_run_monitor.py`, CLI/SDK support under
`environment_setup/azurefactory-cli`, tests, and this document on both `main`
and `release/v.1.25`.

The canonical HTTP API and Tkinter integration are in the separate
`008_aifactory_admin_ux_tkinter` repository. MAUI and its typed client live in
`ESAIF.ConfigWizard` and `ESAIF.DomainLayer`. Updating only a purple submodule does
not update an already running or previously packaged desktop/API binary:
consumers need the matching API build. An old API returning 404 is an upgrade
requirement, not a successful subscription.

## Tests

From either purple branch checkout, using the repository's existing Python test
environment:

```powershell
python -m pytest environment_setup\unit-tests\test-bicep\unit\test_workflow_run_monitor.py -q
python -m pytest environment_setup\azurefactory-cli\tests\test_workflow_events.py -q
```

The tests inject GitHub responses instead of calling GitHub. They cover observed
transitions, shared reads, initial unavailability, scoped cursor replay, reruns,
rate limiting, persistence, cancellation, and stale completion history.
The canonical API repository additionally has `tests/test_workflow_runs.py`
and `tests/test_workflow_run_ui.py`; the Domain/MAUI repositories have dedicated
workflow client and ViewModel tests. These are not live deployment tests.

## References

- [GitHub webhook events: workflow_run](https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run)
- [GitHub webhook events: workflow_job](https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_job)
- [GitHub REST API: workflow runs](https://docs.github.com/en/rest/actions/workflow-runs)
- [GitHub CLI: gh run watch](https://cli.github.com/manual/gh_run_watch)