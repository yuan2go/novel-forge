from __future__ import annotations

from novel_forge.modules.book_authority.member_retry import settled_retry_rows
from tests.integration.authority_postgres_support import (
    connect,
    ensure_migrated,
    identifier,
)


def test_native_member_wait_query_uses_frozen_retry_policy_on_current_postgres_schema():
    ensure_migrated()
    with connect() as connection:
        assert (
            settled_retry_rows(
                connection.cursor(),
                project_id=identifier("member-retry"),
                root_id=identifier("absent-root"),
            )
            == []
        )
