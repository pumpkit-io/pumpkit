"""
The `Classifier` port: asks Jev, TypeSafe's hosted classifier, named questions about a `state`
(ADR 0013). It lives in `core` because no single area owns Jev.

Any provider failure, including an answer that doesn't fit the questions, is a `ClassifierError`;
a missing key is a `ClassifierNotConfiguredError`. Callers catch both and take their cautious path.

Mediators reach Jev only through `get_classifier`; tests override it with `FakeClassifier`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol, Union

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from pumpkit.core.config import settings
from pumpkit.core.errors import AppError, NotConfiguredError

TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
_TIMEOUT_SECONDS = 5.0
# Versions are written inside the request, so one retry bounds the wait at about 10 seconds.
_ATTEMPTS = 2
_RETRIED_STATUSES = frozenset({429, 529})


class ClassifierError(AppError):
    """Asking Jev failed: network, HTTP, or an answer that can't be read."""

    status_code = 502
    public_detail = "The classifier can't be reached right now. Please try again later."
    reported = True


class ClassifierNotConfiguredError(NotConfiguredError, ClassifierError):
    """Raised when Jev is asked without TYPESAFE_API_KEY configured."""

    def __init__(self) -> None:
        super().__init__("TYPESAFE_API_KEY is not set. Add it to .env to ask Jev questions.")


class ChoiceQuestion(BaseModel):
    """Picks one label of `criteria`, which maps each label to when it applies."""

    model_config = ConfigDict(frozen=True)

    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str]


class ChoiceAnswer(BaseModel):
    """The top label, Jev's confidence in it, and every label's probability."""

    model_config = ConfigDict(frozen=True)

    type: Literal["choice"] = "choice"
    choice: str
    confidence: float
    probabilities: dict[str, float]


# Jev's `noul` and `score` types join these as a union discriminated on `type`.
Question = ChoiceQuestion
Answer = ChoiceAnswer


class ClassifierUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int


class Classification(BaseModel):
    """Jev's answers keyed by question name, the model version that gave them, and the usage."""

    model_config = ConfigDict(frozen=True)

    answers: dict[str, Answer]
    model: str
    usage: ClassifierUsage


class Classifier(Protocol):
    async def classify(
        self, *, state: Any, questions: Mapping[str, Question], model: str
    ) -> Classification:
        """
        One answer per question, under the question's name, about `state`: any JSON-serializable
        value. `model` is a Jev name or alias; the result names the version that answered.
        """
        ...


class JevClassifier:
    """Asks Jev over TypeSafe's HTTP API. The key is checked on use, so the app boots without it."""

    async def classify(
        self, *, state: Any, questions: Mapping[str, Question], model: str
    ) -> Classification:
        if not settings.TYPESAFE_API_KEY:
            raise ClassifierNotConfiguredError()
        body = {
            "model": model,
            "state": state,
            "questions": {name: question.model_dump() for name, question in questions.items()},
        }
        response = await _post_with_one_retry(body, api_key=settings.TYPESAFE_API_KEY)
        return parse_classification(response, questions)


def parse_classification(
    response: httpx.Response, questions: Mapping[str, Question]
) -> Classification:
    """The answers out of one Jev response, or a `ClassifierError` when they don't fit."""
    # Only the status goes into the error: the body may echo the request.
    if response.status_code != 200:
        raise ClassifierError(f"Jev returned HTTP {response.status_code}")
    try:
        classification = Classification.model_validate_json(response.content)
    except ValidationError as error:
        raise ClassifierError(
            f"Jev returned an unreadable answer: {error.error_count()} errors"
        ) from error
    for name, question in questions.items():
        answer = classification.answers.get(name)
        if answer is None or answer.type != question.type:
            raise ClassifierError(f"Jev gave no {question.type} answer to {name!r}")
        if answer.choice not in question.criteria:
            raise ClassifierError(f"Jev answered {name!r} with a label it wasn't offered")
    return classification


async def _post_with_one_retry(body: dict, *, api_key: str) -> httpx.Response:
    """Jev's response, retrying once on a timeout, a lost connection, a 429 or a 529."""
    failure = ""
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for _ in range(_ATTEMPTS):
            try:
                response = await client.post(
                    TYPESAFE_SYSTEMONE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                failure = f"unreachable: {type(error).__name__}"
                continue
            except httpx.HTTPError as error:
                raise ClassifierError(f"Jev request failed: {type(error).__name__}") from error
            if response.status_code not in _RETRIED_STATUSES:
                return response
            failure = f"returned HTTP {response.status_code}"
    raise ClassifierError(f"Jev {failure} on each of {_ATTEMPTS} attempts")


@dataclass(frozen=True)
class ClassifierCall:
    state: Any
    questions: dict[str, Question]
    model: str


@dataclass
class FakeClassifier:
    """
    A scripted Jev: each call takes the next of `replies`, the answers by question name or an
    exception to raise, and is recorded in `calls`. With no reply left it raises `ClassifierError`.
    """

    replies: list[Union[dict[str, Answer], Exception]] = field(default_factory=list)
    calls: list[ClassifierCall] = field(default_factory=list)

    async def classify(
        self, *, state: Any, questions: Mapping[str, Question], model: str
    ) -> Classification:
        self.calls.append(ClassifierCall(state=state, questions=dict(questions), model=model))
        if not self.replies:
            raise ClassifierError("Fake classifier has no reply left")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Classification(
            answers=reply, model=model, usage=ClassifierUsage(input_tokens=100, output_tokens=5)
        )


@lru_cache
def get_classifier() -> Classifier:
    """FastAPI dependency for the `Classifier` port."""
    return JevClassifier()
