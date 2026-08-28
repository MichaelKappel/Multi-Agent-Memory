# Connect ChatGPT to Multi-Agent Memory

The public runtime includes a dedicated OAuth 2.1 MCP surface at `/mcp`. It is
separate from the LocalEndpoint connector-pairing protocol and from company
master or governed agent credentials.

## What the human experiences

1. An administrator keeps the Multi-Agent Memory LAN host running over HTTPS.
2. ChatGPT connects through a public HTTPS MCP URL or OpenAI Secure MCP Tunnel.
3. ChatGPT discovers the OAuth metadata and opens the Multi-Agent Memory login
   page in the browser.
4. The human signs in with their normal Multi-Agent Memory username and
   password, chooses one active workspace, reviews the requested read/write
   scopes, and selects **Allow connection**.
5. ChatGPT exchanges the one-use PKCE code and treats the app as connected only
   after `initialize`, `tools/list`, and the read-only `workspace_status` tool
   succeed.

Passwords, company master credentials, governed agent credentials, raw private
payloads, and refresh tokens are never displayed in the approval page.

## Windows host check

From the public repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_chatgpt_mcp.ps1 -Status -LocalMcpUrl https://your-intranet-host.example/mcp
```

The report is redacted. `localMcpReady=true` means the protected-resource
metadata has the exact configured resource and issuer, authorization-server
metadata has the exact configured issuer/endpoints and PKCE S256, and an
unauthenticated MCP initialize received the expected resource-bound OAuth 401
challenge. It does not claim that ChatGPT can reach the host. A public-looking
DNS name is configuration, not proof of external reachability.

Open `/mcp/setup` in a browser for the same operator-facing status and the
configured MCP resource and issuer.

## Private host with OpenAI Secure MCP Tunnel

OpenAI Secure MCP Tunnel is outbound-only: the local `tunnel-client` polls
OpenAI and forwards MCP JSON-RPC to the private `/mcp` endpoint. Before setup,
the operator needs:

- a `tunnel_id` from OpenAI Platform tunnel settings;
- a runtime API key whose principal has Tunnels Read + Use;
- ChatGPT developer-mode access and a tunnel associated with the target
  ChatGPT workspace; and
- the current supported `tunnel-client` downloaded from Platform tunnel
  settings or the official OpenAI release.

Then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_chatgpt_mcp.ps1 `
  -Status -Configure -Run `
  -TunnelId tunnel_0123456789abcdef0123456789abcdef `
  -LocalMcpUrl https://your-intranet-host.example/mcp
```

If `CONTROL_PLANE_API_KEY` is not already present in the process environment,
the helper prompts with hidden input and removes the temporary process value
when it exits. It uses OpenAI's `sample_mcp_with_dcr` profile, runs `doctor
--explain`, and keeps the foreground tunnel process attached to the terminal.
Before configuration, it asks the installed binary to show that built-in sample
and stops with an upgrade instruction if the binary does not support it. It
never writes or prints the runtime API key.

In ChatGPT, enable developer mode, create a developer-mode app, choose
**Tunnel** under Connection, and select the associated tunnel. Keep
`tunnel-client run` healthy for discovery and every tool call.

## OAuth reachability is separate

Secure MCP Tunnel carries MCP discovery and JSON-RPC, but it does not
automatically tunnel the authorization server. The OAuth issuer must expose
this exact, narrow route set through an approved public HTTPS reverse proxy:

- `/.well-known/oauth-authorization-server`
- `/.well-known/oauth-protected-resource/mcp`
- `/oauth/register`
- `/oauth/authorize`
- `/oauth/session`
- `/oauth/token`
- `/oauth/revoke`
- `/static/js/mcp-authorize.js`
- `/static/css/site.css`

The browser needs the authorization, session, JavaScript, and CSS routes;
OpenAI needs discovery, registration, token, and revocation. Do not publish the
entire LAN host merely to expose OAuth. Preserve the public host, scheme, and
forwarded request integrity at the proxy; the login endpoint accepts only an
exact same-origin browser request for the configured issuer.

When an approved proxy provides stable public URLs, save the non-secret URL
configuration locally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_chatgpt_mcp.ps1 `
  -Status `
  -LocalMcpUrl https://your-intranet-host.example/mcp `
  -PublicMcpUrl https://mcp.example.com/mcp `
  -OAuthIssuerUrl https://auth.example.com
```

This writes only URLs and redaction flags to the ignored
`.local-secrets/mcp-host.json` file. It stores no password, OpenAI key, OAuth
code, access token, refresh token, or tenant payload.

## Security contract

- DCR accepts only exact `https://chatgpt.com` connector callbacks.
- OAuth requires PKCE S256 and exact `resource` propagation.
- Authorization codes are one-use and expire after two minutes.
- Access tokens are opaque, audience-bound, and expire after one hour.
- Refresh tokens rotate on use and expire after 30 days; `/oauth/revoke`
  disconnects the connection's token family.
- Every MCP call revalidates the human account, company authority, company, and
  workspace as active.
- Read and write scopes are enforced independently.
- `Origin` is fail-closed when present; requests are size- and rate-limited.
- Tool results remain public-safe and memory writes enter the existing firewall,
  quota, idempotency, confirmed-readback, audit, and review workflow.

Current OpenAI references:

- <https://developers.openai.com/plugins/build/auth>
- <https://developers.openai.com/api/docs/guides/secure-mcp-tunnels>
- <https://developers.openai.com/plugins/deploy/connect-chatgpt>
