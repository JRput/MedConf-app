# test_llm_client.py
"""Tests for llm_client.py's model-fallback chain. No network calls —
uses a fake OpenAI-shaped client and real openai SDK exception classes.

Written as plain `test_*()` functions (no pytest fixtures/decorators) so
this runs identically under `pytest test_llm_client.py` and under plain
`python test_llm_client.py` — the venv here has no pytest installed, and
the __main__ block below drives the same functions directly.
"""

import importlib
import os

import httpx
from openai import APIStatusError, NotFoundError, RateLimitError, APITimeoutError


def _api_status_error(status_code: int, message: str = "boom") -> APIStatusError:
    """Build a real APIStatusError the way the openai SDK would raise one."""
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json={"error": {"message": message}})
    return APIStatusError(message, response=response, body={"error": {"message": message}})


def _not_found_error(message: str = "not found") -> NotFoundError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(404, request=request, json={"error": {"message": message}})
    return NotFoundError(message, response=response, body={"error": {"message": message}})


def _rate_limit_error(message: str = "rate limited") -> RateLimitError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(429, request=request, json={"error": {"message": message}})
    return RateLimitError(message, response=response, body={"error": {"message": message}})


class FakeResponse:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": content})()})()]


class FakeCompletions:
    """Queue-driven fake: .create() looks up the scripted outcome for the
    requested model (an exception to raise, or content string to return)."""

    def __init__(self):
        self.calls = []  # (model, kwargs) for every attempted call
        self.script = {}  # model -> outcome

    def create(self, *, model, **kwargs):
        self.calls.append((model, kwargs))
        outcome = self.script.get(model, "default content")
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions()


class _EnvSandbox:
    """Sets env vars, reloads config + llm_client so the chain reflects
    them, and restores the previous environment + module state on exit."""

    def __init__(self, **env):
        self._env = env
        self._saved = {}

    def __enter__(self):
        for k, v in self._env.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import config
        import llm_client
        importlib.reload(config)
        self.llm_client = importlib.reload(llm_client)
        return self.llm_client

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import config
        import llm_client
        importlib.reload(config)
        importlib.reload(llm_client)
        return False


def _default_sandbox():
    """A clean 3-model text chain / 2-model vision chain, independent of
    whatever the real .env has configured."""
    return _EnvSandbox(
        KIMI_MODEL_CHAIN="model-a,model-b,model-c",
        KIMI_MODEL=None,
        KIMI_VISION_MODEL_CHAIN="vision-a,vision-b",
        KIMI_VISION_MODEL=None,
    )


def test_advance_on_410():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        client.chat.completions.script["model-a"] = _api_status_error(410, "gone")
        client.chat.completions.script["model-b"] = "ok from b"

        resp = llm_client.chat_completion(client, chain="text", messages=[])
        assert resp.choices[0].message.content == "ok from b"
        assert llm_client.current_model("text") == "model-b"
        assert [c[0] for c in client.chat.completions.calls] == ["model-a", "model-b"]


def test_advance_on_404():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        client.chat.completions.script["model-a"] = _not_found_error()
        client.chat.completions.script["model-b"] = "ok from b"

        resp = llm_client.chat_completion(client, chain="text", messages=[])
        assert resp.choices[0].message.content == "ok from b"
        assert llm_client.current_model("text") == "model-b"


def test_no_advance_on_429():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        client.chat.completions.script["model-a"] = _rate_limit_error()

        try:
            llm_client.chat_completion(client, chain="text", messages=[])
            raise AssertionError("expected RateLimitError to propagate")
        except RateLimitError:
            pass
        assert llm_client.current_model("text") == "model-a"
        assert len(client.chat.completions.calls) == 1


def test_no_advance_on_timeout():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        client.chat.completions.script["model-a"] = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))

        try:
            llm_client.chat_completion(client, chain="text", messages=[])
            raise AssertionError("expected APITimeoutError to propagate")
        except APITimeoutError:
            pass
        assert llm_client.current_model("text") == "model-a"


def test_stickiness_across_calls():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        client.chat.completions.script["model-a"] = _api_status_error(410, "gone")
        client.chat.completions.script["model-b"] = "first"

        llm_client.chat_completion(client, chain="text", messages=[])
        assert llm_client.current_model("text") == "model-b"

        # second call: model-a must NOT be retried, goes straight to model-b
        client.chat.completions.script["model-b"] = "second"
        resp = llm_client.chat_completion(client, chain="text", messages=[])
        assert resp.choices[0].message.content == "second"
        assert [c[0] for c in client.chat.completions.calls] == ["model-a", "model-b", "model-b"]


def test_exhaustion_raises():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        for m in ("model-a", "model-b", "model-c"):
            client.chat.completions.script[m] = _api_status_error(410, "gone")

        try:
            llm_client.chat_completion(client, chain="text", messages=[])
            raise AssertionError("expected AllModelsDeadError")
        except llm_client.AllModelsDeadError as e:
            assert e.tried == ["model-a", "model-b", "model-c"]


def test_kimi_model_env_goes_first_and_dedupes():
    with _EnvSandbox(KIMI_MODEL_CHAIN="model-a,model-b,model-c", KIMI_MODEL="model-b",
                      KIMI_VISION_MODEL_CHAIN=None, KIMI_VISION_MODEL=None) as llm_client:
        import config
        assert config.KIMI_MODEL_CHAIN == ["model-b", "model-a", "model-c"]
        assert config.KIMI_MODEL == "model-b"
        assert llm_client.current_model("text") == "model-b"


def test_kimi_model_env_prepended_when_not_in_chain():
    with _EnvSandbox(KIMI_MODEL_CHAIN="model-a,model-b", KIMI_MODEL="override-model",
                      KIMI_VISION_MODEL_CHAIN=None, KIMI_VISION_MODEL=None):
        import config
        assert config.KIMI_MODEL_CHAIN == ["override-model", "model-a", "model-b"]


def test_vision_chain_independent_of_text_chain():
    with _default_sandbox() as llm_client:
        client = FakeClient()
        client.chat.completions.script["vision-a"] = _api_status_error(410, "gone")
        client.chat.completions.script["vision-b"] = "vision ok"

        resp = llm_client.chat_completion(client, chain="vision", messages=[])
        assert resp.choices[0].message.content == "vision ok"
        assert llm_client.current_model("vision") == "vision-b"
        # text chain untouched
        assert llm_client.current_model("text") == "model-a"


ALL_TESTS = [
    test_advance_on_410,
    test_advance_on_404,
    test_no_advance_on_429,
    test_no_advance_on_timeout,
    test_stickiness_across_calls,
    test_exhaustion_raises,
    test_kimi_model_env_goes_first_and_dedupes,
    test_kimi_model_env_prepended_when_not_in_chain,
    test_vision_chain_independent_of_text_chain,
]


if __name__ == "__main__":
    import sys
    import traceback

    passed = failed = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            print(f"PASS {test_fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {test_fn.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
