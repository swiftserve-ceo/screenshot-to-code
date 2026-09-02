"""Phase 1 model registry foundation.

A single typed catalogue of the models the application can use — replacing the
metadata that was scattered across ``llm.py`` (`OPENAI_MODEL_CONFIG`),
``agent/providers/anthropic`` (`ANTHROPIC_MODEL_CONFIG`),
``agent/providers/gemini`` (a conditional chain), ``costs/pricing.py``, and the
membership sets in ``llm.py``.

**Not** in scope (Phase 2+): user-owned keys, org-level provider config, billing,
usage accounting, a routing engine, a provider marketplace. The registry holds
**no secrets** — only public model metadata safe for frontend capability
discovery.

Selection *policy* (which model to pick for which key-combination) still lives in
``routes/model_choice_sets.py``; the registry is the metadata layer it and the
provider factory consult.
"""

from model_registry.registry import (
    MODEL_REGISTRY,
    REPLICATE_REGISTRY,
    api_name_of,
    enabled_models,
    frontend_model_catalog,
    get_model,
    models_for_provider,
    pricing_for,
    pricing_for_api_name,
    provider_of,
    reasoning_effort_of,
)
from model_registry.types import (
    Capability,
    Modality,
    ModelEntry,
    Provider,
    ModelStatus,
)

__all__ = [
    "MODEL_REGISTRY",
    "REPLICATE_REGISTRY",
    "Capability",
    "Modality",
    "ModelEntry",
    "ModelStatus",
    "Provider",
    "api_name_of",
    "enabled_models",
    "frontend_model_catalog",
    "get_model",
    "models_for_provider",
    "pricing_for",
    "pricing_for_api_name",
    "provider_of",
    "reasoning_effort_of",
]
