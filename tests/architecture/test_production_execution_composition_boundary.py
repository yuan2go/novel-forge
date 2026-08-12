from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = ROOT / "src/novel_forge/api/authority_dependencies.py"
CHAPTER_APPLICATION = (
    ROOT / "src/novel_forge/modules/chapter_authority/application.py"
)
COMPOSITION = (
    ROOT / "src/novel_forge/infrastructure/production_execution_composition.py"
)


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"missing function {name}")


def test_shared_production_execution_has_one_explicit_owner() -> None:
    source = COMPOSITION.read_text(encoding="utf-8")
    assert "class ProductionExecutionComposition" in source
    assert "gateway: ProductionExecutionGatewayExternalEffectAdapter" in source
    assert "object_store: ExternalEffectAdapter" in source
    assert "shared_budget_caps: Mapping[str, str]" in source


def test_peer_consumers_do_not_borrow_chapter_application_internals() -> None:
    for builder in (
        "build_agent_authority_scheduler",
        "build_source_import_application",
        "build_book_authority_application",
        "build_book_production_composition",
        "build_reader_outcome_model_port",
        "build_story_planning_generation_application",
    ):
        source = _function_source(DEPENDENCIES, builder)
        assert "ProductionExecutionComposition" in source
        assert ".model_port" not in source
        assert ".object_store_adapter" not in source
        assert ".external_effect_adapters" not in source or builder.startswith(
            "build_book_"
        )


def test_chapter_application_exposes_domain_commands_not_shared_infrastructure() -> None:
    source = CHAPTER_APPLICATION.read_text(encoding="utf-8")
    assert "self.model_port" not in source
    assert "self.object_store_adapter" not in source
    assert "def external_effect_adapters" not in source
    assert "self._model_port" in source
    assert "self._object_store_adapter" in source


def test_domain_modules_do_not_import_the_infrastructure_composition() -> None:
    violations: list[str] = []
    modules = ROOT / "src/novel_forge/modules"
    for path in modules.rglob("*.py"):
        if "novel_forge.infrastructure.production_execution_composition" in path.read_text(
            encoding="utf-8"
        ):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []
