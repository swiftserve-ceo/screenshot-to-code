"""`run_generation` — execute a text→create generation independently of any
WebSocket, reporting progress through an `emit` callback.

Reuses the existing prompt pipeline, the shared model selector, and the moved
`AgenticGenerationStage`. Does not rewrite the generation engine.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, cast

from config import settings
from logging_config import get_logger
from prompts.pipeline import build_prompt_messages

from generation.model_selection import (
    NoProviderCredentialsError,
    select_variant_models,
)
from generation.types import (
    GenerationEvent,
    GenerationOutcome,
    GenerationRequest,
    GenerationVariantResult,
    NonRetryableGenerationError,
    ProviderCredentials,
)
from generation.variants import AgenticGenerationStage, MessageType

logger = get_logger("generation.service")

Emit = Callable[[GenerationEvent], Awaitable[None]]


async def run_generation(
    req: GenerationRequest,
    creds: ProviderCredentials,
    emit: Emit,
    *,
    generation_id: str | None = None,
) -> GenerationOutcome:
    """Run every variant for a text→create request.

    Raises `NonRetryableGenerationError` for deterministic failures (bad input,
    missing credentials, prompt-assembly errors) — the worker must not retry
    those. Transient provider/network errors propagate as-is (retryable).
    """
    if req.input_mode != "text" or req.generation_type != "create":
        raise NonRetryableGenerationError(
            f"queued generation only supports text→create, got "
            f"{req.input_mode}/{req.generation_type}"
        )

    # --- prompt assembly -------------------------------------------------
    try:
        prompt_messages = await build_prompt_messages(
            stack=req.stack,
            input_mode="text",
            generation_type="create",
            prompt=req.prompt,
            history=req.history,
            file_state=None,
            image_generation_enabled=req.should_generate_images,
            design_system=req.design_system,
        )
    except Exception as exc:
        logger.exception("failed to assemble prompt messages")
        await emit(
            GenerationEvent(
                "error",
                "Error assembling the prompt for this request. Check the backend logs "
                "for details.",
            )
        )
        raise NonRetryableGenerationError("prompt assembly failed") from exc

    # --- model selection ----------------------------------------------
    try:
        models = select_variant_models(
            generation_type="create",
            input_mode="text",
            num_variants=settings.num_variants,
            openai_api_key=creds.openai_api_key,
            anthropic_api_key=creds.anthropic_api_key,
            gemini_api_key=creds.gemini_api_key,
        )
    except NoProviderCredentialsError as exc:
        await emit(
            GenerationEvent(
                "error",
                "No OpenAI, Anthropic, or Gemini API key found. Add OPENAI_API_KEY, "
                "ANTHROPIC_API_KEY, or GEMINI_API_KEY to the backend environment and "
                "restart the backend / worker.",
            )
        )
        raise NonRetryableGenerationError(str(exc)) from exc

    # --- initial progress (existing frontend vocabulary) --------------
    await emit(GenerationEvent("variantCount", str(len(models)), 0))
    for i in range(len(models)):
        await emit(GenerationEvent("status", "Generating code...", i))
    if settings.is_debug_enabled:
        await emit(
            GenerationEvent(
                "variantModels", None, 0, data={"models": [m.value for m in models]}
            )
        )

    # --- run variants -------------------------------------------------
    async def send_message(
        type: MessageType,
        value: str | None,
        variant_index: int,
        data: Dict[str, Any] | None,
        event_id: str | None,
    ) -> None:
        await emit(
            GenerationEvent(
                message_type=cast(str, type),
                value=value,
                variant_index=variant_index,
                data=data,
                event_id=event_id,
            )
        )

    stage = AgenticGenerationStage(
        send_message=send_message,
        openai_api_key=creds.openai_api_key,
        openai_base_url=creds.openai_base_url,
        anthropic_api_key=creds.anthropic_api_key,
        gemini_api_key=creds.gemini_api_key,
        replicate_api_key=creds.replicate_api_key,
        should_generate_images=req.should_generate_images,
        should_extract_assets=False,  # text→create has no source screenshots
        file_state=None,
        asset_base_url=req.asset_base_url,
        option_codes=[],
        generation_id=generation_id,
        stack=str(req.stack),
        input_mode="text",
        generation_type="create",
        entry_point="worker",
    )

    completions = await stage.process_variants(models, prompt_messages)

    variants: list[GenerationVariantResult] = []
    for i in range(len(models)):
        if i in completions and completions[i].strip():
            variants.append(GenerationVariantResult(index=i, status="complete", code=completions[i]))
        else:
            variants.append(
                GenerationVariantResult(index=i, status="error", error="variant produced no output")
            )

    outcome = GenerationOutcome(variants=variants, models=[m.value for m in models])
    if not outcome.any_succeeded:
        # Every variant failed for a non-credential reason — surface it, but this
        # is NOT retryable at the job level (a retry would just fail again the
        # same way; individual transient variant errors were already handled).
        await emit(GenerationEvent("error", "Code generation failed for every variant."))
        raise NonRetryableGenerationError("all variants failed")

    return outcome
