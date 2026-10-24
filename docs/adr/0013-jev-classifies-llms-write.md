# Jev classifies; LLMs write

When Pumpkit needs a labelled answer about text (which of a fixed set of labels fits a conversation, a Brief or a Final), the question goes to Jev, TypeSafe's hosted classifier, and not to the LLM that writes the Post. LLMs only write. We chose Jev for three reasons. It answers a labelled question for $0.042 per million input tokens, with output free. TypeSafe cites about a tenth of a second against several seconds for an LLM, which matters because Versions are written inside the request. And it returns a probability for every label, which we can store to tune the question, where an LLM returns one unscored answer.

The port is built and tested, and nothing asks it a question yet. Its first caller asked, before a Feedback Version, whether the next Version needed a new Hook. We removed that check when the Hook moved into the draft and revision calls: the call that writes the opening now decides whether to change it, from the Feedback, and needs no separate question.

## Rules

- The classifier port lives in `core/classifier.py`, not in an area. Several areas may ask Jev questions, so it is shared plumbing. This extends ADR 0008, where each area owns its own provider's adapter: a provider no single area owns lives in `core`.
- The adapter calls `POST /v1/systemone` with `httpx`, with our own short timeout and one retry, not TypeSafe's SDK.
- The model version is pinned in settings, so a new Jev release cannot change answers without a config change.
- Under ADR 0011, Jev is off until `TYPESAFE_API_KEY` is set. When it is off, errors or times out, the caller gets no answer and takes the cautious path.
- While no feature asks Jev, its settings stay out of the self-hosting docs and `.env.example`, since setting them would change nothing. The first caller adds them back.

## Considered Options

- **One more structured call to the existing LLM.** No new provider or setting, but it adds seconds and LLM pricing to every call site, and gives no calibrated probabilities.
- **TypeSafe's Python SDK.** Typed answers and built-in retries, but another dependency from a young vendor for one endpoint, with retries and timeouts we don't control.
