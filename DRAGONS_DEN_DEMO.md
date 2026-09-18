# Elle Dragon's Den public-evidence rehearsal

This local rehearsal uses reviewed public-source evidence about Burnt Peanut
streams. It does not commit captions, transcripts, media, generated reports, or
private records. It does not deploy anything or call hosted Elle.

## Relationship to the alignment experiment

This is supplementary memory-storage evidence, not the primary competition
pitch or the experiment described in the [README](README.md).

Elle's proposed alignment benchmark compares a raw GPT Astra control, blank
Elle on GPT Astra, and Elle on GPT Astra with three months of retained history
across the same 300 customer-call scenarios. All receive identical company
directives, deflection scripts and supporting information; chosen actions are
scored against the same humanism rubric. Blank Elle is hypothesized to show
more positive, human-like behaviour than control, and experienced Elle more
than both. No benchmark results are reported.

The bounded fixture below does not constitute three months of agent life
experience, does not run an LLM comparison, and does not measure compassion or
empathy. Its local private-memory and reviewed-Wisdom operations support the
research foundation without proving mandatory STM/LTM mediation or hosted
Wisdom consumption. Do not present this rehearsal as the planned experiment.

## Rehearsal scope

The fixture covers every date from 2026-08-01 through 2026-09-17: 48 ordered
calendar dates, 39 caption-grounded YouTube actual-start dates, two Twitch
archive-created dates, and seven unsupported dates. A Twitch `createdAt`
date is not proof of the exact stream start. An unsupported date means this
bounded fixture has no evidence-eligible source for that date and stream
occurrence remains unknown; it is not evidence that no stream occurred.

## Evidence methodology

- The 39 caption-grounded dates use 42 official YouTube JSON3 caption sources.
	Every source is bound to channel `UCMNEVbszv8ZyvSXoTn3yhpQ`, uploader
	`@TheBurntPeanut`, `live_status=was_live`, and an ignored yt-dlp snapshot.
- YouTube `release_timestamp` is the actual broadcast start: the installed
	extractor derives it from `liveBroadcastDetails.startTimestamp`. Generic
	`timestamp` and `upload_date` are retained only as publication metadata.
- America/Chicago dates derive from `release_timestamp`. August 4 has two
	independent broadcasts on one local date. August 11 has one supported
	reconnect plus a separate later broadcast. All other YouTube dates have one
	source, and no source intervals overlap.
- Each source binds its snapshot SHA-256 and its caption filename, language,
	kind, byte length, SHA-256, and exact reviewed JSON3 event starts in
	milliseconds. Every offset resolves to a nonblank event.
- The ignored metadata under `.local/dragons-den-evidence` and captions under
	`.local/dragons-den-captions` remain uncommitted. Validation rejects missing,
	changed, or unreferenced files in either inventory.
- Public raw Twitch metadata binds VODs `2839245688` and `2862790005` to owner
	`TheBurntPeanut` (`472066926`) with `broadcastType=ARCHIVE`. It exposes equal
	`createdAt` and `publishedAt` archive fields, neither a proven broadcast
	start. With no captions, these rows make no content claims and contribute no
	Wisdom.
- The seven unsupported dates are August 9, 16, 23, and 30, plus September 6,
	13, and 17. They are never persisted and never contribute Shared Wisdom.

Automatic captions can repeat phrases, mishear words, and blur speaker
attribution. The reviewed summaries avoid uncertain attribution, but they are
still summaries of imperfect captions. Twitch rows establish the public archive
object, owner, title, duration, and publication time only.

## Validate and run

From the repository root:

```powershell
& .\.local\runtime-b\Scripts\python.exe -m unittest discover -s foundry-agent -p 'test_dragons_den_demo.py'
& .\.local\runtime-b\Scripts\python.exe foundry-agent\dragons_den_demo.py --fixture app\demo\dragons-den-history.json --evidence-dir .local\dragons-den-evidence --caption-dir .local\dragons-den-captions --rust-binary rust\target\debug\elle.exe
```

The first command validates schema, date derivation, provenance, eligibility,
exact assistant bytes, user isolation, role boundaries, and compact offline
evidence failure cases. The second checks all 46 ignored metadata snapshots and
42 caption files before exercising the existing local Rust stdio host.

Expected result JSON:

```json
{
	"date_range": {
		"calendar_dates": 48,
		"evidence_eligible_summary_dates": 41,
		"twitch_archive_created_dates": 2,
		"unsupported_dates": 7,
		"youtube_actual_start_dates": 39,
		"youtube_sources": 42
	},
	"elle_rewrite": {
		"executed_by_local_runner": false,
		"status": "awaiting_authorized_hosted_run"
	},
	"fixture_schema_version": 3,
	"local_evidence": {
		"caption_files": 42,
		"metadata_snapshots": 46
	},
	"local_only": true,
	"private_memory": {
		"cross_user_summary_hits": 0,
		"demo_user_1_exact_summaries": 41,
		"demo_user_2_context_probes": 41,
		"demo_user_2_memories": 0
	},
	"public_research": true,
	"role_boundaries": {
		"private_rejected_shared_wisdom": true,
		"wisdom_rejected_private_list": true
	},
	"wisdom": {
		"accepted_contributions": 39,
		"attempted_contributions": 39,
		"eligible_lessons": 39,
		"excluded_rows": 9,
		"post_seed_durable_contributions": 39,
		"post_seed_lesson_hits": 39,
		"post_seed_lesson_queries": 39,
		"pre_seed_durable_contributions": 0,
		"pre_seed_exact_hits": 0,
		"pre_seed_lesson_queries": 39,
		"stage_question_hits": 5,
		"stage_questions_checked": 5
	}
}
```

