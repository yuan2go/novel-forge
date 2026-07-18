"""Trusted Principal and project-scoped permission boundary for Authority admission."""
from .service import Principal, PrincipalType, TrustedPrincipalResolver

__all__ = ["Principal", "PrincipalType", "TrustedPrincipalResolver"]
