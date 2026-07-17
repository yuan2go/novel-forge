"""Content handler/codec registry and shared-runtime registrations."""
from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRegistration
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS, ContentHandlerCodec


class ContentHandlerRegistry:
    def __init__(self) -> None:
        self._codecs = dict(CONTENT_CODECS)

    def require(self, definition_name: str) -> ContentHandlerCodec:
        codec = self._codecs.get(definition_name)
        if codec is None:
            raise KernelError("CONTENT_HANDLER_NOT_REGISTERED", definition_name)
        return codec

    def registration(self, definition_name: str, definition_version: str) -> AuthorityHandlerRegistration:
        codec = self.require(definition_name)
        return AuthorityHandlerRegistration(
            definition_name=definition_name,
            definition_version=definition_version,
            handler_key=f"novel_forge.content_authority.{definition_name}",
            handler_contract_version="content-authority-handler-v2",
            output_asset_type=codec.output_asset_type,
            output_key=codec.output_key,
            role="primary",
            completion_topic=f"content.{definition_name}.materialized",
            handler=codec,
        )

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(f"novel_forge.content_authority.{name}" for name in self._codecs)

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset(self._codecs)


__all__ = ["ContentHandlerRegistry"]
