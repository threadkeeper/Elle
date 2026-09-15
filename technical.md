# Elle technical deployment guide

This guide records the deployment sequence used for the Elle prototype without
including tenant-specific identifiers, credentials, internal links, personal
data, or live service addresses. Replace every value in angle brackets with a
value from your own environment.

## Architecture

Elle is deployed as two independent, authenticated MCP services:

- **Private Elle** provides user-partitioned memory and personality tools.
- **Shared Wisdom** provides reviewed, non-private guidance shared across
  authenticated users.

Both services use the same container image but start with different roles. They
use managed identity for Azure dependencies and delegated Microsoft Entra
tokens for caller identity.

## Deployment steps

1. **Create the source repository.** Keep application code, infrastructure
   scripts, tests, and workflows in source control. Keep secrets, generated
   evaluation results, local build output, and exported archives out of Git.

2. **Implement strict identity partitioning.** Derive each private owner key
   from the validated Entra tenant ID and object ID. Never accept an owner ID as
   a tool argument.

3. **Separate the MCP roles.** Run Private Elle and Shared Wisdom as different
   services with disjoint tool catalogs. Do not expose a combined role.

4. **Encrypt private fields.** Encrypt selected memory and personality fields
   with AES-256-GCM. Derive owner-specific keys and authenticate record binding
   data so ciphertext cannot be moved between owners.

5. **Implement portable archives.** Protect exports with AES-256-GCM and a
   password-derived key. Validate archive ownership, format, size, and
   integrity before restoring records.

6. **Add conservative Shared Wisdom controls.** Require explicit contribution,
   screen generalized lessons, reject identifiers and instruction-like input,
   and store no contributor identity in shared records.

7. **Implement MCP over streamable HTTP.** Expose `POST /mcp`, `GET /healthz`,
   and OAuth protected-resource metadata. Return `401` plus a
   `WWW-Authenticate` resource-metadata challenge for anonymous MCP requests.

8. **Advertise a fully qualified OAuth scope.** Publish
   `api://<api-application-id>/access_as_user` in protected-resource metadata.
   A bare `access_as_user` scope can be incorrectly associated with Microsoft
   Graph by generic MCP clients.

9. **Validate delegated access tokens.** Pin the accepted tenant, audience,
   issuer, signing algorithm, signing keys, lifetime, and `access_as_user`
   scope. Private Elle should additionally enforce an explicit demo-user allow
   list when the deployment is intentionally restricted.

10. **Add secret-safe diagnostics.** Log service role, request sequence, HTTP
    method and path, JSON-RPC method, tool name, status, and redacted error
    category. Never log tokens, request bodies, owner IDs, memory text, secrets,
    or upstream response bodies.

11. **Create synthetic demo data.** Use fictional user histories and generalized
    lessons only. Make seeding idempotent so repeated deployments do not create
    duplicates.

12. **Build deterministic tests.** Cover encryption, identity isolation,
    archive integrity, role-separated tool catalogs, Shared Wisdom isolation,
    malformed input, and storage concurrency.

13. **Create a curated persona gate.** Use a small high-signal evaluation set,
    bounded concurrency, retry malformed judge output, and enforce a workflow
    timeout. Store generated evidence as workflow artifacts rather than tracked
    files.

14. **Create an Azure resource group.** Use a dedicated group for the prototype
    so access control, cost tracking, and cleanup remain bounded.

15. **Create a virtual network.** Reserve separate subnets for Azure Container
    Apps infrastructure and private endpoints. Delegate only the Container Apps
    subnet.

16. **Create Azure Cosmos DB.** Use the NoSQL API, disable key authentication,
    and disable public network access after private connectivity is ready.

17. **Create a Cosmos DB private endpoint.** Place it in the private-endpoint
    subnet and approve the SQL data-plane connection.

18. **Configure private DNS.** Create and link the Cosmos private DNS zone to
    the virtual network. Verify that the normal Cosmos hostname resolves to the
    private endpoint from the application environment.

19. **Create an Azure Container Apps environment.** Integrate it with the
    delegated subnet and enable the logging destination required for operations.

20. **Create an Azure Container Registry.** Build one Linux AMD64 image for both
    MCP roles. Tag immutable images with the full Git commit SHA.

