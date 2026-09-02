from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol

from agent.tools import ToolCall, ToolExecutionResult
from costs.pricing import ModelPricing
from costs.token_usage import TokenUsage
from logging_config import get_logger

_usage_logger = get_logger("providers.usage")


def _log_token_usage(
    provider: str, model_name: str, usage: TokenUsage, pricing: Optional[ModelPricing]
) -> None:
    """Structured per-turn token/cost accounting. Provider + model + counts are
    safe to log; no prompt text or credentials are included."""
    _usage_logger.info(
        "provider token usage",
        extra={
            "provider": provider,
            "model": model_name,
            "input_tokens": usage.input,
            "output_tokens": usage.output,
            "cache_read": usage.cache_read,
            "cache_write": usage.cache_write,
            "total_tokens": usage.total,
            "cache_hit_rate_percent": round(usage.cache_hit_rate_percent(), 2),
            "cost_usd": round(usage.cost(pricing), 4) if pricing else None,
        },
    )


StreamEventType = Literal[
    "assistant_delta",
    "thinking_delta",
    "tool_call_delta",
]


@dataclass
class StreamEvent:
    type: StreamEventType
    text: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Any = None


@dataclass
class ProviderTurn:
    assistant_text: str
    tool_calls: list[ToolCall]
    # Provider-native assistant turn object required to continue the conversation.
    assistant_turn: Any = None


@dataclass
class ExecutedToolCall:
    tool_call: ToolCall
    result: ToolExecutionResult


EventSink = Callable[[StreamEvent], Awaitable[None]]


class ProviderSession(Protocol):
    async def stream_turn(self, on_event: EventSink) -> ProviderTurn:
        ...

    async def append_tool_results(
        self,
        turn: ProviderTurn,
        executed_tool_calls: list[ExecutedToolCall],
    ) -> None:
        ...

    def total_cost_usd(self) -> Optional[float]:
        """USD spent so far this session; None when the model is unpriced."""
        ...

    async def close(self) -> None:
        ...
