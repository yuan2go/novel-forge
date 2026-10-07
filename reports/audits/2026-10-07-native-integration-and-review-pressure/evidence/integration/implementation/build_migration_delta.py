from pathlib import Path
import importlib
import json
import subprocess

root = Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
versions = root / 'src/novel_forge/storage/migrations/versions'
source_names = [
    'v20261006_0157_planning_result_admission',
    'v20261006_0158_planning_capacity_lineage',
    'v20261006_0159_planning_input_order_recovery',
    'v20261006_0160_optional_world_continuation',
    'v20261006_0161_gateway_result_revalidation',
    'v20261006_0162_stage_repair_policy',
    'v20261006_0163_failed_step_successor',
    'v20261006_0164_execution_contract_continuation',
    'v20261007_0165_derived_step_revalidation',
]

dead_letter = """(op.status='FAILED_FINAL' OR (op.status='DEAD_LETTER' AND NOT EXISTS (
                  SELECT 1 FROM authority_external_effect pending
                  WHERE pending.operation_id=parent.operation_id
                    AND pending.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')
              ) AND EXISTS (
                  SELECT 1 FROM authority_external_effect known
                  WHERE known.operation_id=parent.operation_id AND known.status='SUCCEEDED'
              )))"""
capacity_proof = """(
                    source.status IN ('FAILED_FINAL','DEAD_LETTER')
                    AND r.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                    AND source_generation.candidate_asset_version_id IS NULL
                    AND r.successor_command->>'runtime_continuation_id'=r.continuation_id
                    AND COALESCE((SELECT COALESCE(a.result->>'error_code',a.error->>'error_code')
                        FROM authority_attempt a WHERE a.operation_id=source.operation_id
                        ORDER BY a.attempt_number DESC LIMIT 1),'')='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED'
                    AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=source.operation_id)
                    AND NOT EXISTS(SELECT 1 FROM authority_budget_reservation b WHERE b.operation_id=source.operation_id)
                  )"""
legacy_cause = """(child.causation_operation_id=source.operation_id OR (
                    r.target_runtime #>> '{planning_capacity,version}'='planning-capacity-allocation.v1'
                    AND EXISTS (
                      SELECT 1 FROM authority_operation_output_asset repair_output
                      JOIN authority_story_planning_generation repair
                        ON repair.operation_id=repair_output.operation_id
                        AND repair.candidate_asset_version_id=repair_output.asset_version_id
                      WHERE repair_output.asset_version_id=r.source_command->>'repair_of_candidate_id'
                        AND repair.project_id=NEW.project_id AND repair.workspace_id=NEW.workspace_id
                        AND repair.book_id=NEW.book_id
                        AND child.causation_operation_id=repair.operation_id
                    )
                  ))"""
registered_lineage = """EXISTS (
                    SELECT 1 FROM authority_story_planning_runtime_continuation continuation
                    JOIN authority_operation runtime_source ON runtime_source.operation_id=continuation.source_operation_id
                    WHERE continuation.continuation_id=NEW.runtime_continuation_id
                      AND continuation.project_id=NEW.project_id AND continuation.workspace_id=NEW.workspace_id
                      AND continuation.book_id=NEW.book_id
                      AND continuation.successor_command=child.command_payload->'payload'
                      AND continuation.source_command=runtime_source.command_payload->'payload'
                      AND continuation.source_command->>'repair_of_operation_id'=parent.operation_id
                      AND continuation.source_command->>'repair_result_asset_version_id'=NEW.repair_result_asset_version_id
                      AND (continuation.source_command->>'repair_number')::int=NEW.repair_number
                      AND (continuation.successor_operation_id IS NULL OR continuation.successor_operation_id=child.operation_id)
                      AND child.causation_operation_id=runtime_source.operation_id
                  )"""

def integrated_guard(statement, source_index):
    if 'CREATE OR REPLACE FUNCTION authority_planning_result_repair_guard' not in statement:
        return statement
    statement = statement.replace("parent.candidate_asset_version_id IS NULL AND op.status='FAILED_FINAL'", 'parent.candidate_asset_version_id IS NULL AND ' + dead_letter)
    statement = statement.replace('child.causation_operation_id=parent.operation_id OR NEW.runtime_continuation_id IS NOT NULL', 'child.causation_operation_id=parent.operation_id OR ' + registered_lineage)
    statement = statement.replace("source.status='CANCELLED'", "source.status IN ('CANCELLED','FAILED_FINAL','DEAD_LETTER')", 1) if source_index == 1 else statement
    statement = statement.replace("source.status IN ('CANCELLED','FAILED_FINAL')", "source.status IN ('CANCELLED','FAILED_FINAL','DEAD_LETTER')")
    statement = statement.replace('AND child.causation_operation_id=source.operation_id', 'AND ' + legacy_cause, 1)
    if source_index == 1:
        anchor = 'AND source_generation.repair_number=NEW.repair_number'
        statement = statement.replace(anchor, anchor + "\n                  AND (source.status='CANCELLED' OR " + capacity_proof + ')')
        statement = statement.replace(anchor, anchor + "\n                  AND source_generation.repair_of_candidate_id IS NOT DISTINCT FROM NEW.repair_of_candidate_id\n                  AND source_generation.repair_reason IS NOT DISTINCT FROM NEW.repair_reason")
    else:
        statement = statement.replace("(source.status='CANCELLED' OR (", "(source.status='CANCELLED' OR " + capacity_proof + " OR (")
    return statement

records = []
previous = '20261007_0159_planning_dead_letter_result_recovery'
for index, source_name in enumerate(source_names):
    module = importlib.import_module('novel_forge.storage.migrations.versions.' + source_name)
    suffix = source_name.split('_', 2)[2]
    new_id = f'20261007_{160+index:04d}_{suffix}'
    new_name = 'v' + new_id
    statements = [integrated_guard(item, index) for item in module.UPGRADE_STATEMENTS]
    content = ('from __future__ import annotations\n\n'
        + f'MIGRATION_ID = {new_id!r}\nDOWN_REVISION = {previous!r}\n'
        + 'FORWARD_ONLY = True\nBACKUP_REQUIRED = True\n'
        + f'FORWARD_FIX = {module.FORWARD_FIX!r}\n\nUPGRADE_STATEMENTS = [\n'
        + ''.join('    r"""' + statement + '""",\n' for statement in statements)
        + ']\nDOWNGRADE_STATEMENTS: list[str] = []\n')
    (versions / (new_name + '.py')).write_text(content)
    path = f'src/novel_forge/storage/migrations/versions/{source_name}.py'
    blob = subprocess.check_output(['git','-C',str(root),'rev-parse',f'ad1c229d:{path}'],text=True).strip()
    records.append(dict(old_id=module.MIGRATION_ID,new_id=new_id,source_commit='ad1c229d4b17db45fa14c73dcc6569e8655c82c9',source_blob=blob,disposition='PORT_DELTA_COMPOSE_MAIN_GUARDS'))
    previous = new_id

registry = versions / '__init__.py'
text = registry.read_text()
anchor = '    v20261007_0159_planning_dead_letter_result_recovery,\n'
text = text.replace(anchor, anchor + ''.join('    v' + item['new_id'] + ',\n' for item in records))
registry.write_text(text)
manifest = root / 'architecture/manifests/migration-manifest.yaml'
payload = json.loads(manifest.read_text())
payload['migration_ids'].extend(item['new_id'] for item in records)
payload['head'] = records[-1]['new_id']
manifest.write_text(json.dumps(payload,indent=2)+'\n')
(Path(__file__).parent/'migration-identity-map.json').write_text(json.dumps(records,indent=2)+'\n')