21. **Create the two Container Apps.** Deploy `<private-app-name>` with role
    `private` and `<wisdom-app-name>` with role `wisdom`. Configure external
    HTTPS ingress while keeping Cosmos traffic private.

22. **Assign managed-identity permissions.** Grant each app only the registry
    pull, Cosmos data-plane, and model-service permissions required by its role.
    End users do not receive direct Cosmos access.

23. **Configure application settings.** Supply tenant, API audience, public
    origin, storage account details, encryption material, allowed private users,
    model endpoint, chat deployment, embedding endpoint, embedding deployment,
    and embedding dimensions through protected deployment configuration.

24. **Configure model services.** Private Elle can use a model-routing chat
    deployment and a dedicated embedding deployment. Shared Wisdom can run
    without the private retrieval model when its catalog is deterministic.

25. **Create GitHub OIDC deployment identity.** Use federated credentials
    instead of a stored Azure client secret. Put identifiers in repository
    secrets or variables and grant the deployment identity only the required
    Azure roles.

26. **Create the deployment workflow.** Run formatting, strict linting, and all
    tests before Azure login. Build the image in the registry, update both apps
    to the same immutable image, then verify health and anonymous `401`
    behavior.

27. **Register the Entra API.** Expose delegated scope
    `access_as_user`. Configure the MCP servers to validate the API application
    audience rather than the OAuth client audience.

28. **Register an OAuth client.** Use authorization-code flow with PKCE and
    delegated permission to the MCP API. Add each custom connector callback URI
    exactly as generated by Power Platform.

29. **Create a Power Platform environment.** Provision Dataverse in a sandbox
    or production environment appropriate for the intended lifecycle.

30. **Assign maker roles.** Give agent builders the minimum Dataverse roles
    required to create and manage the agent. Verify the role associations
    directly if environment discovery remains empty after sign-in.

31. **Create the Shared Wisdom MCP connector.** Configure the Shared Wisdom HTTPS
    MCP endpoint as a custom connector. Use the Entra OAuth client and fully
    qualified delegated API scope.

32. **Add Private Elle as a direct MCP server.** In the agent editor, select
    **Add tool**, open **Model Context Protocol (MCP)**, select **Add**, and then
    select **Model Context Protocol (MCP)** again to create a new server. Do not
    select a previously created Private connector from the catalog when
    recovering from a stale or broken tool definition.

33. **Enter the direct Private server details.** Supply a generic server name and
    description, and set the server URL to
    `https://<private-app-host>/mcp`. Select **OAuth 2.0** authentication and
    **Manual** configuration.

34. **Configure direct Private OAuth.** Enter the OAuth client ID and a dedicated
    client secret created for the Copilot Studio MCP definition. Use the
    tenant-specific authorization endpoint, token endpoint, and refresh
    endpoint. Set scopes to
    `api://<api-application-id>/access_as_user offline_access`. Store the secret
    only in Entra and Copilot Studio; never put it in source control,
    documentation, logs, or agent instructions.

35. **Register the generated callback URI.** Start connection creation once so
    Copilot Studio displays or sends its generated
    `https://global.consent.azure-apim.net/redirect/<connector-name>` callback.
    Append that exact URI to the OAuth client's web redirect URIs in Entra.
    Preserve all existing callback URIs. Retry the OAuth flow only after the new
    URI is present.

36. **Create the maker connection with an allowed test identity.** Complete the
    new direct server's OAuth connection using an identity accepted by the
    Private server's deployment policy. This connection lets Copilot Studio
    discover the MCP tool inventory; it does not replace per-user runtime
    authentication.

37. **Keep the Private tool in User mode.** After the tool inventory loads,
    choose **User** authentication mode and attach **Elle Private Direct** to the
    agent. Do not leave it in **Maker** mode, which would bind runtime calls to
    the maker connection instead of requiring each caller's connection.

38. **Keep the agent surface minimal.** Disable **Memory (Preview)**, do not add
    knowledge sources or connected agents, and disable web grounding when the
    test is intended to isolate the two Elle MCP services. In this deployment,
    disabling Memory Preview stopped the Microsoft 365 conversation UI from
    failing after conversation creation.

