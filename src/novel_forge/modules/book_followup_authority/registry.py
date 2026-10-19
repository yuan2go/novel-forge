from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRegistration
from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import (
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
    ReaderOutcomeModelPort,
)
from .handlers import LongformRecapHandler, ReaderOutcomeHandler
from .prose_handler import LongformProseReviewHandler
from .prose_review import PROSE_REVIEW_DEFINITION
from .prose_sampling import PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_TYPE, PROSE_SAMPLE_OUTPUT, ProseReviewSampleHandler
from novel_forge.modules.reader_judge_authority import ReaderJudgeRuntimeResolver


class _UnavailableReaderOutcomeHandler:
    def execute(self, _request):
        raise KernelError(
            "READER_OUTCOME_MODEL_PORT_REQUIRED",
            "Reader Outcome execution requires a configured ExternalEffect model port",
        )


class BookFollowupHandlerRegistry:
    def __init__(
        self,
        model_port: ReaderOutcomeModelPort | None = None,
        reader_judge_resolver: ReaderJudgeRuntimeResolver | None = None,
        prose_model_port: ReaderOutcomeModelPort | None = None,
        screenplay_model_ports: dict[str, ReaderOutcomeModelPort] | None = None,
        memory_model_port: ReaderOutcomeModelPort | None = None,
    ) -> None:
        from novel_forge.modules.book_authority.memory_backfill import MemoryExtractionHandler
        self._handlers = {
            "working_memory_extract": MemoryExtractionHandler(memory_model_port),
            PROSE_SAMPLE_DEFINITION: ProseReviewSampleHandler(prose_model_port)
            if prose_model_port is not None else _UnavailableReaderOutcomeHandler(),
            PROSE_REVIEW_DEFINITION: LongformProseReviewHandler(prose_model_port)
            if prose_model_port is not None
            else _UnavailableReaderOutcomeHandler(),
            READER_OUTCOME_DEFINITION: (
                ReaderOutcomeHandler(model_port, reader_judge_resolver)
                if model_port is not None and reader_judge_resolver is not None
                else _UnavailableReaderOutcomeHandler()
            ),
            LONGFORM_RECAP_DEFINITION: LongformRecapHandler(),
        }
        from .screenplay import SCREENPLAY_STAGES
        from .screenplay_handler import ScreenplayHandler
        ports = screenplay_model_ports or {}
        self._handlers.update({stage: ScreenplayHandler(ports[stage], stage) if stage in ports else _UnavailableReaderOutcomeHandler()
                               for stage in SCREENPLAY_STAGES})
        from .screenplay_sampling import sample_definition_name, ScreenplaySampleHandler
        self._handlers.update({sample_definition_name(stage): ScreenplaySampleHandler(ports[stage], stage)
            if stage in ports else _UnavailableReaderOutcomeHandler() for stage in SCREENPLAY_STAGES})


    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        handler = self._handlers.get(definition_name)
        if handler is None:
            raise KernelError("BOOK_FOLLOWUP_HANDLER_NOT_REGISTERED", definition_name)
        from .screenplay import SCREENPLAY_STAGES, CANDIDATE_TYPE, REVIEW_TYPE
        from .screenplay_sampling import sample_definition_name, SCREENPLAY_SAMPLE_TYPE
        asset_type, output_key = {
            "working_memory_extract": ("working_memory_result", "book.working_memory.result"),
            **{sample_definition_name(stage): (SCREENPLAY_SAMPLE_TYPE, sample_definition_name(stage)) for stage in SCREENPLAY_STAGES},
            **{stage: (REVIEW_TYPE if stage == "screenplay_review" else CANDIDATE_TYPE, stage + ".result") for stage in SCREENPLAY_STAGES},
            PROSE_SAMPLE_DEFINITION: (PROSE_SAMPLE_TYPE, PROSE_SAMPLE_OUTPUT),
            PROSE_REVIEW_DEFINITION: (
                "longform_prose_review_report",
                "longform.prose_review.report",
            ),
            READER_OUTCOME_DEFINITION: (
                "reader_outcome_report",
                "reader_outcome.report",
            ),
            LONGFORM_RECAP_DEFINITION: ("longform_recap", "longform.recap.report"),
        }[definition_name]
        return AuthorityHandlerRegistration(
            definition_name=definition_name,
            definition_version=definition_version,
            handler_key=f"novel_forge.book_followup_authority.{definition_name}",
            handler_contract_version="book-followup-handler-v2",
            output_asset_type=asset_type,
            output_key=output_key,
            role="primary",
            completion_topic=f"book_followup.{definition_name}.materialized",
            handler=handler,
        )

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(
            f"novel_forge.book_followup_authority.{name}" for name in self._handlers
        )

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset(self._handlers)


__all__ = ["BookFollowupHandlerRegistry"]
