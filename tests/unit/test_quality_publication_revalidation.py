from copy import deepcopy

import pytest

from novel_forge.modules.chapter_quality_authority.revalidation import (
    corrected_publication_evidence,
)
from novel_forge.modules.command_kernel.errors import KernelError


class Cursor:
    def __init__(self, admission):
        self.admission = admission
        self.result = None
        self.commands = []
        self.old = {
            name: {
                "asset_version_id": "old-" + name,
                "content_hash": "old-hash-" + name,
            }
            for name in (
                "quality_score_report",
                "best_draft_candidate",
                "re_review_report",
                "canon_patch",
            )
        }
        self.new = {
            name: {
                "asset_version_id": "new-" + name,
                "content_hash": "new-hash-" + name,
            }
            for name in self.old
        }
        self.source = {
            "definition_name": "chapter.publishing.prepare_release",
            "definition_version": "3.9.13",
            "operation_id": "publish",
            "root_operation_id": "root",
            "project_id": "project",
            "status": "FAILED_RETRYABLE",
            "input_asset_snapshot": list(self.old.values()),
        }

    def execute(self, query, params):
        self.commands.append(query)
        if "SELECT to_jsonb(o)" in query:
            self.result = (
                {
                    "operation_id": "quality-next",
                    "input_asset_snapshot": list(self.new.values()),
                },
            )
        elif "v.content_hash,v.content" in query:
            self.result = (
                "new-quality_score_report",
                "new-hash-quality_score_report",
                {"internal_admission": self.admission},
            )
        elif "SELECT EXISTS" in query:
            self.result = (False,)
        elif "SELECT status,result" in query:
            self.result = [
                (
                    "FAILED_RETRYABLE",
                    {"error_code": "VALIDATION_QUALITY_ADMISSION_REQUIRED"},
                )
            ]
        elif "a.asset_type,v.content" in query:
            kind = params[0].removeprefix("old-")
            self.result = (
                kind,
                {"internal_admission": {"status": "BLOCKED"}},
                "old-hash-" + kind,
            )
        elif "SELECT a.asset_type" in query:
            self.result = (params[0].removeprefix("new-"),)
        elif "SELECT operation_id FROM" in query:
            name = params[0]
            self.result = (
                "quality-next"
                if name == "new-quality_score_report"
                else "operation:" + name,
            )
        else:
            raise AssertionError(query)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


def test_publication_successor_binds_all_latest_assets_without_mutating_source():
    cursor = Cursor(
        {"status": "INTERNAL_ADMITTED", "strict_certification_eligible": False}
    )
    original = deepcopy(cursor.source)
    proof = corrected_publication_evidence(cursor, cursor.source)
    assert cursor.source == original
    assert proof["input_snapshot"] == list(cursor.new.values())
    assert len(proof["input_replacements"]) == 4
    assert proof["target_version"] == "3.9.13"
    assert all(query.strip().startswith("SELECT") for query in cursor.commands)


@pytest.mark.parametrize(
    "admission",
    [
        {"status": "BLOCKED", "strict_certification_eligible": False},
        {"status": "INTERNAL_ADMITTED", "strict_certification_eligible": True},
    ],
)
def test_blocked_or_strict_disposition_cannot_authorize_internal_rebinding(admission):
    cursor = Cursor(admission)
    with pytest.raises(KernelError, match="QUALITY_REVALIDATION_NOT_READY"):
        corrected_publication_evidence(cursor, cursor.source)
