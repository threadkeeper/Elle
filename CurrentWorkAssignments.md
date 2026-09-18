# Current Work

The active objective is a fast, compelling Elle demo.

## Product path

Use a Microsoft Foundry hosted agent. Do not add an intermediary agent builder
or tool catalog. Private memory is exposed as direct Python functions that call
the existing Rust `/bridge/{tool}` actions over HTTPS.

## Working rules

- Keep changes small and demo-focused.
- Use synthetic data only.
- Preserve the existing Entra identity flow and user partition behavior.
- Test locally before staging.
- Keep deployment promotion guarded and reversible.
- Do not commit local environments, credentials, generated output, or unrelated
  user changes.

## Main surfaces

- `foundry-agent/main.py`: hosted agent entry point.
- `foundry-agent/private_tools.py`: direct private action functions.
- `foundry-agent/deploy.py`: package, stage, test, promote and rollback.
- `rust/src/server.rs`: authenticated direct action routes.
- `ELLE_AGENT_PROMPT.md`: agent behavior and tool routing.
