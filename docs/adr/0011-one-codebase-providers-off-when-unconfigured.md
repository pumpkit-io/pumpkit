# One codebase; each outside provider is off until it is configured

The hosted Instance and every Self-hoster's Instance run the same code from this repo. Nothing selects an edition: each outside provider turns on only when its settings are present, and the app runs with it left out. With no Stripe keys an Instance sells no Plans and every User may use all of Pumpkit. With no Operator details it shows no legal pages, company footer or Terms acceptance. With no PostHog key it loads no analytics and shows no consent banner. With no Google credentials it offers only the Magic link. With no SMTP settings it writes each Magic link to the backend log, in every environment, so a Self-hoster can sign in without an email provider. We chose this so contributors work on the code the Operator ships, and a Self-hoster can run Pumpkit with only the providers the writing itself needs. This narrows ADR 0010: Users accept the Terms at checkout only on an Instance that sells Plans and has Operator details; on any other Instance there are no Terms to accept.

## Considered Options

- **An `EDITION=hosted|self-hosted` switch.** One flag is easy to read, but it ties unrelated providers together. A Self-hoster who wants Google sign-in without Stripe would need a third edition.
- **Hosted-only code in a private repo or overlay.** Keeps Operator details out of the open code, but splits the codebase and hides billing from contributors. The AGPL already stops closed hosted forks (ADR 0001), so there is nothing to protect by hiding it.
