import json

import httpx
import pytest
import respx

from pumpkit.core.classifier import (
    TYPESAFE_SYSTEMONE_URL,
    ChoiceAnswer,
    ChoiceQuestion,
    Classification,
    ClassifierError,
    ClassifierNotConfiguredError,
    ClassifierUsage,
    JevClassifier,
)
from pumpkit.core.config import settings


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "typesafe-test-key")


TONE = ChoiceQuestion(
    instructions="What is the tone of this message?",
    criteria={
        "angry": "An upset or hostile message",
        "calm": "A neutral or polite message",
        "excited": "An enthusiastic or eager message",
    },
)

STATE = {"message": "I was charged twice. Please refund the extra charge."}


def _tone_answer() -> dict:
    """Jev's documented answer to the `tone` question."""
    return {
        "model": "jev-1.13.0",
        "answers": {
            "tone": {
                "type": "choice",
                "choice": "calm",
                "confidence": 0.7,
                "probabilities": {"angry": 0.15, "calm": 0.8, "excited": 0.05},
            }
        },
        "usage": {"input_tokens": 120, "output_tokens": 12},
    }


async def _ask_tone() -> Classification:
    return await JevClassifier().classify(state=STATE, questions={"tone": TONE}, model="jev-latest")


@respx.mock
async def test_asks_jev_the_questions_about_the_state_with_the_bearer_key():
    route = respx.post(TYPESAFE_SYSTEMONE_URL).mock(
        return_value=httpx.Response(200, json=_tone_answer())
    )

    await _ask_tone()

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer typesafe-test-key"
    assert json.loads(request.content) == {
        "model": "jev-latest",
        "state": STATE,
        "questions": {
            "tone": {
                "type": "choice",
                "instructions": "What is the tone of this message?",
                "criteria": {
                    "angry": "An upset or hostile message",
                    "calm": "A neutral or polite message",
                    "excited": "An enthusiastic or eager message",
                },
            }
        },
    }


@respx.mock
async def test_reads_a_choice_answer_with_every_label_s_probability_and_the_resolved_model():
    respx.post(TYPESAFE_SYSTEMONE_URL).mock(return_value=httpx.Response(200, json=_tone_answer()))

    classification = await _ask_tone()

    assert classification == Classification(
        answers={
            "tone": ChoiceAnswer(
                choice="calm",
                confidence=0.7,
                probabilities={"angry": 0.15, "calm": 0.8, "excited": 0.05},
            )
        },
        model="jev-1.13.0",
        usage=ClassifierUsage(input_tokens=120, output_tokens=12),
    )


_TRANSIENT_FAILURES = [
    httpx.ReadTimeout("timed out"),
    httpx.ConnectError("refused"),
    httpx.Response(429, json={"detail": "Too many requests"}),
    httpx.Response(529, json={"detail": "Overloaded"}),
]


@pytest.mark.parametrize("failure", _TRANSIENT_FAILURES)
@respx.mock
async def test_retries_once_after_a_transient_failure(failure):
    route = respx.post(TYPESAFE_SYSTEMONE_URL).mock(
        side_effect=[failure, httpx.Response(200, json=_tone_answer())]
    )

    classification = await _ask_tone()

    assert classification.answers["tone"].choice == "calm"
    assert route.call_count == 2


@pytest.mark.parametrize("failure", _TRANSIENT_FAILURES)
@respx.mock
async def test_a_second_transient_failure_is_a_classifier_error(failure):
    route = respx.post(TYPESAFE_SYSTEMONE_URL).mock(side_effect=[failure, failure])

    with pytest.raises(ClassifierError) as raised:
        await _ask_tone()

    assert not isinstance(raised.value, ClassifierNotConfiguredError)
    assert route.call_count == 2


def _answer_with(**changes) -> dict:
    body = _tone_answer()
    body["answers"]["tone"].update(changes)
    return body


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"detail": "Invalid API key"}),
        httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "bad", "type": "x"}]}),
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"model": "jev-1.13.0", "answers": {}, "usage": {}}),
        httpx.Response(200, json={**_tone_answer(), "answers": {"mood": {}}}),
        httpx.Response(200, json=_answer_with(type="noul", noul=0.9)),
        httpx.Response(200, json=_answer_with(choice="bored")),
        httpx.Response(200, json=_answer_with(confidence="high")),
    ],
)
@respx.mock
async def test_an_unusable_response_is_a_classifier_error_without_a_retry(response):
    route = respx.post(TYPESAFE_SYSTEMONE_URL).mock(return_value=response)

    with pytest.raises(ClassifierError):
        await _ask_tone()

    assert route.call_count == 1


@respx.mock
async def test_an_error_names_the_status_but_never_the_key_or_the_body():
    respx.post(TYPESAFE_SYSTEMONE_URL).mock(
        return_value=httpx.Response(401, json={"detail": "key typesafe-test-key is invalid"})
    )

    with pytest.raises(ClassifierError) as raised:
        await _ask_tone()

    assert "401" in str(raised.value)
    assert "typesafe-test-key" not in str(raised.value)


@respx.mock
async def test_without_the_key_it_fails_on_use_without_calling_jev(monkeypatch):
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", None)
    route = respx.post(TYPESAFE_SYSTEMONE_URL)

    with pytest.raises(ClassifierNotConfiguredError, match="TYPESAFE_API_KEY"):
        await _ask_tone()

    assert not route.called
