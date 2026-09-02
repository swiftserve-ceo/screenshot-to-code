"""Pure variant-model selection.

Extracted verbatim (behaviour-preserving) from
`routes.generate_code.ModelSelectionStage._get_variant_models` so both the
synchronous WebSocket pipeline and the queued worker path use one implementation
(spec FR-G — selection behaviour MUST NOT change).
"""

from __future__ import annotations

from typing import Literal

from custom_types import InputMode
from llm import Llm
from logging_config import get_logger
from model_registry import MODEL_REGISTRY
from routes.model_choice_sets import (
    ALL_KEYS_MODELS_DEFAULT,
    ALL_KEYS_MODELS_TEXT_CREATE,
    ALL_KEYS_MODELS_UPDATE,
    ANTHROPIC_ONLY_MODELS,
    GEMINI_ANTHROPIC_MODELS,
    GEMINI_ONLY_MODELS,
    GEMINI_OPENAI_MODELS,
    OPENAI_ANTHROPIC_MODELS,
    OPENAI_ONLY_MODELS,
    VIDEO_VARIANT_MODELS,
)

logger = get_logger("generation.model_selection")


class NoProviderCredentialsError(RuntimeError):
    """No usable LLM provider key for the requested generation."""


class VideoModeRequiresGeminiError(NoProviderCredentialsError):
    pass


def select_variant_models(
    *,
    generation_type: Literal["create", "update"],
    input_mode: InputMode,
    num_variants: int,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    gemini_api_key: str | None,
) -> list[Llm]:
    """Return the model list for each variant. Raises on missing credentials."""

    if input_mode == "video":
        if not gemini_api_key:
            raise VideoModeRequiresGeminiError(
                "Video mode requires a Gemini API key. "
                "Please add GEMINI_API_KEY to backend/.env or in the settings dialog"
            )
        return list(VIDEO_VARIANT_MODELS)

    if gemini_api_key and anthropic_api_key and openai_api_key:
        if input_mode == "text" and generation_type == "create":
            models = list(ALL_KEYS_MODELS_TEXT_CREATE)
        elif generation_type == "update":
            models = list(ALL_KEYS_MODELS_UPDATE)
        else:
            models = list(ALL_KEYS_MODELS_DEFAULT)
    elif gemini_api_key and anthropic_api_key:
        models = list(GEMINI_ANTHROPIC_MODELS)
    elif gemini_api_key and openai_api_key:
        models = list(GEMINI_OPENAI_MODELS)
    elif openai_api_key and anthropic_api_key:
        models = list(OPENAI_ANTHROPIC_MODELS)
    elif gemini_api_key:
        models = list(GEMINI_ONLY_MODELS)
    elif anthropic_api_key:
        models = list(ANTHROPIC_ONLY_MODELS)
    elif openai_api_key:
        models = list(OPENAI_ONLY_MODELS)
    else:
        raise NoProviderCredentialsError("No OpenAI, Anthropic, or Gemini API key found")

    # Drop any model the registry marks disabled (none today; keeps selection
    # honest as models are retired). Selection *policy* stays in model_choice_sets.
    usable = [m for m in models if MODEL_REGISTRY[m].enabled]
    if not usable:
        raise NoProviderCredentialsError(
            "every candidate model for this request is disabled in the registry"
        )
    if len(usable) != len(models):
        logger.warning(
            "dropped disabled models from selection",
            extra={"dropped": [m.value for m in models if m not in usable]},
        )

    # Cycle through models: [A, B] with num=5 becomes [A, B, A, B, A]
    return [usable[i % len(usable)] for i in range(num_variants)]
