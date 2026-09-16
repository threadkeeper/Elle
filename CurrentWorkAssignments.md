# Current Work Assignments

Updated: 2026-09-16, 20:36 SAST. This is a point-in-time handoff, not a live deployment inventory.

## Objective and priority

Restore Elle's real Private memory/personality, Shared Wisdom, and Microsoft 365 capabilities in the published agent. Release each capability as soon as its own acceptance gates pass. Improve the elephant icon's small-size legibility independently. Do not wait for specialist tools or artwork to ship working Private tools.

The user requested incremental commits and testing, and then paused deployment to refine the local execution plan. Start in **local-only mode**. Do not resume cloud writes or promote tools without a separate release instruction.

## Operating model: one parent, four reusable specialists

This revision follows the supplied VS Code guidance: one orchestrator mediates all specialist communication. A through G below are **work packages**, not ten independent agents with persistent conversations.

```text
You
  project-orchestrator
    architect       -> bounded read-only design
    developer       -> approved implementation
    tester          -> exclusive test authoring, if needed
    tester          -> validate-only --+
    reviewer        -> read-only -----+-> parent integrates results
```

The final tester and reviewer invocations may run in parallel only after writes stop. Corrections go through a fresh developer invocation, followed by new validation/review. Context-isolated subagents share neither conversational history nor a persistent peer-to-peer channel; filesystem isolation must be established separately.

The ready-to-use profiles are:

| Profile | Repository file | Capabilities |
| --- | --- | --- |
| `project-orchestrator` | `.github/agents/orchestrator.agent.md` | User-invocable parent; permitted children explicitly limited to the four specialists; owns integration and human gates. |
| `architect` | `.github/agents/architect.agent.md` | Read/search only; hidden from the normal picker. |
| `developer` | `.github/agents/developer.agent.md` | Read/search/edit/terminal execution within the assigned scope; no Git or cloud mutations. |
| `tester` | `.github/agents/tester.agent.md` | Explicit `author-tests` or `validate-only` mode; hidden from the picker. |
| `reviewer` | `.github/agents/reviewer.agent.md` | Read/search only; independent frozen-diff review; hidden from the picker. |

Profiles use VS Code's `execute` tool group for terminal-capable roles rather than assuming a tool named `terminal`. The parent includes `agent` and an explicit `agents` allowlist. No specialist has the delegation tool. Models are not hardcoded: use an available model selected in VS Code.

Keep nested delegation disabled. Limit the initial run to one developer and at most three concurrent subagent invocations (a project convention, not a VS Code setting). Do not launch ten separate chats to execute this file.

## Verified starting point

| Surface | State at handoff |
| --- | --- |
| Consumer-facing agent | `elle`, hosted in Foundry, using `model-router`; 100% of traffic remains pinned to agent version **3**. |
| Live toolbox | `elle-tools`, default version **3**; web search, Python/code interpreter, Microsoft Learn, and read-only Azure only. |
| Private candidate | Toolbox version **4** preserves those four sources and adds `elle_private` through `elle-private-oauth`. It is NOT the default and no hosted agent candidate using it has been promoted. |
| Private authorization | A dedicated tenant-pinned OAuth2 client/connection exists. DemoUser1 completed authorization. A final browser callback said "Code not found", but subsequent discovery progressed past consent to the MCP server. Do not assume that callback means the connection was lost. |
| Actual next failure | Candidate toolbox discovery returns `-32007`, with an `HTTP_405` source error. Backend logs show a first POST rejected before an RPC result, then GET `/mcp`, then fallback POST `initialize` rejected as invalid parameters. The first POST rejection still needs to be identified. |
| Backend deployment | Diagnostic image from commit `c2cb998` is now deployed to both canonical services: Private revision suffix `0000012`, Wisdom `0000009`. Both report Running. Private's health and anonymous 401 check passed; the post-update Wisdom HTTP check was interrupted and must be repeated. |
| Diagnostic image | Registry build **dtg** succeeded. The deployed digest is `sha256:ba2f6f247762d00d742256ee089e5e251820ac732476feaf876658ecda349033`. It adds fixed-message body-rejection diagnostics and repairs the Docker build-context allowlist. Do not deploy it again merely to obtain that diagnostic. |
| Staged hosted version | Agent version **4** is active but NOT receiving consumer traffic. It pins toolbox **3**, not Private candidate toolbox **4**. It does not restore the missing tools. Its invocation/acceptance was interrupted; do not confuse active provisioning with passed acceptance. |
| Hosted runtime | `foundry-agent/main.py` still creates one long-lived `FoundryToolbox`. Repeated/concurrent user-context handling has not passed acceptance. |
| App branding | App package **1.0.2** has the approved elephant color/outline icons. Admin publication completed; DemoUser1's rendered icon bytes matched the approved PNG. The remaining problem is legibility at approximately 20-32 pixels, not a missing upload. |
| Runtime access | Preserve existing `responses` and `activity` protocols, `Entra` and `BotServiceRbac` authorization, and explicit version routing. Do not infer runtime authorization from the app's Tenant catalog scope. |
| Specialist tools | Azure SQL, Speech, and Flint chart integration are not accepted or live. Discovery/preparation may proceed independently but must not delay core restoration. |

