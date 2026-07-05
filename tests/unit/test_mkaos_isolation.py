from pathlib import Path
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing import create_release_package
from novel_forge.modules.chapter_plan import service as chapter_plan_service
from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.mkaos import (
    build_knowledge_pack,
    create_knowledge_card,
    create_usage_binding,
    import_source_document,
    pack_prompt_preview,
    record_usage_event,
)
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import AgentRun, ChapterPlan, DraftChapter, Outline, ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, generation_context_policy


RAW_SENTINEL = "RAW_MKAOS_SOURCE_SENTINEL_DO_NOT_LEAK_7F3C"


class MkaosIsolationTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

    def test_prose_pack_prompt_preview_and_chapter_prompt_do_not_leak_source_chunk_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Leakage Project")
            setup = _mkaos_fixture(storage, project_id=project_id, workspace_path=workspace_ref, flows=["prose", "chapter_outline"])

            prose_pack = build_knowledge_pack(storage, {"flow": "prose", "project_id": project_id, "chapter_id": "1"})
            preview = pack_prompt_preview(storage, prose_pack["asset"]["id"])

            _assert_no_source_raw_text(self, prose_pack["asset"]["content"])
            self.assertNotIn(RAW_SENTINEL, preview["preview"])
            self.assertNotIn("raw_text", preview["preview"])

            outline_path = storage.write_asset(
                "outlines",
                Outline(
                    title="Leakage outline",
                    content={"acts": [{"act": 1, "goal": "use abstract institutional pressure", "chapters": [{"chapter": 1, "promise": "case opens", "hook": "sealed deed"}]}]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref, setup["knowledge_id"]],
                ),
            )
            chapter_plan_path = chapter_plan_service.generate_chapter_plan(
                storage,
                str(outline_path.relative_to(storage.root)),
                workspace_path=workspace_ref,
                chapter=1,
            )
            chapter_plan = storage.read_asset(chapter_plan_path)
            _assert_no_source_raw_text(self, chapter_plan.content.get("mkaos_knowledge_pack", {}))
            self.assertNotIn(RAW_SENTINEL, _json(chapter_plan.content))

    def test_publish_package_and_recap_context_seam_do_not_leak_source_chunk_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "Publish Recap Leakage Project")
            setup = _mkaos_fixture(storage, project_id=project_id, workspace_path=workspace_ref, flows=["prose"])
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 1",
                    content={"chapter": 1, "text": "原创章节文本，只使用抽象知识造成行动成本和章节钩子。"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref, setup["knowledge_id"]],
                ),
            )

            package_path = create_release_package(
                storage,
                draft_path,
                workspace_path=workspace_ref,
                channel="local_serial",
                human_override=True,
            )
            release_package = storage.read_asset(package_path)
            self.assertEqual(release_package.type, "release_package")
            self.assertNotIn(RAW_SENTINEL, _json(release_package.content))
            self.assertFalse(_contains_key(release_package.content, "raw_text"))

            context_plan = create_context_build_plan(
                storage,
                draft_path,
                query="recap institutional pressure source isolation",
                top_k=8,
                token_budget=2000,
                context_profile="recap",
                workspace_path=workspace_ref,
            )
            recap_bundle = create_context_bundle(
                storage,
                context_plan["path"],
                selected_asset_paths=[setup["source_chunk_path"]],
                priority_asset_paths=[setup["source_chunk_path"]],
            )
            content = recap_bundle["asset"]["content"]
            self.assertNotIn(RAW_SENTINEL, content.get("actual_context", ""))
            self.assertFalse(any(item.get("path") == setup["source_chunk_path"] for item in content.get("selected_assets", [])))
            self.assertTrue(
                any(item.get("path") == setup["source_chunk_path"] and "blocked_asset_type" in item.get("signals", []) for item in content.get("policy_rejections", [])),
                content.get("policy_rejections", []),
            )

    def test_generation_rag_rejects_mkaos_runtime_assets_and_source_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_ref, project_id = _workspace(storage, "RAG Isolation Project")
            setup = _mkaos_fixture(storage, project_id=project_id, workspace_path=workspace_ref, flows=["prose"])
            pack = build_knowledge_pack(storage, {"flow": "prose", "project_id": project_id, "chapter_id": "1"})
            usage = record_usage_event(
                storage,
                {
                    "knowledge_id": setup["knowledge_id"],
                    "knowledge_pack_id": pack["asset"]["id"],
                    "project_id": project_id,
                    "flow": "prose",
                    "target_artifact_id": "draft-1",
                },
            )
            agent_run_path = storage.write_asset(
                "runs",
                AgentRun(
                    title="MKAOS runtime run",
                    content={"status": "succeeded", "prompt": RAW_SENTINEL},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "use_in_generation_rag": False},
                    references=[workspace_ref, pack["asset"]["id"]],
                ),
            )
            target_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="RAG target",
                    content={"chapter": 1, "objective": "prove RAG isolation", "beats": ["inspect runtime assets"], "hook": "gate stays clean"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            runtime_assets = [
                storage.read_json(storage.root / setup["source_chunk_path"]),
                pack["asset"],
                usage["events"][0]["asset"],
                storage.read_asset(agent_run_path).to_dict(),
            ]
            for asset in runtime_assets:
                policy = generation_context_policy(asset)
                self.assertFalse(policy["eligible"], asset.get("type"))

            context = build_rag_context(
                storage,
                storage.read_asset(target_path),
                input_path=target_path,
                query=f"{RAW_SENTINEL} mkaos runtime pack usage source chunk",
                top_k=12,
                backend="local",
            )
            selected_types = {item.get("type") for item in context["items"]}
            self.assertFalse({"source_chunk", "knowledge_pack", "knowledge_usage_event", "agent_run"} & selected_types)
            filtered_types = {item.get("type") for item in context["copyright_filter"]["filtered_assets"]}
            self.assertTrue({"source_chunk", "knowledge_pack", "knowledge_usage_event", "agent_run"}.issubset(filtered_types), context["copyright_filter"])

    def test_mkaos_pack_budget_and_project_scoped_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _workspace(storage, "Budget Project", project_id="p-budget")
            _workspace(storage, "Other Project", project_id="p-other")
            for index in range(5):
                setup = _mkaos_fixture(
                    storage,
                    project_id="p-budget",
                    workspace_path="",
                    flows=["prose"],
                    concept=f"Budget knowledge {index}",
                    raw_suffix=str(index),
                )
                create_usage_binding(
                    storage,
                    setup["knowledge_id"],
                    {"flow": "outline", "usage_type": "required", "input_role": "required", "priority": index + 1},
                )
            other = _mkaos_fixture(storage, project_id="p-other", workspace_path="", flows=["outline"], concept="Other project knowledge")

            prose_pack = build_knowledge_pack(storage, {"flow": "prose", "project_id": "p-budget", "knowledge_budget": {"max_core_knowledge": 3}})
            self.assertLessEqual(len(prose_pack["asset"]["content"]["optional_knowledge"]), 3)
            self.assertNotIn(RAW_SENTINEL, _json(prose_pack["asset"]["content"]))

            budget_outline = build_knowledge_pack(storage, {"flow": "outline", "project_id": "p-budget"})
            budget_knowledge_ids = {item["knowledge_id"] for item in budget_outline["asset"]["content"]["pack_items"]}
            self.assertNotIn(other["knowledge_id"], budget_knowledge_ids)
            for reference in budget_outline["asset"].get("references", []):
                if reference == other["knowledge_id"]:
                    self.fail("cross-project knowledge id entered MKAOS pack lineage")


def _workspace(storage: LocalStorage, title: str, project_id: str | None = None) -> tuple[str, str]:
    if project_id:
        path = storage.write_asset(
            "workspaces",
            ProjectWorkspaceState(
                title=title,
                content={"project_id": project_id, "memory": {}, "chapter_states": [], "continuity_threads": {}, "open_issues": [], "project_config": {}},
            ),
        )
    else:
        path = init_workspace(storage, title)
    asset = storage.read_asset(path)
    return str(path.relative_to(storage.root)), str(asset.content["project_id"])


def _mkaos_fixture(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str,
    flows: list[str],
    concept: str = "土地兼并",
    raw_suffix: str = "",
) -> dict[str, str]:
    source = import_source_document(
        storage,
        {
            "title": f"{concept} source {raw_suffix}",
            "text": f"{RAW_SENTINEL}{raw_suffix} 原始资料句子只可作为证据层保存，不得进入生成上下文。\n\n制度压力导致一方获利、一方受损。",
            "project_id": project_id,
            "workspace_path": workspace_path,
        },
    )
    chunk = source["chunks"][0]
    knowledge = create_knowledge_card(
        storage,
        {
            "concept_name": concept,
            "discipline": "历史制度",
            "knowledge_type": "conflict_mechanism",
            "core_explanation": "制度性资源集中会改变行动成本，并迫使角色在利益压力下选择。",
            "source_chunk_ids": [chunk["id"]],
            "project_id": project_id,
            "workspace_path": workspace_path,
            "quality_score": 0.9,
            "weight": 1.0,
        },
    )
    for flow in flows:
        create_usage_binding(
            storage,
            knowledge["asset"]["id"],
            {
                "flow": flow,
                "usage_type": "optional" if flow == "prose" else "required",
                "input_role": "optional" if flow == "prose" else "required",
                "constraint_text": "只使用抽象机制，不使用原始资料表达。",
                "priority": 10,
            },
        )
    return {
        "source_id": source["asset"]["id"],
        "source_path": source["path"],
        "source_chunk_id": chunk["id"],
        "source_chunk_path": chunk["path"],
        "knowledge_id": knowledge["asset"]["id"],
        "knowledge_path": knowledge["path"],
    }


def _assert_no_source_raw_text(test_case: unittest.TestCase, value) -> None:
    test_case.assertNotIn(RAW_SENTINEL, _json(value))
    test_case.assertFalse(_contains_key(value, "raw_text"), _json(value))


def _contains_key(value, key: str) -> bool:
    if isinstance(value, dict):
        return any(str(item_key) == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
