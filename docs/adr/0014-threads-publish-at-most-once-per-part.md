# A Thread publishes at most once per Part and resumes after the last live Part

A Scheduled post that is a Thread goes out as a chain: Part 1, then each later Part as a reply to the one before. ADR 0007's rule applies to every Part: Pumpkit calls X again for a Part only when X clearly did not publish it (a 429, or a refused connection), and that retry continues from the Part that failed within the usual window. When a Part is refused or its outcome is unknown, the Scheduled post becomes Failed. Pumpkit keeps the X posts of the Parts it knows are live and locks them. The reason names the first Part that failed, and on an unknown outcome tells the User to check their profile. Rescheduling publishes only the Parts not known to be live, as replies to the last live one. If the unknown Part did go through, the User deletes the duplicate on X. Republishing the whole Thread would duplicate every live Part, and so breaks ADR 0007's rule that a duplicate is worse than a missed post.

## Considered Options

- **Republish the whole Thread on reschedule.** Simple, but it duplicates every Part already live.
- **Roll back by deleting the live Parts.** Each delete is another X call that can fail or time out, so a rollback can leave the Thread half deleted.