There are **four tool sources**, not necessarily four individual callable tools. Microsoft Learn, for example, exposes several functions. Prompt front matter naming tools does not register them.

## Ownership and concurrency rules

1. Default to one implementation stream in one local feature branch. Sequential architect/developer/tester calls do not each need a worktree. Only the orchestrator operates Git.
2. For genuinely independent parallel implementations, the orchestrator creates separate worktrees and branches such as `swarm/transport` and `swarm/runtime`. It passes each absolute checkout path and baseline explicitly. Never share an index, dependency environment, build cache, or mutable authentication cache between streams. Separate context alone is not isolation.
3. The parent (`project-orchestrator`, release responsibility **R**) is the only writer of this assignment ledger and the only actor allowed to integrate/commit/push or perform separately authorized live releases. It leases exact source files to one developer invocation, then explicitly transfers test-file ownership to the tester when required. Shared-file edits are serialized.
4. Specialists return a result to the parent. A follow-up is a **new invocation** with the relevant previous result included; do not rely on peer messages, an inherited chat, or an unrecorded claim. Missing information is a BLOCKED report for the parent to resolve.
5. The parent coordinates interactive sign-in and the shared browser using C's acceptance requirements. Specialists must not navigate another session away or change the operator's account. Use isolated per-user CLI caches and verify the exact account before every live test.
6. No shared-user tokens, model-supplied user IDs as authorization, app-only private-memory shortcuts, disabled token validation, broadened user allowlists, or secrets in source/logs. Derive memory ownership from validated delegated identity.
7. Use only synthetic acceptance records; do not dump private memories, conversations, tokens, or consent URLs into commits or this public repository. Clean up only records created by the test.
8. Commit focused, passing steps. Do not force-push, reset others' work, mass-delete caches, or redeploy both backends merely because the existing deployment script does so.
9. Re-read live versions before every approved cloud change. Record the previous image/version and rollback command. R must preserve unrelated metadata, permissions, channels, and installed app identity.
10. User-visible publication, outbound messages, permission expansion, and new artwork require an exact preview and explicit user approval. The previous artwork approval does not approve a redesigned icon.

## Work-package register

The parent schedules these packages using the same four specialist roles, rather than creating a new agent persona for every component. The write scopes below are leases to the current implementation invocation, not permanent ownership by a peer.

