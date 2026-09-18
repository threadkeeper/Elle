# Elle Status

Updated: 18 September 2026

## Alignment experiment

The [README](README.md) is the source of truth for the project narrative.
Elle asks whether separated cognition and memory, together with accumulated
life experience, can produce more positive, human-like behaviour.

The proposed benchmark uses three GPT Astra agents: a raw control, blank Elle,
and Elle with three months of retained history. Each receives identical
company directives, deflection scripts and supporting information, then faces
the same 300 customer-call scenarios. Actions are compared using the same
humanism rubric. The hypothesis is blank Elle above control and experienced
Elle above both; these are expected outcomes, not measured results.

The live demo below is a separate prototype. It does not establish mandatory
STM/LTM mediation, a deployed tenant per person, hosted Wisdom consumption, or
the three-month experimental condition. The benchmark measures observable
behaviour, not whether an agent genuinely experiences compassion or empathy.

## Live demo

- Hosted agent: Elle v19 at 100% traffic.
- Model: `gpt-5.6-luna`.
- Private actions: direct HTTPS calls to the Rust bridge.
- Storage: encrypted, user-partitioned Cosmos memory.
- Private backend: revision 22, healthy on image `7c9347e`.
- Wisdom backend: revision 12, healthy on image `7c9347e`.

## Verified flow

DemoUser1 can recall private context, list memories, save a confirmed synthetic
record, correct it by version, delete it, and open the personality workshop.
Every completed user/Elle turn is also archived automatically after the reply.

Pinned exact-token recall completed in 10.468 seconds on v19 versus 13.453
seconds on v18, a 22.2% hosted-runtime reduction. Two fresh M365 recalls on
v19 completed in 24.882 and 24.520 seconds with exact answers; the outer M365
orchestration masked the lower hosted-runtime latency.

## Demo boundary

Use synthetic data only. Keep the five-minute story focused on continuity:
remember one useful fact, start another conversation, recall it, then show that
the user can correct or remove it.
