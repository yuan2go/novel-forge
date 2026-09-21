from __future__ import annotations

from dataclasses import dataclass

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import ReaderOutcomeModelPort
from .prose_review import validate_window_report


@dataclass(frozen=True, slots=True)
class LongformProseReviewHandler:
    model_port: ReaderOutcomeModelPort

    def __post_init__(self) -> None:
        if not getattr(self.model_port, "external_effect_backed", False):
            raise ValueError(
                "longform prose review requires the existing ExternalEffect model port"
            )

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        source = request.require_input("longform_prose_review_window")
        content = source.content
        payload = request.command["payload"]
        if (
            content.get("schema_version") != "longform-prose-window.v1"
            or content.get("source_isolation") != "ACCEPTED_PROSE_ONLY"
            or any(
                content.get(key) != payload.get(key)
                for key in ("manifest_digest", "book_run_id")
            )
            or content["window"]["window_id"] != payload.get("window_id")
        ):
            raise KernelError(
                "LONGFORM_PROSE_INPUT_DRIFT",
                "operation must bind exact accepted window",
            )

        def assert_current() -> None:
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork
            from .prose_coordinator import load_accepted_sources
            from .prose_review import freeze_manifest

            with AuthorityUnitOfWork(self.model_port.database_url) as uow:
                uow.cursor.execute(
                    "SELECT manifest FROM authority_book_prose_review_run WHERE project_id=%s AND workspace_id=%s AND book_run_id=%s AND manifest_digest=%s",
                    [
                        request.project_id,
                        request.workspace_id,
                        content["book_run_id"],
                        content["manifest_digest"],
                    ],
                )
                rows = uow.cursor.fetchall()
                if not rows or not any(
                    window.get("input_asset", {}).get("asset_version_id")
                    == source.asset_version_id
                    for row in rows
                    for window in row[0]["windows"]
                ):
                    raise KernelError(
                        "LONGFORM_PROSE_INPUT_DRIFT",
                        "window must be registered in its exact Book-owned manifest",
                    )
                current = freeze_manifest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_run_id=content["book_run_id"],
                    sources=load_accepted_sources(
                        uow, content["book_run_id"], request.project_id
                    ),
                    policy=content["policy"],
                )
                if any(row[0]["sources"] != current["sources"] for row in rows):
                    raise KernelError(
                        "LONGFORM_PROSE_SOURCE_STALE",
                        "accepted manuscript changed before Provider dispatch",
                    )

        assert_current()
        result = self.model_port.invoke(
            request,
            stage="longform_prose_review",
            payload={
                "manifest_digest": content["manifest_digest"],
                "window_id": content["window"]["window_id"],
            },
            reservation_tokens=content["policy"]["context_token_budget"],
            pre_send_assertion=assert_current,
        )
        report = validate_window_report(
            result.output, manifest=content, window=content["window"]
        )
        return AuthorityHandlerOutput(
            asset_type="longform_prose_review_report",
            output_key="longform.prose_review.report",
            role="primary",
            content=report,
            qualification_policy="longform-prose-review.v1",
            reference_asset_version_ids=(source.asset_version_id,),
            evidence={
                "model_evidence": result.to_evidence(),
                "manuscript_mutation_allowed": False,
                "semantic_judgment_is_fact": False,
            },
        )
