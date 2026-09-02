"""The registry itself — derived from the existing metadata sources so it cannot
silently drift from provider behaviour (a test pins every derivation).
"""

from __future__ import annotations

from costs.pricing import MODEL_PRICING, ModelPricing
from llm import (
    ANTHROPIC_MODELS,
    GEMINI_MODELS,
    MODEL_PROVIDER,
    OPENAI_MODEL_CONFIG,
    OPENAI_MODELS,
    Llm,
)

from model_registry.types import (
    Capability,
    Modality,
    ModelEntry,
    ModelStatus,
    Provider,
)

# --- api-name / effort resolution (single source of truth) -------------------
# Anthropic api-name + effort, mirrored from
# agent/providers/anthropic/provider.ANTHROPIC_MODEL_CONFIG. Sonnet has no entry
# there and falls back to its enum value.
_ANTHROPIC_API_NAME: dict[Llm, str] = {}
_ANTHROPIC_EFFORT: dict[Llm, str] = {}
for _m in (
    Llm.CLAUDE_OPUS_5_LOW, Llm.CLAUDE_OPUS_5_MEDIUM, Llm.CLAUDE_OPUS_5_HIGH,
    Llm.CLAUDE_OPUS_5_XHIGH, Llm.CLAUDE_OPUS_5_MAX,
):
    _ANTHROPIC_API_NAME[_m] = "claude-opus-5"
for _m in (
    Llm.CLAUDE_OPUS_4_8_LOW, Llm.CLAUDE_OPUS_4_8_MEDIUM, Llm.CLAUDE_OPUS_4_8_HIGH,
    Llm.CLAUDE_OPUS_4_8_XHIGH, Llm.CLAUDE_OPUS_4_8_MAX,
):
    _ANTHROPIC_API_NAME[_m] = "claude-opus-4-8"
for _m in (
    Llm.CLAUDE_FABLE_5_LOW, Llm.CLAUDE_FABLE_5_MEDIUM, Llm.CLAUDE_FABLE_5_HIGH,
    Llm.CLAUDE_FABLE_5_XHIGH, Llm.CLAUDE_FABLE_5_MAX,
):
    _ANTHROPIC_API_NAME[_m] = "claude-fable-5"
for _m, _eff in (
    ("LOW", "low"), ("MEDIUM", "medium"), ("HIGH", "high"), ("XHIGH", "xhigh"), ("MAX", "max"),
):
    for _fam in ("CLAUDE_OPUS_5", "CLAUDE_OPUS_4_8", "CLAUDE_FABLE_5"):
        _ANTHROPIC_EFFORT[Llm[f"{_fam}_{_m}"]] = _eff


def _anthropic_api_name(model: Llm) -> str:
    return _ANTHROPIC_API_NAME.get(model, model.value)


def _gemini_api_name(model: Llm) -> str:
    # Every Gemini enum value is "<api-name> (<effort> thinking)".
    return model.value.split(" (", 1)[0]


def _gemini_effort(model: Llm) -> str | None:
    value = model.value
    if "(" not in value:
        return None
    inside = value.split("(", 1)[1].rstrip(")")
    return inside.replace(" thinking", "").strip() or None


def api_name_of(model: Llm) -> str:
    provider = MODEL_PROVIDER[model]
    if provider == "openai":
        return OPENAI_MODEL_CONFIG[model]["api_name"]
    if provider == "anthropic":
        return _anthropic_api_name(model)
    if provider == "gemini":
        return _gemini_api_name(model)
    raise KeyError(f"unknown provider for {model!r}")


def reasoning_effort_of(model: Llm) -> str | None:
    provider = MODEL_PROVIDER[model]
    if provider == "openai":
        return OPENAI_MODEL_CONFIG.get(model, {}).get("reasoning_effort")
    if provider == "anthropic":
        return _ANTHROPIC_EFFORT.get(model)
    if provider == "gemini":
        return _gemini_effort(model)
    return None


def provider_of(model: Llm) -> Provider:
    return Provider(MODEL_PROVIDER[model])


# --- code-generation model entries -----------------------------------------
_PROVIDER_ENUM = {
    "openai": Provider.OPENAI,
    "anthropic": Provider.ANTHROPIC,
    "gemini": Provider.GEMINI,
}
# Which code-gen models can also drive a screen-recording (video) input.
# Mirrors routes.model_choice_sets.VIDEO_VARIANT_MODELS being Gemini-only.
_VIDEO_CAPABLE = GEMINI_MODELS


