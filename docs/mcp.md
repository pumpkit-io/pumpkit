# Use Pumpkit from AI apps

Pumpkit's backend serves an MCP server, so Claude, ChatGPT, Claude Code, Codex, Gemini CLI, Cursor, VS Code and any other app that follows the MCP authorization spec can act for you in Pumpkit (ADR 0012). It lives at `PUBLIC_URL/api/v1/mcp` on every Instance, such as `https://pumpkit.io/api/v1/mcp`, with nothing extra to install.

You connect an app by pasting that URL into it and signing in to Pumpkit in your browser (ADR 0020). There is no key to copy. The app then calls the tools listed below for you, and Pumpkit lists it in Settings as one of your connected apps.

## Connect an app

Settings' Connect AI apps card shows your Instance's exact URL with a copy button, and the steps for each app below. Copy the URL exactly as shown: no trailing slash, and the same host you open Pumpkit on. The examples use `https://pumpkit.io`; on another Instance, use its `PUBLIC_URL` instead.

Every app ends the same way: it opens Pumpkit in your browser, you sign in if you aren't already, and you click **Allow** on the consent page.

### claude.ai, Claude Desktop and mobile

In Claude, open Settings, then Connectors, and choose **Add custom connector**. Name it Pumpkit, set the URL to `https://pumpkit.io/api/v1/mcp` and leave the OAuth client fields empty. Click **Connect**, sign in and click **Allow**.

On Team and Enterprise plans an Owner adds the connector first, then each member connects. On Free you get one custom connector.

### ChatGPT

In ChatGPT on the web, open Settings, then Apps, then Advanced, and turn on **Developer mode** (on Business and Enterprise, a workspace admin turns it on). Create an app with `https://pumpkit.io/api/v1/mcp` as its MCP server URL and OAuth as its authentication, then sign in and click **Allow**. In a chat, pick Pumpkit from the **+** menu under Developer mode.

### Claude Code

Run this once in a terminal. `--scope user` makes Pumpkit available in Claude Code in every directory.

```sh
claude mcp add --scope user --transport http pumpkit https://pumpkit.io/api/v1/mcp
```

Then, inside Claude Code, run `/mcp`, pick `pumpkit` and choose **Authenticate**, or run `claude mcp login pumpkit` in a terminal. **Check:** `/mcp` lists `pumpkit` as connected.

### Codex CLI

Run these in a terminal, then sign in in the browser that opens:

```sh
codex mcp add pumpkit --url https://pumpkit.io/api/v1/mcp
codex mcp login pumpkit
```

### Gemini CLI

Add this to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "pumpkit": {
      "httpUrl": "https://pumpkit.io/api/v1/mcp"
    }
  }
}
```

Then run `/mcp auth pumpkit` in Gemini CLI and sign in.

### Cursor

Add this to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "pumpkit": {
      "url": "https://pumpkit.io/api/v1/mcp"
    }
  }
}
```

Then click **Connect** next to pumpkit in Cursor's MCP settings and sign in.

### VS Code

Add this to `.vscode/mcp.json` or your user `mcp.json`:

```json
{
  "servers": {
    "pumpkit": {
      "type": "http",
      "url": "https://pumpkit.io/api/v1/mcp"
    }
  }
}
```

Then start the server and sign in when VS Code asks.

### Other apps

Any app that follows the MCP authorization spec connects the same way: give it the URL, and it finds how to sign in from Pumpkit's 401 answer and discovery documents.

None of these setups use a header or a key. If an app already has Pumpkit set up with an API key in `--header`, `headers` or `http_headers`, remove that entry first, then add it again as above.

## What the consent page shows

The consent page, `PUBLIC_URL/oauth/consent`, opens when an app asks to connect. It shows:

- "Connect {app} to Pumpkit", with the account you're signed in as. **Not you?** signs you out and brings you back to the same request once you sign in with the right account.
- What the app can do: "write and revise posts, manage your inspiration authors, schedule posts and publish them on X". It can't see your password or change your subscription.
- Who the app is. **Verified: claude.ai** means the app identified itself with a document published on that domain. **Unverified app** means it registered itself with Pumpkit, as Cursor and Gemini CLI do, so its name is only what it claims. An unverified app can still be allowed in one click: check that you started the connection yourself.
- Where it sends you back: **Sends you back to** a host, or **An app on this computer** for an app such as Claude Code that receives the answer on your machine.

