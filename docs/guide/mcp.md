# Connect your own MCP servers

The Model Context Protocol (MCP) lets you give Heya extra tools. An MCP server
is a small program that exposes tools; Heya is the client that connects to it
and can then call those tools during a task. You add servers in your config.

## Add a server

Each server is a table under `[mcp.servers.<name>]` in
`~/.config/heya/config.toml`. The fields:

- `transport`: `"stdio"`, `"http"`, or `"sse"`.
- `command` and `args`: for `stdio`, the local program to run and its arguments.
- `url`: for `http` or `sse`, the server URL.
- `enabled`: `true` by default; set `false` to keep a server in the file but off.
- `tools`: `["*"]` for all the server's tools, or a list of specific tool names.
- `env_keys`: a list of environment variable NAMES whose values are passed to
  the server at startup. Heya passes the value from your environment and never
  stores it.
- `auth_token_env`: the name of an environment variable holding a bearer token
  (for `http`/`sse`).
- `headers`: extra request headers, for example `{ "X-Tenant" = "acme" }`.
- `tls_verify`, `tls_ca_cert`, `tls_client_cert`, `tls_client_key`: TLS options
  for an `http`/`sse` server that needs a custom CA or mutual TLS.
- `auth`: `"none"` (default), `"bearer"`, or `"oauth"`. Set to `"bearer"` when
  you supply a static token via `auth_token_env`; set to `"oauth"` for a server
  that issues tokens via the OAuth 2.0 device or authorization-code flow.
- `scopes`: a list of OAuth scope strings requested during the OAuth flow (for
  `auth = "oauth"` only).
- `oauth_client_name`: a label Heya shows in OAuth prompts (optional; defaults
  to the server name).
- `oauth_token_store`: where Heya caches the OAuth token between sessions.
  `"keyring"` (default) uses the OS keychain; `"memory"` keeps it only for the
  current run.

## A local (stdio) server

Many MCP servers are published on npm and run with `npx`:

```toml
[mcp.servers.everything]
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-everything"]
enabled = true
tools = ["*"]
```

A stdio server runs a local command, so that command must be installed. For
`npx` that means Node.js. Heya runs the command; it does not install Node for
you. If you are not sure it is there, ask Heya to run `node --version`.

## A remote (http) server

```toml
[mcp.servers.acme]
transport = "http"
url = "https://mcp.acme.example/v1"
auth_token_env = "ACME_MCP_TOKEN"
tools = ["search", "create_ticket"]
```

`auth_token_env` names the environment variable that holds your token. Set it in
your shell (`export ACME_MCP_TOKEN=...`); Heya reads the value at connect time
and never writes it to a file.

## An OAuth-protected server

For servers that use OAuth rather than a static token, set `auth = "oauth"`.
Heya walks you through the browser flow on first connect and caches the token in
your OS keychain (`oauth_token_store = "keyring"`, the default).

```toml
[mcp.servers.my-oauth-server]
transport = "http"
url = "https://mcp.example.com/v1"
auth = "oauth"
scopes = ["read", "write"]
oauth_client_name = "Heya"    # label shown in the OAuth prompt
# oauth_token_store = "keyring"  # keyring (default) | memory
```

`auth = "oauth"` requires `transport = "http"` or `"sse"` and is mutually
exclusive with `auth_token_env`.

## Check what connected

Start Heya and run `/mcp` to list the tools the connected servers expose. If a
server is missing, it was skipped (a bad command, a missing token, or an
unreachable URL); fix the config and restart.