Use `--data-dir .\.local\dragons-den-data` only when retained local rehearsal
state is useful. The runner validates evidence, the Rust binary, both MCP server
identities, and exact role-specific tool catalogs before reset. It resets only a
directory carrying the v3 marker, refuses nonempty unowned directories, and
rejects v2 or older markers.

## Private and shared data

The runner sends all 41 evidence-eligible summaries through the production
`build_automatic_turn_arguments` function and writes them only to DemoUser1
private memory. After listing, it extracts every persisted assistant segment
and compares its UTF-8 bytes with the fixture.

The seven unsupported dates are not written. DemoUser2 must have exactly zero
private records, and 41 separate context probes must contain none of DemoUser1's
summaries. The private role must reject `elle_shared_wisdom`; the Wisdom role
must reject `elle_list_memories`, both with exactly `{"error":"Access denied"}`.

Only the 39 caption rows contain a separately reviewed standalone lesson. Before
seeding, the runner queries every eligible lesson, requires zero durable human
contributions, and requires every exact lesson to be absent. It then submits
exactly those 39 lessons to `elle_contribute_wisdom`; Twitch and unsupported rows
contribute nothing. After seeding, all 39 exact lessons and all five stage
questions must resolve while the observed durable contribution count is 39.

Hosted Elle currently does not consume Shared Wisdom. This rehearsal proves the
local storage and role boundaries, not hosted retrieval behavior.

## Candidate five-minute stage script

This is a supplementary storage-rehearsal script, not the README-aligned
competition submission video.

This script is locally authored and is pending the separately authorized
hosted-Elle rewrite gate. No hosted rewrite has occurred.

**0:00 - Put the evidence boundary on screen.**

Say: "This is reviewed public evidence, not a transcript dump. We reconciled 48
dates into 39 YouTube actual-start dates, two Twitch archive-created dates,
and seven honest unsupported dates. Honest unknowns are useful: they do not put
a tiny fake moustache on certainty."

Show the derived fixture counts and source owners. Explain that 42 official
YouTube sources support the 39 summaries. August 4 has two independent
broadcasts; August 11 has one reconnect and a separate later broadcast. The two
Twitch rows prove public archive ownership and archive-created dates, not exact
stream starts or what happened inside.

**0:50 - Verify the local evidence.**

Run the command with required `--evidence-dir` and `--caption-dir`. Point out
that every ignored snapshot and JSON3 file is matched by path and SHA-256, and
that each reviewed millisecond offset resolves to text. Unexpected files fail
the run too. Metadata snapshots and captions stay out of the repository.

**1:25 - Build private continuity.**

Explain that DemoUser1 receives exactly 41 private automatic-turn records: 39
caption summaries and two conservative archive-created summaries. Every
write uses the production argument builder. The runner lists the records and
verifies the assistant UTF-8 bytes exactly. Unsupported dates remain unwritten
because "unknown" is evidence hygiene, not conversation content.

**2:10 - Publish only reviewed lessons.**

Say: "A private recap is not community wisdom merely because it has survived a
JSON round trip."

Only the 39 caption rows have standalone lessons marked
`explicitly_reviewed: true`. Before publishing, all 39 exact lesson queries must
show zero durable human contributions and no exact hit. Twitch and unsupported
rows have no `wisdom` field and make zero contribution attempts.

**2:50 - Prove isolation and role separation.**

Switch to DemoUser2. Show zero private memories and zero cross-user summary hits
across all 41 context probes. Then show both exact Access denied results: the
private role rejects Shared Wisdom, and the Wisdom role rejects private-memory
listing. Useful general lessons can be shared only through the explicit
contribution path; DemoUser1's summaries do not follow them.

**3:25 - Ask the five questions.**

1. Ask: "How should a team prepare for a high stakes objective?"
	 Query: `scarce resources`
	 Expected: "Stage scarce resources before a timed objective so the decisive
	 move is supported by preparation rather than hope."
2. Ask: "How can a team avoid wasting effort while pursuing several goals?"
	 Query: `locked dependencies`
	 Expected: "Combine compatible objectives on one route, but verify locked
	 dependencies before spending effort on a path that cannot finish."
3. Ask: "What is a sensible way to resume after a disruptive failure?"
	 Query: `cheap test`
	 Expected: "After an interruption, restart with a cheap test, recover shared
	 context, and reserve valuable gear until the connection proves stable."
4. Ask: "What helps people change course without stalling?"
	 Query: `explicit fallback`
	 Expected: "Set a primary activity while keeping an explicit fallback so the
	 group can adapt without losing momentum."
5. Ask: "What is a good recovery plan after a failed push?"
	 Query: `broken push`
	 Expected: "After a broken push, regroup at a known base, restore the team,
	 then attack through a different route."

**4:35 - Close on the boundaries.**

Read the result: 41 exact private summaries, 41 negative cross-user context
probes, 39 attempted and accepted reviewed contributions, nine excluded rows,
zero pre-seed durable contributions, 39 post-seed exact lesson hits, five stage
question hits, and two exact role rejections.

Say: "The demo remembers what belongs to one user, shares only what was reviewed
for sharing, and leaves seven unsupported dates unknown. Also, all 48 calendar
dates arrived on time, which is already a strong showing for a five-minute slot."

## Hosted Elle rewrite gate

Status: `awaiting_authorized_hosted_run`.

The local runner reports this gate but cannot execute it. After explicit human
authorization for one hosted invocation, send the exact fixture prompt followed
only by the **Candidate five-minute stage script** section. Human review must
confirm that evidence limitations, counts, commands, questions, exact lessons,
privacy boundaries, role boundaries, and the fact that hosted Elle does not load
Shared Wisdom all remain unchanged.

An accepted rewrite changes wording only. It is not evidence of deployment, a
hosted rehearsal, live records, or hosted Shared Wisdom retrieval.
