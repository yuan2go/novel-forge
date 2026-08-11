from __future__ import annotations

from novel_forge.modules.content_authority.registry import ContentHandlerRegistry

from .codecs import BOOK_CODECS


class BookHandlerRegistry(ContentHandlerRegistry):
    def __init__(self) -> None:
        self._codecs = dict(BOOK_CODECS)
