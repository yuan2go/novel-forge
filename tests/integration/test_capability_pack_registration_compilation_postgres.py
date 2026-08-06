from __future__ import annotations

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    CapabilityPackPostgresHarness,
)


def test_distinct_pack_versions_freeze_distinct_trusted_compilations() -> None:
    harness = CapabilityPackPostgresHarness("pack-registration")
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    version_2 = harness.register_compile_approve("1.1.0", generation=2)

    assert version_1.manifest_hash != version_2.manifest_hash
    assert version_1.compilation_hash != version_2.compilation_hash
    assert version_1.catalog_snapshot_hash != version_2.catalog_snapshot_hash
    assert version_1.prompt_hash != version_2.prompt_hash
    assert version_1.skill_hash != version_2.skill_hash
    assert version_1.agent_definition_version == 1
    assert version_2.agent_definition_version == 2
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT owner_scope_type, owner_project_id,
                   COUNT(version.pack_version)
            FROM authority_capability_pack AS pack
            JOIN authority_capability_pack_version AS version
              ON version.pack_id=pack.pack_id
            WHERE pack.pack_id=%s
            GROUP BY owner_scope_type, owner_project_id
            """,
            [harness.pack_id],
        )
        assert uow.cursor.fetchone() == ("PROJECT", harness.project_id, 2)
        uow.commit()