| Package | Priority / start | Exclusive implementation scope | Dependencies for completion |
| --- | --- | --- | --- |
| **A - MCP transport** | P0; architect first, then developer | `rust/src/server.rs`, `rust/src/mcp.rs`, `rust/tests/memory_flow.rs`, new transport tests under `rust/tests/` | Diagnostic image already deployed; obtain redacted first-POST evidence. No dependency on B to diagnose. |
| **B - Hosted request isolation** | P0; parallel analysis; edits only in an isolated stream | `foundry-agent/main.py`, `foundry-agent/requirements.txt`, new `request_scoped_tools.py` and `test_runtime_*.py` | Independent local reproduction; C defines identity acceptance requirements, the parent coordinates sign-in; R packages new runtime modules. |
| **C - Private OAuth and acceptance** | P0; read-only design alongside A/B; serialize shared edits | `configure_private_oauth.py`, `probe_toolbox.py`, their tests, new `private_acceptance.py` and `test_private_acceptance.py`, all under `foundry-agent/` | Direct end-to-end Private gate needs A; hosted/multi-user gate needs A+B+R candidate. |
| **D - Shared Wisdom** | P1; prepare now | New `foundry-agent/configure_wisdom_oauth.py`, `wisdom_acceptance.py`, and `test_wisdom_*.py` | Agreed OAuth helper contract with C; live transport gate needs A; hosted gate needs B; promotion follows Private. |
| **E - Work IQ** | P1; prepare now | New `foundry-agent/configure_workiq.py`, `workiq_acceptance.py`, and `test_workiq_*.py` | B for hosted user context; C for browser/sign-in coordination. Direct service diagnosis is independent of A/D. |
| **F - Small-size branding** | P1; independent stream when capacity permits | New candidates under `docs/images/elle-app-legible-*`; preview/export script under `scripts/` | User selects the artwork; R publishes it. No dependency on tool repairs. |
| **G-SQL - SQL capability** | P2; discovery now | New isolated `integrations/sql/` implementation/tests | Exact approved database/entity scope and auth design; R integrates only after acceptance. |
| **G-Speech - Speech capability** | P2; discovery now | New isolated `integrations/speech/` implementation/tests | Confirm actual supported server, storage/auth requirements, cost and network constraints; R integrates later. |
| **G-Chart - Flint capability** | P2; discovery now | New isolated `integrations/chart/` implementation/tests | Confirm existing endpoint/deployment; safe image-return and authentication contract; R integrates later. |
| **R - Parent integration and release** | Parent responsibility, not another subagent | `deploy.py`, `test_deploy.py`, `requirements-deploy.txt`, `.github/workflows/`, `scripts/deploy.ps1`, `Dockerfile`, `.dockerignore`, `README.md`, `ELLE_COPILOT_STUDIO_PROMPT.md`, canonical app icons, this file | Lease shared-code changes to one developer; integrate accepted results; serialize separately approved deployments/promotions. |

The register's abbreviated file names refer to `foundry-agent/` unless a full repository-relative path is shown.

### Safe parallelism

| May run together | Required boundary |
| --- | --- |
| B's architecture research and A's implementation | B reads the frozen baseline, not A's moving diff; no overlapping writes. |
| Tester `validate-only` and reviewer | All candidate writes finished; both receive the same baseline, exact diff and candidate identity. Reviewer is read-only; test commands must not update tracked files. |
| A and B implementations | Optional only: separate worktrees, disjoint file leases, separate environments, and agreed interfaces. R serializes packaging/CI integration afterward. |
| F icon preparation and tool work | Separate worktree for parallel editing; no canonical asset replacement or publication before user selection. |
| D/E/G discovery | Bounded read-only invocations as capacity permits; no broad initial ten-agent fan-out. |

Do not run test authoring while final review reads those files. Either finish authoring before freezing the candidate, or have the reviewer inspect a separate immutable snapshot and require another review after integrating new tests.

### Task packet for every invocation

The parent includes all fields, including prior conclusions needed by the next role:

```text
Work package and phase:
Role and mode: architect | developer | tester(author-tests/validate-only) | reviewer
Exact objective:
Absolute checkout path and branch:
Baseline commit and candidate commit/diff identity:
Read scope:
Exclusive write scope (or NONE):
Approved design and interface contracts:
Relevant prior results and unresolved questions:
Dependencies satisfied / still blocked:
Constraints, including local-only or explicitly approved live-read scope:
Commands/acceptance cases and isolated environment paths:
Expected output and stop conditions:
```

