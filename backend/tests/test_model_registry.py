# pyright: reportPrivateUsage=false
"""Phase 1 Batch 4 — the typed model registry.

The registry is a *derived* layer over the existing metadata (`llm.py`,
`costs.pricing`, provider configs). These tests pin every derivation so it
cannot silently drift from real provider behaviour, and assert the
frontend-facing catalog never leaks secrets.
"""

from __future__ import annotations

import json

import pytest

from llm import GEMINI_MODELS, MODEL_PROVIDER, Llm, get_openai_api_name
from agent.providers.anthropic.provider import _get_anthropic_api_model_name
from agent.providers.gemini import _get_gemini_api_model_name

from model_registry import (
    MODEL_REGISTRY,
    REPLICATE_REGISTRY,
    Capability,
    Modality,
    ModelStatus,
    Provider,
    api_name_of,
    enabled_models,
    frontend_model_catalog,
    get_model,
    models_for_provider,
    pricing_for,
    provider_of,
)


def _legacy_api_name(model: Llm) -> str:
    provider = MODEL_PROVIDER[model]
    if provider == "openai":
        return get_openai_api_name(model)
    if provider == "anthropic":
        return _get_anthropic_api_model_name(model)
    if provider == "gemini":
        return _get_gemini_api_model_name(model)
    raise AssertionError(provider)


# --- coverage + derivation fidelity -----------------------------------------


def test_registry_covers_every_llm_member() -> None:
    assert set(MODEL_REGISTRY) == set(Llm)


@pytest.mark.parametrize("model", list(Llm))
def test_api_name_matches_legacy_provider_resolution(model: Llm) -> None:
    assert api_name_of(model) == _legacy_api_name(model)
    assert MODEL_REGISTRY[model].api_name == _legacy_api_name(model)


@pytest.mark.parametrize("model", list(Llm))
def test_provider_matches_llm_module(model: Llm) -> None:
    assert provider_of(model).value == MODEL_PROVIDER[model]
    assert MODEL_REGISTRY[model].provider.value == MODEL_PROVIDER[model]


@pytest.mark.parametrize("model", list(Llm))
def test_every_code_model_can_generate_code(model: Llm) -> None:
    entry = MODEL_REGISTRY[model]
    assert entry.can_generate_code
    assert Capability.CODE_GENERATION in entry.capabilities
    assert Modality.TEXT in entry.input_modalities
    assert Modality.IMAGE in entry.input_modalities


@pytest.mark.parametrize("model", list(Llm))
def test_video_modality_iff_gemini_screen_recording_capable(model: Llm) -> None:
    has_video = Modality.VIDEO in MODEL_REGISTRY[model].input_modalities
    assert has_video == (model in GEMINI_MODELS)


@pytest.mark.parametrize("model", list(Llm))
def test_preview_status_tracks_api_name(model: Llm) -> None:
    entry = MODEL_REGISTRY[model]
    expected = ModelStatus.PREVIEW if "preview" in entry.api_name else ModelStatus.AVAILABLE
    assert entry.status == expected


def test_pricing_is_sourced_from_costs_module() -> None:
    from costs.pricing import MODEL_PRICING

    for model, entry in MODEL_REGISTRY.items():
        assert entry.pricing is MODEL_PRICING.get(entry.api_name)
        assert pricing_for(model) is entry.pricing


# --- replicate tools -------------------------------------------------------


def test_replicate_registry_has_exactly_one_default_image_generator() -> None:
    defaults = [e for e in REPLICATE_REGISTRY.values() if e.is_default]
    assert [e.key for e in defaults] == ["z_image_turbo"]


def test_replicate_entries_are_not_code_generators() -> None:
    for entry in REPLICATE_REGISTRY.values():
        assert entry.provider is Provider.REPLICATE
        assert not entry.can_generate_code


# --- lookups -------------------------------------------------------------


def test_get_model_accepts_llm_enum_string_key_and_replicate_id() -> None:
    sample = next(iter(Llm))
    assert get_model(sample) is MODEL_REGISTRY[sample]
    assert get_model(sample.name) is MODEL_REGISTRY[sample]
    assert get_model("z_image_turbo") is REPLICATE_REGISTRY["z_image_turbo"]
    with pytest.raises(KeyError):
        get_model("no-such-model")


def test_models_for_provider_partitions_the_registry() -> None:
    total = sum(len(models_for_provider(p)) for p in Provider)
    assert total == len(MODEL_REGISTRY) + len(REPLICATE_REGISTRY)
    assert all(e.provider is Provider.REPLICATE for e in models_for_provider(Provider.REPLICATE))


def test_enabled_models_excludes_disabled_and_deprecated() -> None:
    names = {e.key for e in enabled_models()}
    for entry in (*MODEL_REGISTRY.values(), *REPLICATE_REGISTRY.values()):
        should = entry.enabled and entry.status != ModelStatus.DEPRECATED
        assert (entry.key in names) == should


# --- frontend safety -----------------------------------------------------


def test_frontend_catalog_is_secret_free() -> None:
    catalog = frontend_model_catalog()
    blob = json.dumps(catalog)
    assert "api_name" not in blob
    assert "pricing" not in blob
    # every model appears exactly once
    keys = [m["key"] for m in catalog["models"]]  # type: ignore[index]
    assert len(keys) == len(set(keys))
    assert len(keys) == len(MODEL_REGISTRY) + len(REPLICATE_REGISTRY)


def test_public_dict_never_exposes_provider_facing_or_cost_fields() -> None:
    allowed = {
        "key",
        "provider",
        "display_name",
        "capabilities",
        "input_modalities",
        "status",
        "enabled",
        "is_default",
    }
    for entry in (*MODEL_REGISTRY.values(), *REPLICATE_REGISTRY.values()):
        public = entry.to_public_dict()
        assert set(public) == allowed
        assert entry.api_name not in json.dumps(public) or entry.api_name == entry.display_name
