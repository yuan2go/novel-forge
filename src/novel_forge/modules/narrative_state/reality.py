from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
import re
import hashlib
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


REALITY_CONTRACT = "narrative-reality.v1"


def narrative_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class NarrativeRealityRevision:
    project_id: str
    book_id: str
    book_run_id: str
    chapter_number: int
    acceptance_id: str
    outcome_version_id: str
    state_version_id: str
    canon_version_id: str
    projection_set_id: str
    source_digest: str
    parent_revision_id: str = ""

    def __post_init__(self) -> None:
        if (
            type(self.chapter_number) is not int
            or self.chapter_number <= 0
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_digest)
            or (
                self.parent_revision_id
                and not re.fullmatch(
                    r"reality:sha256:[0-9a-f]{64}", self.parent_revision_id
                )
            )
            or any(
                not isinstance(value, str) or not value.strip()
                for key, value in asdict(self).items()
                if key not in {"parent_revision_id", "chapter_number"}
            )
            or (self.chapter_number == 1) != (not self.parent_revision_id)
        ):
            raise KernelError(
                "NARRATIVE_REALITY_LINEAGE_INVALID",
                "Reality requires one sequential accepted frontier and exact source versions",
            )

    @property
    def revision_id(self) -> str:
        values = [REALITY_CONTRACT, *[str(value) for value in asdict(self).values()]]
        framed = "".join(f"{len(value.encode('utf-8'))}:{value}" for value in values)
        return "reality:sha256:" + hashlib.sha256(framed.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": REALITY_CONTRACT,
            "revision_id": self.revision_id,
            **asdict(self),
        }


def reality_source_digest(hashes: Mapping[str, str]) -> str:
    framed = "".join(
        f"{len(value.encode('utf-8'))}:{value}" for _, value in sorted(hashes.items())
    )
    return "sha256:" + hashlib.sha256(framed.encode()).hexdigest()


def project_reality(
    revision: NarrativeRealityRevision,
    state: Mapping[str, Any],
    canon: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        state.get("project_id") != revision.project_id
        or state.get("book_id") != revision.book_id
        or state.get("based_on_chapter_outcome_asset_version_id")
        != revision.outcome_version_id
        or state.get("accepted_through_chapter") != revision.chapter_number
    ):
        raise KernelError(
            "NARRATIVE_REALITY_SOURCE_MISMATCH",
            "Reality can only project the state derived from its exact accepted outcome",
        )
    return {
        **revision.to_dict(),
        "authority": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
        "current_state": deepcopy(state.get("current_state") or {}),
        "canon": deepcopy(dict(canon)),
        "projection_policy": "narrative-state-reducer-v2",
        "fact_mutation_allowed": False,
    }
