# Elle technical guide

## Runtime

The demo is a Microsoft Foundry hosted agent. Its Python runtime uses the
Foundry Chat client and the Responses host. Private memory is registered as
ordinary Python functions in `foundry-agent/private_tools.py`.

`foundry-agent/turn_memory.py` observes each completed response and queues the
latest user/Elle turn in a background task. This write starts after response
generation and is not part of the model tool loop, so it does not delay the
reply or require a second model round trip.

Each function sends JSON over HTTPS to the existing Rust service at
`/bridge/{tool}`. The request includes the current platform user identity and
the service performs the private partition lookup. No separate tool catalog or
connector is involved in the agent runtime.

## Private actions

- `elle_context`: semantic recall plus personality guidance.
- `elle_list_memories`: list current records.
- `elle_remember`: save a confirmed record.
- `elle_correct`: update a reviewed record version.
- `elle_forget`: delete a reviewed record version.
- `elle_personality`: open the workshop.
- `elle_set_personality`: save a confirmed profile version.

The Rust service validates action payloads, derives the owner partition from the
caller identity, encrypts private fields, and uses Cosmos DB for persistence.

## Deployment

`foundry-agent/deploy.py` packages the Python runtime and stages an explicit
Foundry agent version. It configures:

- `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `ELLE_PRIVATE_TOOLS_ENDPOINT`

Promotion remains guarded by an expected live version. The default model is
`gpt-5.6-luna`; `model-router` remains available through the environment
override.

## Demo discipline

Use fictional records. Keep the prompt and tool responses concise. Automatic
turn archives require no confirmation; explicit corrections, deletions, durable
fact saves and personality changes keep their normal confirmation flow. Run the
focused Python and Rust tests before staging a candidate.
