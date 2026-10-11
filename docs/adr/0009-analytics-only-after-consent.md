# Product analytics run only after Analytics consent

Pumpkit loads no product analytics until a visitor gives Analytics consent: no PostHog pageviews, events, session recordings, exception capture or identification, and no PostHog cookies or local storage. EU ePrivacy rules, which Italy's data protection authority enforces, require prior opt-in for non-essential cookies and recording, and the Operator is an Italian company. Visitors who refuse or ignore the banner are invisible to analytics, so funnels undercount, and that is expected. Session and OAuth cookies need no consent because sign-in cannot work without them. For the same reason, the fonts are served from pumpkit.io rather than Google Fonts, so a page load sends no visitor IP to Google.

## Considered Options

- **Cookieless PostHog with no banner.** Kept every visitor in the counts, but meant giving up session recording and identified Users, and sending email and name to PostHog would still need a legal basis.
- **No banner and no changes.** Not compliant.
