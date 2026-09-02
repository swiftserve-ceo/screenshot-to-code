"""Frontend model-capability discovery (Phase 1 model registry).

Returns only public metadata — provider, display name, capabilities, input
modalities, status, enabled/default flags. **Never** api model names, pricing, or
anything key-related.
"""

from __future__ import annotations

from fastapi import APIRouter

from model_registry import frontend_model_catalog

router = APIRouter()


@router.get("/api/models")
async def list_models() -> dict[str, object]:
    return frontend_model_catalog()
