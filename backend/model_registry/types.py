"""Typed model-registry primitives. No secrets, no keys."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

from costs.pricing import ModelPricing
from llm import Llm


class Provider(str, enum.Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    REPLICATE = "replicate"


class Modality(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"


class Capability(str, enum.Enum):
    CODE_GENERATION = "code_generation"
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDITING = "image_editing"
    BACKGROUND_REMOVAL = "background_removal"
    ASSET_EXTRACTION = "asset_extraction"


class ModelStatus(str, enum.Enum):
    AVAILABLE = "available"
    PREVIEW = "preview"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class ModelEntry:
    """One model the application can address.

    ``key`` is the internal ``Llm`` enum member for code-gen models, or a stable
    string id for non-``Llm`` (e.g. Replicate) models. ``api_name`` is the
    provider-facing model name.
    """

    key: str
    provider: Provider
    api_name: str
    display_name: str
    capabilities: frozenset[Capability]
    input_modalities: frozenset[Modality]
    status: ModelStatus = ModelStatus.AVAILABLE
    enabled: bool = True
    is_default: bool = False
    reasoning_effort: Optional[str] = None
    context_window: Optional[int] = None
    pricing: Optional[ModelPricing] = None
    # The originating Llm enum member, when there is one.
    llm: Optional[Llm] = field(default=None, repr=False)

    @property
    def can_generate_code(self) -> bool:
        return Capability.CODE_GENERATION in self.capabilities

    def to_public_dict(self) -> dict[str, object]:
        """Frontend-safe metadata: no api_name, no pricing, no keys."""
        return {
            "key": self.key,
            "provider": self.provider.value,
            "display_name": self.display_name,
            "capabilities": sorted(c.value for c in self.capabilities),
            "input_modalities": sorted(m.value for m in self.input_modalities),
            "status": self.status.value,
            "enabled": self.enabled,
            "is_default": self.is_default,
        }