Return format:

```text
Package / role / phase:
Status: READY | PASS | FAIL | BLOCKED
Baseline and candidate examined:
Files changed (or NONE):
Key decisions and evidence:
Commands, pass/fail counts, and precise failures:
Remaining risks or missing evidence:
Live changes: NONE (specialists do not deploy)
Required handoff and dependencies unblocked:
```

### Durable state without pretending agents share history

The parent alone updates this tracked file with sanitized milestones. For longer
runs, it may store structured handoff summaries in ignored `.agent-work/` JSON
files (`state.json`, `architecture.json`, `implementation.json`,
`test-results.json`, `review-findings.json`). Specialists return reports; the
parent records them, preserving read-only architect/reviewer roles.

Use unique package/attempt keys rather than overwriting results from concurrent
calls. Include status, baseline/candidate, owner lease, dependencies and next
action. After a reload, the parent rechecks Git and live state before resuming.
These local artifacts are optional, not a VS Code requirement or a token store.

## A - Repair the real transport failure

Start with `server.rs::read_json_body`, `handle_request`, and `mcp.rs` initialization handling. The diagnostic image is already deployed. Ask the parent to obtain redacted HTTP status/framing diagnostics from a fresh authorized toolbox-v4 discovery when live reads are approved; do not assume the old terminal's interrupted request completed.

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

For each G package, an architect invocation first inventories the available evidence and reports the concrete missing prerequisite. Avoid duplicate servers or speculative cloud provisioning.

SQL needs an explicitly authorized database, exposed entities, and identity policy; do not guess or expose all databases. Speech needs supported auth, storage, network, and cost handling without putting keys or SAS values in logs/source. Flint must return usable rendered artifacts rather than inaccessible container file paths and must not expose arbitrary host file access.

Each subsequent developer invocation owns only its assigned integration directory, produces isolated tests/configuration, and returns connection/tool definitions to the parent. No specialist changes the live toolbox or shared requirements directly.

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

Start with an architect pass over A+B+C and one developer implementing A. Run independent B/C analysis while A is implemented when useful; do not split a small review into redundant agents. Add a second implementation worktree only after the parent establishes a real independent boundary. Work IQ preparation does not require waiting for Wisdom. F and G remain optional parallel tracks, not prerequisites for restoring Private.

For **every** package: design -> controlled implementation -> exclusive test authoring if needed -> freeze -> parallel validate-only testing and independent review -> collect both -> focused correction/new invocation -> repeat both gates -> parent commit. Stage and promote only after a separate release instruction; the graph above is the eventual release dependency graph, not automatic authorization.

1. Re-read live routing, toolbox defaults, backend images, and pending build runs. Preserve the known-good v3 rollback. Diagnostic backends and hosted v4 now exist; do not recreate or promote them merely because the earlier handoff said they were absent.
2. Merge A/B/C passing commits. Reconcile runtime/deployment SDK constraints using separate environments, include new modules in the hosted ZIP, and update the corresponding CI jobs. Current deployment SDK is pinned to 2.6.1; the previously resolved runtime required a different projects SDK range. Do not install both requirement sets into one environment.
3. Stage an explicit Private-only candidate preserving all four healthy sources. Use toolbox v4 only if it still contains the intended connection/configuration. Never route consumers to an untested newest version.
4. Pass direct Private, hosted sequential/concurrent user-isolation, and actual Teams/Copilot channel tests. A CLI smoke response does not prove channel identity propagation. The frozen candidate must also have independent tester and reviewer reports; any subsequent edit invalidates the affected acceptance evidence.
5. Promote Private and verify real tool calls plus a fresh consumer conversation. If its gate fails, do not promote; report the exact blocker. On regression, route back to the captured previous version.
6. Add Wisdom, then Work IQ, as separate candidate/test/promotion/commit steps. Build each toolbox from the immediately preceding accepted version, not the unchanged default v3. If dependencies permit Work IQ to finish first, release it independently without dropping accepted tools.
7. Publish the selected icon separately. Complete any pending tenant-admin approval, then refresh the actual client and compare the served icon/version with the approved file. An immediate Foundry "approved" value proved stale during the previous update; the consumer-facing result is the final gate.
8. After each accepted release, push the integrated passing commits within the user's authorization and update this register with commit, toolbox version, agent version, backend image, tests, and rollback. Never mark the whole task complete because one capability works.

