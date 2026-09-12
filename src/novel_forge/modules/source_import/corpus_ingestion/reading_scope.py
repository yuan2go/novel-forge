from __future__ import annotations

from typing import Literal
from pydantic import Field, field_validator
from novel_forge.modules.source_authority.corpus import (
    CorpusContract,
    Text,
    corpus_hash,
)
from novel_forge.modules.command_kernel.errors import KernelError


class ChapterReadingScope(CorpusContract):
    version: Literal["chapter-reading.v1"] = "chapter-reading.v1"
    processing_id: Text
    first_unit_version_id: Text
    last_unit_version_id: Text
    context_before: int = Field(default=0, ge=0, le=2)
    context_after: int = Field(default=0, ge=0, le=2)
    max_chapters: int = Field(default=10, ge=1, le=20)
    max_input_bytes_per_chapter: int = Field(default=48000, ge=256, le=128000)
    max_total_input_bytes: int = Field(default=480000, ge=256, le=1000000)
    max_repairs: int = Field(default=1, ge=0, le=2)
    dimensions: tuple[
        Literal[
            "causal_constraints",
            "character_choice_cost",
            "information_gap",
            "foreshadowing_payoff",
            "chapter_hook",
            "point_of_view",
            "conflict",
            "emotion_curve",
            "world_rules",
            "core_concept",
            "credibility_rule",
            "misuse_risk",
            "review_check",
            "assumption",
            "source_reliability",
        ],
        ...,
    ] = Field(
        default=("causal_constraints", "character_choice_cost", "information_gap"),
        min_length=1,
        max_length=15,
    )

    @field_validator("dimensions")
    @classmethod
    def unique_dimensions(cls, value: tuple) -> tuple:
        if len(set(value)) != len(value):
            raise ValueError("reading dimensions must be unique")
        return value


def freeze_reading_scope(
    repository,
    project: str,
    selected: list[dict],
    scopes: tuple[ChapterReadingScope, ...],
) -> dict:
    if len({s.processing_id for s in scopes}) != len(scopes):
        raise KernelError(
            "READING_SCOPE_DUPLICATE", "one frozen range per selected member"
        )
    if {s.processing_id for s in scopes} != {m["processing_id"] for m in selected}:
        raise KernelError(
            "READING_SCOPE_MEMBER_MISMATCH",
            "every selected member requires an exact range",
        )
    sources = repository.catalog_processings(project, [s.processing_id for s in scopes])
    result = {}
    for scope in scopes:
        source = sources.get(scope.processing_id)
        if source is None:
            raise KernelError(
                "READING_PROCESSING_MISSING", "exact Processing is unavailable"
            )
        units = repository.catalog_reading_units(
            project, source["source_work_asset_version_id"], scope.model_dump()
        )
        excluded = [
            u for u in units if u["kind"] == "volume" and u["status"] == "AVAILABLE"
        ]
        units = [u for u in units if u not in excluded]
        targets = [u for u in units if u["role"] == "TARGET"]
        if not targets or len(targets) > scope.max_chapters:
            raise KernelError(
                "READING_CHAPTER_BOUND", "requested range exceeds frozen chapter bound"
            )
        if any(
            u["kind"] not in {"chapter", "extra"} or u["status"] != "AVAILABLE"
            for u in units
        ):
            raise KernelError(
                "READING_STRUCTURE_UNUSABLE",
                "range contains excluded or non-body units",
            )
        if any(
            u["normalized_byte_end"] - u["normalized_byte_start"]
            > scope.max_input_bytes_per_chapter
            for u in units
        ):
            raise KernelError(
                "READING_WINDOW_TOO_LARGE",
                "split or explicitly narrow the request; no silent truncation",
            )
        if (
            sum(u["normalized_byte_end"] - u["normalized_byte_start"] for u in units)
            > scope.max_total_input_bytes
        ):
            raise KernelError(
                "READING_TOTAL_BOUND", "full selected input exceeds frozen byte bound"
            )
        chunks = repository.catalog_reading_chunks(
            project, source["source_transform_id"], units
        )
        for unit in units:
            unit["chunks"] = [
                c
                for c in chunks
                if c["source_byte_end"] > unit["normalized_byte_start"]
                and c["source_byte_start"] < unit["normalized_byte_end"]
            ]
            cursor = unit["normalized_byte_start"]
            for chunk in unit["chunks"]:
                left = max(chunk["source_byte_start"], unit["normalized_byte_start"])
                right = min(chunk["source_byte_end"], unit["normalized_byte_end"])
                if left != cursor:
                    raise KernelError(
                        "READING_CHUNK_COVERAGE_INVALID",
                        "chunk overlap or gap in exact unit",
                    )
                cursor = right
            if cursor != unit["normalized_byte_end"]:
                raise KernelError(
                    "READING_CHUNK_COVERAGE_INVALID",
                    "unit lacks complete chunk coverage",
                )
        frozen = {
            "contract": scope.model_dump(mode="json"),
            "edition_id": source["edition_id"],
            "processing_id": scope.processing_id,
            "source_work_asset_version_id": source["source_work_asset_version_id"],
            "source_transform_id": source["source_transform_id"],
            "assessment_hash": corpus_hash(source["assessment"]),
            "review_id": source["review_id"],
            "member": next(
                m for m in selected if m["processing_id"] == scope.processing_id
            ),
            "units": units,
            "excluded_structural_units": [
                {
                    "unit_version_id": u["source_unit_version_id"],
                    "reason": "VOLUME_HEADING_NOT_CHAPTER_PROSE",
                }
                for u in excluded
            ],
            "coverage_claim": "SELECTED_CONTIGUOUS_UNITS_ONLY",
            "outside_range": "NOT_READ",
            "tool_access": "DENY_FILESYSTEM_SHELL_WEB_MCP",
        }
        frozen["identity"] = corpus_hash(frozen)
        result[scope.processing_id] = frozen
    return result


