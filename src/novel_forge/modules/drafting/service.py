from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters import ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, retrieval_metadata, retrieval_reference_ids


def draft(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    model = model or model_from_env("draft")
    plan = read_previous(storage, "chapter_plans", input_path)
    retrieved_context = build_rag_context(
        storage,
        plan,
        input_path=input_path,
        query=f"draft chapter {plan.title} {plan.content.get('objective', '')} {plan.content.get('hook', '')}",
    )
    generated = validate_model_output(
        "generate",
        model.generate(
            "Draft an original Chinese web-novel chapter from the chapter plan.",
            {
                "plan": plan.content,
                "source_asset_id": plan.id,
                "retrieved_context": retrieved_context,
            },
        ),
    )
    draft_text = (
        generated["text"]
        if model.name != "mock-model"
        else (
            "雨水把广场的钟声压得很低。林乔抬头时，停用三年的钟楼忽然响了一下。"
            "档案表显示维护员早已离职，但新登记的巡检号正贴在门缝里。"
            "她把纸条塞进口袋，听见第二声钟从城市另一端传来。"
        )
    )
    asset = DraftChapter(
        title="Chapter 1 draft v0",
        source=plan.id,
        tags=["draft", "v0", model.name],
        content={
            "chapter": 1,
            "text": draft_text,
            "model_output": generated,
            "retrieved_context": retrieved_context,
            "copyright_boundary": generated.get("copyright_boundary")
            or "original draft generated from chapter plan; no reference expression copied",
        },
        metadata={
            "model": model.name,
            "provider": generated.get("provider", model.name),
            **retrieval_metadata(retrieved_context),
            "run_metadata": run_metadata(
                "draft",
                plan,
                provider=generated.get("provider", model.name),
                model=generated.get("model", model.name),
            ),
        },
        references=retrieval_reference_ids(plan.id, retrieved_context),
    )
    return storage.write_asset("drafts", asset)
