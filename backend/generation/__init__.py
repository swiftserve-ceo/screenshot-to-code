"""Generation service adapter (Phase 1 Batch 3).

A clean boundary between the queue/worker and the existing provider/agent logic.
`run_generation` executes a generation **independently of any WebSocket** and
reports progress through an `emit` callback, returning a structured
`GenerationOutcome`.

Only the **text → create** path is wired onto the queue this batch (spec §2).
Every other generation path still runs through the synchronous
`routes/generate_code.py` pipeline.
"""

from generation.model_selection import (
    NoProviderCredentialsError,
    select_variant_models,
)
from generation.service import run_generation
from generation.types import (
    GenerationEvent,
    GenerationOutcome,
    GenerationRequest,
    GenerationVariantResult,
    NonRetryableGenerationError,
    ProviderCredentials,
)

__all__ = [
    "GenerationEvent",
    "GenerationOutcome",
    "GenerationRequest",
    "GenerationVariantResult",
    "NoProviderCredentialsError",
    "NonRetryableGenerationError",
    "ProviderCredentials",
    "run_generation",
    "select_variant_models",
]
