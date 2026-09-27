from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority.edition_runtime import inherit_unchanged_prefix
from novel_forge.modules.book_authority.editions import revise_manifest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.book_edition_repositories import BookEditionRepository
from tests.unit.test_book_editions import base_manifest


def test_prefix_reuse_cannot_admit_a_chain_beyond_source_resolver_bound():
    base = base_manifest()
    units = deepcopy(base["units"])
    units[1]["text"] += "他把缘由说清。"
    manifest = revise_manifest(base, units=units, reason="补充语气", change_kind="EXPRESSION")
    cursor = Mock()
    cursor.fetchone.return_value = (64,)
    with pytest.raises(KernelError, match="EDITION_PREFIX_LINEAGE_LIMIT"):
        inherit_unchanged_prefix(SimpleNamespace(cursor=cursor), book_run_id="new-run",
            revision={"revision_id": "candidate", "manifest": manifest}, operation_id="new-operation")
    assert len(cursor.execute.call_args_list) == 1
    assert "SELECT max(depth)" in cursor.execute.call_args.args[0]


def test_selected_scope_freezes_snapshot_while_explicit_run_can_continue():
    manifest = base_manifest()
    cursor = Mock()
    cursor.fetchone.return_value = ({"kind": "ORIGINAL_ACCEPTED_MANUSCRIPT", "source_book_run_id": "run",
        "manifest_digest": manifest["manifest_digest"]}, manifest, manifest["manifest_digest"])
    cursor.fetchall.return_value = [("run",)]
    repo = BookEditionRepository(cursor)
    assert repo.accepted_scope(project_id="p", book_id="b") == ("run", ("accepted-1", "accepted-2"))
    cursor.reset_mock()
    assert repo.accepted_scope(project_id="p", book_id="b", book_run_id="run") == ("run", None)
    cursor.fetchone.assert_not_called()


def test_validated_edit_scope_uses_new_acceptances_not_old_source_mapping():
    manifest = base_manifest()
    cursor = Mock()
    cursor.fetchone.return_value = ({"validation_book_run_id": "edited-run", "manifest_digest": manifest["manifest_digest"],
        "accepted_units": [{"acceptance_id": "new-1"}, {"acceptance_id": "new-2"}]}, manifest, manifest["manifest_digest"])
    cursor.fetchall.return_value = [("edited-run",)]
    assert BookEditionRepository(cursor).accepted_scope(project_id="p", book_id="b") == ("edited-run", ("new-1", "new-2"))


@pytest.mark.parametrize("proof", [None, {"manifest_digest": "wrong"}])
def test_selected_scope_cannot_fall_back_to_live_run_when_proof_is_missing(proof):
    manifest = base_manifest()
    cursor = Mock()
    cursor.fetchone.return_value = (proof, manifest, manifest["manifest_digest"])
    with pytest.raises(KernelError, match="EDITION_ACCEPTANCE_SCOPE_INVALID"):
        BookEditionRepository(cursor).accepted_scope(project_id="p", book_id="b")
