# Elle

Private memory and a recognizably humanistic personality for the AI assistants you already use.

## What is Elle?

Elle is two separately installable MCP servers, not another standalone chatbot:

- **Elle** adds private, user-controlled memory and personality tools.
- **Elle Shared Wisdom** is an optional way to use reviewed shared guidance and, in a future release, help improve Elle by contributing generalized lessons.

Compatible hosts include Scout, Cowork and Microsoft 365 Copilot. You can install either server, both, or neither.

Most AI conversations require you to explain your preferences, background and ongoing work again. Worse, even capable assistants often collapse into the same polished, generic chatbot voice. Elle aims to make conversations feel continuous, personal and alive without pretending that software is human.

You choose what Elle remembers. It can then bring relevant information into later conversations, while letting you see, correct or remove saved memories.

## Our first demo

The first cloud demo will connect both MCP servers separately to Microsoft 365 Copilot. Scout and Cowork connections will use each host's supported MCP configuration. The host decides when to call tools and how to present the answer; installing Elle does not automatically change every conversation.

The demo will show how you can:
- Ask Elle to remember a preference or project detail.
- Start a new conversation and use that saved context.
- Get responses with a consistent, configurable personality.
- Review, correct and forget saved information.
- Download your Elle data and restore a compatible backup.
- Search a shared catalog without exposing another user's private memories.
- Independently opt into or out of future help-improve-Elle participation.
- Build an original Elle personality from favorite fictional characters, public descriptions of the artists behind them, and traits the user explicitly chooses to contribute.

We will use made-up information for the demo, not private work or personal records.

## Two independent MCP servers

### Elle: private memory and personality

The private server stores information for the signed-in user only. It supports remembering, recalling, reviewing, correcting and forgetting memories, plus an evolving personality profile.

On first use, Elle should ask one low-friction question: a few sentences about the user's favorite fictional characters and what resonates about them. The host can research reputable public biographies, interviews and character descriptions, then derive observable traits such as curiosity, emotional expression, humor, decision style, cadence, empathy and confidence. Elle blends those influences with communication traits the user explicitly supplies or permits Elle to infer from their interactions.

The result is an original profile, not copied dialogue, a clinical diagnosis or an impersonation. It should shape reasoning posture, memory salience, initiative, register, humor, empathy and conversational rhythm. The user sees one editable preview and confirms once before it is saved as private Elle data. Shared Wisdom never receives this profile.

Bounded variation keeps Elle from sounding mechanically fixed: warmth, playfulness, directness, curiosity and sentence rhythm can move naturally with context, while identity, values and important user preferences remain stable.

### Elle Shared Wisdom: optional collective improvement

The shared server is positioned like an optional "help improve the product" choice, but it is more explicit than a diagnostics switch: future contributions may contain generalized lesson content. Installing this server does not opt you in, and it cannot query your private Elle memory store.

The first demo exposes a small reviewed, non-private shared catalog and an independent opt-in setting. It does **not** yet collect conversations or publish private-derived lessons. Before contribution is enabled, the project must disclose exactly what is collected, apply automated privacy screening, and provide controls to inspect and delete retained contributions.

Removing either MCP connection stops that server's future access. It does not automatically delete data already stored by that server; deletion is a separate, explicit control.

## Take your data with you

The planned export will let you download all of your Elle application data: saved memories, stored conversation context, preferences and personality settings. This does not include your entire Microsoft 365 account, Copilot's own chat history or platform audit logs.

You will be able to upload a compatible backup to the same Elle account. Restore will check ownership, file integrity and format before adding missing records, without silently overwriting existing information. Any skipped or failed records will be reported.

Backups will be password-protected. File transfer and password entry will use an authenticated Elle page opened from the agent, rather than passing backup files or passwords through chat.

## Encryption and privacy

The current source implements the core cryptography, user partitioning, Entra token verification and MCP role separation. Cloud behavior remains subject to deployment and integration testing.