### Existing commands and important limitations

Reference commands from the repository root using the appropriate environment's
Python. The probe needs approved live-read access; staging and promotion are
cloud writes and must not run during the local-only task:

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

- The diagnostic image build and hosted-v4 staging completed despite interrupted initiating calls. Both backends now have the diagnostic image; v4 still references the healthy toolbox 3. Inspect existing resources before repeating operations.
- Ignored local Python environments disappeared during this session. Do not rely on operator-specific `.local` paths; restore missing dependencies in an isolated environment outside the synced tree.
- `scripts/deploy.ps1` currently updates **both** backends. R must provide a deliberate single-service deployment path for the requested incremental rollout.
- Keep the current Private API's authentication and user isolation intact. GET 405 by itself is not proof that an MCP server needs SSE.
- Leave the operator's unrelated Power Platform connector-title edit and alternative icon drafts untouched.
- This GitHub repository is currently **public**. Do not paste operator-specific account details, tenant/resource identifiers, endpoint inventories, tokens, private chat excerpts, or acceptance-result payloads into this file.

## Run locally after pulling

### 1. Prepare the checkout

Update to a current VS Code build supporting custom subagents, with GitHub
Copilot/Copilot Chat enabled and signed in. Honor organization policy and normal
tool approval prompts; do not enable blanket terminal approval.

In PowerShell, from your existing Elle repository:

```powershell
$pending = git status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Open a valid Elle Git checkout first' }
if ($pending) { throw 'Preserve local changes before proceeding; do not reset or auto-stash' }
git switch main
if ($LASTEXITCODE -ne 0) { throw 'Cannot switch to main safely' }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Resolve the pull without overwriting local work' }
git switch -c work/elle-local-restoration
if ($LASTEXITCODE -ne 0) { throw 'Choose an unused feature branch name' }
code .
```

If you have no checkout, use `git clone https://github.com/threadkeeper/Elle.git`
first, then `Set-Location .\Elle` and create the feature branch. Keep Python/build
environments outside a synced checkout. The parent should run the chosen existing
test command and restore its requirement set only if dependencies are missing.

### 2. Enable the orchestrator

Open Copilot Chat or the Agents window and select **project-orchestrator**.
The four specialists intentionally do not appear in the ordinary picker.
In the tool selector, ensure **agent/runSubagent** and the required read, search,
edit and terminal/execute tools are available. Tool availability does not bypass
approval.

Keep this setting false in your existing VS Code settings; merge it rather than
replacing the whole file:

```json
{
  "chat.subagents.allowInvocationsFromSubagents": false
}
```

If the profile is missing, run **Chat: Open Customizations**, inspect the files in
`.github/agents`, and reload the window. If your installed version or organization
policy does not expose custom subagents, report that limitation; do not pretend
parallel delegation happened. No model override is required.

### 3. Send this first task

```text
Read CurrentWorkAssignments.md and repository instructions. Operate in local-only
mode on my current feature branch. Use architect to assess packages A, B and C,
then give developer one bounded transport repair (A) with regression coverage.
Include the exact checkout, file leases, design, dependencies and previous
conclusions in every stateless delegation. Run independent B/C analysis in
parallel only when useful. If tester needs to author tests, give it an exclusive
writing phase. Freeze the result, then run tester in validate-only mode and
reviewer in parallel on the same candidate. Resolve blockers through fresh
developer invocations and repeat both gates. Make focused local commits after
passing gates and update the ledger. Do not push, change live resources, grant
permissions, publish icons, or promote any agent. Return one consolidated result
and the next required human gate.
```

