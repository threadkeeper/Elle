# Elle Status

Updated: 18 September 2026

## Live demo

- Hosted agent: Elle v18 at 100% traffic.
- Model: `gpt-5.6-luna`.
- Private actions: direct HTTPS calls to the Rust bridge.
- Storage: encrypted, user-partitioned Cosmos memory.
- Private backend: revision 19, healthy at 100% traffic.

## Verified flow

DemoUser1 can recall private context, list memories, save a confirmed synthetic
record, correct it by version, delete it, and open the personality workshop.
Every completed user/Elle turn is also archived automatically after the reply.

A measured fresh-chat recall completed in 22.185 seconds. The direct Private
action took 0.759 seconds; the rest was hosted-model and M365 orchestration.

## Demo boundary

Use synthetic data only. Keep the five-minute story focused on continuity:
remember one useful fact, start another conversation, recall it, then show that
the user can correct or remove it.