def preview_reading(
    database_url,
    project,
    revision_id,
    scopes,
    principal,
    *,
    runtime=None,
    object_store_reader=None,
    inspect_codex=False,
    max_calls=0,
    max_tokens=0,
    authorization_ref="",
    intended_use="SOURCE_ANALYSIS",
    target_book_id="",
):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.storage.source_authority_repositories import (
        SourceAuthorityRepository,
    )
    from novel_forge.modules.source_authority.curation import curated_availability

    principal.require("source.authority.query", project)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(project)
        frozen = repository.catalog_current(
            "curated", project, revision_id, revision=True
        )
        if not frozen or frozen["manifest"]["state"] != "FROZEN":
            raise KernelError(
                "CURATED_CORPUS_NOT_FROZEN", "preview requires an exact frozen revision"
            )
        current = repository.catalog_current("curated", project, frozen["corpus_id"])
        if current["revision_id"] != revision_id:
            raise KernelError(
                "CURATED_REVISION_STALE",
                "preview does not silently substitute the current selection",
            )
        selected = [m for m in frozen["members"] if m["evidence"]["selected"]]
        availability = curated_availability(repository, project, selected)
        if any(not a["available"] for a in availability):
            raise KernelError("CURATED_MEMBERS_UNAVAILABLE", str(availability))
        from novel_forge.modules.source_authority.consumption import require_curated_consumption
        consumption = require_curated_consumption(repository, project, frozen, selected,
                                                   intended_use=intended_use, target_book_id=target_book_id)
        from novel_forge.modules.command_kernel.budget_runtime import (
            unresolved_cli_outcomes,
        )

        execution_blockers = unresolved_cli_outcomes(uow.cursor, project)
        plans = freeze_reading_scope(
            repository,
            project,
            selected,
            tuple(ChapterReadingScope.model_validate(s) for s in scopes),
        )
    input_checks = {"state": "NOT_INSPECTED", "model_input_state": "NOT_SENT"}
    if object_store_reader is not None:
        checked_chunks = 0
        checked_bytes = 0
        for plan in plans.values():
            chunk_ids = list(
                dict.fromkeys(
                    c["asset_version_id"]
                    for unit in plan["units"]
                    for c in unit["chunks"]
                )
            )
            with AuthorityUnitOfWork(database_url) as uow:
                rows = SourceAuthorityRepository(
                    uow.cursor
                ).catalog_reading_chunk_blobs(project, chunk_ids)
            if len(rows) != len(chunk_ids) or any(
                row["status"] != "AVAILABLE" for row in rows
            ):
                raise KernelError(
                    "READING_SOURCE_DRIFT", "selected Blob references are missing"
                )
            segments = tuple(
                {
                    "source_chunk_asset_version_id": row["asset_version_id"],
                    "content": object_store_reader.read(
                        object_key=row["actual_object_key"],
                        expected_hash=row["actual_hash"],
                        expected_size=row["actual_size"],
                    ).decode("utf-8", errors="strict"),
                }
                for row in rows
            )
            validate_reading_segments(plan["units"], segments)
            checked_chunks += len(rows)
            checked_bytes += sum(row["actual_size"] for row in rows)
        with AuthorityUnitOfWork(database_url) as uow:
            repository = SourceAuthorityRepository(uow.cursor)
            repository.corpus_authorization_lock(project)
            consumption = require_curated_consumption(repository, project, frozen, selected,
                                                       intended_use=intended_use, target_book_id=target_book_id)
            current = repository.catalog_current(
                "curated", project, frozen["corpus_id"]
            )
            if (
                current["revision_id"] != revision_id
                or any(
                    not a["available"]
                    for a in curated_availability(repository, project, selected)
                )
                or freeze_reading_scope(
                    repository,
                    project,
                    selected,
                    tuple(ChapterReadingScope.model_validate(s) for s in scopes),
                )
                != plans
            ):
                raise KernelError(
                    "READING_SOURCE_DRIFT",
                    "selection changed during input verification",
                )
        input_checks = {
            "state": "VERIFIED",
            "chunks": checked_chunks,
            "bytes": checked_bytes,
            "model_input_state": "NOT_SENT",
        }
    local_codex = None
    if inspect_codex:
        from novel_forge.modules.production_execution.codex_configuration import (
            inspect_local_codex,
        )

        local_codex = inspect_local_codex()
    chapters = sum(
        sum(u["role"] == "TARGET" for u in p["units"]) for p in plans.values()
    )
    return {
        "revision_id": revision_id,
        "consumption_admission": consumption,
        "reading_plans": plans,
        "target_chapters": chapters,
        "planned_calls_without_repairs": 2 * chapters + 4 * len(plans),
        "planned_calls_with_object_repairs": sum(
            2
            * (sum(u["role"] == "TARGET" for u in p["units"]) + 1)
            * (1 + p["contract"]["max_repairs"])
            + 2
            for p in plans.values()
        ),
        "runtime": runtime or {"state": "NOT_INSPECTED"},
        "prepared_source_checks": input_checks,
        **({"local_codex_preflight": local_codex} if local_codex is not None else {}),
        "execution_blockers": execution_blockers,
        "requested_budget": {
            "max_calls": max_calls,
            "max_tokens": max_tokens,
            "shared_by": [
                "classification",
                "observation",
                "review",
                "revision",
                "synthesis",
                "extraction",
                "retry",
            ],
        },
        "authorization": {
            "status": "AUTHORIZATION_REQUIRED",
            "declared_reference": authorization_ref or None,
            "reference_is_not_verification": True,
        },
        "stop_conditions": [
            "CURRENT_AUTHORIZATION_CHANGED",
            "INPUT_OR_RUNTIME_CHANGED",
            "TOTAL_CALL_OR_TOKEN_BUDGET_EXHAUSTED",
            "REPAIR_ALLOWANCE_EXHAUSTED",
            "UNKNOWN_PROVIDER_OUTCOME",
        ],
        "hidden_backend_usage": "NOT_OBSERVED",
        "token_preview_limit": "Later-stage inputs depend on returned observations; every final request requires native token admission.",
        "model_calls": 0,
        "paid_authorization": "NOT_GRANTED_BY_PREVIEW",
        "input_token_accounting": "FINAL_MATERIALIZED_PROVIDER_REQUEST_REQUIRED",
        "state": "PREVIEW_ONLY",
    }


