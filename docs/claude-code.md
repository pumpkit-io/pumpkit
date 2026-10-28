# Use Pumpkit from Claude Code

Pumpkit's backend serves an MCP server, so Claude Code and other MCP clients can act for you in Pumpkit (ADR 0012). It lives at `PUBLIC_URL/api/v1/mcp` on every Instance, such as `https://pumpkit.io/api/v1/mcp`, with nothing extra to install.

## Connect Claude Code

1. In Pumpkit, open Settings and create an API key in the API keys card. Name it after the machine or tool that will use it, such as "Work laptop".
2. Copy the `claude mcp add` command shown next to the new key, and run it once in a terminal. It looks like this:

   ```sh
   claude mcp add --scope user --transport http pumpkit https://pumpkit.io/api/v1/mcp --header "Authorization: Bearer pumpkit_..."
   ```

   `--scope user` makes Pumpkit available in Claude Code in every directory. Claude Code saves the URL and the key in plain text in `~/.claude.json`.

   Pumpkit shows the key's secret only once. If you lose it, revoke the key and create another.
3. Start Claude Code and run `/mcp`. **Check:** it lists `pumpkit` as connected.

On an Instance that sells Plans, creating a key and using the tools need a Subscription. When yours ends, every tool answers with a link to subscribe, and your keys work again once you resubscribe. Revoking a key in Settings stops it at once.

## Inspiration author tools

| Tool | What it does |
| --- | --- |
| `list_inspiration_authors` | Lists your Inspiration authors, in the order you added them, with how many posts Pumpkit holds for each. |
| `add_inspiration_author` | Adds an X account as an Inspiration author, by its handle with or without the @, and reads its recent posts. You can have up to three. |
| `remove_inspiration_author` | Removes one of your Inspiration authors. Claude Code asks before calling it. |

Each tool refuses what the web app refuses, with the same message. Tools are limited per User: 20 calls a minute to add or remove an Inspiration author, and 60 for the tools that only read. Over the limit, a tool answers with when to try again.

## Post tools

Ask Claude Code to write a Post from an idea, then ask for changes in plain words. Each change makes a new Version and keeps the earlier ones.

| Tool | What it does |
| --- | --- |
| `start_post` | Starts a Post from a Brief and writes its first Version in the style of your Inspiration authors, as a single post or, with `format: "thread"`, a Thread. Answers with the Final's Parts and each Part's character count, against your X account's limit: 25,000 with X Premium, 280 otherwise. |
| `give_feedback` | Gives Feedback on the latest Version of a Post, such as "shorter" or "make Part 3 punchier", and writes the next Version. It keeps the latest Version's Format unless you pass `format: "post"` or `format: "thread"` to switch it. |
| `list_posts` | Lists your Posts of one status, or all of them, 20 at a time (up to 50), with each one's Brief, text, number of Versions and Scheduled post (its state, time, Community, why it failed and its link on X), plus how many Posts each status holds. Scheduled Posts come soonest first, Drafts and the full list by their latest Version, newest first, Published ones most recently published first, and Failed ones most recently due first. |
| `get_post` | Reads one Post with all its Versions, each with its Feedback, text and character count, plus its status (Draft, Scheduled, Published or Failed) and its Scheduled post, so Claude Code can compare Versions, schedule one of a Draft, or see what went out. |

Writing a Version takes up to a minute. `start_post` and `give_feedback` allow 20 calls a minute, and share the web app's limit of 30 attempts at a Version an hour, so attempts in either count toward it. Posts you start from Claude Code show up on the web app's Posts page like any other.

## Scheduled post and link tools

| Tool | What it does |
| --- | --- |
| `schedule_post` | Schedules a post for a time you give with its UTC offset. The post is your own text, as one Part or as several for a Thread, or the Final of a Version you name by its id. A Thread's Final keeps every Part in order. It goes to your profile, or to a Community you name by its URL or ID, and can also be shared with your followers. |
| `post_now` | Publishes your own text, or a Version's Final, on X right away. In a Thread, each Part replies to the one before. It goes to your profile or a Community, as with `schedule_post`. Claude Code shows you the exact text of every Part and asks before calling it. It answers Published with the link to the post on X, Failed with the reason, or, when X hasn't taken the post yet, that Pumpkit keeps trying for 15 minutes. |
| `edit_scheduled_post` | Changes the text, time or Community of a waiting or Failed Scheduled post, or moves it back to your profile. A new time gives a Failed one another try. In a Thread that failed partway, the live Parts are locked; the others can be edited, added, removed and reordered, and a new time publishes only them, as replies to the last live Part. |
| `delete_scheduled_post` | Deletes a waiting or Failed Scheduled post. Claude Code asks before calling it. |
| `list_past_communities` | Lists the Communities you posted to before from your connected X account. |
| `connect_x` | Answers with the link to the Settings page, where you connect, reconnect or disconnect X. |
| `manage_subscription` | Answers with the link to the billing page, where you subscribe or manage your Subscription. On an Instance that sells no Plans, it says so instead. |

Scheduling and Post now follow the web app's rules: it needs an X connection that X still accepts, the text must fit your X account's limit, a scheduled time must be at least a minute away, a Community must be one X knows, and the monthly cap counts X posts, one per Part, including those you scheduled in the web app. The X connection refusals link to the Settings page, and every Scheduled post answer to the Posts page. `connect_x` and `manage_subscription` work without a Subscription. `schedule_post`, `post_now`, `edit_scheduled_post` and `delete_scheduled_post` allow 10 calls a minute, and the others 60.
