# Dragon's Den demo

## The proposition

Models are rented intelligence. Elle makes useful context and explicitly shared human lessons durable, portable and user-controlled across models and conversations.

## Five-minute live story

### 1. Private continuity

Sign in as **DemoUser1** and ask:

> What have we learned about status dashboards and how I like to test architecture ideas?

Elle should recall the fictional three-month history: freshness matters, and a small reversible prototype should precede a larger programme.

Then ask:

> Turn that into the next move for today's fictional operations review.

The host should combine private context with Elle's personality guidance. No other user's history should appear.

### 2. Human wisdom becomes durable

As **DemoUser1**, show the contribution already seeded from an earlier fictional Tuesday review:

> Search Shared Wisdom for green status and fresh timestamps.

Expected lesson:

> A green status without a fresh timestamp is decoration, not evidence.

Explain that this is not harvested conversation text. User 1 explicitly opted in and contributed a standalone lesson that passed conservative privacy screening.

### 3. A second person benefits

Open a separate session as **DemoUser2** and ask:

> We have a green dashboard before the morning status meeting. What should I verify before I trust it?

Then search Shared Wisdom:

> Search Shared Wisdom for green dashboards and evidence.

The same lesson should be returned without DemoUser1's identity or private history. Ask Elle to apply it:

> Give me one sentence to add to the meeting checklist.

Expected outcome: verify the source timestamp or freshness before treating green as evidence.

### 4. Portability and control

Show encrypted export and restore. Explain that the backup contains Elle memories, personality and settings—not an uncontrolled copy of Microsoft 365—and that a wrong password, different owner or modified archive is rejected.

### 5. Close

> The model can change tomorrow. The user's continuity and the community's reviewed experience do not have to disappear with it.

## Judge questions to invite

- Can User 2 see User 1's private history? No; private records remain partitioned by Entra tenant and object ID.
- Is Wisdom automatic surveillance? No; contribution requires explicit opt-in and an explicit tool call.
- Does the application retain value beyond the LLM? Yes; encrypted private context and sanitized shared lessons persist independently of the selected model.
- What is live today? Entra-authenticated MCP endpoints, encrypted memory, personality, export and restore, Model Router configuration, and durable Shared Wisdom.
- What remains prototype-grade? Host integration consent, contribution moderation and production operational controls.

## Reset and replay

The seed is idempotent. Run `elle seed-demo` once for the private role and once for the Wisdom role with `ELLE_DEMO_SEED=1` and the two demo object IDs in `ELLE_DEMO_USER_IDS`. Re-running it does not duplicate memories or the shared lesson.

## MCP endpoint placeholders

- Private Elle: `https://<private-app-host>/mcp`
- Shared Wisdom: `https://<wisdom-app-host>/mcp`

Both endpoints have public HTTPS ingress for Copilot Studio. Their Cosmos DB traffic stays on Private Link inside the VNet.
