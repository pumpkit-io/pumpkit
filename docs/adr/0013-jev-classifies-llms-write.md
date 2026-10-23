# Jev classifies; LLMs write

Writing a Feedback Version now asks a labelled question first, before the hook call and the revision call: given the conversation so far and the latest Feedback, does the next Version need a new Hook, should the opening stay, or did the User write it? Questions like this go to Jev, TypeSafe's hosted classifier, and not to the LLM that writes the Post. LLMs only write. We chose Jev for three reasons. It answers a labelled question for $0.042 per million input tokens, with output free. TypeSafe cites about a tenth of a second against several seconds for an LLM, which matters because Versions are written inside the request. And it returns a probability for every label, which we store to tune the question, where an LLM returns one unscored answer.

## Rules

- The classifier port lives in `core/classifier.py`, not in an area. Several areas may ask Jev questions, so it is shared plumbing. This extends ADR 0008, where each area owns its own provider's adapter: a provider no single area owns lives in `core`.
- The adapter calls `POST /v1/systemone` with `httpx`, with our own short timeout and one retry, not TypeSafe's SDK.
- The model version is pinned in settings, so a new Jev release cannot change answers without a config change.
- Under ADR 0011, Jev is off until `TYPESAFE_API_KEY` is set. When it is off, errors or times out, the caller gets no answer and takes the cautious path. For the Hook, that means the hook call is skipped on Feedback Versions, so it can never overwrite an opening the User asked for. The first Version always gets a Hook and never asks Jev.

## Considered Options

- **One more structured call to the existing LLM.** No new provider or setting, but it adds seconds and LLM pricing to every Feedback Version, and gives no calibrated probabilities.
- **TypeSafe's Python SDK.** Typed answers and built-in retries, but another dependency from a young vendor for one endpoint, with retries and timeouts we don't control.
