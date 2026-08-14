"""Contracts for governed post-chapter execution."""
from __future__ import annotations

from typing import Any, Protocol

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult


READER_OUTCOME_DEFINITION = "reader_outcome.evaluate"
LONGFORM_RECAP_DEFINITION = "longform.recap"
BOOK_FOLLOWUP_DEFINITION_VERSION = "1.1.0"


class ReaderOutcomeModelPort(Protocol):
    external_effect_backed: bool

    def invoke(
        self,
        request: AuthorityHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
    ) -> ModelProviderResult: ...


__all__ = [
    "BOOK_FOLLOWUP_DEFINITION_VERSION",
    "LONGFORM_RECAP_DEFINITION",
    "READER_OUTCOME_DEFINITION",
    "ReaderOutcomeModelPort",
]
