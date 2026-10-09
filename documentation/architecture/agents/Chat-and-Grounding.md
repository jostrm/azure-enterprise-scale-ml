---
id: chat-and-grounding
status: observed
sources:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py
  - usecase_code/40-agent-factory/agent_factory/factory_chat_agent.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/knowledge.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/security.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/web.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/browser_auth.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice_settings.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/speech.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/static/voice.js
tests:
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_conversation.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_knowledge.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_browser_auth.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_web.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_graph_integration.py
  - usecase_code/40-agent-factory/tests/test_factory_chat_agent.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_routes.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_session.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_speech.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_voice_frontend.py
graph_symbols:
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py::class:Conversation
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/foundry.py::function:Conversation.answer
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/graph_service.py::class:GraphQueryService
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/voice.py::class:VoiceSession
reviewed_source: '3e9102ee + working tree; observed 2026-10-07; live voice observed 2026-10-09 at 29642909'
---
# Chat and grounding

## Observed baseline flow

1. Authenticate the user, validate configured tenant/audience/client and require a current exact-scope `knowledge.read` grant.
2. Require ready, fresh, reconciled and nonempty knowledge state before inference.
3. Retrieve scope-filtered source chunks and assign server-owned citation identifiers.
4. Send the question and evidence as untrusted data to the configured Foundry model/agent.
5. Intersect canonical read-tool definitions with available backend descriptors; validate arguments and reauthorize each call.
6. Bound tool rounds, require a completed answer, and reject unsupported citation IDs or omission of available citations.

Citation validation prevents invented identifiers; it is not a proof that every sentence is entailed by a cited passage. Responses still need evidence-aware interpretation, especially for dated release notes and incomplete coverage.

The injected model gateway supports existing project-reference and dedicated agent-endpoint modes. Endpoint invocation uses a narrower consumption permission; model inference permission alone does not establish agent-endpoint invocation rights. Version routing is a separately configured operation, not changed by asking a question.

The app and opt-in project pipeline reuse the canonical prompt definition in
`agent_factory.factory_chat_agent`. Its instructions preserve graph-evidence
citations and freshness limitations. The app appends `graph_query` only when
dual-graph configuration is present, before hashing the deployment definition;
the shared pipeline definition does not enable graph access by itself.

## Optional live voice (speech shell)

When `voice.enabled` is set, the application registers `GET /api/voice/status` and `WS /api/voice/ws`; otherwise neither route exists. Azure Voice Live is used only for speech to text, turn detection, noise suppression, echo cancellation and text to speech. The session is configured server side with `create_response` off, so the speech service never writes an answer. Each final transcript is answered by the same `Conversation.answer` call as a typed question (same exact-scope `knowledge.read` grant, readiness checks, retrieval, tools and citations). The answer is shown on the page and a shortened rendition from `speech.spoken_text` (no citation markers, links, code or long tables) is spoken.

The browser never receives Foundry credentials: it connects to the application's relay, which holds the managed-identity connection to Voice Live. The Entra access token travels in the first WebSocket frame (never a URL), is validated by `principal_from_token` and `authorize`, and bounds the session so it ends no later than token expiry. Origin, pre-authentication, concurrency, audio-rate, idle and maximum-duration limits are enforced by the relay; the browser cannot choose the model, voice, instructions or tools. A transcript or spoken text is user input or evidence, never authorization. Audio is not stored; tokens and transcripts are not logged.

Live voice needs Cognitive Services User and Foundry User on the project Foundry account (assigned from `infra/voice-roles.bicep` only when voice is enabled) and private reachability of the account's `services.ai.azure.com` endpoint from the application. Offline tests with fake backends, mutation checks of the relay's safety properties and real-browser runs cover the relay and UI. A live Voice Live session in a tenant is a separate observation (region, DNS, roles); passing tests do not establish it.

## Separation of operations

Repository packaging, cloud deployment, ingestion, model inference and configuration/runtime actions are distinct. The knowledge refresh can create owned retrieval resources and make embedding calls; ordinary source/graph generation must not invoke it. Private web sign-in and scope grants remain necessary even when the server is reachable.

Graph-enhanced context is implemented locally through `GraphQueryService` and the shared `DualGraphStore`. Architecture/code questions can request bounded combined context; exact `graph.read` and configured corpus scope remain required. Structural/architecture citations stay distinct from repository Search citations. Missing evidence planes and stale/unverified source are surfaced as degraded context; graph results neither replace textual provenance nor establish complete runtime dependencies. Read [[dual-graph-lifecycle]] for verified local commands and release/deployment caveats; [[ADR-001-Dual-Graph]] remains proposed.

See [[Agent-Factory]], [[Retrieval-Provenance]], [[Reviewed-Operations]], [[Trust-and-Authorization]], [[Packaging-and-Release]] and [[Index]].

Authority: [application guide and model/grounding contracts](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