- **Encryption in transit:** HTTPS/TLS will protect connections between the client and Elle.
- **Encrypted memory text:** we plan to adapt the source project's AES-256-GCM field encryption, with separate per-user keys derived using HKDF-SHA256. This protects selected text fields and detects tampering. Elle will require encryption configuration rather than silently saving those fields as plaintext.
- **Protected downloads:** the source archive design uses AES-256-GCM with a password-derived key, PBKDF2-HMAC-SHA256 with 600,000 iterations, and a random salt. We plan to retain this protection for Elle backups. A strong password is still essential.
- **Account isolation:** Microsoft Entra sign-in will establish who is calling. The service, not a chat message, will determine which user's memories can be read, changed, exported or restored.
- **User control:** saving, changing, deleting and restoring information will require explicit user direction. One user's private memories will not be shared with other users.
- **Restricted service access:** Azure managed identities and narrowly scoped permissions will control access to storage and models. Encryption keys will be held outside the source repository, using Azure Key Vault.
- **Limited data exposure:** only relevant context will be sent to the configured AI services. Operational logs will be designed to exclude memory text, passwords and credentials.

### Important limits

This is server-side encryption, not end-to-end encryption or a guarantee that privileged service operators cannot access data. Elle must decrypt selected information to use it, and that information may be processed by Microsoft Foundry and the host application.

Search vectors and structural metadata are not covered by the source project's field encryption. They still require access controls and Azure's storage encryption; vectors should not be treated as anonymous data.

Forgetting a memory will remove it from Elle's active memory and retrieval. It cannot erase information already shown in Copilot conversations or immediately remove every retained backup or platform log. Retention and backup policies must be documented before real personal data is used.

## How it works

Elle connects through Model Context Protocol (MCP), a standard way for AI applications to use external tools.

Azure Cosmos DB stores its memories. Microsoft Foundry provides AI capabilities, including turning text into searchable meaning.

Elle does not read every Copilot conversation or replace Copilot's built-in memory. It only receives information shared through its configured tools.

### The MCP control boundary

MCP can provide memory, personality guidance and tools, but the host still controls the base model, autonomous loop, tool selection and final wording. We therefore do not assume that installing an MCP guarantees the Elle experience.

The acceptance criterion is deliberately demanding: if the connected experience repeatedly sounds like a generic OpenAI or Anthropic chatbot, the experiment has failed. The repository contains a Foundry-compatible custom evaluator and an exact **77-case gate**: eleven interaction situations crossed with seven criteria for non-template voice, contextual specificity, memory continuity, natural register, emotional attunement, useful initiative and bounded variation. Known vanilla-chatbot markers cause an immediate zero.

Run `python evals/export_cases.py` to create the JSONL dataset for a Foundry batch evaluation. CI verifies the evaluator, the exact case count and the immediate-failure behavior. The deterministic evaluator is the hard gate; a Foundry prompt-based judge can supplement it for subjective depth and coherence.

If MCP-hosted trials cannot pass this gate consistently, Elle moves to a standalone Microsoft 365 agent where we can control orchestration, model selection and response synthesis directly while connecting approved Microsoft 365 and Work IQ capabilities.

## Where we want to go

Our first path remains two reusable, independently removable MCP servers for Scout, Cowork, Microsoft 365 Copilot, Clawpilot and other compatible applications. Each host must earn its place by passing the humanism evaluation gate. A standalone Microsoft 365 agent is the planned fallback when a host does not expose enough control.

## Current status

Active internal hackathon prototype. Local memory, encryption, backup/restore and MCP tests are working. Separate private and Shared Wisdom MCP services are deployed to Azure Container Apps through a successful GitHub OIDC pipeline. Delegated Microsoft 365 client consent and host integration remain in progress.

The first milestone is a small, single-user demonstration, not a production-ready service. Memory quality and usefulness will be measured rather than assumed.

Elle is Jean Van Iddekinge's personal project, adapted from his own pre-existing hobby work. It is not an official Microsoft product or an endorsed Microsoft service.

## License

Elle uses the [MIT License](LICENSE), a permissive license also used by Microsoft and Azure sample and accelerator repositories. The Microsoft and Azure names remain their respective owners' trademarks; the license does not imply endorsement.
