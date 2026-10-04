from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.authority_handler_runtime import runtime as authority_runtime
from novel_forge.modules.chapter_authority import runtime
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRegistry, ChapterNode
from novel_forge.modules.chapter_authority.definitions import CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, CHAPTER_SLICE_DEFINITION_VERSION
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError


class ContractAccepted(Exception):
    pass


def frozen_operation(monkeypatch, version, *, node=ChapterNode.CONTEXT, model=True, author_input=False, mismatch=None):
    command = WorkerLeaseCommand("attempt", "project", "worker", 7, "trace", "correlation")
    operation = {"definition_name": node.definition_name, "definition_version": version,
                 "definition_snapshot": {"handler_key": node.handler_key}}
    if mismatch == "name":
        operation["definition_name"] = ChapterNode.DRAFT.definition_name
    elif mismatch == "handler":
        operation["definition_snapshot"]["handler_key"] = "other.handler"
    read = MagicMock(return_value=operation)
    cursor = MagicMock()
    cursor.fetchone.return_value = (version,)
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor = cursor
    uow.repositories.chapter_authority.operation_execution = read
    monkeypatch.setattr(runtime, "AuthorityUnitOfWork", lambda _: uow)
    monkeypatch.setattr(authority_runtime, "AuthorityUnitOfWork", lambda _: uow)
    fence = MagicMock(return_value={"operation_id": "operation"})
    monkeypatch.setattr(authority_runtime, "require_current_fence", fence)
    monkeypatch.setattr(authority_runtime, "_require_approved_archival_story_design", lambda *args, **kwargs: (_ for _ in ()).throw(ContractAccepted()))
    def invoke():
        return runtime.execute_chapter_handler(
            "unused", command=command, node=node, registry=ChapterHandlerRegistry(model_effects_required=model),
            author_input=author_input,
        )
    return invoke, command, cursor, fence, read


@pytest.mark.parametrize("node", tuple(ChapterNode))
@pytest.mark.parametrize("version", [CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, "3.5.0", "3.4.1"])
def test_published_and_current_formal_contracts_reach_unchanged_authority_checks(monkeypatch, node, version):
    invoke, command, cursor, fence, _ = frozen_operation(monkeypatch, version, node=node)
    with pytest.raises(ContractAccepted):
        invoke()
    fence.assert_called_once()
    assert cursor.execute.call_args.args[1] == [command.attempt_id, command.project_id]


@pytest.mark.parametrize("version", ["3.4.0", "3.4.2", "3.6.1", "4.0.0", "3.4.1-author-input.v1"])
def test_other_versions_remain_stale(monkeypatch, version):
    invoke, _, _, fence, _ = frozen_operation(monkeypatch, version)
    with pytest.raises(KernelError, match="AUTHORITY_HANDLER_CONTRACT_STALE"):
        invoke()
    fence.assert_called_once()


@pytest.mark.parametrize("mismatch", ["name", "handler"])
def test_published_version_does_not_bypass_name_or_key_check(monkeypatch, mismatch):
    invoke, _, _, _, _ = frozen_operation(monkeypatch, "3.4.1", mismatch=mismatch)
    with pytest.raises(KernelError, match="AUTHORITY_HANDLER_DEFINITION_CONFLICT"):
        invoke()


def test_published_version_does_not_bypass_current_fence(monkeypatch):
    invoke, _, _, fence, read = frozen_operation(monkeypatch, "3.4.1")
    fence.side_effect = KernelError("ATTEMPT_FENCING_TOKEN_STALE", "stale fence")
    with pytest.raises(KernelError, match="ATTEMPT_FENCING_TOKEN_STALE"):
        invoke()
    read.assert_not_called()


@pytest.mark.parametrize("model,author_input,version", [(False, False, "2.2.1"), (True, True, "3.4.1-author-input.v1")])
def test_fixture_and_author_input_contracts_are_not_reselected(monkeypatch, model, author_input, version):
    invoke, _, cursor, _, _ = frozen_operation(monkeypatch, version, node=ChapterNode.DRAFT, model=model, author_input=author_input)
    with pytest.raises(ContractAccepted):
        invoke()
    if model:
        cursor.execute.assert_called_once()
    else:
        cursor.execute.assert_not_called()


