import pytest

from novel_forge.modules.chapter_authority.quality_correction_control import (
    require_next_pass,
)
from novel_forge.modules.production_execution.execution_template import (
    validate_templates,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_creative_execution_template import template


CONTROL = {
    "version": "quality-correction-control.v1",
    "maximum_passes": 3,
    "maximum_unchanged_candidates": 2,
}


def test_improving_blocked_candidate_can_continue_but_control_exhaustion_cannot_be_completion():
    require_next_pass(
        completed_passes=1, candidate_hashes=["initial", "changed"], control=CONTROL
    )
    require_next_pass(
        completed_passes=2,
        candidate_hashes=["initial", "changed", "changed"],
        control=CONTROL,
    )
    with pytest.raises(KernelError, match="QUALITY_CORRECTION_CONTROL_EXHAUSTED"):
        require_next_pass(
            completed_passes=3, candidate_hashes=["a", "b", "c", "d"], control=CONTROL
        )


def test_repeated_unchanged_selection_stops_before_more_provider_calls():
    with pytest.raises(KernelError, match="QUALITY_CORRECTION_NO_PROGRESS"):
        require_next_pass(
            completed_passes=2,
            candidate_hashes=["same", "same", "same"],
            control=CONTROL,
        )


def test_new_quality_controls_are_explicit_and_do_not_change_strict_or_historical_templates():
    fields = dict(
        version="creative-execution-template.v10",
        world_future_preparation="DISABLED",
        repair_routing={
            "version": "native-repair-routing.v2",
            "max_same_route_repairs": 2,
        },
        canon_validation_contract="grounded-canon-validation.v2",
        quality_corrections=CONTROL,
    )
    validate_templates({"execution_templates": [template(**fields)]})
    fields["quality_corrections"] = None
    with pytest.raises(KernelError, match="EXECUTION_TEMPLATE_QUALITY_CONTROL_INVALID"):
        validate_templates({"execution_templates": [template(**fields)]})
    with pytest.raises(KernelError, match="EXECUTION_TEMPLATE_QUALITY_CONTROL_INVALID"):
        validate_templates(
            {"execution_templates": [template(quality_corrections=CONTROL)]}
        )
    with pytest.raises(KernelError, match="EXECUTION_TEMPLATE_QUALITY_CONTROL_INVALID"):
        validate_templates(
            {
                "execution_templates": [
                    template(
                        mode="STRICT_PRODUCTION",
                        require_literary_qualification=True,
                        quality_corrections=CONTROL,
                    )
                ]
            }
        )
