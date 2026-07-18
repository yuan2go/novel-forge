"""Shared fenced runtime for storage-free authority handlers."""

from .contracts import (
    AuthorityAuxiliaryOutput,
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
    AuthorityInputAsset,
    AuthorityExecutionResult,
    AuthorityMaterializedOutput,
)
from .runtime import execute_authority_handler

__all__ = [
    "AuthorityAuxiliaryOutput",
    "AuthorityExecutionResult",
    "AuthorityHandlerOutput",
    "AuthorityHandlerRegistration",
    "AuthorityHandlerRequest",
    "AuthorityInputAsset",
    "AuthorityMaterializedOutput",
    "execute_authority_handler",
]
