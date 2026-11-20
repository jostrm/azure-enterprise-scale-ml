---
id: chat-and-grounding
status: observed
sources:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/tools.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/costs.py
  - usecase_code/40-agent-factory/agent_factory/factory_chat_agent.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/knowledge.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/web.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/browser_auth.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/app.js
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_realtime.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_delegated.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_settings.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/speech.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/teams_meeting_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/teams_meeting_settings.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/teams-meeting.js
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/voice.js
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/esaif-maui-layout-loader.js
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/esaif-maui-layout.js
tests:
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_conversation.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_costs.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_knowledge.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_browser_auth.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_web.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_graph_integration.py
  - usecase_code/40-agent-factory/tests/test_factory_chat_agent.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_session.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_realtime.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_delegated.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_delegated_transcript.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_speech.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_frontend.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_teams_meeting_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_teams_meeting_frontend.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_companion.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py::class:Conversation
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py::function:Conversation.answer
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/tools.py::function:FactoryTools.execute
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/costs.py::class:CostSkills
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/costs.py::function:CostSkills._billing
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py::class:GraphQueryService
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice.py::class:VoiceSession
reviewed_source: '66f7ea35 + native voice working tree; observed 2026-10-11; no native live deployment asserted'
---
# Chat and grounding

## Default browser presentation

The application root serves the bundled three-panel companion by default over
HTTPS or loopback HTTP. `layout=companion` is no longer required;
`layout=legacy` explicitly retains the original interface. Frames and unknown
host modes do not acquire companion host integration. The embedded MAUI mode
still requires its HTTPS host marker and WebView message channel.

The presentation Adapter moves original DOM nodes, retaining authentication,
voice, scope/view handlers and action confirmations. It renders Gray, neutral
Purple, and Blue / Yellow themes, a pending-answer sweep, and local-only message
feedback/copy/display deletion. It does not call inference, capture audio,
acquire tokens, submit feedback to a service or mutate operation history.
`test_companion.py` covers bare-root wiring, static asset delivery, origin/host
guards and the current template's DOM contract. Source parity does not prove a
deployed Container App revision; live rollout is a separate observation.

## Browser session continuity (source observation, 2026-11-18)

Access tokens remain in memory. After the API validates the browser principal,
tab-scoped session storage retains only a versioned digest of the principal and
configured public client/audience. A reload with that marker starts a fresh PKCE
authorization with `prompt=none`, reusing the Entra browser session when policy
allows. The returned `/api/context` identity must match before the restored
session is exposed to the UI or additional API reads begin.

Explicit sign-out removes the marker. Missing/corrupt markers, account changes,
consent or account-selection requirements, and recovery failures leave the page
signed out without a redirect loop. No access/refresh token, email or raw object
ID is persisted. This is not a promise of indefinite login: conditional access
and Entra session expiry may require interaction. The embedded MAUI token bridge
retains its existing independent lifecycle. `test_web.py` exercises these paths
with controlled Entra/API responses; source coverage does not prove deployment.

## Observed baseline flow

1. Authenticate the user, validate configured tenant/audience/client and require a current exact-scope `knowledge.read` grant.
2. Pin a verified complete, reconciled and nonempty committed knowledge snapshot before inference. A blocked, failed, in-progress or stale refresh can use the last successful snapshot with its committed timestamp and explicit freshness warning; ownership/schema mismatch or uncertain legacy writes remain unavailable.
3. Retrieve scope-filtered source chunks and assign server-owned citation identifiers.
4. Send the question and evidence as untrusted data to the configured Foundry model/agent.
5. Intersect canonical read-tool definitions with available backend descriptors; validate arguments and reauthorize each call.
6. Bound tool rounds, require a completed answer, and reject unsupported citation IDs or omission of available citations.

Citation validation prevents invented identifiers; it is not a proof that every sentence is entailed by a cited passage. Responses still need evidence-aware interpretation, especially for dated release notes and incomplete coverage.

Changed refreshes stage an isolated owned Search generation and promote the manifest only after complete fingerprint, scope, ownership, schema and bounded visibility checks. Retrieval and knowledge-status tools use the same answer-local pin, so concurrent promotion cannot mix snapshots. See [[Retrieval-Provenance]] for separately approved generation permissions and retention/capacity maintenance. This source behavior does not establish cloud rollout.

The injected model gateway supports existing project-reference and dedicated agent-endpoint modes. Endpoint invocation uses a narrower consumption permission; model inference permission alone does not establish agent-endpoint invocation rights. Version routing is a separately configured operation, not changed by asking a question.

The app and opt-in project pipeline reuse the canonical prompt definition in
`agent_factory.factory_chat_agent`. Its instructions preserve graph-evidence
citations and freshness limitations. The app appends `graph_query` only when
dual-graph configuration is present, before hashing the deployment definition;
the shared pipeline definition does not enable graph access by itself.

