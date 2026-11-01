# AI apps connect to the MCP server through OAuth, and API keys are removed

Pumpkit is its own OAuth authorization server for its MCP endpoint, which stays the protected resource on the same origin. A User pastes `PUBLIC_URL/api/v1/mcp` into an AI app, signs in to Pumpkit in the browser and clicks Allow. OAuth access tokens become the only credential the endpoint accepts, and API keys are removed: the model, the table, the Settings card, the docs and the glossary entry. This supersedes the API key decision of ADR 0012, which listed OAuth as an option for later. The MCP endpoint, its tools and their access rules stay as ADR 0012 set them. ChatGPT cannot send an API key at all, claude.ai can only send a fixed header that a User must copy in by hand, and two credentials for one endpoint would double the auth code to secure and test.

A Connected app is never a Sign-in method and never opens a Session, so ADR 0002 holds: the User signs in with Google or a Magic link, and OAuth only lets an app act for them. MCP calls still send no product events (ADR 0009). The consent page's own events are ordinary browser events behind Analytics consent.

## Decisions

- **Authorization server.** The backend serves it in a new area, `connected_apps`, which sits beside `billing` in ADR 0008's order and imports only `auth` below it. The issuer is the bare `PUBLIC_URL`, the endpoints live under `/api/v1/oauth/`, and the metadata documents sit at the root `/.well-known/`. Each Instance gets it with no new setting (ADR 0011).
- **Hand-written endpoints.** The routes are FastAPI routes that follow router, mediator, service. The MCP SDK's own server-side OAuth routes fix their paths at the issuer root, advertise no `none` client authentication, match redirect URIs exactly (which fails Claude Code's portless loopback URIs), check the token audience only when asked, and give a provider no database session. The SDK's client runs in the tests as an independent conformance check.
- **Client registration.** Dynamic Client Registration (RFC 7591) comes first, for public clients by default, because Gemini CLI and Cursor support nothing else. Client ID Metadata Documents (CIMD) follow as the last piece of the same spec, and the authorization server advertises them only once they work end to end, because a client that sees the advertisement never falls back to DCR. CIMD lets the consent page show a verified domain.
- **Tokens.** Access tokens, refresh tokens, authorization codes and client secrets are opaque random values stored as SHA-256 hashes. Access tokens last one hour, refresh tokens 90 days. A refresh token rotates on every use, and presenting a rotated one again after a two-minute grace window disconnects the app. Tokens are bound to the MCP URL (RFC 8707). One scope, `pumpkit`, grants what an API key granted.
- **Consent.** The backend stores the authorization request and sends the browser to a consent page in the web app, which reuses the web app's sign-in and Session. Approving is a bearer-authenticated request, so CSRF cannot forge it.
- **Access rule.** Approving needs a Subscription on an Instance that sells Plans. The consent page sits outside the Onboarding gate, and its details and deny routes are open to any signed-in User. This departs from ADR 0018, which closes every area route to an unsubscribed User. The page is not an area route, and an unsubscribed User who arrives from an app should see the subscribe prompt on Allow instead of losing the authorization request to a redirect to the Paywall. Token issuance and refresh do not re-check billing: each tool call already does.
- **Removing API keys.** The removal ships in the same spec but merges last, after the shared `mcp` test fixture runs on OAuth and the manual client matrix passes with at least Claude Code and claude.ai.

## Considered Options

- **An external identity provider (Auth0, WorkOS, Stytch).** Every Self-hoster would have to configure a third party to use MCP, which ADR 0011 rules out, and it would duplicate the sign-in that ADR 0002 keeps in Pumpkit.
- **Keeping API keys beside OAuth.** It would leave two ways in with two sets of docs, for callers nobody has today.
- **JWT access tokens.** They need their own signing key or audience to stay apart from the web app's Session tokens, they cannot be revoked at once, and they save nothing because the endpoint already reads the database on every request.
- **Per-tool scopes.** They can come later, with `insufficient_scope` step-up.

## Consequences

- Callers that can only send a fixed token lose access: the Claude API MCP connector, the OpenAI Responses API `mcp` tool, n8n and server-side agents with no browser. If someone needs that later, it is a new ADR (personal access tokens issued by the OAuth server, for example), not a revival of API keys.
- Existing API keys stop working. Pumpkit has no deployed users besides the maintainer, so no migration of keys is offered.
- A Self-hoster's own reverse proxy must forward `/.well-known/oauth-*` as well as `/api/*`, and `PUBLIC_URL` must be reachable over HTTPS by hosted clients such as claude.ai and ChatGPT.
- The MCP endpoint's DNS-rebinding comment in ADR 0012 now refers to an OAuth access token, not an API key, as the credential guarding it.
- Browser-based clients (MCP Inspector, web IDEs) need permissive CORS on the discovery, token, register, revoke and MCP paths only, without credentials. The authorize path, the consent API and the Settings API keep the strict CORS.
