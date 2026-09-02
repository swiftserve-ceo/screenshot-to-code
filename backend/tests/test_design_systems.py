import json
from pathlib import Path

import pytest

import routes.design_systems as ds_mod
from routes.design_systems import (
    CreateDesignSystemRequest,
    UpdateDesignSystemRequest,
    create_design_system,
    delete_design_system,
    get_design_systems_file_path,
    list_design_systems,
    update_design_system,
)


@pytest.mark.asyncio
async def test_design_system_crud_persists_to_backend_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ds_mod,
        "settings",
        ds_mod.settings.model_copy(update={"screenshot_to_code_data_dir": str(tmp_path)}),
    )

    assert await list_design_systems() == []

    created = await create_design_system(
        CreateDesignSystemRequest(name="Legal SaaS", content="Use .mockup-frame")
    )

    assert created.name == "Legal SaaS"
    assert created.content == "Use .mockup-frame"
    assert get_design_systems_file_path().exists()

    raw_items = json.loads(get_design_systems_file_path().read_text(encoding="utf-8"))
    assert raw_items[0]["id"] == created.id

    updated = await update_design_system(
        created.id,
        UpdateDesignSystemRequest(name="Legal Marketing", content="Use Roboto"),
    )

    assert updated.name == "Legal Marketing"
    assert updated.content == "Use Roboto"

    await delete_design_system(created.id)

    assert await list_design_systems() == []
