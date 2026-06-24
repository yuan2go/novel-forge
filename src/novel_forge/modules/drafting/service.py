from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.common import read_previous
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


def draft(storage: LocalStorage, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    model = model or MockModelAdapter()
    plan = read_previous(storage, "chapter_plans", input_path)
    generated = model.generate("draft chapter from plan", {"plan": plan.content})
    asset = DraftChapter(
        title="Chapter 1 draft v0",
        source=plan.id,
        tags=["draft", "v0", "mock"],
        content={
            "chapter": 1,
            "text": (
                "雨水把广场的钟声压得很低。林乔抬头时，停用三年的钟楼忽然响了一下。"
                "档案表显示维护员早已离职，但新登记的巡检号正贴在门缝里。"
                "她把纸条塞进口袋，听见第二声钟从城市另一端传来。"
            ),
            "model_output": generated,
            "copyright_boundary": "mock original draft; no reference expression copied",
        },
        references=[plan.id],
    )
    return storage.write_asset("drafts", asset)
