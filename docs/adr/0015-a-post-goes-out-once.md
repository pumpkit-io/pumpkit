# A Post goes out once, and every Scheduled post comes from one

Every Scheduled post is copied from a Version of a Post, and a Post has at most one Scheduled post. The web app's redesign files everything under Posts, sorted by status: Draft, Scheduled, Published or Failed. A Post takes its status from its one Scheduled post, so each Post sits in exactly one tab and its page shows one scheduled or published panel. A Scheduled post with no Post would have no place in that view. The User can still edit a Scheduled post's text after scheduling it, and to post the same text in a second place they start a new Post. The rule holds for the MCP tools too: `schedule_post` and `post_now` take a Version, not typed Parts. ADR 0016 amends this: a Scheduled post is copied from its Post's Text, so they take the Post.

## Considered Options

- **Keep typed Scheduled posts.** The old Scheduled page had a composer for them, but in the redesign they have no Post to appear under, and every Scheduled post the User wants can start as a Brief.
- **Several Scheduled posts per Post.** This would let a User send one Post to their profile and to a Community, but then the Post's status, its breadcrumb and its panel would need a rule for which Scheduled post they follow.