def _display_name(api_name: str, effort: str | None) -> str:
    label = api_name.replace("gpt-", "GPT-").replace("claude-", "Claude ").replace(
        "gemini-", "Gemini "
    )
    return f"{label} ({effort})" if effort else label


def _build_llm_registry() -> dict[Llm, ModelEntry]:
    out: dict[Llm, ModelEntry] = {}
    for model in Llm:
        provider_name = MODEL_PROVIDER[model]
        api_name = api_name_of(model)
        effort = reasoning_effort_of(model)
        modalities = {Modality.TEXT, Modality.IMAGE}
        if model in _VIDEO_CAPABLE:
            modalities.add(Modality.VIDEO)
        status = (
            ModelStatus.PREVIEW if "preview" in api_name else ModelStatus.AVAILABLE
        )
        out[model] = ModelEntry(
            key=model.name,
            provider=_PROVIDER_ENUM[provider_name],
            api_name=api_name,
            display_name=_display_name(api_name, effort),
            capabilities=frozenset({Capability.CODE_GENERATION}),
            input_modalities=frozenset(modalities),
            status=status,
            enabled=True,
            reasoning_effort=effort,
            pricing=MODEL_PRICING.get(api_name),
            llm=model,
        )
    return out


MODEL_REGISTRY: dict[Llm, ModelEntry] = _build_llm_registry()


# --- Replicate (image) tools ------------------------------------------------
# Sourced from image_generation/replicate.py. These are not `Llm` members.
REPLICATE_REGISTRY: dict[str, ModelEntry] = {
    "z_image_turbo": ModelEntry(
        key="z_image_turbo",
        provider=Provider.REPLICATE,
        api_name="prunaai/z-image-turbo",
        display_name="z-image-turbo",
        capabilities=frozenset({Capability.IMAGE_GENERATION}),
        input_modalities=frozenset({Modality.TEXT}),
        is_default=True,
    ),
    "flux_2_klein": ModelEntry(
        key="flux_2_klein",
        provider=Provider.REPLICATE,
        api_name="black-forest-labs/flux-2-klein-4b",
        display_name="FLUX.2 Klein",
        capabilities=frozenset({Capability.IMAGE_GENERATION}),
        input_modalities=frozenset({Modality.TEXT}),
    ),
    "p_image_edit": ModelEntry(
        key="p_image_edit",
        provider=Provider.REPLICATE,
        api_name="prunaai/p-image-edit",
        display_name="p-image-edit",
        capabilities=frozenset({Capability.IMAGE_EDITING}),
        input_modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
    ),
    "remove_background": ModelEntry(
        key="remove_background",
        provider=Provider.REPLICATE,
        api_name="lucataco/remove-bg",
        display_name="Background remover",
        capabilities=frozenset({Capability.BACKGROUND_REMOVAL}),
        input_modalities=frozenset({Modality.IMAGE}),
    ),
}


# --- lookups ---------------------------------------------------------------
def get_model(key: "Llm | str") -> ModelEntry:
    if isinstance(key, Llm):
        return MODEL_REGISTRY[key]
    if key in REPLICATE_REGISTRY:
        return REPLICATE_REGISTRY[key]
    for entry in MODEL_REGISTRY.values():
        if entry.key == key:
            return entry
    raise KeyError(f"unknown model {key!r}")


def models_for_provider(provider: Provider) -> list[ModelEntry]:
    both = list(MODEL_REGISTRY.values()) + list(REPLICATE_REGISTRY.values())
    return [e for e in both if e.provider == provider]


def enabled_models() -> list[ModelEntry]:
    both = list(MODEL_REGISTRY.values()) + list(REPLICATE_REGISTRY.values())
    return [e for e in both if e.enabled and e.status != ModelStatus.DEPRECATED]


def pricing_for(model: Llm) -> ModelPricing | None:
    return MODEL_REGISTRY[model].pricing


def pricing_for_api_name(api_name: str) -> ModelPricing | None:
    return MODEL_PRICING.get(api_name)


def frontend_model_catalog() -> dict[str, object]:
    """Everything the frontend may safely learn about model capabilities."""
    return {
        "providers": [p.value for p in Provider],
        "models": [
            e.to_public_dict()
            for e in (*MODEL_REGISTRY.values(), *REPLICATE_REGISTRY.values())
        ],
    }
