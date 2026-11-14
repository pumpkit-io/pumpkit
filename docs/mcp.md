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

None of these setups add a header. If an app already has Pumpkit set up with an `Authorization` header in `--header`, `headers` or `http_headers`, remove that entry first, then add it again as above.

## What the consent page shows

The consent page, `PUBLIC_URL/oauth/consent`, opens when an app asks to connect. It shows:

- "Connect {app} to Pumpkit", with the account you're signed in as. **Not you?** signs you out and brings you back to the same request once you sign in with the right account.
- What the app can do: "write and revise posts, edit your positioning, schedule posts and publish them on X". It can't see your X password or change your subscription.
- Who the app is. **Verified: claude.ai** means the app identified itself with a document published on that domain. **Unverified app** means it registered itself with Pumpkit, as Cursor and Gemini CLI do, so its name is only what it claims. An unverified app can still be allowed in one click: check that you started the connection yourself.
- Where it sends you back: **Sends you back to** a host, or **An app on this computer** for an app such as Claude Code that receives the answer on your machine.

**Allow** connects the app and sends you back to it. **Cancel** sends you back too and tells the app you refused. When the app opens through a link of its own, such as Cursor's `cursor://`, the browser tab stays where it is, so the page says "Done. Return to {app}." ("Cancelled. Return to {app}." after Cancel) with a link to Pumpkit, and you switch back to the app yourself.

A few cases end without buttons:

- "This request expired or was already used. Start connecting again from your app." A request lasts 30 minutes and works once.
- "This connection request isn't valid", when the app isn't registered with Pumpkit or its return address doesn't match what it registered. Start again from the app.
- On an instance that sells plans, connecting an app needs current access through a subscription or free access: without it, **Allow** shows a link to subscribe. Tools that require current access check it on every call and return a subscription link when access ends. Same-account recovery through `connect_x` remains available without a paid subscription; it restores publishing authorization without changing account identity.

You don't need to have finished Onboarding to connect an app.

### Signing in from the consent page

If you're signed out when the app opens the consent page, Pumpkit sends you to **Continue with X** and back to the request in the same browser. Cancellation, missing confirmed email or a provider failure preserves the request for retry within its original 30-minute lifetime. A successful sign-in consumes the saved return once; the server still checks that the request is valid and unused. Starting again on another device cannot recover the first browser's saved request. X is the only sign-in method, and connecting an AI app never creates a Pumpkit session on its own.

## Stay connected and disconnect

An app stays connected without asking you to sign in again: it renews its access on its own while you use it. If it goes unused for 90 days, it asks you to sign in again.

Settings' Connect AI apps card lists your connected apps, each with whether it is verified, when it connected and when it was last used. Connecting the same app again keeps one row. **Disconnect** asks you to confirm, and the app stops working with Pumpkit at once: its next call fails and it asks you to connect again. Deleting your account disconnects every app.

## Positioning tools

Your positioning is a few sentences about who you are on X, what you post about, who you write for, what you post for and what you can point readers to. It is the same text as on the Persona page of the web app.

| Tool              | What it does                                                                                                      |
| ----------------- | ----------------------------------------------------------------------------------------------------------------- |
| `get_positioning` | Reads your positioning and when you last saved it. Both are empty until you save one.                             |
| `set_positioning` | Saves your positioning, in place of the one you had. It holds up to 4,000 characters, and a blank one is refused. |

`set_positioning` is limited to 20 calls a minute per User, and `get_positioning` to 60.

## No inspiration author tools

The server lists no tools for inspiration authors. Your positioning is your persona, and Pumpkit no longer writes in the style of other X accounts (ADR 0024). `list_inspiration_authors`, `add_inspiration_author` and `remove_inspiration_author` are gone from every Instance, and an app that calls one gets an unknown-tool error.

## Post tools

Ask your app to write a Post from an idea, then ask for changes in plain words. Each change makes a new Version and keeps the earlier ones.

