from __future__ import annotations
from dataclasses import dataclass
from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError
from .contracts import ReaderOutcomeModelPort
from .prose_review import prose_review_invoke_payload, validate_window_report, validate_window_source_binding


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
            content.get("schema_version") not in {"longform-prose-window.v1", "longform-prose-window.v2", "longform-prose-window.v3"}
            or content.get("source_isolation") not in {"ACCEPTED_PROSE_ONLY", "AUTHOR_SELECTED_UNREVIEWED_PROSE"}
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

        def assert_current(*, dispatch: bool = False) -> None:
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork

            from .prose_coordinator import load_review_sources
            from .prose_review import freeze_manifest

            with AuthorityUnitOfWork(self.model_port.database_url) as uow:
                uow.cursor.execute(
                    "SELECT run_id,manifest FROM authority_book_prose_review_run WHERE project_id=%s AND workspace_id=%s AND book_run_id=%s AND manifest_digest=%s",
                    [
                        request.project_id,
                        request.workspace_id,
                        content["book_run_id"],
                        content["manifest_digest"],
                    ],
                )
                rows = [
                    row
                    for row in uow.cursor.fetchall()
                    if any(
                        window.get("input_asset", {}).get("asset_version_id")
                        == source.asset_version_id
                        for window in row[1]["windows"]
                    )
                ]
                if len(rows) != 1:
                    raise KernelError(
                        "LONGFORM_PROSE_INPUT_DRIFT",
                        "window must be registered in its exact Book-owned manifest",
                    )
                current = freeze_manifest(
                    project_id=request.project_id,
                    workspace_id=request.workspace_id,
                    book_run_id=content["book_run_id"],
                    sources=load_review_sources(
                        uow, content["book_run_id"], request.project_id
                    ),
                    policy=content["policy"],
                    work_intent=content["schema_version"] in {"longform-prose-window.v2", "longform-prose-window.v3"},
                )
                run_id, manifest = rows[0]
                validate_window_source_binding(manifest=manifest, window=content["window"])
                if (
                    manifest["sources"]
                    != current["sources"][: len(manifest["sources"])]
                ):
                    raise KernelError(
                        "LONGFORM_PROSE_SOURCE_STALE",
                        "frozen accepted manuscript changed before Provider dispatch",
                    )
                uow.cursor.execute(
                    "SELECT 1 FROM authority_book_prose_review_event WHERE run_id=%s AND kind='WINDOW_ADMITTED' AND authority_generation_current_operation(content->>'operation_id')=%s AND content->>'window_id'=%s",
                    [run_id, request.operation_id, content["window"]["window_id"]],
                )
                if not uow.cursor.fetchone():
                    raise KernelError(
                        "LONGFORM_PROSE_ADMISSION_UNLINKED",
                        "review requires its durable Book admission before dispatch",
                    )
                if dispatch:
                    uow.cursor.execute(
                        "SELECT kind FROM authority_book_prose_review_event WHERE run_id=%s AND kind IN ('PAUSED','RESUMED') ORDER BY event_version DESC LIMIT 1",
                        [run_id],
                    )
                    control = uow.cursor.fetchone()
                    if control and control[0] == "PAUSED":
                        raise KernelError(
                            "LONGFORM_PROSE_PAUSED",
                            "resume the frozen review before Provider dispatch",
                        )

        assert_current()
        from .prose_recovery import literal_citation_retry_feedback
        invocation = prose_review_invoke_payload(content)
        invocation.update(literal_citation_retry_feedback(request, source=source, payload=invocation))
        result = self.model_port.invoke(
            request,
            stage="longform_prose_review",
            payload=invocation,
            reservation_tokens=content["policy"]["context_token_budget"],
            pre_send_assertion=lambda: assert_current(dispatch=True),
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
