"""Handler registry for governed post-chapter operations."""
from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRegistration
from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import (
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
    ReaderOutcomeModelPort,
)
from .handlers import LongformRecapHandler, ReaderOutcomeHandler


class _UnavailableReaderOutcomeHandler:
    def execute(self, _request):
        raise KernelError(
            "READER_OUTCOME_MODEL_PORT_REQUIRED",
            "Reader Outcome execution requires a configured ExternalEffect model port",
        )


class BookFollowupHandlerRegistry:
    def __init__(self, model_port: ReaderOutcomeModelPort | None = None) -> None:
        self._handlers = {
            READER_OUTCOME_DEFINITION: (
                ReaderOutcomeHandler(model_port)
                if model_port is not None
                else _UnavailableReaderOutcomeHandler()
            ),
            LONGFORM_RECAP_DEFINITION: LongformRecapHandler(),
        }

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        handler = self._handlers.get(definition_name)
        if handler is None:
            raise KernelError("BOOK_FOLLOWUP_HANDLER_NOT_REGISTERED", definition_name)
        asset_type, output_key = {
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
            handler_contract_version="book-followup-handler-v1",
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
