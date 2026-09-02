# pyright: reportUnknownVariableType=false
"""Structured DTOs for the generation service.

Deliberately **contains no provider credentials in anything that is persisted or
enqueued**. `ProviderCredentials` is resolved from server config at execution
time inside the worker and never serialised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from prompts.prompt_types import PromptHistoryMessage, Stack, UserTurnInput


class NonRetryableGenerationError(RuntimeError):
    """A deterministic generation failure (bad input, missing credentials,
    prompt-assembly error). The worker must NOT retry these."""


@dataclass(frozen=True)
class GenerationRequest:
    """Everything needed to run a text→create generation — **no secrets**.

    This is exactly what gets stored in `jobs.params` and travels through Redis.
    """

    stack: Stack
    prompt: UserTurnInput
    history: list[PromptHistoryMessage] = field(default_factory=list)
    design_system: Optional[str] = None
    should_generate_images: bool = True
    should_extract_assets: bool = False
    asset_base_url: str = ""
    # Fixed for this batch — only text→create is queue-backed.
    input_mode: str = "text"
    generation_type: str = "create"

    def to_params(self) -> dict[str, Any]:
        return {
            "stack": self.stack,
            "prompt": self.prompt,
            "history": self.history,
            "design_system": self.design_system,
            "should_generate_images": self.should_generate_images,
            "should_extract_assets": self.should_extract_assets,
            "asset_base_url": self.asset_base_url,
            "input_mode": self.input_mode,
            "generation_type": self.generation_type,
        }

    @staticmethod
    def from_params(params: dict[str, Any]) -> "GenerationRequest":
        return GenerationRequest(
            stack=params["stack"],
            prompt=params["prompt"],
            history=params.get("history") or [],
            design_system=params.get("design_system"),
            should_generate_images=bool(params.get("should_generate_images", True)),
            should_extract_assets=bool(params.get("should_extract_assets", False)),
            asset_base_url=params.get("asset_base_url", ""),
            input_mode=params.get("input_mode", "text"),
            generation_type=params.get("generation_type", "create"),
        )


@dataclass(frozen=True)
class ProviderCredentials:
    """Resolved at execution time from server config. Never persisted / logged."""

    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    replicate_api_key: Optional[str] = None

    @staticmethod
    def from_settings() -> "ProviderCredentials":
        from config import settings

        base_url = None if settings.is_prod else settings.openai_base_url
        return ProviderCredentials(
            openai_api_key=settings.openai_api_key,
            openai_base_url=base_url,
            anthropic_api_key=settings.anthropic_api_key,
            gemini_api_key=settings.gemini_api_key,
            replicate_api_key=settings.replicate_api_key,
        )

    @property
    def has_any_llm_key(self) -> bool:
        return bool(self.openai_api_key or self.anthropic_api_key or self.gemini_api_key)


@dataclass(frozen=True)
class GenerationEvent:
    """One progress event, in the existing frontend WS vocabulary."""

    message_type: str  # variantCount | status | setCode | variantComplete | variantError | thinking | assistant | toolStart | toolResult | chunk | variantModels
    value: Optional[str] = None
    variant_index: int = 0
    data: Optional[dict[str, Any]] = None
    event_id: Optional[str] = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "message_type": self.message_type,
            "value": self.value,
            "variant_index": self.variant_index,
            "data": self.data,
            "event_id": self.event_id,
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "GenerationEvent":
        return GenerationEvent(
            message_type=payload["message_type"],
            value=payload.get("value"),
            variant_index=payload.get("variant_index", 0),
            data=payload.get("data"),
            event_id=payload.get("event_id"),
        )


@dataclass
class GenerationVariantResult:
    index: int
    status: str  # "complete" | "error"
    code: str = ""
    error: Optional[str] = None


@dataclass
class GenerationOutcome:
    variants: list[GenerationVariantResult]
    models: list[str]

    @property
    def any_succeeded(self) -> bool:
        return any(v.status == "complete" and v.code.strip() for v in self.variants)