@pytest.mark.parametrize("version,accepted", [("3.4.1", True), ("3.5.0", True), (CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, True), (CHAPTER_SLICE_DEFINITION_VERSION, True), ("3.4.0", False), ("3.4.2", False), ("4.0.0", False), ("2.2.0", False), ("2.2.2", False), ("", False)])
def test_gateway_legacy_graph_compatibility_is_bounded(monkeypatch, version, accepted):
    from novel_forge.modules.chapter_authority import execution_gateway
    cursor = MagicMock()
    cursor.fetchone.return_value = (ChapterNode.DRAFT.definition_name, version, "root", "saga")
    cursor.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(execution_gateway, "get_database_runtime", lambda _: SimpleNamespace(connection=lambda: connection))
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    binder.database_url = "unused"
    if accepted:
        assert binder._operation_graph("operation", "project")["definition_version"] == version
    else:
        with pytest.raises(KernelError, match="CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED"):
            binder._operation_graph("operation", "project")


@pytest.mark.parametrize("version", ["3.4.1", CHAPTER_MODEL_EFFECT_DEFINITION_VERSION])
def test_pack_request_uses_original_workflow_and_operation_version(version):
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    binder.capability_pack_id = "pack"
    binder.pack_environment = "test"
    binder.pack_runtime_profile = "test"
    binder.pack_release_channel = "stable"
    binder.workflow_definition_ref = f"chapter_authority_slice@{CHAPTER_MODEL_EFFECT_DEFINITION_VERSION}"
    binder.pack_resolver = MagicMock()
    expected = binder.pack_resolver.freeze_attempt_snapshot.return_value
    assert binder._resolve_pack_snapshot(
        project_id="project", workspace_id="workspace", book_id="book", operation_id="operation",
        attempt_id="attempt", execution_fencing_token=7, worker_id="worker", snapshot_creation_fencing_token=7,
        snapshot_creation_worker_id="worker", stage="draft", route=SimpleNamespace(release_sha="e" * 40),
        graph={"definition_name": ChapterNode.DRAFT.definition_name, "definition_version": version},
    ) is expected
    request = binder.pack_resolver.freeze_attempt_snapshot.call_args.args[0]
    assert request.workflow_definition_ref == f"chapter_authority_slice@{version}"
    assert request.operation_definition_ref == f"{ChapterNode.DRAFT.definition_name}@{version}"
    assert request.pack_id == "pack"


@pytest.mark.parametrize("version", ["3.4.1", CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, CHAPTER_SLICE_DEFINITION_VERSION, "4.0.0"])
def test_formal_version_does_not_admit_an_unpublished_operation_name(monkeypatch, version):
    from novel_forge.modules.chapter_authority import execution_gateway
    cursor = MagicMock()
    cursor.fetchone.return_value = ("chapter.unpublished.execute", version, "root", "saga")
    cursor.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(execution_gateway, "get_database_runtime", lambda _: SimpleNamespace(connection=lambda: connection))
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    binder.database_url = "unused"
    with pytest.raises(KernelError, match="CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED"):
        binder._operation_graph("operation", "project")


def test_non_chapter_graph_remains_subject_to_its_domain_binder(monkeypatch):
    from novel_forge.modules.chapter_authority import execution_gateway
    cursor = MagicMock()
    cursor.fetchone.return_value = ("narrative.evaluation.evaluate", "1.0.0", "root", "saga")
    cursor.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(execution_gateway, "get_database_runtime", lambda _: SimpleNamespace(connection=lambda: connection))
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    binder.database_url = "unused"
    assert binder._operation_graph("operation", "project") == {
        "definition_name": "narrative.evaluation.evaluate", "definition_version": "1.0.0",
        "root_operation_id": "root", "saga_id": "saga",
    }


@pytest.mark.parametrize("name,version,accepted", [
    ("chapter.provider.sample.draft", "1.0.0", True),
    ("chapter.provider.sample.review", "1.0.0", True),
    ("chapter.provider.sample.review", "1.1.0", True),
    ("chapter.provider.sample.rereview", "1.1.0", True),
    ("chapter.provider.sample.draft", "1.1.0", False),
    ("chapter.provider.sample.unpublished", "1.0.0", False),
    ("chapter.provider.sample.review", "4.0.0", False),
])
def test_gateway_only_admits_published_sample_contracts(monkeypatch, name, version, accepted):
    from novel_forge.modules.chapter_authority import execution_gateway
    cursor = MagicMock()
    cursor.fetchone.return_value = (name, version, "root", "saga")
    cursor.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(execution_gateway, "get_database_runtime", lambda _: SimpleNamespace(connection=lambda: connection))
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    binder.database_url = "unused"
    if accepted:
        assert binder._operation_graph("operation", "project")["definition_name"] == name
    else:
        with pytest.raises(KernelError, match="CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED"):
            binder._operation_graph("operation", "project")
