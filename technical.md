# Elle technical guide

## Research goal and implementation boundary

The [README](README.md) defines Elle's alignment hypothesis: separate raw LLM
cognition from short-term and long-term memory, mediate outside interactions
through those memory layers, and give each agent a unique retained history.
The proposed trust model combines a tenant for each person with an opt-in
Wisdom layer for anonymized lessons rather than raw private histories.

The proposed experiment compares a raw GPT Astra endpoint, a blank Elle agent
on GPT Astra, and an Elle agent on GPT Astra with three months of retained
history. All receive the same company directives, deflection scripts and
supporting information for the same 300 customer-call scenarios. Chosen actions
are scored against a common humanism rubric. The hypothesis is that blank Elle
outperforms the raw control and experienced Elle outperforms both.

The runtime below is a prototype foundation, not a completed implementation or
evaluation of that research design. Its current Luna model is distinct from the
proposed Astra experimental conditions. Private memory tools and post-response
archiving do not establish mandatory pre-LLM STM/LTM mediation. User-partitioned
storage is not a separate deployed tenant for every person, and hosted Elle
does not currently consume Shared Wisdom. No 300-scenario results or genuine
compassion/empathy claims are reported.

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
