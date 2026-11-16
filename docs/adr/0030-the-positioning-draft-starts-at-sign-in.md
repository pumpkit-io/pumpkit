---
status: accepted
---

# The Positioning draft starts at sign-in, and a User gets one

ADR 0024 ran the Positioning draft when Onboarding's Persona step first opened, so the Operator paid twitterapi.io and the model only for a User past the Paywall. The User then waited on "Reading your X profile…" at the step. Nearly every User who signs in goes on past the Paywall, so the draft now starts at sign-in and is usually ready when the User reaches the step. The Operator accepts paying for the drafts of Users who sign in and never subscribe.

This amends ADR 0024's Positioning section. Its other decisions continue to apply: what the draft reads, what it may say, its model setting, and its answer when X or the model fails.

- A sign-in starts a draft when the User has no Positioning, no kept draft and no draft running. It runs in the background (ADR 0026), so signing in doesn't wait for it. An Instance without `TWITTERAPI_IO_API_KEY` or `LLM_API_KEY` starts none.
- The draft is kept apart from the Positioning, unsaved. Saving it into the Positioning would make Onboarding's Persona step count as done before the User had seen it (ADR 0018). The step fills its text with the kept draft, and Continue saves it as the Positioning. A User who has a Positioning has no kept draft.
- At a step that opens while the draft runs, the text stays locked until it lands. When the sign-in draft failed or never ran, the step starts one draft itself, as before. When that fails too, the text opens empty with the reason in words.
- There is no redraft. The Persona step and the Persona page no longer offer one, so a User gets one draft. The limit of 5 drafts in 24 hours stays as the cost guard on draft requests, and no User sees it.
- The draft still asks the model for three to five sentences, while the Persona step and page tell the User that two or three are enough. The draft gives the User material to cut, and the advice says how short a Positioning can be.
