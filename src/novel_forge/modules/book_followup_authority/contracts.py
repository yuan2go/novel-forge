from __future__ import annotations

from typing import Any, Protocol, Callable

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult


READER_OUTCOME_DEFINITION = "reader_outcome.evaluate"
LONGFORM_RECAP_DEFINITION = "longform.recap"
BOOK_FOLLOWUP_DEFINITION_VERSION = "1.1.0"


class ReaderOutcomeModelPort(Protocol):
    external_effect_backed: bool
    database_url: str

    def invoke(
        self,
        request: AuthorityHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
        reservation_tokens: int | None = None,
        pre_send_assertion: Callable[[], None] | None = None,
    ) -> ModelProviderResult: ...


__all__ = [
    "BOOK_FOLLOWUP_DEFINITION_VERSION",
    "LONGFORM_RECAP_DEFINITION",
    "READER_OUTCOME_DEFINITION",
    "ReaderOutcomeModelPort",
]
