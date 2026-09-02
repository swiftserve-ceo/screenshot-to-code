"""Per-variant agent execution.

`AgenticGenerationStage` was moved here (unchanged) from
`routes.generate_code` so the synchronous WebSocket pipeline and the queued
worker path share one implementation. It takes a `send_message` callable and is
therefore independent of any WebSocket.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Literal, cast

import openai
from openai.types.chat import ChatCompletionMessageParam

from agent.runner import Agent
from config import IS_PROD
from fs_logging.agent_runs import AgentRunRecorder
from llm import Llm
from logging_config import get_logger

logger = get_logger("generation.variants")

# WebSocket / event message vocabulary (unchanged).
MessageType = Literal[
    "chunk",
    "status",
    "setCode",
    "error",
    "variantComplete",
    "variantError",
    "variantCount",
    "variantModels",
    "thinking",
    "assistant",
    "toolStart",
    "toolResult",
]

SendMessage = Callable[
    [MessageType, "str | None", int, "Dict[str, Any] | None", "str | None"],
    Coroutine[Any, Any, None],
]


class AgenticGenerationStage:
    """Handles agent tool-calling generation for each variant."""

    def __init__(
        self,
        send_message: SendMessage,
        openai_api_key: str | None,
        openai_base_url: str | None,
        anthropic_api_key: str | None,
        gemini_api_key: str | None,
        replicate_api_key: str | None,
        should_generate_images: bool,
        file_state: Dict[str, str] | None,
        asset_base_url: str,
        option_codes: List[str] | None,
        should_extract_assets: bool = True,
        generation_id: str | None = None,
        stack: str | None = None,
        input_mode: str | None = None,
        generation_type: str | None = None,
        entry_point: str = "websocket",
    ):
        self.send_message = send_message
        self.openai_api_key = openai_api_key
        self.openai_base_url = openai_base_url
        self.anthropic_api_key = anthropic_api_key
        self.gemini_api_key = gemini_api_key
        self.replicate_api_key = replicate_api_key
        self.should_generate_images = should_generate_images
        self.should_extract_assets = should_extract_assets
        self.file_state = file_state
        self.asset_base_url = asset_base_url
        self.option_codes = option_codes or []
        self.generation_id = (
            generation_id
            or f"gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
        self.stack = stack
        self.input_mode = input_mode
        self.generation_type = generation_type
        self.entry_point = entry_point

    async def process_variants(
        self,
        variant_models: List[Llm],
        prompt_messages: List[ChatCompletionMessageParam],
    ) -> Dict[int, str]:
        tasks: List[asyncio.Task[str]] = []
        for index, model in enumerate(variant_models):
            tasks.append(
                asyncio.create_task(self._run_variant(index, model, prompt_messages))
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        variant_completions: Dict[int, str] = {}
        for index, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "variant task raised",
                    extra={"variant": index + 1, "error": repr(result)},
                )
                continue
            if result:
                variant_completions[index] = result

        return variant_completions

    async def _run_variant(
        self,
        index: int,
        model: Llm,
        prompt_messages: List[ChatCompletionMessageParam],
    ) -> str:
        try:

            async def send_runner_message(
                type: str,
                value: str | None,
                variant_index: int,
                data: Dict[str, Any] | None,
                event_id: str | None,
            ) -> None:
                await self.send_message(
                    cast(MessageType, type),
                    value,
                    variant_index,
                    data,
                    event_id,
                )

            recorder = AgentRunRecorder(
                generation_id=self.generation_id,
                variant_index=index,
                entry_point=self.entry_point,
                stack=self.stack,
                input_mode=self.input_mode,
                generation_type=self.generation_type,
            )
            runner = Agent(
                send_message=send_runner_message,
                variant_index=index,
                openai_api_key=self.openai_api_key,
                openai_base_url=self.openai_base_url,
                anthropic_api_key=self.anthropic_api_key,
                gemini_api_key=self.gemini_api_key,
                replicate_api_key=self.replicate_api_key,
                should_generate_images=self.should_generate_images,
                should_extract_assets=self.should_extract_assets,
                asset_base_url=self.asset_base_url,
                initial_file_state=self.file_state,
                option_codes=self.option_codes,
                recorder=recorder,
            )
            completion = await runner.run(model, prompt_messages)
            if completion:
                await self.send_message("setCode", completion, index, None, None)
            await self.send_message(
                "variantComplete",
                "Variant generation complete",
                index,
                None,
                None,
            )
            return completion
        except openai.AuthenticationError as e:
            logger.warning(
                "OpenAI authentication failed",
                extra={"variant": index + 1, "error": str(e)},
            )
            error_message = (
                "Incorrect OpenAI key. Please make sure your OpenAI API key is correct, "
                "or create a new OpenAI API key on your OpenAI dashboard."
                + (
                    " Alternatively, you can purchase code generation credits directly on this website."
                    if IS_PROD
                    else ""
                )
            )
            await self.send_message("variantError", error_message, index, None, None)
            return ""
        except openai.NotFoundError as e:
            logger.warning(
                "OpenAI model not found", extra={"variant": index + 1, "error": str(e)}
            )
            error_message = (
                e.message
                + ". Please make sure you have followed the instructions correctly to obtain "
                "an OpenAI key with GPT vision access: "
                "https://github.com/abi/screenshot-to-code/blob/main/Troubleshooting.md"
                + (
                    " Alternatively, you can purchase code generation credits directly on this website."
                    if IS_PROD
                    else ""
                )
            )
            await self.send_message("variantError", error_message, index, None, None)
            return ""
        except openai.RateLimitError as e:
            logger.warning(
                "OpenAI rate limit exceeded",
                extra={"variant": index + 1, "error": str(e)},
            )
            error_message = (
                "OpenAI error - 'You exceeded your current quota, please check your plan and billing details.'"
                + (
                    " Alternatively, you can purchase code generation credits directly on this website."
                    if IS_PROD
                    else ""
                )
            )
            await self.send_message("variantError", error_message, index, None, None)
            return ""
        except Exception as e:
            logger.exception("variant generation failed", extra={"variant": index + 1})
            await self.send_message("variantError", str(e), index, None, None)
            return ""
