# A Post has one Text, and its Versions are an append-only History

A Post has one Text, the text on screen, which the User edits in place in the web app. Feedback rewrites that Text as it is when sent, the User's edits included, and the new Version always goes at the end of the Post's History. Versions are never removed or branched. When the Text a Feedback was given on differs from the Version before it, the new Version keeps it as its Starting text. The writing call then sees the whole History in order, with each Version numbered and each Starting text in its place ("You went back to Version 1 and changed it to: …"), so Feedback such as "like Version 2, with a different hook" works from the MCP tools, which have no screen to go back on. The humanizer sees every Feedback so far and the sentences the User wrote by hand, so it keeps them.

Undo and redo are one straight line per browser tab through every change to the Text, the User's edit bursts and Pumpkit's rewrites alike, and typing after an undo drops the redo steps, as in a document editor. Nothing is lost that cost a write: every Version stays in History, and restoring one is a single undoable step. This amends ADR 0015: a Scheduled post is copied from its Post's Text, not from a Version.

## Considered Options

- **Feedback only on the latest Version, with a pager to flip between Versions.** This was the previous design. It can't take Feedback on edited text or on an older Version, and edits made on one page of the pager had no clear place in the history.
- **An undo tree that keeps every branch.** No redo step would ever be lost, but people can't find their way around a tree, and History already keeps everything that cost a write.
- **Branching Versions, each recording its parent.** The writing call would need a rule for which branch to show the model, and the MCP tools would need a way to name a branch. A straight line with Starting texts tells the model the same facts.
- **Sending the model only the Starting text and the new Feedback.** This is simpler, but "like two rounds ago" would stop working and the humanizer would forget earlier asks.
