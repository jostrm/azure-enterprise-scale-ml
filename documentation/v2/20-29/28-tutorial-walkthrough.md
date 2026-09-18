# AI Factory tutorial — Take2: UX first, version 1.25+

**Delivery status (18 September 2026): Part 1 video, 13 chapter snippets and the 23-slide PowerPoint with four embedded clips are delivered. The full deployment tutorial is not complete.** Part 1 is **10:30.69** (rounded **10:31**), with 13 fresh recorded chapters, local English narration, timed subtitles, native tutor highlighting and real read-only API/CLI commands. The intended **25–35 minutes** still describes the complete three-phase film, not this foundation part. Quoted deployment outcome lines below remain gated by actual evidence.

Start in the maximized Windows MAUI app, with **Tutorial Mode checked**, and open the existing orange **`azurefactory`** folder. Follow one registered-layout workflow throughout. Explicitly choose **1.25** wherever this walkthrough requests a version; use a later supported release only after separately validating its contracts. Do not leave a picker at its default, use `main` as a release, or suggest that selecting a version upgrades a checkout or deployed resources.

**Watch in this order:** orientation and every menu view → project001 Function and project003 in Dev001 → regional expansion → configuration clone → corresponding CLI/API lab → verified outcomes. No terminal detours during the UX scenarios.