**Allow** connects the app and sends you back to it. **Cancel** sends you back too and tells the app you refused. When the app opens through a link of its own, such as Cursor's `cursor://`, the browser tab stays where it is, so the page says "Done. Return to {app}." ("Cancelled. Return to {app}." after Cancel) with a link to Pumpkit, and you switch back to the app yourself.

A few cases end without buttons:

- "This request expired or was already used. Start connecting again from your app." A request lasts 30 minutes and works once.
- "This connection request isn't valid", when the app isn't registered with Pumpkit or its return address doesn't match what it registered. Start again from the app.
- On an Instance that sells Plans, connecting an app needs a subscription: without one, **Allow** shows a link to subscribe. Every tool call checks it too: when your subscription ends, each tool answers with the link to subscribe, and the app works again once you resubscribe.

You don't need to have finished Onboarding to connect an app.

### Signing in from the consent page

If you're signed out when the app opens the consent page, Pumpkit sends you to sign in and back to the request afterwards, with Google or with a Magic link opened in the same browser. A Magic link opened on another device, such as your phone, signs you in there but can't bring back the request, which lives in the first browser: start connecting again from your app.

## Stay connected and disconnect

An app stays connected without asking you to sign in again: it renews its access on its own while you use it. If it goes unused for 90 days, it asks you to sign in again.

Settings' Connect AI apps card lists your connected apps, each with whether it is verified, when it connected and when it was last used. Connecting the same app again keeps one row. **Disconnect** asks you to confirm, and the app stops working with Pumpkit at once: its next call fails and it asks you to connect again. Deleting your account disconnects every app.

## Inspiration author tools

| Tool | What it does |
| --- | --- |
| `list_inspiration_authors` | Lists your Inspiration authors, in the order you added them, with how many posts Pumpkit holds for each. |
| `add_inspiration_author` | Adds an X account as an Inspiration author, by its handle with or without the @, and reads its recent posts. You can have up to three. An account Pumpkit doesn't know yet is looked up on X first, as in the web app: a handle that isn't on X or is private is refused, and lookups are limited per User and per Instance. |
| `remove_inspiration_author` | Removes one of your Inspiration authors. Apps such as Claude Code ask before calling it. |

Each tool refuses what the web app refuses, with the same message. Tools are limited per User: 20 calls a minute to add or remove an Inspiration author, and 60 for the tools that only read. Over the limit, a tool answers with when to try again.

## Post tools

Ask your app to write a Post from an idea, then ask for changes in plain words. Each change makes a new Version and keeps the earlier ones.