39. **Create the Copilot Studio agent.** Enable generative orchestration, add
    clear privacy instructions, and attach only Private Elle Direct and Shared
    Wisdom as separate MCP tools using User/invoker authentication.

40. **Share any connector-backed definitions with users.** Grant intended users
    read/use access to custom connector records that remain in use. They do not
    need edit access. Direct MCP server definitions instead prompt each user to
    create their own runtime connection.

41. **Publish to Microsoft 365 and Teams.** Enable the channel, publish the
    agent, select the intended audience, and submit through the organization
    catalog approval process when broad discovery is required.

42. **Configure Copilot Credits.** Link an eligible billing plan or allocate
    prepaid capacity. Confirm the effective environment entitlement rather than
    relying only on the billing-policy status.

43. **Allocate capacity to the environment.** Assign the required Copilot
    Credits to the agent environment and choose whether it may draw from the
    unallocated tenant pool. Verify that environment status reports
    `WithinCapacity`.

44. **Create end-user connections.** Each user opens the agent connection page,
    creates their own OAuth connection for Shared Wisdom and Private Elle
    Direct, explicitly chooses their own account, and confirms both show
    `Connected`.

45. **Start a fresh conversation.** Tool availability can be snapshotted when a
    conversation starts. After changing connectors, permissions, or
    connections, republish the agent and start a new conversation.

46. **Test Shared Wisdom.** Ask an explicit shared query and verify that a
    reviewed lesson is returned without private user context.

47. **Test private recall.** Explicitly request the Private Elle context tool and
    verify that the response reflects only the signed-in user's synthetic
    history.

48. **Test cross-user isolation.** Repeat with a second user. Confirm that both
    users can retrieve Shared Wisdom while neither can retrieve the other's
    private memories.

49. **Test generic MCP clients.** Configure each remote server with `type:
    "http"`, its `/mcp` URL, and a fixed OAuth client ID when the authorization
    server does not support dynamic client registration. Verify the browser
    requests the fully qualified API scope.

50. **Monitor safely.** Stream each Container App independently during retries.
    If no Private request appears, investigate host tool discovery, connector
    permissions, connection binding, or publication state before investigating
    Cosmos.

51. **Interpret Copilot Studio authorization errors at both layers.** A
    Copilot Studio `modelcontextprotocol/listtools` response can report `403`
    because its token exchange lacks connection ACL access even when the Private
    service itself records `401 token_rejected`. Check both the Power Platform
    response body and redacted Container App diagnostics. A green connection
    status alone does not prove that a usable bearer token reached the MCP
    server.

52. **Isolate broken write-approval behavior explicitly.** Copilot Studio can
    render a write approval card with only **Retry** and **Deny**, making an
    approved `elle_remember` call impossible. For this prototype only,
    `elle_remember` advertises `readOnlyHint: true` so the host can be tested
    without that broken card. The operation still writes durable private data,
    remains owner-partitioned, and must not be treated as genuinely read-only.
    Remove this compatibility exception when the host supports usable standing
    approval or per-call approval.

53. **Keep operations bounded.** Set cost alerts, document temporary-capacity
    expiry, remove elevated setup roles when no longer needed, rotate client
    credentials, and retain only synthetic data until production controls are
    complete.

## Generic verification checklist

1. `GET https://<private-app-host>/healthz` returns `200`.
2. `GET https://<wisdom-app-host>/healthz` returns `200`.
3. Anonymous `POST /mcp` returns `401` from both services.
4. Protected-resource metadata advertises the fully qualified delegated scope.
5. Private and Shared Wisdom expose disjoint tool catalogs.
6. The direct Private MCP definition can load its tool inventory.
7. The Private tool uses User authentication mode, not Maker mode.
8. Memory Preview, web grounding, knowledge, and connected agents are disabled
   for the isolated two-MCP test.
9. Each end-user connection shows `Connected`.
10. The environment has effective, allocated Copilot Credits.
11. Shared Wisdom returns reviewed guidance.
12. Private recall returns only the caller's partition.
13. A second user cannot retrieve the first user's private data.
14. Logs contain protocol metadata and redacted errors only.
