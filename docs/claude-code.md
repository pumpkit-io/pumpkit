# Use Pumpkit from Claude Code

Pumpkit's backend serves an MCP server, so Claude Code and other MCP clients can act for you in Pumpkit (ADR 0012). It lives at `PUBLIC_URL/api/v1/mcp` on every Instance, such as `https://pumpkit.io/api/v1/mcp`, with nothing extra to install.

## Connect Claude Code

1. In Pumpkit, open your account dialog and create an API key in the API keys section. Name it after the machine or tool that will use it, such as "Work laptop".
2. Copy the `claude mcp add` command shown next to the new key, and run it once in a terminal. It looks like this:

   ```sh
   claude mcp add --transport http pumpkit https://pumpkit.io/api/v1/mcp --header "Authorization: Bearer pumpkit_..."
   ```

   Pumpkit shows the key's secret only once. If you lose it, revoke the key and create another.
3. Start Claude Code and run `/mcp`. **Check:** it lists `pumpkit` as connected.

On an Instance that sells Plans, creating a key and using the tools need a Subscription. When yours ends, every tool answers with a link to subscribe, and your keys work again once you resubscribe. Revoking a key in the account dialog stops it at once.

## Tools

| Tool | What it does |
| --- | --- |
| `list_inspiration_authors` | Lists your Inspiration authors, in the order you added them, with how many posts Pumpkit holds for each. |
| `add_inspiration_author` | Adds an X account as an Inspiration author, by its handle with or without the @, and reads its recent posts. You can have up to three. |
| `remove_inspiration_author` | Removes one of your Inspiration authors. Claude Code asks before calling it. |

Each tool refuses what the web app refuses, with the same message. Tools are limited per User: 20 calls a minute to add or remove an Inspiration author, and 60 for the tools that only read. Over the limit, a tool answers with when to try again.