## Selected-project cost observations

Cost path source reviewed against main revision `99e6fb1c` on 2026-10-14;
this is not an observation of a deployed agent or live Azure billing.

`POST /api/chat` binds the authenticated caller to a configured scope.
`Conversation.answer` supplies that `active_scope`, retrieves explanatory
knowledge and dispatches permitted read-only model function calls.
`cost_monthly_project_forecast` flows through `FactoryTools.execute` to
`CostSkills.execute`, which requires both `factory.read` and `cost.read` and
checks the exact configured project RG. Chat additionally needs `knowledge.read`
and knowledge readiness. The scope's subscription is not a model argument.

`CostSkills._billing` obtains an ARM token through the configured credential and
POSTs directly to RG-scoped `Microsoft.CostManagement/query` and `/forecast`
(`2025-03-01`). No Factory HTTP API or dashboard scraping is involved.
ActualCost is summed daily by service for MTD; the full-month forecast includes
its own actual component and must not be added to the separate MTD total.
Results return to the model as `function_call_output`. The authenticated skill
panel's `/api/skills/{skill_name}/run` calls the same cost adapter directly.

On-demand reads are not instantaneous billing: observation time, posted actual
cutoff and billing lag are separate evidence. Currency partitions are retained,
and missing actual/forecast data, access failures or incomplete pagination do not
become zero or synthetic estimates. Azure execution-identity RBAC and application
caller grants are independent. Common-RG cost reads require an explicit allowlist;
default-template idle estimates use a pinned template and public retail prices,
not applied settings or measured inactivity.

