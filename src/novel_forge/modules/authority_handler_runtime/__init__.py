"""Shared fenced runtime for storage-free authority handlers."""

from .contracts import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
    AuthorityInputAsset,
    AuthorityExecutionResult,
)
from .runtime import execute_authority_handler

__all__ = [
    "AuthorityExecutionResult",
    "AuthorityHandlerOutput",
    "AuthorityHandlerRegistration",
    "AuthorityHandlerRequest",
    "AuthorityInputAsset",
    "execute_authority_handler",
]
