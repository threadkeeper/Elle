# Elle

An AI assistant that remembers what matters, so you do not have to keep starting over.

## What is Elle?

Most AI conversations require you to explain your preferences, background and ongoing work again. Elle aims to make those conversations feel more consistent, personal and useful.

You choose what Elle remembers. It can then bring relevant information into later conversations, while letting you see, correct or remove saved memories.

## Our first demo

Elle will appear as a named agent you select inside Microsoft 365 Copilot.

The demo will show how you can:
- Ask Elle to remember a preference or project detail.
- Start a new conversation and use that saved context.
- Get responses with a consistent, configurable personality.
- Review, correct and forget saved information.
- Download your Elle data and restore a compatible backup.

We will use made-up information for the demo, not private work or personal records.

## Take your data with you

The planned export will let you download all of your Elle application data: saved memories, stored conversation context, preferences and personality settings. This does not include your entire Microsoft 365 account, Copilot's own chat history or platform audit logs.

You will be able to upload a compatible backup to the same Elle account. Restore will check ownership, file integrity and format before adding missing records, without silently overwriting existing information. Any skipped or failed records will be reported.

Backups will be password-protected. File transfer and password entry will use an authenticated Elle page opened from the agent, rather than passing backup files or passwords through chat.

## Encryption and privacy

These are planned Elle safeguards, not a claim that an Elle release is already available.

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

Elle does not read every Copilot conversation or replace Copilot's built-in memory. It only receives information shared through its configured tools. Copilot still controls how answers are presented.

## Where we want to go

After the first demo, we aim to support Scout, Clawpilot and other compatible MCP applications, plus a standalone Elle experience. Each integration will need its own setup and validation.

## Current status

Proposal and development stage. There is no working Elle release in this repository yet. The source project contains encryption and export/restore components, but adapting them to Elle and its Microsoft 365 integration is still work to do.

The first milestone is a small, single-user demonstration, not a production-ready service. Memory quality and usefulness will be measured rather than assumed.

Elle is Jean Van Iddekinge's personal project, adapted from his own pre-existing hobby work. It is not an official Microsoft product or an endorsed Microsoft service.