- [Workflow and UX changes](#take2-workflow-and-ux-changes)
- [Part 1 media and chapter index](#take2-part-1-media-and-chapter-index)
- [Producer-only readiness gate](#take2-producer-only-readiness-gate)
- [Director and teacher screenplay](#take2-director-and-teacher-screenplay)
- [CLI/API correspondence and guarded sample](#take2-cliapi-correspondence-and-guarded-sample)
- [Production and delivery plan](#take2-production-and-delivery-plan)
- [Preserved original walkthrough](#preserved-original-walkthrough)

Installation/reference: [Windows MAUI setup](../../../environment_setup/install_config_wizard/maui/readme.md), [end-to-end setup](24-end-2-end-setup.md), [SDK/CLI](../../../environment_setup/azurefactory-cli/readme.md), [API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md). The separate [FinOps monitoring tutorial](tutorial-fiops.md) remains a companion, not a prerequisite scene.

## Take2 Part 1 media and chapter index

Part 1 covers the improved desktop interface first, followed by real REST health, CLI health and ADO/GitHub launcher-capability commands. The command under discussion is highlighted in the terminal and enlarged in a labeled editorial callout. Native tutorial read-aloud has its own uninterrupted demonstration. Guidance is paused after that demonstration rather than showing an unrelated tutorial step throughout the menu tour.

Files are relative to the user's delivered `tutorial` folder, **not** this repository:

```text
video\take2\AI Factory tutorial - Take2 - Part 1.mp4
video\take2\AI Factory tutorial - Take2 - Part 1.srt
video\take2\AI Factory tutorial - Take2 - Part 1.chapters.json
video\take2\originals\                         full original takes, including preserved superseded attempts
video\snippets-take2\Take2-Part1-*.mp4         13 edited chapter clips, each with its own SRT
image-screenshots\maui-take2\take2-new-*.png   26 accepted new screenshots, plus preserved retakes
ppt\maui-take2\AI Factory tutorial - Take2 - Part 1.pptx
```

The 23-slide deck includes four embedded H.264/AAC clips, actual narration in speaker notes, chapter references, a relative full-video link, and one explicit next-lab roadmap. Keep the `tutorial` directory structure together for the full-video link. Embedded clips are self-contained and are intended for desktop PowerPoint Slide Show.

| Start | Chapter |
|---|---|
| 00:00 | Open the orange factory and use the tutor |
| 01:26 | Find settings without losing your place |
| 02:33 | Select scope before choosing an operation |
| 03:12 | Existing-factory work or a new quickstart |
| 03:45 | Full bootstrap: configure, review, run |
| 04:33 | Monitoring by question and source |
| 05:18 | Agent and model map |
| 05:53 | Portfolio and individual factory views |
| 06:34 | Projects and scale sets |
| 07:12 | Concept animations |
| 07:46 | Tickets, API connection, appearance and About |
| 08:42 | Actual read-only API and CLI commands |
| 09:46 | Next-lab roadmap |

The edited video is 2560 x 1440, H.264/AAC, with captions outside the full native window. Clip timing is retained; no whole-chapter speed changes are used. Simple Mode explicitly shows 1.25 in the accepted retake. Its account labels are editorially masked in the edited video and deck derivatives; original user-owned captures remain unchanged.

Production evidence covers complete media decoding, audio presence, measured cue bounds, native PowerPoint rendering, package/embedded-media consistency, and independent rendered-slide inspection. It does not claim a continuous human watch-and-listen review of the entire film.

**Still to record:** the real project001 Function update, project003 deployment, Germany West Central dedicated-subscription scenario, intentionally undeployed configuration clone, and corresponding execution CLI/API workflows. Part 1 does not claim those operations occurred. Project001's Function remains absent and project003's canonical resource group was absent in the latest exact-scope readiness evidence; the recorded draft is not a substitute for deployment.

**Continuation (18 September):** the owner supplied the Germany subscription and tenant, and the subscription is enabled in that tenant. They are also the existing Sweden subscription and tenant, so reusing them must not be presented as dedicated-subscription isolation. A native **configuration-only** review succeeded for a separate Germany West Central factory, explicit release **1.25**, Dev suffix **002**, and a proposed **`172.17.0.0/20`** network with capacity **one**. The range does not overlap the registered Sweden ranges or the VNets observed in the supplied subscription; this is not an organizational IPAM or peering approval. The review remains **unconfirmed**, with no Germany factory/project saved or Azure deployment started. Keep actual subscription/tenant IDs in private operator material, not this public guide.

## Take2 workflow and UX changes

The learning model is **select scope → inspect configuration → review an exact operation → explicitly confirm once → verify its result**. Saving configuration and deploying it are separate operations. Tutorial Mode is guidance over the real application, not a sandbox or an AI chatbot.

| Status | Change | What the manuscript can show |
|---|---|---|
| Implemented in the revised source/build work; verify the installed recording build | Bundled API payload/startup and stale ephemeral-port recovery repaired; explicit connection failure/recovery | Healthy local API independently of the selected folder, backend choice, and Azure sign-in. A healthy API does not establish Azure/ADO readiness. |
| Implemented | Centered 42px action buttons and progressive disclosure in catalog, projects, scale sets, Simple Mode, and bootstrap | A clear primary action with advanced details opened deliberately. Consent, warnings, exact scopes, and review controls remain present. |
| Implemented in the continuation build | Catalog saved-release guidance follows the actual version field immediately | Selecting 1.25 no longer leaves a stale "release 124" explanation. Blank new-factory input requests an explicit release; blank clone input retains source inheritance. Saving a release is not described as deploying or upgrading Azure. |
| Implemented | Full bootstrap now starts with a provider choice and grouped destination/team fields; network and source options expand on demand | A page-level **Setup details** button uses the existing selectable details viewer. Static notes are neutral; actual blockers remain visible and still prevent starting. |
| Implemented | **Copy common details** explicitly copies account/team defaults into the separate new-factory draft | The new destination, project, networking and resource settings are not copied. API/CLI `mapping_mode=common-details` returns a partial configuration to merge; strict conversion remains available. Existing UAMI, self-hosted runner and ADO-tenant inputs now reach the reviewed launcher. |
| Implemented | Tutorial current step/progress pinned; history and read-only console compactly disclosed | The supported configuration tutorial remains legible instead of leaving an obsolete step in view. Verification still requires explicit action. |
| Implemented | Optional **local Windows read-aloud**, awaited sentence highlighting, Replay and Stop; playback cancellation on pause/unload/scenario change | Default silent behavior, then one deliberate read-aloud demonstration. No cloud speech service and no automatic advancement. |
| Preserved | Agent/model map, AI Factories, AI Factory, and Concept animations | Keep these strong explanatory views; retain honest sample/live/source labels. |
| Production design / proposed app enhancement, **not implemented app-wide** | A current-phase tutorial for catalog, deployment, regional expansion, clone, and terminal; command-editor selection synchronized to narration | Use clearly editorial phase cards and manual command selections. Pause/hide unrelated native tutorial guidance. Do not draw fake native progress or imply the editor follows speech automatically. |
| Implemented navigation; unified operation engine still proposed | Simple Mode starts with **Work with an existing factory**, with a direct catalog shortcut before new-factory creation | New-factory creation remains **GitHub-only**. The existing-factory shortcut opens catalog/project operations with their explicit scope and consent; it does not route an ADO update through GitHub bootstrap. |

**Presentation recommendations:** one primary action per step; selected factory/environment/suffix/project always visible; summaries first, details on demand; concise effect labels such as “Save definition” versus “Run deployment”; destructive controls visually separate. A blue pulse should identify the current target, then stop. It must not become a permanently animated substitute for progressing the lesson.

## Take2 producer-only readiness gate

**NOT SPOKEN. Do this before scheduling the deployment take. Stop production of a dependent scene when any gate is red; do not film a blocked form and explain it away.** Resolve prerequisites off camera with the owner, then capture a clean, real action. Never reset, pull over, clean, or otherwise discard a dirty repository.

| Gate | Current read-only finding / required decision |
|---|---|
| Recording build and release | Rebuild/install the revised MAUI app and its correct bundled API; confirm healthy startup and the intended live URL. Use an isolated supported **1.25** source checkout without changing the dirty working tree. Existing source being on `main` is not a release qualification. Recheck every relevant picker and the prepared operation's resolved source ref. |
| Scope and existing work | The orange register already exists. Discover UUIDs from it; never publish machine-specific IDs. Project001's saved `enableFunction` is already true, but no live Function site/plan was established by the readiness check. Project003 already exists as a **Dev001-only draft**, with no cloud resource group established. Reuse both; do not toggle off/on or add another project003 for a “new edit” shot. |
| Execution enrollment | **ADO authentication is working** through explicit cached organization-tenant account selection; no new login or default Azure account switch is needed. The existing federated service connection matches the deployment managed identity. The 18 September recheck confirms that both explicit v1.25 prepares still stop at missing ADO runtime binding and Blob-lease enrollment. The existing Windows VM is now **deallocated** and its agent **offline**; neither was changed. The registered scoped contract requires Linux. An additional Linux ADO worker can preserve Windows, but still needs approval. Project001 lacks verified ownership; project003's exact Dev RG remains absent. Identify the authorized common/network writer and establish actual lease governance across existing writers before enrollment. A lock container or a runner alone does not establish that governance; do not silently adopt common resources, redirect legacy pipelines, or attest ownership. |
| Consent and cost | Present approval covers project001 DEV update and project003 costs—not regional expansion, clone, ownership changes, or arbitrary wider writes. Review the exact service profile: saved defaults include Foundry/capability host, Search, AML, Cosmos DB, ADF, Databricks, Event Hubs, Bot, and admin VM. “Defaults” is not a low-cost guarantee. Do not change unrelated services to make a demo succeed. |
| Non-deletion | Every delete/cleanup flag must be false, including `deleteAllForProject`, `deleteAllServicesForProject`, `enableDeleteForDisabledResources`, and `debugEnableCleaning` where present. The supported runtime uses incremental ARM and accepts only **Create, Modify, NoChange** what-if changes. Reject destructive or unresolved changes. There is no `--no-delete` switch. Retain all existing files/resources. |
| Phase 2 decision | Region belongs to the **factory**, not the scale set. The supplied Germany target is valid but is also the Sweden shared subscription. Confirm intentional reuse for a one-project regional demonstration, or supply a separate dedicated subscription for the original isolation scenario. The unconfirmed regional proposal is `ai-spider-germany`, prefix `spider-gw-`, Dev002, release 1.25, ADO, `172.17.0.0/20`, capacity one, followed by project004 in Dev002 only. It leaves Sweden unchanged. Own-subscription mode does not create subscriptions or make a reused subscription exclusive. The existing shared configuration estimates seven, despite the “up to 8” mode label. |
| Phase 3 decision | Clone copies configuration with new UUIDs and reset ownership; it retains subscription/address choices. Copied identity/network fields are currently locked against ordinary settings edits, so do not promise an available deployable retarget flow. Obtain approval for an explicitly **undeployed configuration clone**, or substitute an approved local network-planning exercise. Do not deploy a copied overlapping network. |
| Capture and privacy | Maximize each actual window after every switch. Keep scope, footer, review, and tutorial readable. Use local Microsoft Zira for the teacher track; native read-aloud is a separate deliberate demonstration. Hide keys, receipts, sensitive paths, full-state exports, account IDs, and unredacted logs. Obtain the app URL/key off camera; never inspect protected credential files. |
| Release evidence | No deployment was executed as part of preparing this manuscript. Before using any success line, retain the real job result and scoped Azure evidence privately. A successful local save, queue entry, or script exit alone is insufficient. |

The original film review used its **full transcript and selected decoded frames**, not complete audio listening. The supplied OneDrive PowerPoint has now been located; its slide contents were not re-analyzed during this media continuation. Production lessons: the old 13:37.54/14-chapter edit showed a real pulsing ring but stale tutorial step 1 at several later points; screen/caption drift occurred at 02:05, 02:25, and 11:50; whole-chapter retiming ranged from 0.39× to 2.14×; the 126px caption strip obscured lower UI. The Function segment did not deploy, project003 was a local save, Germany lacked IDs, and clone never reached confirmation. These are off-camera findings—not scenes to replay.

## Take2 director and teacher screenplay

### Direction conventions

- **Teacher:** quoted sentences are the narration manuscript. Speak at a natural pace; let viewers read before the next click. Do not say a success line before its evidence exists.
- **Director:** record each action from visible input through its actual result. Use a whole-window establishing shot, then a readable crop without losing scope. Pulse the named control for about two seconds before a click; never pulse an unrelated disabled control.
- **Chat:** native current-step/sentence highlighting is available only within supported tutorial scenarios. Elsewhere pause/hide it and use an **editorial** phase label; this is a recording treatment, not a shipped global tutorial.
- **Evidence / cut:** capture the checkpoint and dwell on it. Trim only waiting with a labeled **“Elapsed time: [measured interval]”** cut. Do not fabricate the interval, globally speed up a chapter, insert unrelated editor footage, or simulate a successful result.

**Budget, not chapter timestamps:** opening/tutorial 3 minutes; menu tour 7; phase 1 UX 8; phase 2 UX 3; phase 3 UX 2; terminal/API 7; outcomes 2. Approximate total 32 minutes; adjust the finished cut to 25–35 minutes after actual actions and speech.

### Scene 01 — Open the right place

**Teacher:** “We will work in the desktop app first, then connect each operation to its command-line and API equivalent. This is the registered AI Factory workflow, using version 1.25. Tutorial Mode is on. I am opening our orange Azure Factory folder—the folder containing the register.”

**Director / clicks / pulse:** Begin with MAUI already maximized and Tutorial Mode visibly checked. Establish the app title and folder picker. Pulse **Open existing** / browse, select the actual `azurefactory` folder rather than its repository parent, and wait for loaded scope. Do not show a migration or another configuration root. Mask private path segments without obscuring the folder name.

**Chat:** Show the supported open-existing scenario. Use **Show me**, complete the real open, then **Verify action**. Capture the actual step advancing; typing a path is not evidence of loading.

**Evidence / cut:** Register-backed factory selection and successful load must be visible. Keep one continuous input-to-result shot; no release comparison or recovery footage.

### Scene 02 — Learn the tutor, then release the screen

**Teacher:** “The instruction stays beside the work, with the current step and progress at the top. Show me points to the next control. Verify action checks what I actually completed; it does not perform the operation for me. Guidance is silent by default. I can ask Windows to read it locally, replay it, or stop it.”

**Director / clicks / pulse:** Show **Hint**, **Show me**, current step/progress, and **Verify action**. Open and close history and console once. Turn local read-aloud on, let a complete sentence play with its real highlight, then demonstrate Replay and Stop. Pause the teacher voiceover during native speech; do not mix two voices.

**Chat:** Keep the actual supported instruction visible. Explain Back/Next/Restart without restarting completed writes. Stop playback and pause guidance before leaving its supported scenario.

**Evidence / cut:** Highlight follows spoken sentence completion, not a timed guess; Stop really stops. Leave the screen with compact disclosures and no stale open-existing step.

### Scene 03 — Menu tour: configuration

**Teacher:** “The configuration wizard organizes settings into manageable sections. I can search by a friendly label or by an exact field name. The catalog organizes registered factories, scale sets, and projects. Simple Mode is the starting point for a new GitHub factory; our existing ADO factory stays in the catalog. Full bootstrap is a separate creation workflow with its own review.”

**Director / clicks / pulse:** Open every listed view. In the wizard, visit **Start & destination**, **Scale set & region**, **Platform networking**, **Security & governance**, **Project**, **Services**, **SKUs**, **Advanced**, and **Review & save**. Demonstrate section expansion/search/clear without changing saved identity. Select **1.25** explicitly where offered. In catalog, inspect selected scope, actions, and review area. In Simple Mode, inspect version/subscription/repository proposal and available navigation; do not click creation/start. In Full bootstrap, inspect provider and capability details; do not start.

**Chat:** Use the native configure/validate scenario only while its actual field is being taught; otherwise pause it. Editorial card: **Orientation — configuration views**.

**Evidence / cut:** Every view title and primary action is readable. Centered buttons and disclosures get a brief dwell. Show—not click—save, deploy, create-repository, and deletion controls during this tour.

### Scene 04 — Menu tour: operations and visualization

**Teacher:** “Monitoring answers what is running and what it costs; the data source and freshness label tell us what we are looking at. The agent and model map helps explain relationships. AI Factories gives the environment overview; AI Factory narrows the focus to one factory. Projects and Scale sets make the selected work explicit.”

**Director / clicks / pulse:** Open **Monitoring** and each visible subview, including ML, Models & quota, and automation/FinOps reports. Demonstrate a safe tab, filter, and details expansion. Open **Agent/model map**, use search/filter and select a node; preserve its useful motion. Open **AI Factories**, then **AI Factory**, select a visible environment/factory card, and inspect its details. Visit **Projects** and **Scale sets**, select existing records, and show configure/review/operation buttons without executing them.

**Chat:** Paused; editorial card **Orientation — operations views**. No claim of a native phase tracker across these pages.

**Evidence / cut:** Retain source/time/mock labels in frame. A diagram or configured card must not be narrated as proof of a deployed workload.

### Scene 05 — Menu tour: concepts and controls

**Teacher:** “Concept animations explain promotion, DataOps, MLOps, RAG, and fine-tuning before we run anything. Tickets hold work and review context. API connection tells us which local backend this window uses. Appearance and About control presentation and identify the application. These are different concerns from Azure access.”

**Director / clicks / pulse:** Visit **Concept animations** and select promotion, DataOps, MLOps, RAG, combined flow, and fine-tuning; demonstrate available play/pause without portraying execution. Inspect Tickets read-only. On **API connection**, show healthy status, **Open live Swagger**, and **Open OpenAPI JSON**; keep authorization/key entry off camera and do not use Swagger “Try it out.” Tour **Appearance** and **About**. Show the shared footer and expand/collapse terminal output. Highlight destructive/stop/input controls only; never cancel a running job merely for the tour.

**Chat:** Paused; return to compact configuration guidance only when the next supported step starts.

**Evidence / cut:** Each menu view has been visited, not simply mentioned. End back at the same registered factory without opening a terminal editor.

### Scene 06 — Phase 1: select project001 and review Function

**Teacher:** “Our first task is project001 in Development, scale-set suffix 001. We are updating this environment, not promoting it. Function is already enabled in the saved configuration, so I will not switch it off and on for the demonstration. I am checking the runtime, version, and development SKU before reviewing deployment.”

**Director / clicks / pulse:** In the catalog/project workflow, select the exact factory, Dev001, and project001. Show scoped settings; search `enableFunction`, then inspect `functionRuntime`, `functionVersion`, and `skuFunctionDev` where exposed. Keep current values unless a separately reviewed change is needed. Use the actual scoped configuration/parameter review when necessary; save only a genuine approved difference.

**Chat:** Native configure/validate guidance only if bound to these actual editor values; otherwise paused with editorial card **Phase 1 — project001 / Dev001**. Never leave open-existing step 1 visible.

**Evidence / cut:** Capture the loaded value and selected scope. Do not claim a new Function edit or cloud deployment has happened yet.

### Scene 07 — Phase 1: review and execute the existing-project update

**Teacher:** “The review binds the operation to this project, environment, source version, and resource scope. I am using 1.25 explicitly. I check the changes and warnings, then confirm this approved operation once. The job view lets us follow the actual run.”

**Director / clicks / pulse:** Only after the producer gate passes, open the registered **deployment review** for project001/Dev001. Select 1.25; inspect resolved ref, target, costs, non-deletion checks, and allowed changes. Keep consent and warnings visible. Pulse the separate confirmation control, accept the exact scope, confirm once, and follow its real job/terminal.

**Chat:** Paused; editorial phase label stays **project001 — review → run → verify**, driven manually by the actual stage.

**Evidence / cut:** Retain the real receipt/job privately. After completion, show the scoped job result and actual Function App/hosting plan evidence in Azure, masking identities. Only then record: **“The job completed, and the Function resource is present in the intended Development scope.”** If not established, hold this scene out of the finished film rather than changing the narration to a simulated success.

### Scene 08 — Phase 1: continue the existing project003 draft

**Teacher:** “Next is project003. Its definition already exists, so I select that draft rather than creating a duplicate. It has one placement: Development in the same Dev001 scale set. The defaults enable several services, so we review the service profile and cost before deploying.”

**Director / clicks / pulse:** Select existing project003. Show only its Dev001 placement and no Stage/Prod placement. Inspect the saved service flags and SKU/network summaries, including billable defaults. Explain **Add a new project** by highlighting the entry point, not by submitting number 003 again. Review/confirm configuration only if there is a genuine approved difference; reload afterward.

**Chat:** Paused or bound supported configuration guidance; editorial card **Phase 1 — project003 / Dev001**.

**Evidence / cut:** One project003 UUID, one Dev placement, saved profile unchanged except approved edits. Teacher follow-up: **“The definition is saved; deployment is the next distinct operation.”**

### Scene 09 — Phase 1: deploy project003 and verify both outcomes

**Teacher:** “I now prepare project003's own deployment review. The environment remains Development and the source version remains 1.25. After reviewing the exact services and cost, I confirm once and follow this project's job.”

**Director / clicks / pulse:** Prepare runtime deployment for the existing project003 UUID/Dev001, inspect the complete review, then perform the separately approved confirm. Capture the actual job and scoped resulting resource group/service inventory. Never reuse project001's receipt.

**Chat:** Paused; editorial card follows this project's real stage.

**Evidence / cut:** Preserve creation/deployment evidence. Only after verifying it, record: **“Both outcomes are now visible: project001's Function in Development, and project003's approved resources in its Development scope. Stage and Production were not part of these operations.”** Trim waiting with measured elapsed-time cards, not accelerated clicking.

### Scene 10 — Phase 2: teach the scaling choice

**Teacher:** “Shared subscriptions place multiple projects within an environment, subject to network capacity. The mode label says ‘up to eight’; this configured full profile currently estimates seven. Own subscriptions means we supply dedicated subscriptions for the project—it does not buy or create subscriptions. A full-profile slash-twenty allocation accommodates one project.”

**Director / clicks / pulse:** Show the scaling-mode explanation and actual capacity calculation. Inspect both mode descriptions in a separate unsaved planning view without saving over existing Dev001. Show the network preview and the relationship between reserved/common subnets and project allocation. Do not press **Apply network defaults** against the existing saved network.

**Chat:** Paused; editorial card **Phase 2 — capacity and placement**.

**Evidence / cut:** Keep the actual seven-project estimate visible; do not substitute the ceiling label. No addressing change to the source factory.

### Scene 11 — Phase 2: the approved regional definition

**Teacher — Germany branch, only after approval:** “Germany West Central is a new regional factory identity in our existing Azure Factory register. Region belongs to the factory; the scale set inherits it. I select Germany West Central, choose 1.25, and use the approved dedicated subscription and nonoverlapping network for Development suffix 002.”

**Director / clicks / pulse:** In catalog, create the approved new regional factory using the agreed unique prefix, `germanywestcentral`, 1.25, real tenant/dedicated subscription, provider, and agreed Dev002 `/20` plan with capacity one. Review and confirm the **configuration-only** operation once. Reload and select the returned regional factory/Dev002; add the agreed unused project number only after refreshing its UUID.

**Chat:** Paused; editorial card **Phase 2 — Germany regional definition**.

**Evidence / cut:** Show both regional identities in the same register and the new definition's exact placement. Only then say: **“The Germany definition and its Development placement are saved. This result is a configuration definition, not a deployment.”** Do not add a cloud-start scene without separate deployment authorization and readiness.

**Approved substitution, not an automatic fallback:** If the owner chooses “same factory” instead, replace this scene with another Sweden scale set. Exact narration: **“We are keeping the same Sweden factory and adding another Development scale set with the approved suffix, subscription, and network. It inherits Sweden Central from its factory.”** Use its agreed values and label the scene accordingly. Do not show either branch as completed while its approval is outstanding.

### Scene 12 — Phase 3: a deliberate configuration clone

**Teacher:** “Clone is useful for a configuration example. I choose the source factory, a new prefix, version 1.25, and no project definitions. The result gets new configuration identities. It does not copy Azure resources or their ownership.”

**Director / clicks / pulse:** Only with separate configuration-clone approval, open **Advanced → Clone configuration**, select the exact source and agreed new prefix/region, explicitly choose 1.25, and set **include projects: none**. Prepare; inspect the retained subscription and CIDR values, warnings, reset ownership, and new identities. Confirm only the approved **undeployed configuration example** and reload its saved result.

**Teacher, over the verified result:** “This clone is saved as configuration only. Its copied subscription and address choices remain visible; it is not a ready-to-deploy isolated Azure environment.”

**Chat:** Paused; editorial card **Phase 3 — configuration clone only**.

**Evidence / cut:** Verify new UUIDs and unchanged source privately, and absence of a runtime job for this operation. Show the configuration-only result, never a fictional Azure clone. If this scope is not approved, substitute an explicitly approved local **network-planning preview** and retitle/narrate the scene as such. Do not film another inconclusive clone attempt.

### Scene 13 — Transition to the terminal/API lab

**Teacher:** “We have completed the app walkthrough. Now we map the same scenarios to commands and API requests. We will inspect the configuration and completed jobs, not repeat the deployments. The local API connection, Azure identity, and execution approval are separate.”

**Director / clicks / pulse:** Move to a maximized terminal/editor only now. Use the same app instance's live URL and process-local key, obtained off camera. Show health, contract check, and scoped discovery from the sample below. Mask private paths and returned IDs. No environment dump or full-state print.

**Chat:** Native tutorial paused. Use the editor's actual selection to highlight the exact command discussed. Selection changes are manual production actions, not a shipped speech-synchronization feature.

**Evidence / cut:** Health is real; catalog mode/layout and exact project placement are verified. Keep this window and the displayed code consistent throughout the lab.

### Scene 14 — CLI/API: project001 and project003

**Teacher:** “Catalog list discovers identities. Catalog settings reads one exact selection. A settings prepare reviews configuration changes, while typed ARM parameter editing has its own prepare and confirm endpoints. Project add saves a new definition only when that number is genuinely new. Here project003 already exists, so our demonstration reads it.”

**Director / command highlights:** Select the scenario 1 rows in the matrix below. Run scoped **reads** for project001 and project003, including parameter introspection with 1.25 when the producer verified support. Show only a redacted summary. Display the previously used deployment command as code, selecting `runtime deploy`, selectors, `--version-ref 1.25`, then `--save-receipt` in sentence order. Do not run it again after the UX deployment.

**Teacher:** “Despite its name, runtime deploy prepares a review. Runtime confirm is the separate execution step. Its response contains job dot id; status, poll, and logs follow that job. A configuration confirmation is not a runtime confirmation.”

**Evidence / cut:** Execute only status/poll/log reads for the actual prior job, with sensitive log lines excluded. If filming the runnable sample instead of the UX execution, choose that path in advance and omit the corresponding UX confirm—one mutation, one evidence trail.

### Scene 15 — CLI/API: regional expansion and clone

**Teacher:** “Factory create prepares a regional definition. Scale-set add stays inside the selected factory's region. Project placement uses the returned scale-set UUID, not the suffix alone. Factory clone prepares configuration copying; catalog confirm saves that configuration. Neither operation is a cloud-resource clone.”

**Director / command highlights:** Select the actual scenario 2 and 3 command rows. Show the reviewed, redacted request bodies and saved configuration outcomes from the preceding UX scenes; run catalog reads only. Explain `--aifactory-version 1.25` for create/clone versus `--version-ref 1.25` for runtime. Do not substitute `main`, raw updater flags, invented flags, or an ellipsis for an executable line.

**Chat:** Paused; editorial labels match the scenario being explained. Move the real text selection with each sentence.

**Evidence / cut:** API request `action` and returned `operation_mode` agree. Never confirm a receipt twice to obtain a better shot.

### Scene 16 — The guarded runtime contract

**Teacher:** “The receipt binds the request, preview, API endpoint, source revision, and expiry. The command refuses a blocked or altered receipt. A human still reviews the effects and authorizes the exact scope. Our registered ADO entrypoint uses a protected manifest; it is not the raw legacy updater.”

**Director / highlights:** Show the receipt field table, not a private raw receipt. Open live Swagger/OpenAPI read-only to point to `/api/v1/factory-catalog/prepare` and `/api/v1/factory-catalog/confirm`. Display the in-memory request-body construction below. Demonstrate scoped launcher **help** only if needed; protected-manifest `inspect` requires a real authorized manifest and is not generic JSON inspection. Do not execute a launcher manually to duplicate a catalog job.

**Teacher:** “Non-deletion comes from the reviewed configuration and guarded runtime: delete and cleanup flags stay false, deployment is incremental, and the what-if changes must be Create, Modify, or NoChange. There is no special no-delete command-line switch.”

**Evidence / cut:** The sentence and highlighted command/field remain in sync. Keep receipt identifiers, keys, and manifest paths off screen.

### Scene 17 — Outcomes and next steps

**Teacher, only for evidence actually obtained:** “We used one registered workflow and one explicit supported version. We inspected the application first, then connected each scenario to its command and API contract. The outcome board separates saved configuration, executed jobs, and verified Azure resources.”

**Director / clicks / pulse:** Return to MAUI **AI Factories / AI Factory** and show a concise outcome board: project001 Function, project003 Dev placement/resources, the approved phase 2 definition, and the undeployed clone or substituted network plan. Populate each row only from the actual evidence—not from this screenplay. Open the relevant real job when demonstrating an executed result.

**Teacher:** “Promotion, DataOps, MLOps, RAG, and fine-tuning have their own inputs, access, validation, and release decisions. The concept views help explain those next workflows; the diagrams themselves do not execute them.”

**Chat:** Stop native speech and leave no stale lesson visible. Final editorial card: **Configuration ≠ execution ≠ verified outcome**.

**Evidence / cut:** Capture a truthful final summary and portable handoff. Do not publish a completed-film claim until audio, captions, scene evidence, and links all pass the checks below.

## Take2 CLI/API correspondence and guarded sample

### Contract matrix

This is a **reference, not a batch script**. Commands use the installed `azurefactory` executable; `python -B -m azurefactory` invokes the same parser from the SDK source. Variables represent exact discovered selections, not public example UUIDs. `$root`, `$factoryId`, `$scaleId`, `$projectId`, and `$revision` are established in the runnable sample. Before using other rows, supply the explicitly approved local patch/scale-set files, unused project number, regional/clone prefix, and fresh returned scale-set UUID. Keep all such material private.

| Scenario / effect | Exact CLI form | Actual API contract |
|---|---|---|
| Connection / reads | `azurefactory health`; `azurefactory doctor` | `GET /health`; `GET /openapi.json` and schema/contract checks. No Azure-readiness claim. |
| Discover registered scope / read | `azurefactory catalog list --folder $root` | `GET /api/v1/factory-catalog` with query `folder` returns `mode`, `layout_version`, `revision`, `factories`; each factory contains `scale_sets` and `projects`. The SDK URL-encodes the query value. |
| Project001 or project003 settings / read | `azurefactory catalog settings --folder $root --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId` | `GET /api/v1/factory-catalog/settings` with `folder`, `factory_id`, `scale_set_id`, `project_id`; response contains `revision`, `state`, `field_keys`. |
| Genuine Function settings change / configuration review | `azurefactory request POST /api/v1/factory-catalog/prepare --body-json .\function-settings.json --write --yes` | Body: `contract_version:1`, `action:"configure-settings"`, exact folder/IDs, `expected_revision`, and `settings:{"enableFunction":"true"}`. Do not run for an already-true value. Generic POST flags permit preparation; they are not deployment approval. This generic command does **not** save a CLI receipt. |
| Typed parameters / read then review | `azurefactory parameters get --folder $root --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId --version-ref 1.25`; `azurefactory parameters prepare --request-json .\approved-parameters.json --save-receipt .\parameters.receipt.json` | `GET /api/v1/factory-catalog/parameters`, then `POST /api/v1/factory-catalog/parameters/prepare`. Request uses returned `source_revision` as `expected_revision`, returned `schema_revision`, exact template names/types, `version_ref:"1.25"`, and only intentional edits in `templates`. Do not invent a template name or silently reset a profile. |
| Typed parameter save / separate approved local write | `azurefactory parameters confirm --receipt .\parameters.receipt.json --yes` | `POST /api/v1/factory-catalog/parameters/confirm`, not the generic catalog confirm endpoint. |
| New project definition / configuration review | `azurefactory project add --folder $root --factory-id $factoryId --number $unusedProjectNumber --placement "dev=$scaleId" --expected-revision $revision --save-receipt .\new-project.receipt.json` | `POST /api/v1/factory-catalog/prepare`, `action:"add-project"`, `project:{number,display_name,placements:[{environment:"dev",scale_set_id}]}`. Existing project003 takes the read/reuse path instead. |
| Germany factory plus scale set / configuration review | `azurefactory factory create --folder $root --prefix $germanyPrefix --region germanywestcentral --aifactory-version 1.25 --scale-set-json .\approved-germany-scaleset.json --expected-revision $revision --save-receipt .\germany.receipt.json` | Same prepare endpoint, `action:"create-factory"`, `factory_kind:"ai"`, `target_prefix`, `target_region`, `aifactory_version:"1.25"`, `scale_sets`. Each entry requires `environment`, `suffix`, `tenant_id`, `subscription_id`, `orchestrator`, `network:{vnet_cidr,max_projects}`; optional explicit subnets follow the live schema. |
| Another scale set in the same factory / configuration review | `azurefactory scaleset add --folder $root --factory-id $factoryId --scale-set-json .\approved-scaleset.json --expected-revision $revision --save-receipt .\scaleset.receipt.json` | Same prepare endpoint, `action:"create-scale-set"`, `factory_id`, `scale_sets`. **No region field:** inherits the factory region. |
| Configuration clone / review | `azurefactory factory clone --folder $root --factory-id $factoryId --prefix $clonePrefix --region $approvedCloneRegion --aifactory-version 1.25 --include-projects none --expected-revision $revision --save-receipt .\clone.receipt.json` | Same prepare endpoint, `action:"clone"`, exact source, `target_prefix`, `target_region`, `aifactory_version:"1.25"`, `include_projects:"none"`. Subscription/CIDR retention and reset ownership are reviewed, not hidden. |
| Save an approved catalog definition / local write | `azurefactory catalog confirm --receipt $configurationReceipt --yes` | `POST /api/v1/factory-catalog/confirm`, body `{folder,contract_version:1,confirmation_id}`. Requires configuration-mode receipt. Response has `catalog` and no runtime `job`. For the generic settings prepare row, use the separately reviewed API confirmation; do not fabricate a CLI receipt. |
| Project deployment / **prepare only** | `azurefactory runtime deploy --folder $root --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId --version-ref 1.25 --expected-revision $revision --save-receipt $receiptPath` | `POST /api/v1/factory-catalog/prepare`, `contract_version:1`, `action:"deploy"`, exact IDs/root, `version_ref:"1.25"`, `expected_revision`. Preparation can persist server-side review bookkeeping; it is not execution. |
| Deployment execution / separate approval | `azurefactory runtime confirm --receipt $receiptPath --yes` | `POST /api/v1/factory-catalog/confirm`, `{folder,contract_version:1,confirmation_id}`; runtime result is `contract_version:1` plus **`job.id`**, not a top-level `job_id`. |
| Job evidence / reads | `azurefactory runtime poll --folder $root --job-id $jobId --poll-timeout 1800`; `azurefactory runtime status --folder $root --job-id $jobId`; `azurefactory runtime logs --folder $root --job-id $jobId --cursor 0` | `GET /api/v1/factory-catalog/jobs/{job_id}` with folder; `GET /api/v1/factory-catalog/terminal` with folder/job_id/cursor. List jobs through `GET /api/v1/factory-catalog/jobs`. |

Settings flags often use strings such as `"true"`; typed ARM parameters must use the types returned by their selected schema. `configure-settings` is not a way to overwrite immutable version, region, subscription, or placement fields. Additional placements are configuration, not promotion.

### Runnable guarded example: discover, prepare, separately approve, observe

**Operator example for a future authorized run, not executed in preparing this guide.** Use a private working directory outside the repository for receipts; do not publish raw output. Run each numbered block separately. If the UX already executed this project, skip preparation/confirmation and use its recorded job ID for reads. Current enrollment blockers must be resolved with approval before block B; do not run the blocked demonstration on camera.

#### A. Read-only discovery in a private PowerShell session

The CLI's API URL/key environment names are `AIFACTORY_API_URL` and `AIFACTORY_API_KEY`. Supply the latter through your approved process-local secret mechanism, off camera. Do not print it or put it in a command argument. The API uses the selected app instance's actual ephemeral port; there is no fixed-port assumption.

```powershell
$ErrorActionPreference = 'Stop'
$sourceRoot = Read-Host 'Path to the approved supported source checkout'
$env:PYTHONPATH = Join-Path $sourceRoot 'environment_setup\azurefactory-cli\src'
if (-not (Test-Path (Join-Path $env:PYTHONPATH 'azurefactory\cli.py'))) {
    throw 'CLI source not found'
}
$env:AIFACTORY_API_URL = Read-Host 'Live base URL from the intended MAUI API connection page'
if (-not $env:AIFACTORY_API_KEY) { throw 'Supply the process-local API key off camera first' }
$env:AIFACTORY_ROOT = Read-Host 'Exact azurefactory folder on the API host'
$root = $env:AIFACTORY_ROOT
if ((Split-Path $root -Leaf) -ine 'azurefactory') { throw 'Select the registered azurefactory root' }

function Read-AzureFactoryJson {
    param([string[]]$Arguments)
    $output = & python -B -m azurefactory @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'CLI failed; inspect privately and do not retry a write automatically' }
    return (($output -join "`n") | ConvertFrom-Json)
}
function Select-ExactlyOne {
    param([object[]]$Items, [string]$Label)
    if ($Items.Count -ne 1) { throw "Expected exactly one $Label; do not guess" }
    return $Items[0]
}

$health = Read-AzureFactoryJson -Arguments @('health')
$doctor = Read-AzureFactoryJson -Arguments @('doctor')
$catalog = Read-AzureFactoryJson -Arguments @('catalog', 'list', '--folder', $root)
if ($catalog.mode -ne 'catalog' -or $catalog.layout_version -ne 2) {
    throw 'This tutorial requires the registered version-2 layout'
}
$factoryKey = Read-Host 'Exact factory key from the approved catalog selection'
$factory = Select-ExactlyOne -Items @($catalog.factories | Where-Object key -CEQ $factoryKey) -Label 'factory'
$scale = Select-ExactlyOne -Items @($factory.scale_sets | Where-Object {
    $_.environment -eq 'dev' -and $_.suffix -eq '001'
}) -Label 'Dev001 scale set'
if ($scale.orchestrator -ne 'ado') { throw 'This existing-factory runtime example is scoped to ADO' }
$number = Read-Host 'Approved project number: 001 or 003'
if ($number -notin @('001', '003')) { throw 'Outside this example scope' }
$project = Select-ExactlyOne -Items @($factory.projects | Where-Object number -CEQ $number) -Label 'project'
$placement = Select-ExactlyOne -Items @($project.placements | Where-Object {
    $_.environment -eq 'dev' -and $_.scale_set_id -eq $scale.id
}) -Label 'matching project placement'
if ($number -eq '003' -and @($project.placements).Count -ne 1) {
    throw 'Project003 is expected to have only the approved DEV placement'
}
$env:AIFACTORY_FACTORY_ID = $factoryId = [string]$factory.id
$env:AIFACTORY_SCALE_SET_ID = $scaleId = [string]$scale.id
$env:AIFACTORY_PROJECT_ID = $projectId = [string]$project.id
$revision = [string]$catalog.revision
$settings = Read-AzureFactoryJson -Arguments @(
    'catalog', 'settings', '--folder', $root, '--factory-id', $factoryId,
    '--scale-set-id', $scaleId, '--project-id', $projectId
)
$dangerous = @($settings.state.PSObject.Properties | Where-Object {
    ($_.Name -match '^(delete|clean)' -or
     $_.Name -in @('enableDeleteForDisabledResources', 'debugEnableCleaning')) -and
    ([string]$_.Value -match '^(true|1|yes)$')
})
if ($dangerous.Count) { throw 'Deletion/cleanup flags require correction and a new approved review' }
[pscustomobject]@{ Project = $number; Environment = 'dev'; Suffix = '001'; RequestedVersion = '1.25' }
```

This last line is a limited presentation summary, not proof of backend enrollment or deployment. Review settings privately; do not print `$settings`, the complete catalog, environment variables, or secrets. The backend performs additional non-deletion and scope checks beyond this local check.

#### B. Prepare once, after the producer gate and exact scope approval

```powershell
if ((Read-Host 'Type PREPARE after reviewing this exact scope and completing enrollment') -cne 'PREPARE') {
    throw 'Preparation not approved'
}
$fresh = Read-AzureFactoryJson -Arguments @('catalog', 'list', '--folder', $root)
if ($fresh.revision -ne $revision) { throw 'Catalog changed; rediscover and review before preparation' }
$receiptPath = Join-Path (Get-Location).Path ("project$number-" + [guid]::NewGuid().ToString('N') + '.receipt.json')
$previewOutput = & python -B -m azurefactory runtime deploy --folder $root `
    --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId `
    --version-ref 1.25 --expected-revision $revision --save-receipt $receiptPath
if ($LASTEXITCODE -ne 0) { throw 'Prepare did not pass; inspect privately, never confirm a blocked review' }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.format -ne 'azurefactory-review-receipt-v1' -or
    $receipt.purpose -ne 'catalog-confirm' -or $receipt.operation -ne 'runtime-deploy' -or
    $receipt.operation_mode -ne 'runtime' -or $receipt.can_execute -ne $true -or
    @($receipt.preview.blockers).Count -ne 0 -or
    [DateTimeOffset]::Parse($receipt.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Receipt is not a current executable runtime review'
}
$receipt | Select-Object format, purpose, operation, operation_mode, can_execute, expires_at
```

**Stop here.** Privately review the entire effects/warnings/what-if, binding, target, exact source ref, costs, and scope against the approved work. The prompt is only an operator pause, not an organizational approval system. No missing binding, ownership, runner, or subscription is silently supplied by this script. Receipt creation refuses overwriting an existing file; never edit a receipt to clear a blocker.

#### C. Separately confirm the reviewed receipt, once

```powershell
if ((Read-Host 'Type EXECUTE only after the exact unexpired receipt has been authorized') -cne 'EXECUTE') {
    throw 'Execution not approved'
}
$confirmOutput = & python -B -m azurefactory runtime confirm --receipt $receiptPath --yes
if ($LASTEXITCODE -ne 0) {
    throw 'Inspect catalog jobs before doing anything else; do not repeat confirmation'
}
$confirmed = ($confirmOutput -join "`n") | ConvertFrom-Json
if ($confirmed.contract_version -ne 1 -or -not $confirmed.job.id) {
    throw 'Missing runtime acknowledgement; inspect jobs, never guess or retry'
}
$env:AIFACTORY_JOB_ID = $jobId = [string]$confirmed.job.id
```

The CLI validates receipt purpose/mode, request/preview hashes and bindings, API URL, blockers, and expiry; the server owns final concurrency and execution checks. Hashes detect receipt edits; they are not signatures or a substitute for authorization. If the app/API restarted, use its current coherent connection and a newly reviewed operation rather than patching the stored receipt.

#### D. Read job evidence without re-execution

```powershell
$job = Read-AzureFactoryJson -Arguments @(
    'runtime', 'poll', '--folder', $root, '--job-id', $jobId, '--poll-timeout', '1800'
)
$status = Read-AzureFactoryJson -Arguments @('runtime', 'status', '--folder', $root, '--job-id', $jobId)
$logs = Read-AzureFactoryJson -Arguments @(
    'runtime', 'logs', '--folder', $root, '--job-id', $jobId, '--cursor', '0'
)
[pscustomobject]@{ Project = $number; Status = $status.status; ExitCode = $status.exit_code }
```

A poll timeout does not authorize resubmission: read status/logs for the same job. A successful job still needs independent verification of the intended Function/resource-group/service outcome, correct environment, and absence of unintended changes. Keep `$logs` private; publish only reviewed excerpts.

### Actual API bodies and receipt shape

The following constructs the equivalent runtime request **in memory only**. It makes no HTTP call and is not a second deployment. An integration sends this to **`POST /api/v1/factory-catalog/prepare`**, reviews the returned preview, and only after its approval policy passes sends the separate confirmation body to **`POST /api/v1/factory-catalog/confirm`**. Authentication is `X-API-Key` over the intended local connection; never expose the desktop loopback API as a public ITSM endpoint.

```powershell
$prepareBody = @{
    folder = $root
    contract_version = 1
    action = 'deploy'
    factory_id = $factoryId
    scale_set_id = $scaleId
    project_id = $projectId
    version_ref = '1.25'
    expected_revision = $revision
} | ConvertTo-Json
$confirmBody = @{
    folder = $receipt.folder
    contract_version = 1
    confirmation_id = $receipt.confirmation_id
} | ConvertTo-Json
```

| Actual field | Meaning |
|---|---|
| Receipt `format` | `azurefactory-review-receipt-v1` |
| `purpose`, `operation`, `operation_mode` | Runtime: `catalog-confirm`, `runtime-deploy`, `runtime`. Configuration and parameter receipts have different operation/purpose requirements; do not interchange them. |
| `base_url`, `folder`, `confirmation_id`, `can_execute`, `expires_at` | Bound connection/root/review and executable lifetime. |
| `request`, `preview`, `request_hash`, `preview_hash` | Sanitized reviewed content and canonical hashes. The preview includes `contract_version`, `source_revision`, `effects`, `warnings`, `blockers`, `target`, `inventory`, and applicable `source_version`/`binding`. |
| Optional `blocked_reason` | A stored blocked preview is still not confirmable. |
| Runtime confirmation response | `contract_version:1`, optional `catalog`, and `job` containing `id`, `action`, `status`, `factory_id`, optional `scale_set_id`, timestamps, message, and runtime evidence fields. |
| Configuration confirmation response | `contract_version:1`, `catalog`, and `job:null`; a configuration save is not a deployment job. |

Source-checked against [CLI parser/handlers](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py), [SDK route/body methods](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py), [receipt validation](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py), and backend `factory_catalog_models.py`, `catalog_parameter_models.py`, `api.py`, and `catalog_runtime.py`. Registered [ADO](../../../bootstrap/ADO-azurefactory.sh) and [GHA](../../../bootstrap/GHA-azurefactory.sh) launchers expose protected-manifest `inspect`/`execute`; [runtime guards](../../../bootstrap/lib/factory_lifecycle.py) enforce scoped execution. Read the running API's OpenAPI before production; checked-out source alone does not certify a bundled binary.

## Take2 production and delivery plan

**The complete three-phase film remains planned.** The separately named, delivered Part 1 files and measured chapter index are listed above. Keep all original captures, the prior film, and any supplied decks. Create Take2 alongside them; never overwrite the old media. Paths below reserve the future complete-film names relative to the delivered `tutorial` bundle, not this Markdown file:

```text
tutorial\
  video\
    take2\
      AI Factory tutorial - MAUI UX - Take2.mp4
      AI Factory tutorial - MAUI UX - Take2.srt
      AI Factory tutorial - MAUI UX - Take2-chapters.json
    snippets-take2\
  image-screenshots\
    maui-take2\
  ppt\
    maui-take2\
      AI Factory tutorial - MAUI UX - Take2.pptx
```

1. **Capture:** preserve full-resolution original actions, unretimed audio, and per-scene evidence. Maximize before every capture, including a deliberate browser/terminal switch. Hold each title, selection, review, and outcome long enough to read.
2. **Narration:** use local Microsoft Zira at a natural, consistent rate. Split audio at sentence/action boundaries; align each sentence to the actual screen state. Native tutorial speech gets its own uninterrupted demonstration and is otherwise stopped to avoid doubled narration.
3. **Edit:** use straight cuts and measured elapsed-time cards for waiting. No whole-chapter retiming. Use player captions or a reserved safe area that does not cover footer, chat, buttons, or warnings; do not repeat the old bottom-strip obstruction. Inspect every transition for screen/caption/command drift.
4. **Deck:** build a new companion after screenshots and clips are verified: learning path, menu map, one scenario/evidence pair per completed phase, CLI/API matrix, receipt boundary, and truthful outcomes. Do not assert the contents of the earlier OneDrive deck without reading it through its authorized document route. From `ppt\maui-take2`, the planned complete-film video target is `..\..\video\take2\AI Factory tutorial - MAUI UX - Take2.mp4`; Part 1 has its own explicitly scoped filenames.
5. **Portable packaging:** set relative media targets from each deliverable's own directory. Validate them after moving the entire bundle to a different folder. Add clickable chapter timestamps and links to this guide only after actual files exist and final durations are measured.
6. **Acceptance:** watch/listen to the entire finished cut, not just transcript/frames. Verify every spoken sentence against its screen, every pulse against its intended control, every command selection against its narration, every claimed outcome against retained evidence, and every caption/clip/PPT link from the relocated bundle. Update the status at the top only after this passes.

## Preserved original walkthrough

<details>
<summary>Archive — complete pre-Take2 walkthrough and its historical technical references</summary>

**Historical context, not the Take2 itinerary.** The original text below is preserved intact, including its original recording claims, technical detail, links, and source snapshots. Its dates, media descriptions, old-version/migration examples, and deployment limitations belong to that earlier guide; they are not new production evidence. Use the coherent 1.25+ manuscript above for Take2.

# AI Factory tutorial - MAUI UX

**Recording: 16 September 2026 · 13 minutes 37.54 seconds (rounded: 13:38) · Windows MAUI + local Python API**

This guide follows the completed recording, not an idealized deployment demo. It teaches three phases: update an existing project and add another; plan dedicated-subscription regional expansion; then preview an advanced clone. The API/CLI chapter uses the same configuration backend as the desktop app.

> **Safety boundary:** Tutorial Mode is not a sandbox. Save, export, confirmation, deployment, and deletion controls retain their real effects. The recording contains reviewed local configuration saves and previews, but no deployment start, pipeline dispatch, or deletion control/API call. Do not replay completed writes.
>
> For the separate Monitor dashboard and FinOps report walkthrough, see [AI Factory tutorial: FinOps monitoring](tutorial-fiops.md).

## Navigate the tutorial

- [Recording and chapter index](#recording-and-chapter-index)
- [Before opening the app](#before-opening-the-app)
- [Tutorial Mode and menu tour](#tutorial-mode-and-menu-tour)
- [Q3: What runs when Tutorial Mode is enabled?](#q3-what-runs-when-tutorial-mode-is-enabled)
- [Q1: Which folder is authoritative?](#q1-which-folder-is-authoritative)
- [Q4: Safe hybrid validation and copy migration](#q4-safe-hybrid-validation-and-copy-migration)
- [Phase 1: Function update and project 003](#phase-1-function-update-and-project-003)
- [Phase 2: Dedicated subscriptions and Germany](#phase-2-dedicated-subscriptions-and-germany)
- [Phase 3: Clone preview](#phase-3-clone-preview)
- [Q2: API connection and Windows storage](#q2-api-connection-and-windows-storage)
- [API and CLI lab](#api-and-cli-lab)
- [All API: recorded contract inventory](#all-api-recorded-contract-inventory)
- [Deployment, promotion, operations, and handoff](#deployment-promotion-operations-and-handoff)

## Recording and chapter index

Keep the supplied media together; these are companion files, not files embedded in this repository. These portable paths are relative to the parent of the delivered `tutorial` folder, not to this Markdown file:

```text
tutorial\
  ppt\AI Factory tutorial - MAUI UX.pptx
  video\maui-final-video\
    AI Factory tutorial - MAUI UX.mp4
    AI Factory tutorial - MAUI UX.srt
    AI Factory tutorial - MAUI UX-chapters.json
  video\snippets\                         (14 chapter clips)
  video\AI-Factory-original-20260916-*.mp4 (20 original recordings)
  image-screenshots\
```

The final-video folder contains the same 13:38 edited master and its renamed sidecars, not a new recording; earlier media and original captures remain preserved. From the deck's `ppt` folder, the portable video target is `..\video\maui-final-video\AI Factory tutorial - MAUI UX.mp4`.

The delivered deck has **33 slides and six embedded clips**; the edited master has **14 chapters**. For a player rooted at the delivered `tutorial` folder, the relative video URI is `video/maui-final-video/AI%20Factory%20tutorial%20-%20MAUI%20UX.mp4`; the captions and chapter index use the same stem with `.srt` and `-chapters.json`. Do not replace these portable references with a presenter's machine-specific path.

The chapter JSON contains exact fractional-second offsets; the times below are rounded to the nearest second. Edited chapter order is educational order, not the chronological order of every original capture.

| Start | Chapter | Main lesson |
|---|---|---|
| 00:00 | 01 · Open MAUI, turn Tutorial Mode on | Guidance over real configuration |
| 00:51 | 02 · Open the orange Azure Factory folder | Reviewed COPY; preserve the legacy source |
| 01:51 | 03 · Configuration menu | Wizard, Factory catalog, Simple Mode, Full bootstrap |
| 02:47 | 04 · Operations menu | Monitoring, maps, environments, projects, tickets, settings |
| 03:51 | 05 · Project 001 Function | Review an earlier saved draft and validate explicitly |
| 04:57 | 06 · Project 003 | Save default configuration with only a Dev001 placement |
| 06:01 | 07 · Scaling modes | Shared versus own subscriptions; network capacity |
| 06:54 | 08 · Germany West Central | Separate regional factory identity; missing prerequisites |
| 08:00 | 09 · Clone | Inspect overlapping-network warnings; do not confirm |
| 08:56 | 10 · API foundation | Actual endpoint, protected key, exact UUID selectors |
| 09:49 | 11 · API configuration | Full-state validation and scoped settings preview |
| 10:43 | 12 · CLI and orchestrators | Clone preview; ADO/GHA help and manifest boundary |
| 11:36 | 13 · Operations lessons | Promotion, DataOps, MLOps, RAG, fine-tuning |
| 12:41 | 14 · Handoff | Saved configuration versus unexecuted plans |

### What actually happened

| Scenario | Recorded outcome | Not established |
|---|---|---|
| Project 001 Function | Continued an earlier **locally saved legacy Function draft**; reviewed settings and obtained passing validation | No Function App deployed; earlier deployment review was blocked by an Azure identity mismatch |
| Legacy to registered layout | Explicit COPY completed; sibling `azurefactory\register.json` created; original `aifactory` preserved | Not an Azure deployment, repository clone, or ownership transfer |
| Project 003 | Reviewed and saved a new catalog **draft**, placed only in Dev suffix `001` | No Stage/Prod placement or Azure deployment |
| Germany / Dev002 / project004 | Planning and prerequisite explanation only | No dedicated subscription supplied/created; no saved Germany definition or project004 |
| Clone | UI and CLI previews, including overlapping-address warnings | No accepted/confirmed clone and no copied Azure resources |
| Menus and API | Real navigation, selected reads, validation, settings/clone previews, and launcher help | Not every API endpoint or menu action was executed |

## Before opening the app

Use the [Windows app setup](../../../environment_setup/install_config_wizard/maui/readme.md), [end-to-end setup](24-end-2-end-setup.md), and [API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md) for installation and prerequisites.

1. Identify **purple** accelerator source versus the **orange** team repository. Updating an orange submodule changes code/templates; it does not migrate configuration, refresh every copied launcher, or update an already-running bundled API.
2. Preserve dirty working trees. This walkthrough does not require a pull, reset, commit, push, template refresh, sign-in change, or deployment.
3. Choose the intended app window and its API connection. On Windows the bundled sidecar normally uses a fresh loopback port per launch; do not assume `8765`.
4. Use real, owner-approved tenant/subscription identities only when a future operation needs them. Never publish keys, full state dumps, private local paths, or unredacted identity screenshots.
5. Read warnings in the installed build. Its capabilities and live OpenAPI may differ from newer checked-out source.
6. Before **every new screenshot or recording segment**, maximize both the MAUI and Tkinter windows (or make each full-height within its monitor's usable work area). Verify that the title, selected scope, lower controls, and relevant warnings are visible; recheck after switching windows or monitors. This is capture guidance, not a claim that every preserved original capture already met it.

Portable examples below use `C:\work\team-factory\aifactory`, its sibling `C:\work\team-factory\azurefactory`, and `C:\work\azure-enterprise-scale-ml`. Substitute your own explicit roots. File arguments are paths **on the API host**, not automatically paths on a remote client.

## Tutorial Mode and menu tour

### Q3: What runs when Tutorial Mode is enabled?

In **AI Factory configuration**, check **Tutorial Mode**. Choose a scenario, read the instruction, use **Hint** or **Show me**, perform the requested action, and select **Verify action**. Back, Next, Restart, progress, and the read-only console support instruction; they are not deployment consent.

The tutorial is a **local, in-process MAUI `TutorialSession`**, constructed by `ConfigurationTutorial`. It observes the real `WizardViewModel` and completed operation evidence. It is not a second API sidecar, external chatbot, or independent sandbox. The ordinary Python sidecar still performs application operations.

- **Open an existing AI Factory:** opening reads configuration and replaces editor values; typing a path alone is not successful loading.
- **Configure and validate a project:** Show me navigates to the field. You must click **Validate** yourself; Verify action checks the completed Python result. Editing invalidates earlier verification.
- **Validate and export variables:** export deliberately writes a local file. Keep potentially sensitive exports private.
- The enabled preference is saved as `tutorial.configuration.enabled`; session progress is in memory. Hiding/leaving pauses guidance, and changing factory scope restarts its verification.
- **Review & save** opens a section; **Save** is a separate write. Tutorial Mode does not disable normal save/deploy controls. A version picker changes configuration, not a repository checkout or Azure.

The in-process trace is `MainPage` → `new ConfigurationTutorial(viewModel)` → `Session = new TutorialSession(CreateScenarios())` → UI `TutorialPanel(Session)`. `TutorialSession` is an `ObservableObject` with in-memory progress and verifier delegates; `await step.Verify(...)` is not a process launch. The separate, ordinary API subprocess is explicitly started by `BundledApiHost` using `ProcessStartInfo` / `Process.Start` for `ApiHost\aifactory-api.exe`.

**There are three different kinds of state:**

| Owner | State and boundary |
|---|---|
| MAUI `ConfigurationTutorial.Session` | Educational progress and verification, in process. The enabled preference is persisted, not the progress. |
| MAUI `WizardSession.State` | The actual editable `JsonObject`, also in process; the tutorial observes it through `WizardViewModel`. This is not a separate tutorial configuration copy. |
| Python API / storage | Validation receives a complete request state and merges defaults into a request-local dictionary. Explicit save/export operations persist files; catalog preparation persists confirmation receipts in SQLite. The overall application is therefore **not** wholly in-memory or stateless. |

**Endpoint correction:** the implemented route is **`POST /api/v1/validation`**, not `/api/v1/validate`. `AiFactoryApiClient.ValidateAsync` posts a state snapshot there; tutorial **Verify action** only checks the completed result. `POST /api/v1/export` renders the supplied state and writes on the API host **when `path` is provided**. With no server path, the API returns content, but the **MAUI Export action still writes** it to the app-data `exports` directory through `MauiConfigurationFileService`.

The Python `src\api_sidecar.py` entry point imports `src.api.app`, parses the loopback port/owning parent, and runs Uvicorn; it does not own `ConfigurationTutorial.Session`. The host starts during ordinary `WizardSession.InitializeAsync`, independently of Tutorial Mode.

Source: MAUI `Services\ConfigurationTutorial.cs:13–40,73–167`; `MainPage.xaml.cs:27–38,88–115`; `Services\WizardSession.cs:15–34,62–81`; `ViewModels\WizardViewModel.cs:359–368,394–417,594–602`; `Services\MauiConfigurationFileService.cs:37–55`; `Services\BundledApiHost.cs:42–73,106–107`; ESAIF.BaseLayer `src\ESAIF.BaseLayer\Tutorials\TutorialSession.cs:5–21,59–78,171–192`; ESAIF.DomainLayer `src\ESAIF.DomainLayer\Configuration\AiFactoryApiClient.cs:74–83,100–111`; Python `src\api_sidecar.py:15,18–23,88–96`, `src\api.py:1552–1556,1676–1701,1735–1747`, `src\factory_catalog.py:1166–1182`.

### Tour the menu before editing

| Area | What to inspect | Boundary to explain |
|---|---|---|
| Configuration wizard | Start & destination; Scale set & region; Platform networking; Security & governance; Project; Services; SKUs; Advanced; Review & save | Schema-backed editor; global search accepts labels or exact API field names |
| Factory catalog | Registered factories, exact scale sets/projects, configuration actions, review, jobs | Selection is explicit; configure-only saves definitions, not Azure resources |
| Simple Mode | New private Dev GitHub factory preset, existing subscription, prefix, version, repository proposal | **Installed build creates NEW GitHub Actions factories only**, not an existing ADO update |
| Full bootstrap | Explicit ADO/GHA create route, capability registry, warnings, configure-only alternative | Execution can create common infrastructure/initial project, incur cost, commit/push, and run pipelines; not activated here |
| Monitoring | Overview, ML, Models & quota, Automation reports, current-factory analytics | Distinguish cached, live, unavailable, and sample results; read source/time labels |
| Agent map | Map, dashboards, charts, filters, search, selected scope | Mock data is labeled; animation is not proof of a live workload |
| AI Factories / environment board | Dev, Stage, Prod; observed groups versus saved plans; update/promotion entry points | A configured project, draft, or cached card is not deployment success |
| Projects / Scale sets | Exact project number, suffix, environment and source | Configuration scope and Azure access verification are separate |
| Concept animations | Promotion, DataOps, MLOps, RAG, combined flows, fine-tuning | Read-only teaching diagrams, not pipelines or telemetry |
| Tickets | Work requests and review context | A ticket is not permission to execute |
| API connection | Base address, Open live Swagger, Open OpenAPI JSON, Copy key for Swagger | Swagger Try it out can mutate real state; keep keys off camera |
| Appearance / About | Presentation, motion preferences, installed application identity | These do not change factory infrastructure |
| Shared footer / terminal | Scope, Azure refresh, warnings, owned job output | Refresh can contact Azure; terminal input/stop are active controls, not read-only logs |

In the captured Full bootstrap registry, launchers were unavailable because the published launcher cache was missing. Help output alone does not repair that prerequisite. No bootstrap was started.

## Q1: Which folder is authoritative?

**Sibling roots can coexist.** The completed example now has both the preserved orange `aifactory` and the registered `azurefactory`. Open the latter explicitly for ongoing registered configuration. A repository parent is not a substitute for either API root. Do not operate both as independent runtime writers against the same physical Azure targets.

Keep the **consumer repository root** (`C:\work\team-factory`, containing pipelines and the accelerator submodule) separate from its **configuration root** (`...\aifactory` or `...\azurefactory`). The legacy `aifactory_folder` and catalog `folder` arguments select configuration roots. A launcher's `--repo-root` selects a repository/workspace; it is not a synonym for those API arguments. Pulling the purple submodule changes source, not which configuration root a request selected.

| Selected root | Correct interpretation |
|---|---|
| `aifactory` without `config-wizard\catalog.json` | Legacy load/list/save routes use this exact root |
| `aifactory` with `config-wizard\catalog.json` | Opt-in catalog-v1 root; use catalog selectors, even if legacy files remain |
| `azurefactory`, including an empty one | Catalog-layout root by **folder name**; never fall back to legacy project APIs |
| `azurefactory\register.json` | Canonical version-2 catalog; generated projections are not a competing source of truth |

Same-root layout conflicts are different from sibling coexistence: `aifactory\register.json` conflicts with layout 1, and `azurefactory\config-wizard\catalog.json` conflicts with layout 2. The backend rejects these with HTTP 409; it does not choose one identity by guessing. Extra legacy-looking files do not authorize fallback from `azurefactory` to legacy operations.

More precisely, a `variables.json` file beside a valid register is not itself the conflicting-register check: the catalog remains authoritative. An existing `azurefactory` without `register.json` reads as an empty catalog, even if legacy-looking files are present; those files still make it an invalid nonempty COPY destination. A malformed register fails rather than falling back to legacy state (`factory_catalog.py:547–554,647–658`).

`api.py:1212–1214` guards legacy routes using `factory_catalog.is_catalog_root`: `Path(folder).name.casefold() == "azurefactory" or has_catalog(folder)` (`factory_catalog.py:40–48`). `catalog_storage.py:118–126` rejects conflicting same-root register locations. Thus explicit `aifactory` reads can still work beside `azurefactory`; that is not permission to deploy from both.

### Exactly which legacy endpoints use that guard?

The following **24 route handlers directly call `_require_legacy_root`** in the inspected source. All paths have the `/api/v1` prefix. This is a routing inventory, not permission to invoke mutating routes.

| Method | Paths after `/api/v1` | Guard source in `src\api.py` |
|---|---|---|
| GET | `/operations/project-deployments`; `/operations/project-deployments/terminal` | 1240, 1289 |
| POST | `/operations/project-deployments/plan`; `/prepare`; `/start`; `/reconcile/prepare`; `/reconcile`; `/terminal/input`; `/terminal/resize` (all under `/operations/project-deployments`) | 1248, 1257, 1266, 1274, 1282, 1298, 1305 |
| POST | `/analytics/current-factory`; `/startup/load` | 1418, 1755 |
| POST | `/projects`; `/projects/verify-resource-groups`; `/projects/load`; `/projects/save`; `/projects/delete` | 1770, 1834, 1845, 1860, 1897 |
| POST | `/scale-sets`; `/scale-sets/verify-resource-groups`; `/scale-sets/load`; `/scale-sets/save`; `/scale-sets/delete` | 1919, 1980, 1991, 2010, 2036 |
| POST | `/operations/overview`; `/operations/factory-actions`; `/operations/project-actions` | 2113, 2200, 2217 |

Save handlers check the submitted state's `_save_folder`; the other handlers check their explicit `folder` or `aifactory_folder`. The internal `_project` helper also checks the guard (`1584–1585`) but is not another endpoint.

**Not every legacy-looking endpoint uses this helper.** Defaults, validation, import/export, recent-projects, operations config load/save, and factory configuration prepare/save have no direct call. Factory configuration has its own downstream root checks (`factory_configuration.py:84–86,136–144`); absence of this helper is not a bypass or a safety guarantee. For example, export can write a supplied path, recent-project recording writes app settings, and operations config save persists SQLite (`api.py:1735–1747,2049–2059,2080–2099,2163–2186`). Catalog scope errors are returned using their status code (`api.py:955–958`).

The shell boundary is stricter: unlike the API's exact-root check, legacy bootstrap workspace checks walk ancestor workspaces and reject a registered sibling/ancestor. Current dual-layout launchers detect that register and route supported registered operations to reviewed manifests instead of accepting legacy create/update arguments. Never bypass this by deleting, renaming, or hiding the register. See [layout routing](../../../bootstrap/lib/layout_router.sh) (`aif_registered_layout_root`, lines 28–48; routing, 68–131) and [bootstrap terminal guards](../../../bootstrap/ui/terminal.sh) (`aif_require_legacy_workspace`, lines 70–82). This distinction covers legacy-only, v2-only, and mixed sibling repositories; there is no automatic merge or fallback.

## Q4: Safe hybrid validation and copy migration

The safe sequence for a not-yet-migrated factory is **read legacy → validate its complete state → review explicit COPY → confirm once → read the new catalog**. In the recorded factory, COPY is already complete: use catalog reads, not another migration.

1. Load project `001` from the explicit legacy root with `POST /api/v1/projects/load`. Retain the full `state`, `_json_source` provenance, and any returned independent `environment_states`.
2. Change only the intended draft fields, then submit the **complete** state to `POST /api/v1/validation`. A tiny `{"enableFunction":"true"}` state would default unrelated settings. Validation is offline; it does not save, check Azure permissions, or prove deployment readiness.
3. Review source coherence: one factory prefix/primary region; unambiguous environment/suffix/subscription/tenant mappings; valid project placements. Do not save a Germany snapshot into the Sweden legacy root before migration, and do not delete conflicting snapshots to force it through.
4. Choose a **different, non-nested, absent or empty `azurefactory` destination**. A sibling satisfies the non-nested rule. In the recording, Git Bash created only the empty directory before the UI COPY review.
5. In **Factory catalog → Advanced → Copy legacy layout**, supply both source and destination. **Do not initialize `register.json` first**: even a zero-factory register makes COPY's destination nonempty. Choose another empty destination rather than deleting existing content.
6. Inspect `can_execute`, blockers, effects, warnings, expiry, exact source/destination, and `migration_receipt.files`. Explicit `source_folder` selects COPY; omitting it is the different in-place catalog-v1 registration workflow.
7. Only an explicitly approved configuration review may be confirmed. COPY rechecks source fingerprints, stages destination projections, and publishes `register.json` last. It is a semantic configuration conversion, not a byte-for-byte backup or repository/template copy.
8. Reload the destination catalog and inspect exact identities/placements. A successful COPY returns `catalog` and `job: null`: no deployment job is expected.

COPY preserves source files, existing logical identities/placements, and supported saved UUIDs; it does not transfer legacy plaintext credentials or prove cloud ownership. Execution toggles/local metadata are normalized. The backend removes its **own destination staging directory** after activation (`azurefactory_migration.py:157`): source preservation is not a promise of zero internal filesystem cleanup. Under a literal no-files-deleted policy, do not replay this operation.

`prepare` can create the destination and store an owner-bound, approximately ten-minute confirmation. It is **not zero-write**. Its top-level `source_revision` is the destination catalog revision; `migration_receipt.source_revision` fingerprints the source inputs. Do not interchange them. Any changed/expired/consumed review requires a new preview, never an automatic retry.

**Do not run legacy template-copy scripts for this tutorial.** The inspected purple script and orange copies have an early `--no-delete` branch (`99–108`), but their normal path removes template content (`134`, `138`), removes `aifactory-usecase-code` (`193`), and overwrites `.gitignore` (`198`). None was run for this documentation review. `--init-azurefactory` is a new-empty-register alternative, not a COPY prerequisite. Even a non-deleting template refresh is not configuration migration and is unnecessary for this already-migrated example; older copied launchers may differ.

Source: Python `factory_catalog.py:239–335,958–994,1166–1205`; `azurefactory_migration.py:12–19,45–82,96–157`; [template-copy source](../../../bootstrap/01-aif-copy-aifactory-templates.sh).

## Phase 1: Function update and project 003

### Existing project 001: keep identity, change service configuration

1. In the recorded legacy wizard, verify project `001`, Dev, suffix `001`, original subscription/tenant, original region, and orchestrator. This is an **update**, not promotion.
2. Tour networking and security first. Distinguish Private access from Hybrid public UI/IP allowlisting with private backend; do not change network posture merely to follow the lesson.
3. Search `enableFunction`; review `"true"`. The recording continues an earlier saved legacy draft, so the toggle is already on. Inspect `functionRuntime`, `functionVersion`, and `skuFunctionDev`.
4. Open **Review & save**, clear search if necessary, and click **Validate**. The captured result passed. Warnings, supported runtime/SKU, regional availability, quota, and real Azure authorization still need separate review.
5. Do not re-save the earlier draft just to imitate the video. For a future approved legacy save, `/projects/save` writes the project snapshot and optional ADO YAML/GHA ENV plus JSON under `config-wizard\project-001`; it does not rewrite root `variables.json` or deploy.
6. After migration use catalog scoped settings, not legacy save against `azurefactory`. A catalog settings preview was demonstrated but **not confirmed** in the API chapter.

Source precedence matters: nested `projects\project-NNN\variables.json` takes precedence over snapshots, then root configuration. A snapshot save is not proof that a later load chose it. Inspect the returned source path without publishing confidential values.

### New project 003: same Dev001 scale set, explicit defaults

1. Open the orange `azurefactory` register, choose the existing factory, then **Add a new project**.
2. Enter `003` and a friendly name. Select only **Development → exact Dev001**; leave Stage/Prod at no additional placement.
3. Prepare, inspect the identity/placement and configuration-only effects, accept the exact review, and confirm once. Reload the register.
4. The recorded result is a saved **draft**, not a new Azure resource group. Do not repeat Add project: `003` already exists.
5. Read scoped settings for the saved project. Recorded version-specific defaults enabled Foundry, AI Search, Cosmos DB, Azure ML, Databricks, Data Factory, and Event Hubs; **Function was false**. Do not describe these as deployed services or universal defaults.

The current network estimate was **seven** full projects. “Common subscriptions for up to 8 projects” is a mode ceiling, not a guaranteed capacity reservation. The allocator estimate is not live Azure subnet inventory. Existing layout-2 projects snapshot configuration at creation; later factory/scale-set settings do not silently propagate into them.

For an unmigrated legacy-only alternative, start a genuine defaults/template draft (`POST /api/v1/state/defaults`, `{"state":{}}`) and deliberately populate its identity and scale-set settings. **Never** duplicate JSON-origin project001 by changing its number or stripping `_json_source`; the source-bound clone guard rejects cross-project identity changes.

## Phase 2: Dedicated subscriptions and Germany

### Compare the scaling choices without rewriting existing networks

- **B) Common subscriptions for up to 8 projects:** multiple projects share environment infrastructure, subject to configured and actual capacity.
- **A) Own subscriptions per project:** configure owner-provided dedicated subscriptions. The mode does not create subscriptions, establish ownership, transfer resources, or allocate quota.
- Switching the wizard mode retains existing addressing. **Apply network defaults** deliberately replaces draft ranges only; it is not an Azure network migration. The recording compares modes without saving over the shared configuration.

### Plan Germany West Central correctly

The requested “West Germany” maps to **Germany West Central**, canonical name **`germanywestcentral`**.

1. A catalog scale set has **no region field**: it inherits its factory's region. Suffix `002` under a Sweden factory is still Sweden.
2. Plan a **separate Germany regional factory identity inside the same register**, with a reviewed unique prefix. Then define Dev suffix `002`, explicit `ado` or `gha`, real dedicated subscription ID, and real tenant ID.
3. Review non-overlapping network-aligned private IPv4 addressing, hub/peering/DNS/access posture, policy, service availability, SKU, permissions, and quota. The example `max_projects: 1` expresses the dedicated-project intent, not a subscription purchase.
4. Only after the regional factory/scale-set definition has been reviewed and saved should a new project such as `004` be added with its exact Dev002 UUID placement. Stage/Prod require their own explicit scale sets, subscription choices, and placements.
5. **Stop here for the recorded scenario:** real dedicated-subscription IDs were not supplied. The incomplete UI definition was blocked; neither the Germany factory/scale set nor project004 was saved or deployed.

Do not fill missing IDs with zeros, copied sample GUIDs, or the old shared subscription and call it “dedicated.” Current inputs require nonzero UUIDs, but UUID syntax alone never proves ownership. Source: `factory_catalog_models.py:149–194,259–353`; `factory_catalog.py:1012–1028`.

## Phase 3: Clone preview

In **Factory catalog → Advanced → Clone configuration**, select the exact source factory, a different prefix, Germany West Central, and **no project definitions**. Leave the version blank to inherit the saved source version; this is not an instruction to assume a particular release.

Prepare and inspect the preview. The real UI and CLI reported copied address ranges overlapping the source factory. Previewability is not deployment readiness. Review subscriptions, networks, regional support, bindings, and intended isolation before any future use.

The clone proposes new configuration identities; it does not copy Azure resources, secrets, resource ownership, or live writer/lock enrollment. This recording stops **without accepting or confirming the clone**.

## Q2: API connection and Windows storage

Use the selected window's **API connection** page, not a guessed port or another running instance's persisted settings.

- `ConnectionSettingsService` stores the base address in MAUI **Preferences**, key `api.base-address`, and the API key in **SecureStorage**, key `api.key` (`Services\ConnectionSettingsService.cs:7–23,35–55`).
- The checked source targets an **unpackaged Windows app** (`ESAIF.ConfigWizard.csproj:41`) with resolved MAUI Essentials **10.0.20** (`obj\project.assets.json`, `Microsoft.Maui.Essentials/10.0.20`). Windows SecureStorage encrypts using `DataProtectionProvider("LOCAL=user")`. This is **not a Windows Credential Manager/PasswordVault implementation**.
- **Unpackaged:** encrypted byte arrays are JSON-serialized to `FileSystem.AppDataDirectory\..\Settings\securestorage.dat`. Preferences are separately JSON-serialized to `...\Settings\preferences.dat`, without SecureStorage encryption. The upstream `FileSystem` resolves AppDataDirectory to `%LOCALAPPDATA%\<sanitized publisher>\<sanitized package>\Data`; both settings files therefore sit in the sibling `Settings` directory. Publisher/package segments come from application metadata, not the factory folder. These are storage descriptions, **not instructions to open the files**.
- **Packaged:** MAUI selects different implementations using `AppInfoUtils.IsPackagedApp`. Preferences use `ApplicationData.Current.LocalSettings` (the root container for this app's default preferences); SecureStorage puts encrypted bytes into an alias-named subcontainer of the same Windows-managed local settings store. It does **not** use the unpackaged `securestorage.dat` / `preferences.dat` files. Packaging can therefore change the backing location without changing the two application keys above.
- Upstream source: [SecureStorage encryption and packaged container](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/SecureStorage/SecureStorage.windows.cs#L20-L108), [unpackaged backing file](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/SecureStorage/SecureStorage.windows.cs#L110-L151), [Preferences implementations](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/Preferences/Preferences.windows.cs#L18-L150), [AppDataDirectory resolution](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/FileSystem/FileSystem.windows.cs#L31-L54).
- `ApiConnectionSession` pins the pair after its first read; a successful explicit save replaces the cached pair (`Services\ApiConnectionSession.cs:13–33`). Shared persisted settings can change when another app instance starts, without repointing an already-initialized session. In this build `ConnectionSettingsService` is a **singleton per app instance** (`MauiProgram.cs:57–61`), not a separate credential store for every hypothetical additional window in one process. Use the intended recording window/app instance; do not combine one instance's port with another's key.
- Pinning is **not a cross-process transaction**: the persistence writer stores/removes `api.key` first and then sets `api.base-address` (`ConnectionSettingsService.cs:43–55`). It protects an initialized session from later shared-setting changes, not an uninitialized reader from every concurrent write. Confirm the intended window's live pair; do not reconstruct it from shared settings files.
- The bundled host chooses an ephemeral loopback port and random per-launch key, passing the latter to its child via `AIFACTORY_API_KEY`, not a command-line argument (`Services\BundledApiHost.cs:33–73,109–114`).
- GUI overrides are `ESAIF_API_BASE_ADDRESS` / `ESAIF_API_KEY`, applied field-by-field when getting the connection, after reading the cached pair. If overrides are deliberately used, keep them coherent. SDK/CLI names are **`AIFACTORY_API_URL` / `AIFACTORY_API_KEY`**; these are not interchangeable.

### macOS, iOS, and Android storage

These are source-backed MAUI **10.0.20 platform implementations**, not a claim that those app builds were run in this Windows recording. They use the same application keys, not the factory repository.

| Platform | `api.base-address` via Preferences | `api.key` via SecureStorage |
|---|---|---|
| macOS through **Mac Catalyst**, and iOS | `NSUserDefaults.StandardUserDefaults`, the OS-managed standard app preferences domain; this app supplies no suite name | Apple **Keychain**, generic-password record with `Account = "api.key"` and `Service = <package-name>.microsoft.maui.essentials.preferences`; default accessibility is `AfterFirstUnlock`. Not a Windows credential store or a plaintext preferences entry. |
| Android | `PreferenceManager.GetDefaultSharedPreferences(context)`, the app-private default shared-preferences store | AndroidX `EncryptedSharedPreferences` in the app-private alias-named preferences store, with the master key protected by Android **KeyStore**; AES-256-SIV preference-key encryption and AES-256-GCM value encryption. The API key is encrypted preference data, not the master key itself. |

The SecureStorage alias comes from `Preferences.GetPrivatePreferencesSharedName("preferences")`, which prefixes the runtime package name. Physical OS-managed paths and sandbox identity depend on the installed package; do not guess a portable Keychain database/plist path or inspect credential files to locate the setting.

Platform sources: [Apple Preferences, lines 153–158](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/Preferences/Preferences.ios.tvos.watchos.macos.cs#L153-L158); [Apple SecureStorage, lines 11–36 and 58–74](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/SecureStorage/SecureStorage.ios.tvos.watchos.macos.cs#L11-L74); [Android Preferences, lines 164–176](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/Preferences/Preferences.android.cs#L164-L176); [Android SecureStorage, lines 126–140](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/SecureStorage/SecureStorage.android.cs#L126-L140); [SecureStorage alias, line 207](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/SecureStorage/SecureStorage.shared.cs#L207); [package-scoped naming, lines 259–260](https://github.com/dotnet/maui/blob/10.0.20/src/Essentials/src/Preferences/Preferences.shared.cs#L259-L260).

**Linux is a separate support question.** This MAUI project has Android, iOS, Mac Catalyst, and Windows targets, but no native Linux desktop target or Linux SecureStorage implementation. The Android target retained when building on Linux is not a Linux desktop app (`ESAIF.ConfigWizard.csproj:4–6`). The bundled host is Windows-only (`Services\BundledApiHost.cs:14–22`). Running a Python API/CLI or Bash separately on Linux does not establish MAUI desktop support, a Linux keyring backend, or portability of Windows-protected manifests.

Off camera, use **Copy key for Swagger**, paste into **Authorize** or a non-echoing local prompt, then clear the clipboard. Do not put the key in a URL, command argument, recording, checked-in JSON, environment dump, or log. This guide was verified from source, not by reading credential values.

## API and CLI lab

### Read-only connection, scope, and full-state validation

Use the existing [stdlib Python SDK/CLI](../../../environment_setup/azurefactory-cli/readme.md). From PowerShell, point Python at your source copy and enter the base address shown by the intended window:

```powershell
$env:PYTHONPATH = 'C:\work\azure-enterprise-scale-ml\environment_setup\azurefactory-cli\src'
$env:AIFACTORY_API_URL = Read-Host 'Base address from the selected API connection page'
python -B -m azurefactory --help
python -B -m azurefactory health
```

Run the following in a local Python session with a real console for `getpass`. These calls read configuration and validate an in-memory draft; none saves configuration or starts a deployment. HTTP POST does not by itself mean a write.

```python
import copy
import getpass
import os
from azurefactory import AzureFactoryClient

api = AzureFactoryClient(
    base_url=os.environ["AIFACTORY_API_URL"],
    api_key=getpass.getpass("Local API key (not echoed): "),
)
catalog_root = r"C:\work\team-factory\azurefactory"
legacy_root = r"C:\work\team-factory\aifactory"
catalog = api.catalog_list(catalog_root)
assert catalog["mode"] == "catalog"

def exactly_one(items):
    matches = list(items)
    if len(matches) != 1:
        raise ValueError("Choose one exact scope; do not guess a first match.")
    return matches[0]

factory_key = input("Exact factory key from your catalog: ")
factory = exactly_one(f for f in catalog["factories"] if f["key"] == factory_key)
scale = exactly_one(s for s in factory["scale_sets"]
                    if s["environment"] == "dev" and s["suffix"] == "001")
project = exactly_one(p for p in factory["projects"] if p["number"] == "003")
settings = api.catalog_settings(catalog_root, factory["id"], scale["id"], project["id"])
print({"mode": catalog["mode"], "project": project["number"],
       "status": project["status"], "enableFunction": settings["state"]["enableFunction"]})

# Preserved legacy source: validation only, not a second active writer.
loaded = api.request("POST", "/api/v1/projects/load",
                     body={"aifactory_folder": legacy_root, "project_number": "001"})
state = copy.deepcopy(loaded["state"])
state["enableFunction"] = "true"
validation = api.request("POST", "/api/v1/validation", body={"state": state})
print({"valid": validation["valid"], "issue_count": len(validation["issues"])})
```

Do not print the complete loaded state/schema defaults: configuration may contain confidential values. Retain the original `loaded` response, including provenance and environment-specific states. Review validation issues privately. The SDK sends `X-API-Key`, disables proxies/redirects, and redacts API errors; that does not make arbitrary application output safe to publish.

### Reviewed configuration request fragments — NOT ready to execute

**Reference only.** Each JSON object below is a request-body template for `POST /api/v1/factory-catalog/prepare`, not an executed command. Replace placeholders with owner-reviewed real IDs and the **fresh** catalog revision; retain exact environment scope. Never automatically chain prepare to confirm. Preparing stores local confirmation bookkeeping even when configuration remains unchanged.

**COPY, for a different not-yet-migrated factory only** — omit `expected_revision` on an initially absent destination; do not repeat the completed recording's COPY:

```json
{"contract_version":1,"action":"migrate",
 "source_folder":"C:\\work\\team-factory\\aifactory",
 "folder":"C:\\work\\team-factory\\azurefactory"}
```

**Project001 Function settings preview** — use catalog UUIDs, not `"001"`:

```json
{"contract_version":1,"folder":"<CATALOG_ROOT>","expected_revision":"<FRESH_REVISION>",
 "action":"configure-settings","factory_id":"<FACTORY_UUID>",
 "scale_set_id":"<DEV001_UUID>","project_id":"<PROJECT001_UUID>",
 "settings":{"enableFunction":"true"}}
```

**New project with only Dev001 placement** — `003` is already saved in the recorded factory; do not repeat it there:

```json
{"contract_version":1,"folder":"<CATALOG_ROOT>","expected_revision":"<FRESH_REVISION>",
 "action":"add-project","factory_id":"<FACTORY_UUID>",
 "project":{"number":"003","display_name":"Project 003",
 "placements":[{"environment":"dev","scale_set_id":"<DEV001_UUID>"}]}}
```

**Germany regional factory plus dedicated Dev002** — planning only; all identity/network placeholders remain unresolved:

```json
{"contract_version":1,"folder":"<CATALOG_ROOT>","expected_revision":"<FRESH_REVISION>",
 "action":"create-factory","factory_kind":"ai",
 "target_prefix":"<UNIQUE_LOWERCASE_PREFIX>","target_region":"germanywestcentral",
 "scale_sets":[{"environment":"dev","suffix":"002",
 "subscription_id":"<REAL_DEDICATED_SUBSCRIPTION_UUID>","tenant_id":"<REAL_TENANT_UUID>",
 "orchestrator":"ado","network":{"vnet_cidr":"<REVIEWED_NONOVERLAPPING_CIDR>","max_projects":1}}]}
```

If a Germany factory already exists, use `action:"create-scale-set"`, its `factory_id`, and the same `scale_sets` structure; omit `factory_kind`, `target_prefix`, and `target_region`. After an approved save and fresh catalog read, add unused project `004` with the **returned Dev002 UUID**, not its suffix. `configure-settings` cannot change immutable identity, tenant/subscription, region, placement, or version fields.

**Clone preview only:**

```json
{"contract_version":1,"folder":"<CATALOG_ROOT>","expected_revision":"<FRESH_REVISION>",
 "action":"clone","factory_id":"<SOURCE_FACTORY_UUID>",
 "target_prefix":"<DIFFERENT_PREFIX>","target_region":"germanywestcentral","include_projects":"none"}
```

**Confirmation boundary, described but not automated:** `POST /api/v1/factory-catalog/confirm` takes `{"contract_version":1,"folder":"<SAME_ROOT>","confirmation_id":"<REVIEWED_CONFIRMATION_UUID>"}`. Confirm only an independently approved configuration review with correct action/scope, `operation_mode:"configuration"`, `can_execute:true`, no blockers, and unexpired receipt. Do not confirm this tutorial's clone, Germany plan, or any runtime/deletion action.

For a future approved **legacy** Function save, the distinct `/api/v1/projects/save` body is `{"state":<FULL_REVIEWED_STATE>,"write_variables":true}`, with `_save_folder` inside state set to the intended legacy root. This is not a patch, not create-only, and not executed in the API recording. Wizard booleans commonly use strings such as `"true"`; transport controls such as `write_variables` and `patch` are JSON booleans.

### CLI equivalents and ADO/GHA boundary

The protected CLI requires a process-local `AIFACTORY_API_KEY` supplied by your approved secret-handling mechanism, never a recorded literal or `--api-key` argument. The following catalog commands are reads; output can still expose private configuration metadata:

```powershell
$root = 'C:\work\team-factory\azurefactory'
python -B -m azurefactory catalog list --folder $root
python -B -m azurefactory catalog jobs --folder $root
```

This separate **preview-only fragment is not ready to run** until its variables come from fresh reviewed scope. It creates a local review receipt on the server; there is no invented `--dry-run` flag:

```powershell
python -B -m azurefactory factory clone --folder $root `
  --factory-id $factoryId --expected-revision $freshRevision `
  --prefix $differentPrefix --region germanywestcentral --include-projects none
```

Read launcher help from the installed copies, as demonstrated; source-copy equivalents from an orange repository are:

```powershell
bash '.\azure-enterprise-scale-ml\bootstrap\ADO-azurefactory.sh' --help
bash '.\azure-enterprise-scale-ml\bootstrap\GHA-azurefactory.sh' --help
```

Both expose **`inspect`** and **`execute`**. An optional future local inspection uses `inspect --protected-manifest <REVIEWED_DPAPI_PATH>` with a real, correctly routed protected manifest, not ordinary JSON. Help was executed; manifest inspection was **explained, not performed**. Inspection does not authenticate or prove Azure readiness. Execute additionally requires source/execution roots and a receipt and can change Azure; never substitute it for inspect.

`--non-interactive` suppresses prompts, not effects. `--no-wait` still dispatches. `--prepare-only` is not a universal zero-write guarantee. Generic CLI POST requests require `--write --yes` even for validation; the SDK's explicit validation request above makes the boundary clearer.

### Additional API workflows: choose by root and effect

| Workflow | Current contract | Important limit |
|---|---|---|
| Discovery | `GET /health`, `/openapi.json`; protected `GET /api/v1/schema` | Read the running server's contract; not a deployment readiness test |
| Legacy scope | `POST /api/v1/startup/load`, `/api/v1/projects`, `/api/v1/projects/load`, `/api/v1/scale-sets`, `/api/v1/scale-sets/load` with their documented body fields | Startup loading chooses source identity, not a requested project hint; exact project loading uses the project load route |
| Defaults / validation / network | `POST /api/v1/state/defaults`, `/api/v1/validation`, `/api/v1/network/placement/preview` with `state` | Offline draft operations; no live network capacity guarantee |
| Import / export | `POST /api/v1/import`, `/api/v1/export` | Import retains source provenance; explicit export destinations write files; an inline JSON preview is not a source-bound save |
| Registered settings / ARM parameters | `GET /api/v1/factory-catalog/settings`, `/api/v1/factory-catalog/parameters` with exact selectors | Typed edits use `/api/v1/factory-catalog/parameters/prepare` and `/api/v1/factory-catalog/parameters/confirm`, not the generic confirmation route |
| Local factory/scale-set drafts | `POST /api/v1/factories/configuration/prepare`, `/api/v1/factories/configuration/save` | Separate legacy configuration-only workflow; do not mix a new Germany identity into the coherent source before COPY |
| Registered placements / bindings | Catalog prepare actions `add-project-placements`, `configure-binding` | Additional placements are not promotion; saved bindings are not verified enrollment or ownership |
| Catalog jobs / output | `GET /api/v1/factory-catalog/jobs`, `/api/v1/factory-catalog/jobs/{job_id}`, `/api/v1/factory-catalog/terminal` | Include exact `folder`, and `job_id`/cursor for terminal; terminal input/stop are not reads |
| Local legacy overview | `POST /api/v1/operations/overview` with `aifactory_folder`, `include_azure:false`, `force_refresh:false` | Azure inventory is a separate external read when explicitly enabled; catalog inventory is not a fictional `/inventory` endpoint |

These are a workflow reference, **not a claim that every route was executed**. The live API segment called health, catalog read, legacy project load/full validation, scoped settings read/prepare, OpenAPI read, clone prepare through CLI, launcher help, and catalog jobs read.

### All API: recorded contract inventory

The recording's OpenAPI inventory contains **83 HTTP operations across 81 unique paths**, not 83 executed calls. This list was checked entry-for-entry against the captured `api-route-inventory.json`; the recording's API showcase completion marker is not evidence that every operation was exercised. The two dual-method paths are `/api/v1/simple-mode/options` and `/api/v1/recent-projects`. `GET /openapi.json` retrieves the contract itself and is not an additional operation in this inventory.

The list below is reference text, **not a script or a replay checklist**. In particular, login/logout, saves, starts, confirmations, synchronization, terminal controls, and deletions can have real effects. Their presence here does not authorize execution. Use live Swagger/OpenAPI for request schemas and the installed version's capability boundaries; do not bulk-call the inventory.

<details>
<summary>Show all 83 recorded method/path entries</summary>

```text
POST /api/v1/azure/auth/status
POST /api/v1/azure/auth/login
POST /api/v1/azure/auth/logout
GET /api/v1/azure/auth/operations/{operation_id}
POST /api/v1/automation-reports/options
POST /api/v1/automation-reports/prepare
POST /api/v1/automation-reports/start
POST /api/v1/automation-reports/jobs/{job_id}
POST /api/v1/automation-reports/latest
GET /api/v1/factory-catalog
GET /api/v1/factory-catalog/settings
GET /api/v1/factory-catalog/parameters
POST /api/v1/factory-catalog/parameters/prepare
POST /api/v1/factory-catalog/parameters/confirm
POST /api/v1/factory-catalog/prepare
POST /api/v1/factory-catalog/confirm
GET /api/v1/factory-catalog/jobs
GET /api/v1/factory-catalog/jobs/{job_id}
GET /api/v1/factory-catalog/terminal
POST /api/v1/factory-catalog/terminal/input
POST /api/v1/factory-catalog/terminal/resize
POST /api/v1/factory-catalog/terminal/stop
GET /api/v1/operations/project-deployments
POST /api/v1/operations/project-deployments/plan
POST /api/v1/operations/project-deployments/prepare
POST /api/v1/operations/project-deployments/start
POST /api/v1/operations/project-deployments/reconcile/prepare
POST /api/v1/operations/project-deployments/reconcile
GET /api/v1/operations/project-deployments/terminal
POST /api/v1/operations/project-deployments/terminal/input
POST /api/v1/operations/project-deployments/terminal/resize
GET /api/v1/creation/capabilities
POST /api/v1/creation/bootstrap/config
POST /api/v1/creation/bootstrap/prepare
POST /api/v1/creation/bootstrap/start
GET /api/v1/creation/bootstrap/jobs/{job_id}
GET /api/v1/simple-mode/options
POST /api/v1/simple-mode/options
POST /api/v1/simple-mode/prepare
POST /api/v1/simple-mode/start
GET /api/v1/simple-mode/jobs/{job_id}
POST /api/v1/simple-mode/jobs/{job_id}/status
POST /api/v1/analytics/current-factory
POST /api/v1/tickets/list
POST /api/v1/tickets/resource-group/parse
POST /api/v1/tickets/create
POST /api/v1/tickets/update
POST /api/v1/tickets/quota/update
POST /api/v1/tickets/connections/list
POST /api/v1/tickets/connections/save
POST /api/v1/tickets/sync/preview
POST /api/v1/tickets/sync
GET /health
GET /api/v1/schema
POST /api/v1/state/defaults
POST /api/v1/network/placement/preview
POST /api/v1/validation
POST /api/v1/import
POST /api/v1/export
POST /api/v1/startup/load
POST /api/v1/projects
POST /api/v1/projects/verify-resource-groups
POST /api/v1/projects/load
POST /api/v1/projects/save
POST /api/v1/projects/delete
POST /api/v1/scale-sets
POST /api/v1/scale-sets/verify-resource-groups
POST /api/v1/scale-sets/load
POST /api/v1/scale-sets/save
POST /api/v1/scale-sets/delete
GET /api/v1/recent-projects
POST /api/v1/recent-projects
POST /api/v1/factories/configuration/prepare
POST /api/v1/factories/configuration/save
POST /api/v1/operations/overview
GET /api/v1/operations/regions
POST /api/v1/operations/region-findings/report
POST /api/v1/operations/region-findings/import
POST /api/v1/operations/config/load
POST /api/v1/operations/config/save
POST /api/v1/operations/factory-actions
POST /api/v1/operations/project-actions
POST /api/v1/operations/prompts/search
```

</details>

## Deployment, promotion, operations, and handoff

**Explained, never executed here:** legacy update planning uses `/api/v1/operations/project-deployments/plan` with `folder`, `project_number:"001"`, `source_environment:"dev"`, `target_environment:"dev"`, `operation:"update"`, `patch:false`. Promotion planning uses `operation:"deploy"` and a different allowed target (`dev→stage`, `stage→prod`, or `dev→prod`), not a made-up `promote` operation.

Planning persists a local draft and checks authenticated owner/source inventory. `/prepare` takes its `draft_id` and can perform external read-only authorization/inventory checks. CLI equivalents are `legacy plan ... --operation update --source-env dev --target-env dev --no-patch` and `legacy prepare ... --draft-id <DRAFT_UUID> --no-patch`. These are not zero-write/offline demos. **Do not call `/start`.**

Registered roots instead use catalog `prepare` with `action:"deploy"` and exact factory/scale-set, optional project/version selectors. Runtime preparation checks bindings, identities, inventory, source version, and blockers. Runtime confirmation can dispatch; configuration confirmation cannot be treated as deployment success.

Deletion is also a real boundary: catalog `delete-factory` / `delete-scale-set` are runtime actions requiring ownership and reviewed scope. Legacy `/projects/delete` removes a selected local snapshot, not Azure resources. Neither is part of this tutorial; do not use deletion to fix a conflict or clean up a failed exercise.

In **Concept animations**, use Play, Back, Next, the step picker, speed, and reduced-motion controls. Promotion moves reviewed versioned artifacts through isolated environments. DataOps curates trusted data; MLOps adds training/evaluation/registration/serving; RAG retrieves context during inference rather than training a model; fine-tuning changes model behavior through training. Combined lessons show separate quality and release gates. Playback performs none of those workloads.

Before any later authorized execution, independently verify:

- Exact root, catalog revision, factory/project/scale-set UUIDs, environment, version, source inputs, and expiry.
- Correct Azure account, tenant, dedicated/shared subscription intent, permissions/PIM/policy, and pipeline route/binding.
- Network allocation, real available capacity, DNS/access, regional services, runtime/SKU support, and quota.
- Approval of the exact effects and receipt; no automatic confirm, input retry, or rerun after uncertainty.
- After an approved future run, inspect the pipeline result and actual resources. Script exit zero or a saved draft is not cloud success.

**Handoff:** preserve both roots but maintain one active writer; use the registered folder for ongoing configuration. Project003 is saved Dev-only; project001's Function was reviewed/validated, not deployed; Germany/project004 still need prerequisites; clone remains unconfirmed.

### Source map and further reading

Verified against the recording evidence and source on 16 September 2026; file/line references are snapshot references and can shift in later releases.

| Topic | Authoritative source |
|---|---|
| API roots and routes | Python backend `src\api.py:1122–1214,1623–1682,1750–1877,2080–2116` |
| Catalog types, region, scope, confirmation | Python `src\factory_catalog_models.py:149–194,259–366`; `src\factory_catalog.py:958–1209` |
| Root conflicts / COPY | Python `src\catalog_storage.py:118–126`; `src\azurefactory_migration.py:12–19,45–82,96–157` |
| Source-preserving JSON edit | Python `src\json_roundtrip.py:100–137`; API full-state load/validate/save above |
| Tutorial and connection | MAUI `src\ESAIF.ConfigWizard\Services\ConfigurationTutorial.cs`, `ConnectionSettingsService.cs`, `ApiConnectionSession.cs`, `BundledApiHost.cs` |
| Real SDK/CLI | [Client source](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py), [CLI source](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py), [usage examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md) |
| Scoped orchestrators | [ADO launcher](../../../bootstrap/ADO-azurefactory.sh), [GHA launcher](../../../bootstrap/GHA-azurefactory.sh), [lifecycle launcher](../../../bootstrap/AIFactory-lifecycle.sh) |
| Wider setup and lifecycle | [End-to-end setup](24-end-2-end-setup.md), [update an AI Factory](26-update-AIFactory.md), [personas](25-personas-aifactory.md) |

</details>