"""Read-only PostgreSQL projections for governed post-chapter results."""

from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class BookFollowupProjectionQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database URL is required")
        self.database_url = database_url

    def reader_outcome(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        return self._require(
            "authority_reader_outcome_projection",
            "reader_outcome_report_asset_version",
            "reader_outcome_report",
            project_id,
            operation_id,
        )

    def longform_recap(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        return self._require(
            "authority_longform_recap_projection",
            "longform_recap_asset_version",
            "longform_recap",
            project_id,
            operation_id,
        )

    def asset(self, *, project_id: str, asset_version_id: str) -> dict[str, Any]:
        """Resolve one immutable input with content and project ownership."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash,
                       version.content, asset.asset_type
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=%s
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_FOLLOWUP_INPUT_ASSET_MISSING",
                "governed follow-up input AssetVersion does not exist",
            )
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
            "content": dict(row[2] or {}),
            "asset_type": str(row[3]),
        }

    def reader_recap_evidence(
        self,
        *,
        project_id: str,
        book_run_id: str,
        through_chapter: int,
        current_report_asset_version_id: str,
    ) -> dict[str, Any]:
        """Load the complete accepted Reader sequence for a recap boundary.

        Every accepted chapter through the boundary must have a successful
        Reader report and state transition. Missing sidecar evidence fails
        closed instead of being represented by invented stable defaults.
        """

        if through_chapter <= 0 or not current_report_asset_version_id:
            raise ValueError("Reader recap evidence boundary is invalid")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.chapter_number,
                       operation.status,
                       report_binding.asset_version_id,
                       report_binding.content_hash,
                       report_version.content,
                       state_binding.asset_version_id,
                       state_binding.content_hash,
                       state_version.content,
                       acceptance.chapter_outcome_asset_version_id,
                       outcome_version.content_hash
                FROM authority_book_chapter_acceptance AS acceptance
                LEFT JOIN authority_book_followup_operation AS link
                  ON link.chapter_request_id=acceptance.chapter_request_id
                 AND link.followup_type='READER_OUTCOME'
                LEFT JOIN authority_operation AS operation
                  ON operation.operation_id=link.operation_id
                LEFT JOIN authority_operation_output_asset AS report_binding
                  ON report_binding.operation_id=operation.operation_id
                 AND report_binding.output_key='reader_outcome.report'
                LEFT JOIN authority_asset_version AS report_version
                  ON report_version.asset_version_id=report_binding.asset_version_id
                LEFT JOIN authority_operation_output_asset AS state_binding
                  ON state_binding.operation_id=operation.operation_id
                 AND state_binding.output_key='reader_outcome.state_transition'
                LEFT JOIN authority_asset_version AS state_version
                  ON state_version.asset_version_id=state_binding.asset_version_id
                JOIN authority_asset_version AS outcome_version
                  ON outcome_version.asset_version_id=
                     acceptance.chapter_outcome_asset_version_id
                WHERE acceptance.project_id=%s
                  AND acceptance.book_run_id=%s
                  AND acceptance.chapter_number <= %s
                ORDER BY acceptance.chapter_number
                """,
                [project_id, book_run_id, through_chapter],
            )
            rows = uow.cursor.fetchall()
        if not rows or int(rows[-1][0]) != through_chapter:
            raise KernelError(
                "BOOK_FOLLOWUP_READER_HISTORY_INCOMPLETE",
                "accepted Reader history does not reach the recap boundary",
            )
        incomplete = [
            int(row[0])
            for row in rows
            if str(row[1] or "") != "SUCCEEDED"
            or not row[2]
            or row[4] is None
            or not row[5]
            or row[7] is None
        ]
        if incomplete:
            raise KernelError(
                "BOOK_FOLLOWUP_READER_HISTORY_INCOMPLETE",
                "accepted Reader history is missing successful evidence for "
                + ", ".join(str(item) for item in incomplete),
            )

        history: list[dict[str, Any]] = []
        source_assets: list[dict[str, str]] = []
        previous_state: dict[str, Any] | None = None
        for row in rows:
            chapter_number = int(row[0])
            report = dict(row[4] or {})
            transition = dict(row[7] or {})
            state = dict(
                transition.get("reader_state") or report.get("reader_state") or {}
            )
            trend = _reader_state_trend(previous_state, state)
            history.append(
                {
                    "chapter_number": chapter_number,
                    "report_asset_version_id": str(row[2]),
                    "state_asset_version_id": str(row[5]),
                    "chapter_outcome_asset_version_id": str(row[8]),
                    "reader_state": state,
                    **trend,
                }
            )
            source_assets.extend(
                (
                    {
                        "asset_version_id": str(row[2]),
                        "content_hash": str(row[3]),
                    },
                    {
                        "asset_version_id": str(row[5]),
                        "content_hash": str(row[6]),
                    },
                    {
                        "asset_version_id": str(row[8]),
                        "content_hash": str(row[9]),
                    },
                )
            )
            previous_state = state

        current = history[-1]
        if current["report_asset_version_id"] != current_report_asset_version_id:
            raise KernelError(
                "BOOK_FOLLOWUP_READER_HEAD_MISMATCH",
                "Reader report does not match the accepted recap boundary",
            )
        current_report = dict(rows[-1][4] or {})
        snapshot = dict(current_report.get("reader_judge_execution_snapshot") or {})
        qualification = self._qualification_evidence(
            project_id=project_id,
            decision_id=str(snapshot.get("qualification_decision_id") or ""),
            fallback_status=str(
                current_report.get("judge_qualification_status") or "SHADOW"
            ),
            fallback_confidence=float(current_report.get("confidence") or 0.0),
            observed_sample_size=len(history),
        )
        drift = self._latest_drift(
            project_id=project_id,
            judge_version_id=str(snapshot.get("judge_version_id") or ""),
        )
        disagreement = dict(current_report.get("disagreement") or {})
        position = dict(current_report.get("position_sensitivity") or {})
        ood_status = str(current_report.get("ood_status") or "NOT_EVALUATED")
        latest_window = history[-3:]
        direction = (
            "DECLINING"
            if len(latest_window) == 3
            and all(bool(item["declining"]) for item in latest_window)
            else "STABLE"
        )
        return {
            "contract_version": "reader-longitudinal-evidence-v1",
            "evidence_class": "READER_PROXY_ADVISORY",
            "observed_through_chapter": through_chapter,
            "current_reader_state": dict(current["reader_state"]),
            "current_state_asset_version_id": current["state_asset_version_id"],
            "chapter_outcome_versions": [
                str(item["chapter_outcome_asset_version_id"]) for item in history
            ],
            "source_assets": _deduplicate_asset_refs(source_assets),
            "recent_reports": history,
            "trend": {
                "direction": direction,
                "declining": direction == "DECLINING",
                "window_chapters": [
                    int(item["chapter_number"]) for item in latest_window
                ],
                "lexical_similarity_used": False,
            },
            "qualification": {
                **qualification,
                "disagreement": _diagnostic_risk(
                    disagreement.get("status"),
                    safe={"AGREED", "NO_DISAGREEMENT", "PASS", "PASSED"},
                ),
                "position_bias": _diagnostic_risk(
                    position.get("status"),
                    safe={"STABLE", "NO_BIAS", "PASS", "PASSED"},
                ),
                "ood": _diagnostic_risk(
                    ood_status,
                    safe={"IN_DISTRIBUTION", "NOT_OOD", "PASS", "PASSED"},
                ),
                "drift_detected": bool(drift),
                "recent_reports": history,
                "last_adjustment_chapter": self._last_reader_adjustment_chapter(
                    project_id=project_id,
                    book_id=str(current_report.get("book_id") or ""),
                ),
                "diagnostic_evidence": {
                    "disagreement": disagreement,
                    "position_sensitivity": position,
                    "ood_status": ood_status,
                    "drift": drift,
                },
            },
        }

    def _qualification_evidence(
        self,
        *,
        project_id: str,
        decision_id: str,
        fallback_status: str,
        fallback_confidence: float,
        observed_sample_size: int,
    ) -> dict[str, Any]:
        if not decision_id:
            return {
                "qualification_status": fallback_status,
                "decision_id": "",
                "evidence_level": "UNAVAILABLE",
                "sample_size": 0,
                "confidence": fallback_confidence,
                "observed_proxy_report_count": observed_sample_size,
            }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT qualification_status, evidence_level, evidence,
                       COALESCE(calibration_profile_id, '')
                FROM authority_reader_judge_qualification_decision
                WHERE project_id=%s AND decision_id=%s
                """,
                [project_id, decision_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_FOLLOWUP_READER_QUALIFICATION_MISSING",
                "Reader report references a missing qualification decision",
            )
        evidence = dict(row[2] or {})
        return {
            "qualification_status": str(row[0]),
            "decision_id": decision_id,
            "evidence_level": str(row[1]),
            "calibration_profile_id": str(row[3]),
            "sample_size": int(evidence.get("sample_size") or 0),
            "confidence": float(evidence.get("confidence") or 0.0),
            "observed_proxy_report_count": observed_sample_size,
            "qualification_evidence": evidence,
        }

    def _latest_drift(
        self, *, project_id: str, judge_version_id: str
    ) -> dict[str, Any]:
        if not judge_version_id:
            return {}
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT drift_id, severity, drift_type, evidence, downgrade_mode,
                       created_at
                FROM authority_reader_judge_drift
                WHERE project_id=%s AND judge_version_id=%s
                ORDER BY created_at DESC, drift_id DESC LIMIT 1
                """,
                [project_id, judge_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return {}
        return {
            "drift_id": str(row[0]),
            "severity": str(row[1]),
            "drift_type": str(row[2]),
            "evidence": dict(row[3] or {}),
            "downgrade_mode": str(row[4]),
            "created_at": str(row[5]),
        }

    def _last_reader_adjustment_chapter(
        self, *, project_id: str, book_id: str
    ) -> int | None:
        if not book_id:
            return None
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source.content->>'chapter_number'
                FROM authority_plan_change_proposal AS proposal
                JOIN authority_asset_version AS source
                  ON source.asset_version_id=proposal.source_evidence_version_id
                WHERE proposal.project_id=%s AND proposal.book_id=%s
                  AND proposal.source_type='READER_OUTCOME'
                  AND proposal.status='ACTIVE'
                  AND source.content ? 'chapter_number'
                ORDER BY proposal.updated_at DESC, proposal.proposal_id DESC
                LIMIT 1
                """,
                [project_id, book_id],
            )
            row = uow.cursor.fetchone()
        return int(row[0]) if row is not None and row[0] is not None else None

    def _require(
        self,
        view: str,
        version_column: str,
        content_column: str,
        project_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        # View and column names are private constants, never request data.
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT book_run_id, chapter_request_id, operation_id, project_id,
                       status, {version_column}, {content_column}, updated_at
                FROM {view}
                WHERE project_id=%s AND operation_id=%s
                """,
                [project_id, operation_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_FOLLOWUP_PROJECTION_NOT_FOUND",
                "governed follow-up projection does not exist",
            )
        return {
            "book_run_id": row[0],
            "chapter_request_id": row[1],
            "operation_id": row[2],
            "project_id": row[3],
            "status": row[4],
            "asset_version_id": row[5] or "",
            "content": dict(row[6] or {}),
            "updated_at": str(row[7]),
            "authoritative": False,
            "rebuildable": True,
        }


_POSITIVE_READER_DIMENSIONS = frozenset(
    {
        "continue_intent",
        "curiosity",
        "satisfaction",
        "trust",
        "character_attachment",
        "antagonist_pressure",
        "promise_expectation",
        "payoff_satisfaction",
    }
)
_ADVERSE_READER_DIMENSIONS = frozenset({"confusion", "drop_risk", "repetition_fatigue"})


def _reader_state_trend(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    material_delta: float = 0.05,
) -> dict[str, Any]:
    if previous is None:
        return {
            "declining": False,
            "declining_dimensions": [],
            "dimension_deltas": {},
            "comparison_status": "NO_PREVIOUS_ACCEPTED_READER_STATE",
        }
    deltas: dict[str, float] = {}
    declining: list[str] = []
    for dimension in sorted(_POSITIVE_READER_DIMENSIONS | _ADVERSE_READER_DIMENSIONS):
        if dimension not in previous or dimension not in current:
            continue
        delta = round(float(current[dimension]) - float(previous[dimension]), 6)
        deltas[dimension] = delta
        if (dimension in _POSITIVE_READER_DIMENSIONS and delta <= -material_delta) or (
            dimension in _ADVERSE_READER_DIMENSIONS and delta >= material_delta
        ):
            declining.append(dimension)
    return {
        "declining": bool(declining),
        "declining_dimensions": declining,
        "dimension_deltas": deltas,
        "comparison_status": "COMPARED_TO_PREVIOUS_ACCEPTED_READER_STATE",
    }


def _diagnostic_risk(value: Any, *, safe: set[str]) -> bool:
    return str(value or "NOT_MEASURED").upper() not in safe


def _deduplicate_asset_refs(
    assets: list[dict[str, str]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in assets:
        version_id = str(item["asset_version_id"])
        if version_id in seen:
            continue
        seen.add(version_id)
        result.append(
            {
                "asset_version_id": version_id,
                "content_hash": str(item["content_hash"]),
            }
        )
    return result


__all__ = ["BookFollowupProjectionQuery"]
