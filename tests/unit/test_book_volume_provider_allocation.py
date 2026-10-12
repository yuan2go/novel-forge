import pytest

from novel_forge.modules.chapter_authority.provider_output_contracts import (
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.domain import PlanContractType
from novel_forge.modules.story_planning_runtime.domain import (
    canonical_book_volume_allocation,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_provider_output_schema,
)


def test_current_provider_preserves_unequal_native_six_volume_allocation():
    ranges = [[1, 100], [101, 220], [221, 340], [341, 460], [461, 550], [551, 600]]
    full_schema = planning_provider_output_schema(
        PlanContractType.BOOK,
        work_requirements=True,
        aligned_methods=True,
        serialization_contract=True,
        typed_volume_allocation=True,
    )
    schema = {
        "$schema": full_schema["$schema"],
        **full_schema["properties"]["volume_skeleton"],
    }
    skeleton = [
        {"volume": ordinal, "function": "完成本阶段故事目标", "chapter_range": bounds}
        for ordinal, bounds in enumerate(ranges, 1)
    ]
    validate_chapter_provider_output_against_schema("planning", schema, skeleton)
    allocated, target = canonical_book_volume_allocation(
        {
            "volume_skeleton": skeleton,
            "length_strategy": {"target_chapters": 600},
        }
    )
    assert [v["chapter_range"] for v in allocated] == ranges
    assert target == 600


def test_current_provider_requires_ranges_while_historical_schema_remains_readable():
    skeleton = [{"volume": 1, "function": "完成本阶段故事目标"}]
    historical_full = planning_provider_output_schema(PlanContractType.BOOK, serialization_contract=True)
    current_full = planning_provider_output_schema(
        PlanContractType.BOOK,
        serialization_contract=True,
        typed_volume_allocation=True,
    )
    historical = {
        "$schema": historical_full["$schema"],
        **historical_full["properties"]["volume_skeleton"],
    }
    current = {
        "$schema": current_full["$schema"],
        **current_full["properties"]["volume_skeleton"],
    }
    validate_chapter_provider_output_against_schema("planning", historical, skeleton)
    with pytest.raises(KernelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_chapter_provider_output_against_schema("planning", current, skeleton)
