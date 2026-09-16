# Current Work Assignments

Updated: 2026-09-16, 20:19 SAST. This is a point-in-time handoff, not a live deployment inventory.

## Objective and priority

Restore Elle's real Private memory/personality, Shared Wisdom, and Microsoft 365 capabilities in the published agent. Release each capability as soon as its own acceptance gates pass. Improve the elephant icon's small-size legibility independently. Do not wait for specialist tools or artwork to ship working Private tools.

The user requested incremental commits and testing. The user will launch the swarm; no workers are assumed to be running.

## Verified starting point

| Surface | State at handoff |
| --- | --- |
| Consumer-facing agent | `elle`, hosted in Foundry, using `model-router`; 100% of traffic remains pinned to agent version **3**. |
| Live toolbox | `elle-tools`, default version **3**; web search, Python/code interpreter, Microsoft Learn, and read-only Azure only. |
| Private candidate | Toolbox version **4** preserves those four sources and adds `elle_private` through `elle-private-oauth`. It is NOT the default and no hosted agent candidate using it has been promoted. |
| Private authorization | A dedicated tenant-pinned OAuth2 client/connection exists. DemoUser1 completed authorization. A final browser callback said "Code not found", but subsequent discovery progressed past consent to the MCP server. Do not assume that callback means the connection was lost. |
| Actual next failure | Candidate toolbox discovery returns `-32007`, with an `HTTP_405` source error. Backend logs show a first POST rejected before an RPC result, then GET `/mcp`, then fallback POST `initialize` rejected as invalid parameters. The first POST rejection still needs to be identified. |
| Backend deployment | Both canonical Private and Wisdom services still use image tag `353b5eb7eb56d4415c4644fcdc72dc0b71ac615c`. |
| Diagnostic image | Registry build **dtg** succeeded for tag `c2cb998974c04107dd462b9d0a1fb4193226ea88`. It adds fixed-message body-rejection diagnostics and repairs the Docker build-context allowlist. It is NOT deployed. No need to rebuild it just to obtain that diagnostic. |
| Hosted runtime | `foundry-agent/main.py` still creates one long-lived `FoundryToolbox`. Repeated/concurrent user-context handling has not passed acceptance. |
| App branding | App package **1.0.2** has the approved elephant color/outline icons. Admin publication completed; DemoUser1's rendered icon bytes matched the approved PNG. The remaining problem is legibility at approximately 20-32 pixels, not a missing upload. |
| Runtime access | Preserve existing `responses` and `activity` protocols, `Entra` and `BotServiceRbac` authorization, and explicit version routing. Do not infer runtime authorization from the app's Tenant catalog scope. |
| Specialist tools | Azure SQL, Speech, and Flint chart integration are not accepted or live. Discovery/preparation may proceed independently but must not delay core restoration. |

There are **four tool sources**, not necessarily four individual callable tools. Microsoft Learn, for example, exposes several functions. Prompt front matter naming tools does not register them.

## Ownership and concurrency rules

1. Each worker uses its own branch/worktree, named `swarm/<agent-id>`. Never let several workers edit the same checkout, index, dependency environment, or authentication cache.
2. Agent R is the only writer to `main`, this assignment file, live agent routing, canonical toolbox defaults, canonical Container App revisions, shared CI, and app publication. Workers return commit SHAs, evidence, and exact proposed deployment changes.
3. Workers may read all relevant source, but edit only their assigned files. Request a handoff before touching another owner's files. New shared helpers belong to one agreed owner, not parallel copies.
4. Agent C coordinates interactive sign-in and the shared browser. Other agents request a sign-in slot rather than navigating away or changing the operator's account. Use isolated per-user CLI caches and verify the exact account before every live test.
5. No shared-user tokens, model-supplied user IDs as authorization, app-only private-memory shortcuts, disabled token validation, broadened user allowlists, or secrets in source/logs. Derive memory ownership from validated delegated identity.
6. Use only synthetic acceptance records; do not dump private memories, conversations, tokens, or consent URLs into commits or this public repository. Clean up only records created by the test.
7. Commit focused, passing steps. Do not force-push, reset others' work, mass-delete caches, or redeploy both backends merely because the existing deployment script does so.
8. Re-read live versions before every change. Record the previous image/version and rollback command. Agent R must preserve unrelated metadata, permissions, channels, and installed app identity.
9. User-visible publication, outbound messages, permission expansion, and new artwork require an exact preview and explicit user approval. The previous artwork approval does not approve a redesigned icon.

## Assignment register

All named agents below are proposed assignments, initially unclaimed. Agent R records claims before work starts.

| Agent | Priority / start | Exclusive write scope | Dependencies for completion |
| --- | --- | --- | --- |
| **A - MCP transport** | P0; start now | `rust/src/server.rs`, `rust/src/mcp.rs`, `rust/tests/memory_flow.rs`, new transport tests under `rust/tests/` | R deploys diagnostic/candidate image for live evidence; no dependency on B to diagnose. |
| **B - Hosted request isolation** | P0; start now, parallel with A | `foundry-agent/main.py`, `foundry-agent/requirements.txt`, new `request_scoped_tools.py` and `test_runtime_*.py` | Independent local reproduction; C supplies authorized identities for hosted acceptance; R packages new runtime modules. |
| **C - Private OAuth and acceptance** | P0; start now, parallel with A/B | `configure_private_oauth.py`, `probe_toolbox.py`, their tests, new `private_acceptance.py` and `test_private_acceptance.py`, all under `foundry-agent/` | Direct end-to-end Private gate needs A; hosted/multi-user gate needs A+B+R candidate. |
| **D - Shared Wisdom** | P1; prepare now | New `foundry-agent/configure_wisdom_oauth.py`, `wisdom_acceptance.py`, and `test_wisdom_*.py` | Agreed OAuth helper contract with C; live transport gate needs A; hosted gate needs B; promotion follows Private. |
| **E - Work IQ** | P1; prepare now | New `foundry-agent/configure_workiq.py`, `workiq_acceptance.py`, and `test_workiq_*.py` | B for hosted user context; C for browser/sign-in coordination. Direct service diagnosis is independent of A/D. |
| **F - Small-size branding** | P1; start now, fully parallel | New candidates under `docs/images/elle-app-legible-*`; preview/export script under `scripts/` | User selects the artwork; R publishes it. No dependency on tool repairs. |
| **G-SQL - SQL capability** | P2; discovery now | New isolated `integrations/sql/` implementation/tests | Exact approved database/entity scope and auth design; R integrates only after acceptance. |
| **G-Speech - Speech capability** | P2; discovery now | New isolated `integrations/speech/` implementation/tests | Confirm actual supported server, storage/auth requirements, cost and network constraints; R integrates later. |
| **G-Chart - Flint capability** | P2; discovery now | New isolated `integrations/chart/` implementation/tests | Confirm existing endpoint/deployment; safe image-return and authentication contract; R integrates later. |
| **R - Integration and release** | P0; start now | `deploy.py`, `test_deploy.py`, `requirements-deploy.txt`, `.github/workflows/`, `scripts/deploy.ps1`, `Dockerfile`, `.dockerignore`, `README.md`, `ELLE_COPILOT_STUDIO_PROMPT.md`, canonical app icons, this file | Integrate each worker's accepted result; serialize all canonical deployments and promotions. |

The register's abbreviated file names refer to `foundry-agent/` unless a full repository-relative path is shown.

## A - Repair the real transport failure

Start with `server.rs::read_json_body`, `handle_request`, and `mcp.rs` initialization handling. Coordinate with R to deploy the already-built diagnostic image to **Private only**. Capture redacted HTTP status/framing diagnostics from a fresh authorized v4 discovery.

The server currently requires a single Content-Length, rejects Transfer-Encoding, returns JSON responses, and returns 405 for GET `/mcp`. Under Streamable HTTP, a server may legitimately reject a standalone GET stream with 405. Do not add SSE or weaken initialization validation merely to hide the last error in a fallback chain.

Determine whether the first request is rejected for framing, media negotiation, protocol version, or something else. If valid chunked requests are the cause, reuse the existing HTTP parser's decoded body reader, retain a strict decoded-size bound, reject ambiguous/conflicting framing, and cover malformed/truncated/oversized requests. Do not implement a second handwritten HTTP parser.