These tools return cost reports, not embedded Portal blades or arbitrary
dashboard telemetry. Search/graph evidence explains implementation but does not
establish spend. See the
[dashboard and cost question walkthrough](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md#ask-about-azure-dashboards-and-current-project-costs).

## Optional live voice (compatibility shell and native realtime)

When `voice.enabled` is set, the application registers `GET /api/voice/status` and `WS /api/voice/ws`; otherwise neither route exists. In the compatibility shell, Azure Voice Live is used only for speech to text, turn detection, noise suppression, echo cancellation and text to speech. The session is configured server side with `create_response` off, so the speech service never writes an answer. Each final transcript is answered by the same `Conversation.answer` call as a typed question (same exact-scope `knowledge.read` grant, readiness checks, retrieval, tools and citations). The answer is shown on the page and a shortened rendition from `speech.spoken_text` (no citation markers, links, code or long tables) is spoken.

That flow remains the default `voice.mode: speech_shell`, not a native speech-to-speech latency claim. Opt-in `realtime` uses Voice Live `gpt-realtime-mini`/`gpt-realtime` directly with incoming audio and server-triggered native response/audio streaming. `Conversation.prepare` extracts the shared governed readiness, retrieval, canonical read-tool intersection, per-call authorization/argument validation/audit and final citation checks; typed `Conversation.answer` uses that same prepared turn and retains the existing model gateway/reference. Native voice never invokes the external full-answer gateway or sends an answer as predefined TTS. VAD automatic response creation stays off to gate response creation on evidence readiness. Native output uses configured OpenAI voices; optionally Azure-standard voices select Azure synthesis within Voice Live, not model-native audio.

Native live transcripts and audio are explicitly provisional. Only completed, citation-validated replies enter the authoritative answer card. A reply that ends `incomplete` because it reached the 4096-token output cap (model-native audio tokens count toward it) is a reply too: the speech already relayed keeps playing and the validated text is published with `spoken_truncated: true`. Any other non-completed response stops the turn, and `voice_response_not_completed` logs its status, bounded reason label and output-token count, never the transcript. An unsupported (invented) citation ID, a denied tool or tool-round exhaustion stops the turn; already played speech cannot be recalled. Because a speech model rarely says `[S1]` aloud, `finish(..., spoken=True)` accepts a spoken reply that omits the markers and publishes it with the retrieved sources attached (`citation_validation: sources_attached`); typed answers still must cite. As in typed chat, a failed read tool (`ok: false`) is returned to the model as data and logged as `voice_tool_failed` with only its tool name and error code. Citation validation still does not establish semantic entailment. Readiness, transcription, Search/embedding, optional graph, network and tools still contribute latency. A first-relayed-audio histogram/log records end-of-speech latency without transcript/token content; live deployment and browser playback measurements remain separate requirements.

Barge-in is owned by the relay, and the server never interrupts or answers on its own (`interrupt_response` and `create_response` stay off). Native speech is generated faster than real time, so the relay estimates browser playback from the PCM16 audio it relayed (bytes / 48,000 per second against wall clock, plus a 0.5 s margin). When `speech_started` arrives before that estimate expires, the relay sends `interrupted`, even after `response.done`, and the browser flushes its playback queue. There is no `conversation.item.truncate` and no `auto_truncate`, which would require server-side interruption. The next grounded turn deletes every earlier item, including the interrupted answer, and waits for the deletions to be acknowledged before `response.create`. The model therefore never carries unheard speech forward. Native tool calls start at `response.output_item.done`, before the response finishes, and independent calls run concurrently. Exactly-once execution, per-call authorization/audit, the round limit and barge-in cancellation are unchanged. Outputs are created only after `response.done` has listed the response. Grounding before speech is measured as `aifactory.voice.grounding.duration` and the `voice_grounding_ready` log.

Client-created context and tool-output item IDs are at most 32 characters, including their ownership prefix. Live Voice Live validation enforces this limit even where the published schema omits it. Provider rejection diagnostics log only bounded code/parameter labels, never the raw provider message, transcripts, credentials or event payload.

Unsupported native capabilities, upstream authentication/protocol rejection and failed native responses terminate voice and preserve typed chat. There is no automatic mode/model downgrade or ungrounded generation fallback, and no request for service secrets or extra consent. Native failure telemetry records server-owned error codes only, not service messages or transcripts.

The browser never receives Foundry credentials: it connects to the application's relay, which holds the managed-identity connection to Voice Live. The Entra access token travels in the first WebSocket frame (never a URL), is validated by `principal_from_token` and `authorize`, and bounds the session so it ends no later than token expiry. Origin, pre-authentication, concurrency, audio-rate, idle and maximum-duration limits are enforced by the relay; the browser cannot choose the model, voice, instructions or tools. A transcript or spoken text is user input or evidence, never authorization. Audio is not stored; tokens and transcripts are not logged.

An optional hello `language` selects only a configured server-owned BCP-47 locale profile, not an English/Swedish-only list; arbitrary voice/model/instructions/tools fields remain forbidden. Native transcription uses `gpt-4o-mini-transcribe` with the locale's base language code, and native profiles use `server_vad`. With the opt-in realtime `voice.multilingual`, transcription omits the language (auto-detect) and the model replies in the user's language. `input_languages` may then list several hints, the first being the fallback. Turn detection becomes `azure_semantic_vad_multilingual` unless the operator keeps `server_vad`. A selected profile then chooses only the voice, greeting and fallback language. Without the opt-in, behaviour is unchanged. Operators verify model-specific input and voice output support separately. The browser closes/reopens voice when language changes, retaining the authenticated text session. Voice-only status/auth/transport failures release audio but never clear or reacquire the text token. Explicit typed-chat fallback copies an utterance only on user request, without submitting it. Canceled tools cannot resume an old turn; in-flight synchronous read workers may finish but are never replayed or allowed to approve/execute writes. Native completion rechecks the current exact-scope knowledge grant before publishing an authoritative answer.

`host=esaif-maui` stays text-only by default. An explicit `voice=on` embedded page may enable native voice only when the authenticated status declares `mode: realtime`, relay `protocol: 1` and `embedded_voice_version: 1`. Speech-shell and incompatible deployments remain text-only. The page requests a microphone only on Start talking; the compatible desktop host must independently enforce exact-origin permission and current document binding. This backend capability is not proof that an installed desktop build implements it. `voice=off` always denies microphone use.

Live voice needs Cognitive Services User and Foundry User on the project Foundry account (assigned from `infra/voice-roles.bicep` only when voice is enabled) and private reachability of the account's `services.ai.azure.com` endpoint from the application. Offline tests with fake backends, mutation checks of the relay's safety properties and real-browser runs cover the relay and UI. A live Voice Live session in a tenant is a separate observation (region, DNS, roles); passing tests do not establish it.

## Attended Teams media pilot (source observation, 2026-11-18)

The existing Spider browser deployment was observed on 2026-11-20 using direct
Voice Live `delegated` mode with transcript-triggered `Conversation.answer`.
Its deployed voice modules matched the committed consumer implementation; the
shared source now preserves that mode instead of downgrading an existing
deployment. `model_tool` first forces `ask_specialist`; `transcript` invokes the
same authenticated specialist directly. Both keep the authoritative answer and
citations in the governed backend and treat native spoken rephrasing as
provisional. This is not a managed Voice Agent hosted conversation engine.
The browser retains device-timestamp playback receipts; the Teams sender does
not claim remote hearing from local render progress. It validates metadata/PCM
framing, discards metadata across provider resets and conservatively leaves
remote-playback positions unacknowledged.

An opt-in ACS browser Adapter joins a Teams meeting as a visibly named external
AI participant. Remote meeting audio is forwarded to the existing authenticated
voice relay; relay output feeds an ACS custom local audio stream, not the
operator's microphone or browser speakers. It reuses `Conversation.answer` or
`Conversation.prepare`, not a separately privileged reasoning implementation.
On 2026-11-20 the authorized Spider project001 test established visible meeting
participation, non-silent inbound PCM, one governed backend answer and a
participant-confirmed clearly audible response inside Teams. This does not
establish full lifecycle acceptance, latency targets or the managed Voice Agent
hosted-conversation-engine path. No meeting media/transcript is stored as evidence.
The test reported delayed self-monitoring; the ACS local speaker is now explicitly
muted with `muteIncomingAudio`, while raw input capture and outgoing replies
remain separate. The participant subsequently confirmed the delayed self-audio
was gone.

Admission binds an explicitly approved host, exact meeting URL, scope, explanation
audience and expiry to a one-use opaque voice ticket. The derived principal has
only the scope's `knowledge.read`; canonical read-tool permission filtering and
per-call authorization enforce that restriction. In the default same-tenant
policy, approved listener grants are rechecked. An external meeting requires
an explicit `meeting_tenant_id`, exact independently verified audience IDs and
`external_audience_disclosure_approved`; this approves disclosure in that meeting,
not backend sign-in or general app access. The original host's grant is always
required. Scope-wide meeting-safe disclosure approval remains mandatory.

The browser checks a small approved meeting-tenant roster and endpoint set, refuses
unknown/anonymous participants, and leaves on changes or uncertainty. This
client-side observation is not cryptographic listener authentication; the pilot
also requires controlled admission and content safe for all approved attendees.
Meeting tenant and disclosure mode are pinned with the session; changing either
invalidates authorization and cannot be bypassed by resetting voice.
Pause before admitting anyone because already-transmitted audio cannot be recalled.
Teams recording/transcription or additional consent requirements stop this
no-recording pilot; the application does not grant recording consent.

Mute suppresses new capture/output and rotates a generation-bound one-use voice
ticket. Resume opens a fresh provider connection; delayed input/output from the
old connection cannot enter the new turn. Stop speaking also replaces the voice
session while retaining the ACS participant. A local `pong` is not a provider-input
drain guarantee. Old-session cleanup cannot revoke a newer generation, and reset
never extends admission expiry. Leave tears down media immediately while
server/ACS cleanup reports its separate outcome. The browser never uses
`stopAudio()`, which would select the default microphone. Echo protection is
half-duplex by default. Explicit `full_duplex` admission allows remote capture
during playback so upstream speech detection can interrupt; it does not mix
the assistant's outgoing media into its input. An optional meeting-only realtime
profile uses the shared `Conversation.prepare` path instead of serial
`Conversation.answer` plus voice presentation, without changing browser defaults
or permissions. Both settings are server-owned and pinned to the meeting session;
changing them invalidates the session. Human-perceived full-duplex behavior
remains separate live evidence. Reconnect requires a fresh
explicit join. Single-replica/single-worker deployment is mandatory because
tickets and cleanup ownership are process-local.

Synthetic live relay observations on 2026-11-20 (not another Teams meeting)
measured speech-end-to-first-audio at 16.84/11.99 s for inherited delegated mode
and 6.87/6.37 s for the native meeting profile. Both native turns completed with
exact-scope source citations; grounding remained about 5.17 s in the inspected
turn. Overlapping generated speech produced an interruption acknowledgement in
513 ms and no subsequent audio during that input; a later run acknowledged in
495 ms and completed a replacement grounded answer. Additional first-audio
samples included an 11.65 s outlier, so latency remains variable rather than
consistently near-instant. These bounded samples do not
establish end-user latency or remote playback cancellation; no microphone or
meeting recording was used.

The PG's managed Voice Agent hosted-conversation-engine path is a separate
integration, not implied by this ACS transport or the existing Voice Live relay.
No Windows media host or Teams-native app package is required for this attended
external participant; unattended Graph media uses a different adapter.

## Separation of operations

Repository packaging, cloud deployment, ingestion, model inference and configuration/runtime actions are distinct. The knowledge refresh can create owned retrieval resources and make embedding calls; ordinary source/graph generation must not invoke it. Private web sign-in and scope grants remain necessary even when the server is reachable.

Graph-enhanced context is implemented locally through `GraphQueryService` and the shared `DualGraphStore`. Architecture/code questions can request bounded combined context; exact `graph.read` and configured corpus scope remain required. Structural/architecture citations stay distinct from repository Search citations. Missing evidence planes and stale/unverified source are surfaced as degraded context; graph results neither replace textual provenance nor establish complete runtime dependencies. Read [[dual-graph-lifecycle]] for verified local commands and release/deployment caveats; [[ADR-001-Dual-Graph]] remains proposed.

See [[Agent-Factory]], [[Retrieval-Provenance]], [[Reviewed-Operations]], [[Trust-and-Authorization]], [[Packaging-and-Release]] and [[Index]].

Authority: [application guide and model/grounding contracts](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
