"""A capturing stand-in for the OpenAI SDK, shared by the agent tests.

The suite must never make a network call, but it still has to prove that the *right* request
goes out — the model id, the reasoning effort, the cached instruction prefix and the document
blocks are all things that can silently rot. So the fake records every keyword argument and
returns whatever text the test asked for.
"""
from __future__ import annotations

from types import SimpleNamespace


def make_response(text: str, *, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        output_text=text,
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        usage=SimpleNamespace(
            input_tokens=4200,
            output_tokens=1800,
            input_tokens_details=SimpleNamespace(cached_tokens=3100),
            output_tokens_details=SimpleNamespace(reasoning_tokens=900),
        ),
    )


class FakeResponses:
    def __init__(self, captured: dict, text: str, status: str = "completed"):
        self._captured = captured
        self._text = text
        self._status = status

    def create(self, **kwargs):
        self._captured.clear()
        self._captured.update(kwargs)
        return make_response(self._text, status=self._status)


class FakeClient:
    """Mimics the surface `openai_client` actually touches."""

    def __init__(self, captured: dict, text: str, status: str = "completed"):
        self.responses = FakeResponses(captured, text, status)
