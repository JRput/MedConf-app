# llm_client.py
"""Model-fallback wrapper around the OpenAI-compatible client.

NVIDIA's free-tier API retires models without warning (410 Gone once dead,
sometimes 404 while the change propagates — see config.py's 2026-08-26
note). This module walks a chain of models per call site and advances past
any model the API reports as gone, so a single dead model doesn't take
every LLM-backed extraction down with it.

The advance is process-level and sticky: once a model is marked dead we
never try it again in this process, and every subsequent call for that
chain starts from the new current index.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

from openai import APIStatusError, NotFoundError

from config import KIMI_MODEL_CHAIN, KIMI_VISION_MODEL_CHAIN

logger = logging.getLogger(__name__)

# Per-model max_tokens floors. Some models on the chain need more headroom
# than the tight budgets our prompts were tuned for on the old single model:
# reasoning models spend part of the budget on hidden <thinking> content
# before the visible JSON, and an insufficient cap comes back as
# finish_reason="length" with empty/truncated content. Probed 2026-09-20
# against the real soft-fields prompt (extractors/rcseng.py):
#   nemotron-3-super-120b-a12b — fine at 512.
#   meta/muse-glimmer-30b      — empty at 512, needs >=1024.
#   openai/gpt-oss-20b         — truncated at 512, fine at >=800.
_MIN_MAX_TOKENS = {
    "meta/muse-glimmer-30b": 1024,
    "openai/gpt-oss-20b": 800,
}

_CHAINS: Dict[str, List[str]] = {
    "text": list(KIMI_MODEL_CHAIN),
    "vision": list(KIMI_VISION_MODEL_CHAIN),
}

# Process-level, sticky current index per chain.
_current_index: Dict[str, int] = {"text": 0, "vision": 0}


class AllModelsDeadError(RuntimeError):
    """Raised when every model in a chain has been exhausted (all dead)."""

    def __init__(self, chain: str, tried: List[str]):
        self.chain = chain
        self.tried = tried
        super().__init__(f"All models in the '{chain}' chain are dead. Tried: {tried}")


def current_model(chain: str = "text") -> str:
    """Return the model currently in use for `chain` ('text' or 'vision')."""
    models = _CHAINS[chain]
    return models[_current_index[chain]]


def _is_model_gone(exc: Exception) -> bool:
    """True if the API is telling us the requested model no longer exists."""
    if isinstance(exc, NotFoundError):
        return True
    if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 410:
        return True
    return False


def chat_completion(client: Any, *, chain: str = "text", **create_kwargs):
    """Drop-in replacement for `client.chat.completions.create(...)` that
    walks the model chain on a "model gone" error (404/410).

    Any other exception (429 rate limit, timeout, 5xx) propagates unchanged
    — callers already have their own try/except around these calls and
    should not be retried on a different model, only the current one.
    """
    models = _CHAINS[chain]
    tried: List[str] = []

    while True:
        idx = _current_index[chain]
        if idx >= len(models):
            raise AllModelsDeadError(chain, tried)

        model = models[idx]
        kwargs = dict(create_kwargs)
        floor = _MIN_MAX_TOKENS.get(model)
        if floor and kwargs.get("max_tokens") is not None and kwargs["max_tokens"] < floor:
            kwargs["max_tokens"] = floor

        tried.append(model)
        try:
            return client.chat.completions.create(model=model, **kwargs)
        except Exception as e:
            if not _is_model_gone(e):
                raise
            next_idx = idx + 1
            next_model = models[next_idx] if next_idx < len(models) else None
            logger.warning(
                f"llm_client: model '{model}' is gone ({e}); "
                f"advancing to '{next_model or '<chain exhausted>'}'"
            )
            _current_index[chain] = next_idx
            # loop and retry on the next model (or raise AllModelsDeadError)
