from __future__ import annotations

import pytest

from novel_forge.modules.authority_security import TrustedPrincipalResolver


def test_source_import_worker_permission_subset_excludes_approval() -> None:
    principal = TrustedPrincipalResolver(environment="production").resolve_worker_principal(
        "source-import-worker-1",
        permission_subset=frozenset(
            {
                "source.authority.execute",
                "mkaos.authority.execute",
                "external_effect.execute",
            }
        ),
    )
    assert principal.allows("source.authority.execute", "project-1")
    assert principal.allows("mkaos.authority.execute", "project-1")
    assert not principal.allows("mkaos.authority.approve", "project-1")


def test_worker_permission_subset_cannot_expand_trusted_policy() -> None:
    with pytest.raises(RuntimeError, match="exceeds"):
        TrustedPrincipalResolver(environment="production").resolve_worker_principal(
            "source-import-worker-1",
            permission_subset=frozenset({"system.root"}),
        )
