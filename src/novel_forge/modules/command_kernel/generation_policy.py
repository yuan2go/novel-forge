from __future__ import annotations

from collections.abc import Iterable


def pure_generation_capabilities(capabilities: Iterable[str]) -> bool:
    values = tuple(capabilities)
    return bool(values) and all(value.startswith("model.") for value in values)


def pure_generation_operation(cursor, operation_id: str, project_id: str) -> bool:
    cursor.execute(
        """SELECT definition_snapshot->'external_capabilities'
        FROM authority_operation WHERE operation_id=%s AND project_id=%s""",
        [operation_id, project_id],
    )
    row = cursor.fetchone()
    return bool(row and pure_generation_capabilities(row[0] or ()))


def generation_graph(cursor, operation_id: str, project_id: str) -> bool:
    if pure_generation_operation(cursor, operation_id, project_id):
        return True
    cursor.execute(
        """SELECT child.definition_snapshot->'external_capabilities'
        FROM authority_operation child
        WHERE (child.root_operation_id=%s OR child.operation_id=%s) AND child.project_id=%s""",
        [operation_id, operation_id, project_id],
    )
    capabilities = tuple(value for row in cursor.fetchall() for value in (row[0] or ()))
    return any(value.startswith("model.") for value in capabilities) and all(
        value.startswith("model.") or value == "object_store.put" for value in capabilities
    )