def read_evidence(
    app,
    project: str,
    job: str,
    operation: str,
    chunk_id: str,
    start: int,
    end: int,
    principal,
) -> dict:
    import hashlib
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.storage.source_import_repositories import SourceImportRepository
    from novel_forge.storage.source_authority_repositories import (
        SourceAuthorityRepository,
    )
    from novel_forge.modules.source_authority.curation import (
        require_curated_operation_current,
    )

    principal.require("source.authority.query", project)
    if not 0 <= start < end or end - start > 4096:
        raise KernelError(
            "READING_EVIDENCE_BOUND",
            "request at most 4096 UTF-8 bytes within an actual input chunk",
        )
    with AuthorityUnitOfWork(app.database_url) as uow:
        imports = SourceImportRepository(uow.cursor)
        stage = imports.reading_stage(project, job, operation)
        repository = SourceAuthorityRepository(uow.cursor)
        require_curated_operation_current(repository, project, operation)
        from .reading_evidence import receipt_input_evidence

        evidence = receipt_input_evidence(
            imports.reading_input_records(project, operation), stage["payload"]
        )
        plan = stage["payload"]["narrative_reading"]
        for receipt in evidence["input_receipts"]:
            manifest = receipt.get("manifest")
            if receipt["state"] == "CONFIRMED_RETURNED" and (
                manifest.get("reading_identity") != plan["identity"]
                or manifest.get("processing_id") != plan["processing_id"]
                or manifest.get("source_transform_id") != plan["source_transform_id"]
                or manifest.get("manifest_hash")
                != corpus_hash(
                    {k: v for k, v in manifest.items() if k != "manifest_hash"}
                )
                or not set(manifest.get("target_units", []))
                <= {
                    u["source_unit_version_id"]
                    for u in plan["units"]
                    if u["role"] == "TARGET"
                }
            ):
                raise KernelError(
                    "READING_RECEIPT_SCOPE_INVALID",
                    "receipt does not match the frozen stage and source version",
                )
        inputs = evidence["coverage"]["actual_text_inputs"]
        actual = next(
            (
                s
                for s in inputs
                if s["source_chunk_asset_version_id"] == chunk_id
                and start >= s["byte_start"]
                and end <= s["byte_end"]
            ),
            None,
        )
        if not actual:
            raise KernelError(
                "READING_EVIDENCE_NOT_READ",
                "source is outside this stage's actual reading evidence",
            )
        rows = repository.catalog_reading_chunk_blobs(project, [chunk_id])
        if len(rows) != 1 or rows[0]["content_hash"] != actual["content_hash"]:
            raise KernelError(
                "READING_SOURCE_DRIFT", "exact input is no longer available"
            )
        row = rows[0]
    content = app.object_store_reader.read(
        object_key=row["actual_object_key"],
        expected_hash=row["actual_hash"],
        expected_size=row["actual_size"],
    )
    try:
        text = content[start:end].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise KernelError(
            "READING_EVIDENCE_UTF8_BOUNDARY", "span splits a Unicode code point"
        ) from exc
    with AuthorityUnitOfWork(app.database_url) as uow:
        require_curated_operation_current(
            SourceAuthorityRepository(uow.cursor), project, operation
        )
    return {
        "operation_id": operation,
        "chunk_id": chunk_id,
        "byte_start": start,
        "byte_end": end,
        "offset_kind": "CHUNK_UTF8_BYTES",
        "content_hash": actual["content_hash"],
        "input_state": "CONFIRMED_RETURNED",
        "manifest_hash": evidence["coverage"]["manifest_hash"],
        "evidence_hash": "sha256:" + hashlib.sha256(content[start:end]).hexdigest(),
        "text": text,
        "generation_allowed": False,
    }