Allow relevant local file/terminal actions when prompted. Follow each subagent's
collapsible activity or read-only peer view; direct follow-up instructions go to
the parent chat, not those read-only subagent views.

### 4. Optional parallel implementation

After agreeing the architecture, ask the parent to create isolated A/B worktrees
from the same recorded baseline and invoke `developer` separately with each exact
path. It must keep shared packaging/CI work serialized and integrate one stream
at a time. If the installed harness cannot access the second worktree, use a
separate VS Code session for that independent stream and return its result to the
original parent explicitly. Only the original parent integrates or releases.

Do not run several writers in the same window/checkout and assume subagent
context isolation prevents conflicts. Start without nested agents or extra
sessions; add parallel editing only when it demonstrably helps.

### 5. Resume and release deliberately

After reopening VS Code, start project-orchestrator with: "Read the ledger and
local .agent-work state, reconcile with Git, and resume the next ready package
in local-only mode." It must not assume any previous subagent is still running.

When ready for cloud work, use a separate instruction naming the exact package
and candidate: "Prepare the Private release preview, verify the current target
and rollback, and show the proposed cloud changes and synthetic acceptance
records. Wait for my approval before applying them." Approve a specific release
only after seeing those details. New artwork has its own preview/selection gate.
Review the full outgoing Git range before authorizing push to the public repo.

## Completion ledger

Only the orchestrator edits this ledger. Claim a **package/phase** with an
invocation ID, checkout and file lease; do not invent persistent agent identities.
Use `planned -> design -> implementing -> testing -> reviewing -> local-ready`
with `blocked` or `fix-required` branches. Track `staged -> live-accepted ->
released` separately so a local PASS cannot silently become a deployed claim.

| Package | Status / current lease | Commit / evidence | Next gate |
| --- | --- | --- | --- |
| A | Planned; no invocation | Diagnostic image c2cb998 deployed to both backends | Identify first authorized POST rejection |
| B | Planned; no invocation | Existing global toolbox lifetime not accepted | Reproduce and fix current-request context |
| C | Planned; no invocation | OAuth/discovery tooling 3202e6d; consent progressed | Private read/write/isolation after transport fix |
| D | Planned; no invocation | Existing service/catalog, not attached live | Separate OAuth and Wisdom acceptance |
| E | Planned; no invocation | Existing excluded connection, not accepted | Confirm supported Work IQ contract/auth |
| F | Planned; no invocation | Published icons 0b1b471, app 1.0.2 | Native-size candidates and user selection |
| G-SQL | Planned; no invocation | Scope not yet accepted | Authorized database/entity selection |
| G-Speech | Planned; no invocation | Not yet accepted | Endpoint/auth/storage inventory |
| G-Chart | Planned; no invocation | Not yet accepted | Endpoint/artifact/auth inventory |
| R | Parent responsibility; live writes paused | Gates 915845a; hosted v4 active on toolbox 3, live still v3 | Reconcile candidates, integrate local changes, request release approval |

## Guidance applied

The supplied document's recommended parent-mediated, single-level pattern is
implemented here; its internal briefing content is not reproduced in this
public repository. Optional durable artifacts are a project convention, not a
VS Code protocol. Sequential UI handoffs are optional human-controlled
transitions, not autonomous peer messaging; this setup keeps approval gates in
the parent chat rather than bypassing it with specialist handoff buttons.

- [VS Code custom agents](https://code.visualstudio.com/docs/agent-customization/custom-agents)
- [VS Code subagents and orchestration](https://code.visualstudio.com/docs/agents/run/subagents)
- [VS Code tool availability and approvals](https://code.visualstudio.com/docs/agents/run/tools)