| Tool | What it does |
| --- | --- |
| `start_post` | Starts a Post from a Brief and writes its first Version in the style of your Inspiration authors, as a single post or, with `format: "thread"`, a Thread. Answers with the Version's Parts and each Part's character count, against your X account's limit: 25,000 with X Premium, 280 otherwise. |
| `give_feedback` | Gives Feedback on a Post's Text as it is, your edits in the web app and a restored Version included, such as "shorter", "make Part 3 punchier" or "like Version 2, with a different hook", and writes the next Version, which becomes the Text. The writing sees every Version in order and what you did to the Text before each Feedback, and keeps the sentences you wrote by hand unless the Feedback asks to change them. It keeps the Text's Format unless you pass `format: "post"` or `format: "thread"` to switch it. Only a Draft or a Failed Post takes Feedback: on a Scheduled Post it answers that you edit or unschedule it first, and on a Published one that you start a new Post. |
| `restore_version` | Makes an earlier Version of a Post, named by its number, the Post's Text again, without writing a new Version. Hand edits to the Text are replaced; every Version stays in the Post's History. Only a Draft or a Failed Post's Text changes. |
| `list_posts` | Lists your Posts of one status, or all of them, 20 at a time (up to 50), with each one's Brief, text, number of Versions and Scheduled post (its state, time, Community, why it failed and its link on X), plus how many Posts each status holds. Scheduled Posts come soonest first, Drafts and the full list by their latest Version, newest first, Published ones most recently published first, and Failed ones most recently due first. |
| `get_post` | Reads one Post with its Text, whether you edited it since its Version, and all its Versions, each with its Feedback, text, character count and Starting text (the Text its Feedback was given on, when that wasn't the Version before as written), plus its status (Draft, Scheduled, Published or Failed) and its Scheduled post, so the app can compare Versions, schedule a Draft's Text, or see what went out. |

`restore_version` allows 10 calls a minute. Writing a Version takes up to a minute. `start_post` and `give_feedback` allow 20 calls a minute, and share the web app's limit of 30 attempts at a Version an hour, so attempts in either count toward it. Posts you start from an app show up on the web app's Posts page like any other.

On an Instance that sells Plans, each post you start and each round of feedback uses one generation of your allowance, wherever you write it, and a failed attempt none. Pumpkit's instructions tell the app so, and that `get_usage` says what is left, so it writes a new version only when you ask for one.

## Scheduled post and link tools

Every Scheduled post is copied from its Post's Text, the text set from each new Version, and a Post goes out once, so it has at most one Scheduled post. That Scheduled post gives the Post its status: Draft without one, then Scheduled, Published or Failed.

| Tool | What it does |
| --- | --- |
| `schedule_post` | Schedules the Text of a Post you name by its id, for a time you give with its UTC offset. A Thread keeps every Part in order. It goes to your profile, or to a Community you name by its URL or ID, and can also be shared with your followers. A Post goes out once: if it already has a Scheduled post, in any state, the tool refuses and tells you to edit that one, or unschedule it first. |
| `post_now` | Publishes the Text of a Post you name by its id on X right away. In a Thread, each Part replies to the one before. Like `schedule_post`, it refuses a Post that already has a Scheduled post. It goes to your profile or a Community, as with `schedule_post`. Pumpkit's instructions tell the app to show you the exact text of every Part and ask before calling it. It answers Published with the link to the post on X, Failed with the reason, or, when X hasn't taken the post yet, that Pumpkit keeps trying for 15 minutes. |
| `edit_scheduled_post` | Changes the text, time or Community of a waiting or Failed Scheduled post, or moves it back to your profile. The text can be every Part typed out, edited from what the Scheduled post holds, or, with `copy_text`, its Post's Text as it is now, such as after Feedback on a Failed Post. A new time gives a Failed one another try. In a Thread that failed partway, the live Parts are locked; the others can be edited, added, removed and reordered, the Text's Parts in the live ones' places are skipped, and a new time publishes only the rest, as replies to the last live Part. |
| `delete_scheduled_post` | Deletes a waiting or Failed Scheduled post, which unschedules it: its Post is a Draft again, so it takes Feedback and can be scheduled anew. Apps such as Claude Code ask before calling it. |
| `list_past_communities` | Lists the Communities you posted to before from your connected X account. |
| `connect_x` | Answers with the link to the Settings page, where you connect, reconnect or disconnect X. |
| `get_usage` | Says what you have left of your allowance this period: generations, X posts and, of those, X posts with a link, each with its limit, how many you used and how many are left, and when the period resets (or your trial ends), plus what each of your top-ups has left and until when. On an Instance that sells no Plans it says there is no allowance. |
| `manage_subscription` | Answers with the link to the Settings page, where you manage your Subscription. Without a Subscription, it answers like every tool, with the link to the page where you subscribe. On an Instance that sells no Plans, it says so instead. |

Scheduling and Post now follow the web app's rules: it needs an X connection that X still accepts, the text must fit your X account's limit, a scheduled time must be at least a minute away, a Community must be one X knows, and your X posts are counted, one per Part, and one link post per Part containing a link, including those you scheduled in the web app. At your allowance's limit the refusal says when it resets and links to the Settings page. The X connection refusals link to the Settings page, and every Scheduled post answer to its Post's page in the web app. `schedule_post`, `post_now`, `edit_scheduled_post` and `delete_scheduled_post` allow 10 calls a minute, and the others 60.
