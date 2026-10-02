from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import CorpusUse
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository


def require_corpus_consumption(
    database_url: str, project_id: str, payload: Any, *, source_analysis: bool,
    operation_id: str = ""
) -> None:
    identities: set[str] = set()
    pending = [(payload, 0)]
    inspected = 0
    while pending:
        value, depth = pending.pop()
        inspected += 1
        if depth > 32 or inspected > 50000:
            raise KernelError(
                "CORPUS_CONSUMPTION_INPUT_BOUND",
                "provider input exceeds lineage inspection bounds",
            )
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).endswith(
                    ("asset_version_id", "source_document_id", "knowledge_pack_id")
                ) and isinstance(item, str):
                    identities.add(item)
                elif str(key).endswith("asset_version_ids") and isinstance(
                    item, (list, tuple)
                ):
                    identities.update(
                        identity for identity in item if isinstance(identity, str)
                    )
                elif isinstance(item, (Mapping, list, tuple)):
                    pending.append((item, depth + 1))
        elif isinstance(value, (list, tuple)):
            pending.extend(
                (item, depth + 1)
                for item in value
                if isinstance(item, (Mapping, list, tuple))
            )
    if not identities:
        return
    with AuthorityUnitOfWork(database_url) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        inputs = payload.get("input", payload) if isinstance(payload, Mapping) else {}
        observation = None
        if inputs.get("observation_boundary"):
            if not source_analysis or not operation_id:
                raise KernelError("SOURCE_OBSERVATION_USE", "research scope requires an admitted source Operation")
            observation = repository.require_source_observation(project_id, operation_id, inputs)
        repository.require_corpus_execution_assets(
            project_id,
            tuple(sorted(identities)),
            CorpusUse.SOURCE_ANALYSIS
            if source_analysis
            else CorpusUse.ABSTRACT_GENERATION,
            observation=observation,
        )