| Tool              | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `start_post`      | Starts a Post from a Brief: plans it around your Positioning, then writes its first Version from that Plan. The Plan chooses a single post or a Thread: a Thread when the material needs more room than one post on your account holds, or when the Brief asks for one ("as a thread"). A Brief that holds several separate ideas still gets one Post covering all of them; New post in the web app can write one Post per idea instead. Without a Positioning it is refused with a link to the Persona page. Answers once the Brief is planned, with the Plan (the core idea, the takeaway, what the Post is built for, the action it aims for, its Format and, for a single post, its Length) and the Post being written; `get_post` shows the Version's Parts once it is written, each with its character count against your X account's limit: 25,000 with X Premium, 280 otherwise.                                                                                                                                                                                                                                                                                                                                                                                                  |
| `give_feedback`   | Gives Feedback on a Post's Text as it is, your edits in the web app and a restored Version included, such as "shorter", "make Part 3 punchier" or "like Version 2, with a different hook", and writes the next Version in the background, which then becomes the Text. The writing sees every Version in order and what you did to the Text before each Feedback, and keeps the sentences you wrote by hand unless the Feedback asks to change them. It keeps the Text's Format unless you pass `format: "post"` or `format: "thread"` to switch it: a post's first reply moves into the thread's last part, and a thread turned into a post gets the length your X account allows. A post written before plans existed takes no feedback. Only a Draft or a Failed Post takes Feedback: on a Scheduled Post it answers that you edit or unschedule it first, and on a Published one that you start a new Post. |
| `restore_version` | Makes an earlier Version of a Post, named by its number, the Post's Text again, without writing a new Version. Hand edits to the Text are replaced; every Version stays in the Post's History. Only a Draft or a Failed Post's Text changes.                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `list_posts`      | Lists your Posts of one status, or all of them, 20 at a time (up to 50), with each one's Brief, text, number of Versions and Scheduled post (its state, time, Community, why it failed and its link on X), plus how many Posts each status holds. Scheduled Posts come soonest first, Drafts and the full list by their latest Version, newest first, Published ones most recently published first, and Failed ones most recently due first.                                                                                                                                                                                                                                                       |
| `get_post`        | Reads one Post with its Text, whether you edited it since its Version, and all its Versions, each with its Feedback, text, character count, whether its last Part is a First reply, and Starting text (the Text its Feedback was given on, when that wasn't the Version before as written), plus each Part's Media with its id, kind and alt text, its writing state (being written, or couldn't be written), its status (Draft, Scheduled, Published or Failed, none until its first Version is written), the id of its Brief and its place among the Brief's Posts (`place_in_brief`: its position, how many Posts the Brief has, and the previous and next Post's ids), and its Scheduled post, with its own Media and whether it is posting (being published or due), so the app can compare Versions, schedule a Draft's Text, or see what went out.                                                                                                                                                        |
| `delete_post`     | Discards a Draft for good: the Post, every Version and its Media are deleted, and its Idea stays on its Brief as not written, so it can be written again. The generations it used stay used. A Scheduled, Published or Failed Post is refused, and so is one still being written or with no Version yet. Apps such as Claude Code ask before calling it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

`restore_version` and `delete_post` allow 10 calls a minute. `start_post` answers once the brief is planned, and Pumpkit writes the first Version in the background, which takes about a minute: `get_post` says `writing_state` "writing" until it is written, and "not_written" if Pumpkit couldn't write it, which the user can retry from the post's page in the web app. `give_feedback` answers the same way, with `writing_state` "writing": the Text stays as it was, and can't be edited, restored or given more feedback, until the new Version replaces it. Once `get_post` says `writing_state` null, a new Version means it was written; none means Pumpkit couldn't write it, the Text is unchanged, and `failed_feedback` holds the Feedback and its Format to give again. Scheduling the Post or posting it now is refused while its Feedback is written. `start_post` and `give_feedback` allow 20 calls a minute, and share the web app's limit of 30 attempts at a Version an hour, so attempts in either count toward it. Posts you start from an app show up on the web app's Posts page like any other.

On an Instance that sells Plans, each post you start and each round of feedback uses one generation of your allowance, wherever you write it, and a failed attempt none. Pumpkit's instructions tell the app so, and that `get_usage` says what is left, so it writes a new version only when you ask for one.

## Media tools

Media is your own content, like a hand edit: Pumpkit publishes it inside the X post exactly as you gave it, and its writing never reads it: not the image, its name or its alt text. When an image should shape the post, the app looks at it itself and writes what it shows into the Brief or the Feedback. Pumpkit's instructions tell the app so.

| Tool           | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `attach_media` | Downloads an image, a GIF or a video from a public https URL and attaches it to a Part of a Post, `part` 1 unless you name another, last after the Media it has, with optional alt text of up to 1,000 characters for an image or GIF: a video with alt text is refused. On a Draft or a Failed Post it changes the Text; on a Scheduled Post it changes the Scheduled post's own copy. It refuses a Published Post and a Part already live on X. Without a URL, it answers with a one-time upload link for that Part and the `curl` command that sends local media to it, as the next section shows. |
| `remove_media` | Takes one Media, by the id `get_post` lists, off a Post, by the same rule.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

`attach_media` takes what the web app's upload takes: a JPEG, PNG or WEBP image up to 5 MB, a GIF up to 15 MB, or an MP4 or MOV video up to 512 MB. A Part takes up to 4 images, or 1 GIF, or 1 video, as X does. Pumpkit checks the type from its own bytes. It downloads only from public hosts on port 443, following up to 3 redirects, stops a download that passes its kind's limit, and gives up after 60 seconds for an image, 2 minutes for a GIF and 4 minutes for a video, so the app gets its answer before the web server's 5 minutes run out. A large video on a slow host is better sent through an upload link, as the next section shows. It refuses, with the web app's words, an image, GIF or video too large, a type Pumpkit doesn't take, an image it can't read, a URL it can't download and a Part that holds all X takes. Pumpkit never reads a video's length, so a video over 20 minutes on an X account without Premium fails when X refuses it at publish time; the web app warns of it, an app doesn't. An X connection made before Pumpkit could publish Media is asked to reconnect first, with the link to the Settings page. Neither tool uses a generation, and each allows 10 calls a minute.

Alt text is stored with the image or GIF (a video takes none), `get_post` lists it, and Pumpkit sets it on X when the image goes out, for people using screen readers. You can also change or clear it on the Post's page in the web app.

### Attaching local media

An app that can run commands, such as Claude Code, attaches an image, a GIF or a video from your disk without a public URL. Called without `url`, `attach_media` checks the Post and Part as it would for a URL and answers with:

- `upload_url`: a link under `/api/v1/media-uploads/`, made for that Part of that Post. It works once, for 15 minutes.
- `upload_expires_at`: when the link stops working.
- `curl_command`: the command that sends the file, with `FILE_PATH` in place of the file's path.
- `post_url`: the Post's page, for an app that can't run commands, where you attach the media yourself.

The app replaces `FILE_PATH` with the file's path, quoted as its shell needs, and runs the command:

```sh
curl -F 'file=@-' 'https://pumpkit.example.com/api/v1/media-uploads/Xq3…' < ~/"Desktop/Q3 chart.png"
```

The shell opens the file and passes it to `curl` on its standard input, so `~`, `$HOME` and any character a quoted path may hold work in the path. Since standard input is the file itself, `curl` streams it, so a 512 MB video isn't read into memory first; piping the file in (`cat video.mp4 | curl …`) would be.

The link takes the file as the multipart field `file`, with no other credentials, and attaches it where `attach_media` named, with the alt text given to `attach_media`: to the Post's Text, or to its waiting Scheduled post's own copy. It answers with the attached Media as `get_post` lists it. Uploads through links follow the web app's rules: the same checks on the file, the web upload's limit of 60 a minute, and a refusal when your subscription has ended or X needs reconnecting. An upload spends the link once your account and the Part pass these checks, before the file arrives, even when the file is then refused. A second use, or a use after 15 minutes, is refused with a message saying to call `attach_media` again. Disconnecting the app in Settings stops the links it made and hasn't used. The link names no Post or Part: Pumpkit keeps them with a hash of the link's token, so a changed link is unknown.

## Scheduled post and link tools

Every Scheduled post is copied from its Post's Text, the text set from each new Version, and a Post goes out once, so it has at most one Scheduled post. That Scheduled post gives the Post its status: Draft without one, then Scheduled, Published or Failed.

| Tool                    | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schedule_post`         | Schedules the Text of a Post you name by its id, for a time you give with its UTC offset. A Thread keeps every Part in order, and a First reply goes out as a reply to its post. A Text that still holds the `[link]` placeholder is refused. It goes to your profile, or to a Community you name by its URL or ID, and can also be shared with your followers. A Post goes out once: if it already has a Scheduled post, in any state, the tool refuses and tells you to edit that one, or unschedule it first.                                                                                                                                                                                                                                                                                                                             |
| `post_now`              | Publishes the Text of a Post you name by its id on X right away. In a Thread, each Part replies to the one before, and a First reply replies to its post. A Text that still holds the `[link]` placeholder is refused. Like `schedule_post`, it refuses a Post that already has a Scheduled post. It goes to your profile or a Community, as with `schedule_post`. Pumpkit's instructions tell the app to show you the exact text of every Part and ask before calling it. It answers Published with the link to the post on X, Failed with the reason, or, when X hasn't taken the post yet, that Pumpkit keeps trying for 15 minutes. A Post with a GIF or a video answers that it's being published: Pumpkit uploads the media and waits while X processes it, up to an hour for a video, and `get_post` shows when it's out. |
| `edit_scheduled_post`   | Changes the text, time or Community of a waiting or Failed Scheduled post, or moves it back to your profile. The text can be every Part typed out, edited from what the Scheduled post holds, or, with `copy_text`, its Post's Text as it is now, Media included, such as after Feedback on a Failed Post. A new time gives a Failed one another try. In a Thread that failed partway, the live Parts are locked; the others can be edited, added, removed and reordered, the Text's Parts in the live ones' places are skipped, and a new time publishes only the rest, as replies to the last live Part.                                                                                                                   |
| `delete_scheduled_post` | Deletes a waiting or Failed Scheduled post, which unschedules it: its Post is a Draft again, so it takes Feedback and can be scheduled anew. Apps such as Claude Code ask before calling it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `list_past_communities` | Lists the Communities you posted to before from your connected X account.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `connect_x`             | Answers with the link to the Settings page, where you restore publishing authorization for the same X account you signed in with. It cannot switch or disconnect that identity.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `get_usage`             | Says what you have left of your allowance this period: generations, X posts and, of those, X posts with a link, each with its limit, how many you used and how many are left, and when the period resets (or your trial ends), plus what each of your top-ups has left and until when. On an Instance that sells no Plans it says there is no allowance.                                                                                                                                                                                                                                                                                                                                                                     |
| `manage_subscription`   | Answers with the link to the Settings page, where you manage your subscription. Without current access, it answers with the link to the page where you subscribe. On an instance that sells no plans, it says so instead.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

Scheduling and Post now follow the web app's rules: it needs an X connection that X still accepts, the text must fit your X account's limit, a scheduled time must be at least a minute away, a Community must be one X knows, and your X posts are counted, one per Part, and one link post per Part containing a link, including those you scheduled in the web app. At your allowance's limit the refusal says when it resets and links to the Settings page. The X connection refusals link to the Settings page, and every Scheduled post answer to its Post's page in the web app. `schedule_post`, `post_now`, `edit_scheduled_post` and `delete_scheduled_post` allow 10 calls a minute, and the others 60.
