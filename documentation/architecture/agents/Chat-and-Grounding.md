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
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_realtime.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_settings.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/speech.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/voice.js
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
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_speech.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_frontend.py
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

Native live transcripts and audio are explicitly provisional. Only completed, citation-validated replies enter the authoritative answer card. An unsupported (invented) citation ID, a denied tool or tool-round exhaustion stops the turn; already played speech cannot be recalled. Because a speech model rarely says `[S1]` aloud, `finish(..., spoken=True)` accepts a spoken reply that omits the markers and publishes it with the retrieved sources attached (`citation_validation: sources_attached`); typed answers still must cite. As in typed chat, a failed read tool (`ok: false`) is returned to the model as data and logged as `voice_tool_failed` with only its tool name and error code. Citation validation still does not establish semantic entailment. Readiness, transcription, Search/embedding, optional graph, network and tools still contribute latency. A first-relayed-audio histogram/log records end-of-speech latency without transcript/token content; live deployment and browser playback measurements remain separate requirements.

Client-created context and tool-output item IDs are at most 32 characters, including their ownership prefix. Live Voice Live validation enforces this limit even where the published schema omits it. Provider rejection diagnostics log only bounded code/parameter labels, never the raw provider message, transcripts, credentials or event payload.

Unsupported native capabilities, upstream authentication/protocol rejection and failed native responses terminate voice and preserve typed chat. There is no automatic mode/model downgrade or ungrounded generation fallback, and no request for service secrets or extra consent. Native failure telemetry records server-owned error codes only, not service messages or transcripts.

The browser never receives Foundry credentials: it connects to the application's relay, which holds the managed-identity connection to Voice Live. The Entra access token travels in the first WebSocket frame (never a URL), is validated by `principal_from_token` and `authorize`, and bounds the session so it ends no later than token expiry. Origin, pre-authentication, concurrency, audio-rate, idle and maximum-duration limits are enforced by the relay; the browser cannot choose the model, voice, instructions or tools. A transcript or spoken text is user input or evidence, never authorization. Audio is not stored; tokens and transcripts are not logged.

An optional hello `language` selects only a configured server-owned BCP-47 locale profile, not an English/Swedish-only list; arbitrary voice/model/instructions/tools fields remain forbidden. Native transcription uses `gpt-4o-mini-transcribe` with the locale's base language code, and native profiles use `server_vad`. Operators verify model-specific input and voice output support separately. The browser closes/reopens voice when language changes, retaining the authenticated text session. Voice-only status/auth/transport failures release audio but never clear or reacquire the text token. Explicit typed-chat fallback copies an utterance only on user request, without submitting it. Canceled tools cannot resume an old turn; in-flight synchronous read workers may finish but are never replayed or allowed to approve/execute writes. Native completion rechecks the current exact-scope knowledge grant before publishing an authoritative answer.

`host=esaif-maui` stays text-only by default. An explicit `voice=on` embedded page may enable native voice only when the authenticated status declares `mode: realtime`, relay `protocol: 1` and `embedded_voice_version: 1`. Speech-shell and incompatible deployments remain text-only. The page requests a microphone only on Start talking; the compatible desktop host must independently enforce exact-origin permission and current document binding. This backend capability is not proof that an installed desktop build implements it. `voice=off` always denies microphone use.

Live voice needs Cognitive Services User and Foundry User on the project Foundry account (assigned from `infra/voice-roles.bicep` only when voice is enabled) and private reachability of the account's `services.ai.azure.com` endpoint from the application. Offline tests with fake backends, mutation checks of the relay's safety properties and real-browser runs cover the relay and UI. A live Voice Live session in a tenant is a separate observation (region, DNS, roles); passing tests do not establish it.

## Separation of operations

Repository packaging, cloud deployment, ingestion, model inference and configuration/runtime actions are distinct. The knowledge refresh can create owned retrieval resources and make embedding calls; ordinary source/graph generation must not invoke it. Private web sign-in and scope grants remain necessary even when the server is reachable.

Graph-enhanced context is implemented locally through `GraphQueryService` and the shared `DualGraphStore`. Architecture/code questions can request bounded combined context; exact `graph.read` and configured corpus scope remain required. Structural/architecture citations stay distinct from repository Search citations. Missing evidence planes and stale/unverified source are surfaced as degraded context; graph results neither replace textual provenance nor establish complete runtime dependencies. Read [[dual-graph-lifecycle]] for verified local commands and release/deployment caveats; [[ADR-001-Dual-Graph]] remains proposed.

See [[Agent-Factory]], [[Retrieval-Provenance]], [[Reviewed-Operations]], [[Trust-and-Authorization]], [[Packaging-and-Release]] and [[Index]].

Authority: [application guide and model/grounding contracts](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
