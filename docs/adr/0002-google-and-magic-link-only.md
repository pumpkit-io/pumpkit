# Sign-in only via Google OAuth and magic link

ADR 0023 supersedes the sign-in-method decision below: X is the only usable sign-in method; the Google and Magic link implementations remain disabled. The password decision remains unchanged.

Pumpkit users sign in with Google OAuth or a magic link, and nothing else. The app was imported with a full password ("first-party") auth stack: signup, email confirmation and password reset. None of it was routed in the frontend, the backend linked to pages that didn't exist, it had no tests, and it roughly doubled the auth code. We deleted it before any deployment held real users, rather than finishing the wiring. Passwordless sign-in removes password storage, reset flows and credential-stuffing exposure. Bringing passwords back would mean rebuilding hashing, verification and reset flows, their emails and their tables, so don't re-add them without a new decision.