Deliver focused regression tests that reproduce the actual failing request shape, successful initialize/notification/tools-list behavior, and unchanged unauthorized/invalid-origin rejection. Keep logs free of request payloads, Authorization values, or memory content. Acceptance requires Foundry toolbox discovery against Private, not only a direct curl or local unit test.

## B - Make the hosted tool lifetime request-safe

Investigate the installed SDK and [agent-framework issue 7690](https://github.com/microsoft/agent-framework/issues/7690). The reported failure is a long-lived MCP writer task retaining the first request's ContextVar and forwarding a stale `x-agent-foundry-call-id`.

Reproduce before selecting a remedy. Prefer a verified supported SDK fix or a supported per-request tool/session lifetime. Avoid monkey patches, global mutable headers, a shared user credential, or serializing every user behind one global lock as a substitute for correct isolation.

Keep the agent identity at the agent-to-toolbox boundary; preserve the platform's opaque call context. Test two sequential turns, concurrent users, cancellation, errors, cleanup, and post-consent retry. Streaming tools must remain open until streaming completes; closing them immediately after returning a lazy response stream is not sufficient.

Surface authorization-required/unavailable capability states explicitly. A missing optional connection must not be disguised as success or falsely advertised as an available tool. Do not silently remove every failing source to make the chat appear repaired.

Deliver exact dependency versions and test results to R. **Packaging trap:** `deploy.py::package_source()` currently includes only `main.py`, `requirements.txt`, and generated `instructions.txt`. R must include and test any added runtime modules.

## C - Complete Private under real user identities

Reuse `elle-private-oauth`; do not revert to the old `elle-private` UserEntraToken connection. The API expects a valid delegated v2 token, its configured audience, `access_as_user`, the configured tenant, and an allowed demo-user object ID.

Check the existing DemoUser1 connection before launching consent again. A callback error is not definitive: the follow-up probe already progressed to the server. Never complete a consent link created under an administrator's identity using a demo user's account.

Build a repeatable synthetic acceptance harness for the seven expected private functions:

`elle_context`, `elle_list_memories`, `elle_remember`, `elle_correct`, `elle_forget`, `elle_personality`, `elle_set_personality`.

Use returned tool names and schemas; source prefixes may change exposed names. Verify discovery, remember, read-after-write, semantic recall, version-checked correction/deletion, and personality retrieval. Exercise personality mutation only on an explicitly designated disposable fixture and restore its original state; do not overwrite the user's real profile.

Test DemoUser1 and DemoUser2 independently. Demonstrate that one user's uniquely marked record cannot be retrieved, corrected, or deleted by the other, and that repeated/concurrent hosted turns preserve the correct partition. Existing token/tenant/scope-denial tests must remain passing.

No real Microsoft 365 content or raw private results in test logs. Return pass/fail evidence, request identifiers, sanitized failure categories, and synthetic cleanup outcome. A tool inventory written by the model alone is not acceptance evidence.

## D - Restore Shared Wisdom separately

Private and Wisdom are separate MCP servers with disjoint storage roles. Reuse a reviewed OAuth helper contract from C rather than editing C's provisioning code concurrently. Prepare a separate user-authorized connection for Wisdom; preserve the existing reviewed catalog and contributor screening.

Expected functions: `elle_shared_wisdom` and `elle_contribute_wisdom`. Verify catalog discovery/search and that private tools/data remain inaccessible through this server. Test contribution screening locally; publish a synthetic shared lesson only after preview/approval, not as an unannounced demo side effect.

Return the candidate connection name and test evidence to R. The same transport binary may fix both services, but R updates and checks the Wisdom service separately. Do not promote a combined Private/Wisdom version until Private's release gate is complete.

## E - Restore the intended Work IQ capability

Identify which contract is being integrated: Work IQ A2A (`work_iq_preview`), Work IQ MCP, or individual Agent365/M365 tool servers. Do not claim that a single Work IQ ask endpoint exposes every direct mail/calendar/chat tool.

Use current supported documentation and real connection discovery. The previous `workiq` UserEntraToken source was removed with the two Elle sources after initialization failures. Custom OAuth is documented for Work IQ; first-party token passthrough has service-specific support and audience requirements. Do not copy a custom-API audience setting and assume it works.

Confirm least-privilege delegated scopes, actual consent, licensing/billing prerequisites, and per-user access. Test harmless, read-only user-context operations and explicit handling of unavailable services. Do not send mail/messages, create meetings, or expose private data as a smoke test.

Deliver the supported tool inventory, the exact remaining gaps against the intended Microsoft 365 experience, consent prerequisites, and an independently testable candidate. R adds it without losing already-restored Private/Wisdom tools.

## F - Make the elephant recognizable at app-icon size

Use the committed `docs/images/elle-m365-color-192.png` and `elle-m365-outline-32.png` as the portable starting assets. Higher-resolution local drafts may exist on the operator's machine but are not guaranteed to be in a fresh clone.

Keep the approved baby-elephant identity and palette. Produce a tighter head/ears/trunk composition, reduce outer whitespace and decorative detail, and improve silhouette/contrast. Changing PNG resolution alone will not enlarge the host application's 20-32px icon slot.

Deliver at most two candidates and a comparison at **20, 24, 32, and 192 pixels**, at native display scale on light and dark backgrounds. The elephant's face, ears, and trunk must remain distinguishable at 24px. Provide a real 192x192 color PNG and a visible, white-on-transparent 32x32 outline PNG; never an empty outline.

Do not overwrite canonical assets or publish before the user chooses the new composition. R reads current publish defaults and increments the app package version (likely 1.0.3; verify first), preserving the same title/app identity and metadata. App-package versions and hosted-agent versions are independent.

## G - Specialist tools without blocking the core release

Each G worker first inventories what actually exists and reports the concrete missing prerequisite. Avoid duplicate servers or speculative cloud provisioning.

SQL needs an explicitly authorized database, exposed entities, and identity policy; do not guess or expose all databases. Speech needs supported auth, storage, network, and cost handling without putting keys or SAS values in logs/source. Flint must return usable rendered artifacts rather than inaccessible container file paths and must not expose arbitrary host file access.

Each worker owns only its integration directory, produces isolated tests/configuration, and hands connection/tool definitions to R. No worker changes the live toolbox or shared requirements directly.

## R - Critical path, sequencing, and release gates

The parallel work graph is:

```text
A transport ------------+
B request isolation ----+--> C Private end-to-end --> R Private release
C auth/test preparation-+

D Wisdom preparation ------> A+B accepted + Private release --> R Wisdom release
E Work IQ preparation -----> B accepted + user consent ------> R Work IQ release
F icon candidates ---------> user selection ----------------> R icon publication
G specialist discovery ---> approved scope + acceptance ----> later independent releases
```

Start A, B, C, D, E, and F together. With fewer workers, prioritize A+B+C and let R handle integration; artwork and specialists must not stall the tool critical path. Work IQ preparation does not require waiting for Wisdom; only writes to the canonical live deployment must be serialized.

1. Re-read live routing, toolbox defaults, backend images, and pending build runs. Preserve the known-good v3 rollback and deploy the completed diagnostic image only where needed.
2. Merge A/B/C passing commits. Reconcile runtime/deployment SDK constraints using separate environments, include new modules in the hosted ZIP, and update the corresponding CI jobs. Current deployment SDK is pinned to 2.6.1; the previously resolved runtime required a different projects SDK range. Do not install both requirement sets into one environment.
3. Stage an explicit Private-only candidate preserving all four healthy sources. Use toolbox v4 only if it still contains the intended connection/configuration. Never route consumers to an untested newest version.
4. Pass direct Private, hosted sequential/concurrent user-isolation, and actual Teams/Copilot channel tests. A CLI smoke response does not prove channel identity propagation.
5. Promote Private and verify real tool calls plus a fresh consumer conversation. If its gate fails, do not promote; report the exact blocker. On regression, route back to the captured previous version.
6. Add Wisdom, then Work IQ, as separate candidate/test/promotion/commit steps. Build each toolbox from the immediately preceding accepted version, not the unchanged default v3. If dependencies permit Work IQ to finish first, release it independently without dropping accepted tools.
7. Publish the selected icon separately. Complete any pending tenant-admin approval, then refresh the actual client and compare the served icon/version with the approved file. An immediate Foundry "approved" value proved stale during the previous update; the consumer-facing result is the final gate.
8. After each accepted release, push the integrated passing commits normally and update this register with commit, toolbox version, agent version, backend image, tests, and rollback. Never mark the whole task complete because one capability works.

### Existing commands and important limitations

Run these from the repository root using the appropriate environment's Python:

```powershell
python -m unittest discover -s foundry-agent -p "test_*.py"
python foundry-agent\probe_toolbox.py --version 4
python foundry-agent\deploy.py --toolbox-version 4
python foundry-agent\deploy.py --test-version <candidate-agent-version>
python foundry-agent\deploy.py --promote-version <accepted-agent-version> --expected-live-version <current-agent-version>
```

The angle-bracket values above are placeholders, not literal arguments. `probe_toolbox.py` uses the current Azure CLI identity and can output a personal consent URL; keep that output out of public logs. `--test-version` creates a version-pinned hosted session, uses Microsoft Learn, and stops the session; it is NOT a Private/Wisdom/Work IQ acceptance test.

For additional sources, use `--add-mcp NAME=CONNECTION --base-toolbox-version VERSION` with values returned from discovery. The current CLI only adds MCP sources; a Work IQ A2A source requires a deliberate, tested extension by R. Promoting an agent does not automatically promote the toolbox default. Keep the agent's explicit toolbox pin authoritative and coordinate any default change.

Use existing Rust tests (`cargo test --locked` with targeted selectors), formatting, and Clippy for changed Rust behavior. Windows builds require the installed Visual C++ environment in the same shell invocation. Build a clean committed source snapshot for ACR rather than scanning a synced working tree containing large caches.

### Known pitfalls and work to preserve

- The diagnostic image build completed even though the initiating shell sequence was interrupted. Inspect registry runs before paying for another identical build.
- Ignored local Python environments disappeared during this session. Do not rely on operator-specific `.local` paths; restore missing dependencies in an isolated environment outside the synced tree.
- `scripts/deploy.ps1` currently updates **both** backends. R must provide a deliberate single-service deployment path for the requested incremental rollout.
- Keep the current Private API's authentication and user isolation intact. GET 405 by itself is not proof that an MCP server needs SSE.
- Leave the operator's unrelated Power Platform connector-title edit and alternative icon drafts untouched.
- This GitHub repository is currently **public**. Do not paste operator-specific account details, tenant/resource identifiers, endpoint inventories, tokens, private chat excerpts, or acceptance-result payloads into this file.

## Handoff format and completion ledger

Each agent reports: **status; branch and commit SHA; owned files changed; exact tests and results; live changes (or none); sanitized blocker; dependencies unblocked; rollback; next owner**.

Only R edits this ledger. Replace `Unclaimed` with the actual worker identifier before assigning work.

| Agent | Claim / status | Commit / evidence | Next gate |
| --- | --- | --- | --- |
| A | Unclaimed | Diagnostic image c2cb998 available, not deployed | Identify first authorized POST rejection |
| B | Unclaimed | Existing global toolbox lifetime not accepted | Reproduce and fix current-request context |
| C | Unclaimed | OAuth/discovery tooling 3202e6d; consent progressed | Private read/write/isolation after transport fix |
| D | Unclaimed | Existing service/catalog, not attached live | Separate OAuth and Wisdom acceptance |
| E | Unclaimed | Existing excluded connection, not accepted | Confirm supported Work IQ contract/auth |
| F | Unclaimed | Published icons 0b1b471, app 1.0.2 | Native-size candidates and user selection |
| G-SQL | Unclaimed | Scope not yet accepted | Authorized database/entity selection |
| G-Speech | Unclaimed | Not yet accepted | Endpoint/auth/storage inventory |
| G-Chart | Unclaimed | Not yet accepted | Endpoint/artifact/auth inventory |
| R | Unclaimed | Staging gates 915845a; live still v3 | Integrate and release Private first |
