from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError


def require_next_pass(*, completed_passes, candidate_hashes, control):
    if completed_passes >= control["maximum_passes"]:
        raise KernelError(
            "QUALITY_CORRECTION_CONTROL_EXHAUSTED",
            "The latest candidate remains blocked; preserve the current checkpoint",
        )
    unchanged = 0
    for previous, current in zip(
        reversed(candidate_hashes[:-1]), reversed(candidate_hashes[1:])
    ):
        if previous != current:
            break
        unchanged += 1
    if unchanged >= control["maximum_unchanged_candidates"]:
        raise KernelError(
            "QUALITY_CORRECTION_NO_PROGRESS",
            "Repeated correction selected unchanged blocked prose; preserve the current checkpoint",
        )
