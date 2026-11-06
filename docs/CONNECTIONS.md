# Protected MCP connections

Für eine direkte ChatGPT-Verbindung ab Version 2.1 siehe [CHATGPT.md](CHATGPT.md). Verwaltung und MCP können dieselbe Domain und Port 3061 verwenden. Nur exakte OAuth-/MCP-Pfade erhalten Bypass-Regeln; die Verwaltung behält ihre Pangolin-Anmeldung. Der gemeinsame direkte Endpunkt akzeptiert keine alten Bridge-Tokens. Die folgenden Einstellungen gelten für den bisherigen Bridge-Modus.


## Browser

Pangolin authentication stays active for the resource. Browser administration then requires the single central GitHub OAuth login and numeric account allowlist. Public app protocol metadata or health output does not bypass the front proxy or grant vault access.

One GitHub OAuth App serves every configured vault. Browser and MCP OAuth are different flows with two callback paths on the same App. Browser session cookies are not accepted as MCP credentials. MCP tokens do not grant browser administration.

## Header bridge

Create a limited app client token in `/admin/` and a separate resource access token in Pangolin. Store their values in a protected local file, outside Git:

```dotenv
MCP_SERVER_URL=https://YOUR_HOST/mcp
PANGOLIN_TOKEN_ID=enter-locally
PANGOLIN_ACCESS_TOKEN=enter-locally
MCP_CLIENT_TOKEN=enter-locally
```

The generated values are header-safe strings. Do not add shell quotes to a file consumed by `docker run --env-file`; that format treats quote characters literally. Restrict the file to its operator. This file is separate from the stack's GitHub credentials.

A local MCP client can start the bridge with this argv-style command configuration. Replace paths and image tag locally:

```json
{
  "mcpServers": {
    "obsidian-protected": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--env-file", "/ABSOLUTE/PRIVATE/PATH/bridge.env", "ghcr.io/3115a083/obsidian-mcp:stable", "python", "/app/bridge.py"]
    }
  }
}
```

The operator's Docker client must already be able to pull the private image. The bridge has no vault mount and no Docker socket. Its STDIO output belongs only to the MCP client. Do not add a public unauthenticated HTTP listener around it.

Both Pangolin headers accompany every upstream MCP request. The application capability grants access to selected immutable share IDs and expires after 1 to 90 days. It defaults to read-only access. Version 2.2.0 can grant explicit write folders as described in [WRITING.md](WRITING.md). Its raw value is never committed or logged by this implementation. If Pangolin uses custom header names rather than its documented defaults, adapt the bridge through a reviewed change; do not turn off protection to make it connect.

Synthetic integration tests exercise two consecutive authorization boundaries and verify redirects do not forward credentials to a different host. They do not verify your real Pangolin resource or account configuration.

## Cloud ChatGPT through a private tunnel

The direct custom-MCP setup must not be represented as supporting arbitrary additional Pangolin headers. The bridge solves the header problem on the operator side. A private Secure MCP Tunnel can expose the bridge's **STDIO** service to a supported OpenAI product while the bridge's HTTPS upstream remains Pangolin-protected.

Availability, account/workspace association and permissions are prerequisites, not implementation defaults. OpenAI documents Tunnels Read + Manage for creation and Read + Use for runtime/selection. Obtain `tunnel_id` and the restricted runtime key in the appropriate Platform organization. Enter the actual key locally, never in chat, argv or Git.

With the official `tunnel-client`, inspect `tunnel-client help quickstart` first. A named STDIO profile is initialized with `--sample sample_mcp_stdio_local`, `--profile <name>`, `--tunnel-id <id>` and `--mcp-command <the bridge command>`. Run `tunnel-client doctor --profile <name> --explain`, then `tunnel-client run --profile <name>`. The command contains only local credential-file paths, not secret values.

In ChatGPT select **Tunnel** for a custom MCP connection. The bridge itself is a private STDIO service without another browser OAuth exchange; upstream app and Pangolin credentials are already supplied by the bridge. Selecting no extra auth on this private tunnel is not disabling authentication on the public Pangolin resource.

Setup is complete only after the intended workspace lists the tunnel, the client is healthy, the expected note tools appear and a representative allowed-vault read succeeds. Verify a denied vault and token revocation too. Until then this path remains unverified. The app never installs tunnel binaries or creates account resources automatically.

## Sources

- https://docs.pangolin.net/manage/access-control/links
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://github.com/openai/tunnel-client