def validate_reading_segments(units: list[dict], segments: tuple[dict, ...]) -> None:
    import hashlib

    chunks = {c["asset_version_id"]: c for u in units for c in u["chunks"]}
    if {s["source_chunk_asset_version_id"] for s in segments} != set(chunks):
        raise KernelError(
            "READING_SEGMENT_SCOPE_MISMATCH",
            "actual chunks differ from frozen allowed input",
        )
    bodies = {u["source_unit_version_id"]: bytearray() for u in units}
    for segment in segments:
        content = segment["content"].encode("utf-8")
        chunk = chunks[segment["source_chunk_asset_version_id"]]
        if (
            len(content) != chunk["byte_size"]
            or "sha256:" + hashlib.sha256(content).hexdigest() != chunk["content_hash"]
        ):
            raise KernelError(
                "READING_SOURCE_DRIFT", "actual bytes differ from the frozen chunk"
            )
        covered = bytearray(len(content))
        for unit in units:
            left = max(0, unit["normalized_byte_start"] - chunk["source_byte_start"])
            right = min(
                len(content), unit["normalized_byte_end"] - chunk["source_byte_start"]
            )
            if left < right:
                covered[left:right] = b"\1" * (right - left)
                bodies[unit["source_unit_version_id"]].extend(content[left:right])
        if bytes(v for v, c in zip(content, covered) if not c).strip():
            raise KernelError(
                "READING_CHUNK_REPROCESS_REQUIRED",
                "out-of-range prose requires chapter-aligned reprocessing",
            )
    for unit in units:
        if (
            "sha256:"
            + hashlib.sha256(bodies[unit["source_unit_version_id"]]).hexdigest()
            != unit["normalized_content_hash"]
        ):
            raise KernelError(
                "READING_UNIT_COVERAGE_MISMATCH",
                "unit bytes, order or coverage differ from frozen Processing",
            )
