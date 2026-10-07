import json, hashlib, subprocess
from pathlib import Path
root=Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
out=Path('/tmp/novel-forge-pr133-audit-20261007/implementation')
p=out/'source-adjudication.json'
d=json.loads(p.read_text())
main=d['fixed_sources']['main']; source=d['fixed_sources']['pr133']
protected=['files','commits','overlaps','text_conflicts','migrations','counts','fixed_sources']
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
original={k:canonical(d[k]) for k in protected}
backup=out/'source-adjudication.original-source-verdicts.json'
if not backup.exists():backup.write_bytes(p.read_bytes())
def git(*args):return subprocess.check_output(['git','-C',str(root),*args])
def blob(ref,path):
 try:data=git('show',f'{ref}:{path}')
 except subprocess.CalledProcessError:return None
 return {'git_blob':git('rev-parse',f'{ref}:{path}').decode().strip(),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
def working(path):
 f=root/path
 if not f.exists():return None
 data=f.read_bytes();return {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
original_paths={x['path'] for x in d['files']}
groups=[
 ('planning_serialization_contract_successor', 'Planning 1.19.0 / Pack 2.11.0 / Prompt v9 / chapter-mission-scene.v4 / runtime projection 3.0.0 / activated-chapter-plan.v3 / work-v4. Frozen 1.18 Pack 2.10, Prompt v8, Mission v3 and work-v3 remain version selected; forward identities repair exact rendered Provider serialization mismatches rather than rewriting published contracts.',[
 'src/novel_forge/modules/story_planning_runtime/domain.py','src/novel_forge/modules/story_planning_runtime/execution.py','src/novel_forge/modules/story_planning_runtime/application.py','src/novel_forge/modules/story_planning_runtime/binder.py','src/novel_forge/modules/story_planning_runtime/result_recovery.py','src/novel_forge/modules/story_planning_runtime/gateway_result_recovery.py','src/novel_forge/modules/story_planning_runtime/result_admission.py','src/novel_forge/modules/hierarchical_planning/chapter_contracts.py','src/novel_forge/modules/hierarchical_planning/domain.py','src/novel_forge/modules/capability_packs/longform_profiles.py','config/capability_packs/artifacts/story_planning_system_instruction_v9.md','tests/unit/test_story_planning_runtime.py','tests/unit/test_work_intent_residuals.py']),
 ('chapter_plan_serialization_successor', 'Plan materialization 3.9.16 and current Pack 2.26.0 carry Mission v4 projection through authoritative-chapter-plan-v5 and draft-plan-view-v4 into native ExecutionIntent. Earlier 3.9.1/Pack 2.25 and historical plan/view versions retain frozen definitions.',[
 'src/novel_forge/modules/chapter_authority/chapter_plan_views.py','src/novel_forge/modules/chapter_authority/execution_artifacts.py','src/novel_forge/modules/chapter_authority/definitions.py','src/novel_forge/modules/chapter_authority/handlers.py','src/novel_forge/modules/chapter_authority/realization_composition.py','src/novel_forge/modules/chapter_authority/contracts.py','config/capability_packs/chapter_generation_pack.json','config/capability_packs/artifacts/chapter_generation_contract_catalog.json','tests/unit/test_chapter_authority_definitions.py','tests/unit/test_work_realization_contract.py','tests/unit/test_capability_pack_resolution_compiler.py']),
 ('frozen_world_native_qualification_bridge', 'Independent narrative-design-evaluation PASS is accepted only with exact same project/Book/World/hash, independent successful native evaluation output, native APPROVE receipt and successful original ACTIVATE identity. The exact approval asset is retained as frozen Quality input; missing proof, foreign identity and FAIL stay blocked.',[
 'src/novel_forge/modules/chapter_quality_authority/foundation_context.py','src/novel_forge/modules/chapter_authority/orchestrator.py','src/novel_forge/modules/chapter_authority/scheduler.py','src/novel_forge/modules/chapter_authority/handlers.py','tests/unit/test_quality_frozen_world_foundation.py']),
 ('production_ports_and_owned_policy', 'API composition injects Planning receipt resolver and frozen legacy-evidence validator into production Router. Native retained-output file/process/hash verification is a pure production reader; Planning owns schema and semantic validation. Execution-template mutation moves to owning authority policy command with existing CLI/creation callers. Genuine pure command-definition factories are reused by runtime and manifest, rather than manifest-only stubs.',[
 'src/novel_forge/api/authority_dependencies.py','src/novel_forge/modules/production_execution/routing_runtime.py','src/novel_forge/modules/production_execution/rejected_output.py','src/novel_forge/modules/story_planning_runtime/gateway_result_recovery.py','src/novel_forge/modules/authority_handler_runtime/policy_commands.py','src/novel_forge/modules/production_execution/execution_template.py','src/novel_forge/cli/execution_template.py','src/novel_forge/modules/book_authority/creation_runtime.py','src/novel_forge/modules/story_planning_runtime/result_admission.py','src/novel_forge/modules/story_planning_runtime/world_optional.py','architecture/manifests/production-entry-manifest.yaml']),
 ('production_legacy_pre_database_denial', 'Exact-main offline counterexample proved dispatch read persisted Effect before rejecting uncontrolled legacy adapters. Integration appends pre-database execution-mode denial while preserving frozen blob-storage admission below; no Provider call or database connection was used in the baseline proof.',[
 'src/novel_forge/modules/command_kernel/external_effect_runtime.py','tests/architecture/test_repository_execution_boundaries.py']),
 ('exact_main_fixture_alignment', 'Read-only exact-main reproduced 18 unit/architecture failures plus Book acceptance wrong error-code assertion. Fixture repairs align current receipt SQL rows, scope/control metadata, frozen model/reference contracts and literal ownership assertions with existing implementation; immutable baseline FAIL logs retained. Execution-plane dependency corrections are production ports in the separate group, not fixture weakening.',[
 'tests/unit/test_narrative_search_branch_registration.py','tests/unit/test_cross_chapter_prose_review.py','tests/unit/test_runtime_dispatch_control.py','tests/unit/test_story_formation_worker_wait.py','tests/unit/test_chapter_agent_binding_boundary.py','tests/unit/test_creation_runner_settings.py','tests/unit/test_prose_reviewer_sampling.py','tests/architecture/test_capability_pack_authority_boundaries.py','tests/integration/test_book_to_chapter_authority_vertical_postgres.py']),
 ('integration_protection_and_checked_projection', 'Integration-specific migration/history/cancel/frozen-World protection tests and checked canonical projections retain WIRED ceiling, no qualification IDs and historical evidence. These supplement rather than modify original PR-source adjudication.',[
 'tests/integration/test_creative_validation_integration_upgrade_postgres.py','tests/integration/test_migration_history_admission_postgres.py','tests/unit/test_migration_history_admission.py','tests/unit/test_creation_recovery_control.py','tests/unit/test_quality_frozen_world_foundation.py','architecture/manifests/historical-reality-policy.yaml','architecture/manifests/backend-qualification-manifest.yaml','architecture/manifests/test-manifest.yaml','architecture/reality-evidence.json','docs/current-system.md','docs/runtime-operations.md'])]
records=[]
for name,rationale,paths in groups:
 entries=[]
 for path in paths:
  entries.append({'path':path,'in_original_132_path_verdicts':path in original_paths,'exists_currently':(root/path).exists(),'fixed_main':blob(main,path),'fixed_pr133':blob(source,path),'working_snapshot':working(path),'attribution':'INTEGRATION_FORWARD_FIX','qualification_upgrade':False})
 records.append({'id':name,'rationale':rationale,'paths':entries})
d['integration_forward_fixes']={'schema_version':'novel-forge.integration-forward-fixes.v1','snapshot_kind':'UNCOMMITTED_WORKING_TREE','base_sha':main,'source_sha':source,'current_head_sha':git('rev-parse','HEAD').decode().strip(),'final_commit_sha':'NOT_FROZEN','final_tree_sha':'NOT_FROZEN','evidence_ceiling':'WIRED_WITH_SCOPE_BOUND_TARGETED_ENGINEERING_CHECKS','original_source_verdicts_preserved':original,'groups':records,'no_new_run_authorization':True}
published=[]
for path in git('ls-tree','-r','--name-only',main,'src/novel_forge/storage/migrations/versions').decode().splitlines():
 if Path(path).name.startswith('v') and path.endswith('.py'):
  baseline=blob(main,path);now=working(path);published.append({'path':path,'fixed_main':baseline,'integration_working_snapshot':now,'byte_identical':now is not None and baseline['sha256']==now['sha256']})
report={'schema_version':'novel-forge.published-migration-byte-proof.v1','fixed_main_sha':main,'scope':'All fixed-main v*.py migration bodies; mutable registration __init__.py is excluded','published_count':len(published),'all_byte_identical':all(x['byte_identical'] for x in published),'files':published,'new_migration_mapping':d['migrations'],'old_branch_identity_retained':True,'real_provider':'NOT_RUN','ddl':'NOT_RUN'}
(out/'published-migration-byte-proof.json').write_text(json.dumps(report,indent=2)+'\n')
d['published_migration_byte_proof']={'path':str(out/'published-migration-byte-proof.json'),'published_count':len(published),'all_byte_identical':report['all_byte_identical'],'old_nine_mapping_retained':True}
d['implementation_baseline_evidence']=[{'scope':'exact fixed-main untouched unit/architecture matrix','result':'18_FAIL_79_PASS','path':str(out/'fixed-main-untouched-counterexamples.log'),'qualification':False},{'scope':'exact fixed-main Book acceptance fixture code assertion','result':'FAIL_EVIDENCE_MISSING_VS_EXPECTED_NOT_READY','path':str(out/'fixed-main-book-acceptance.log'),'own_database':'REMOVED','qualification':False},{'scope':'exact fixed-main legacy adapter denial before DB read','result':'FAIL_READ_BEFORE_DENIAL_OFFLINE_SENTINEL','path':str(out/'fixed-main-legacy-guard.log'),'external_io':'NOT_RUN','qualification':False},{'scope':'integration baseline fixture repair focused matrix','result':'99_PASS','path':str(out/'baseline-fixture-repair.log'),'qualification':False}]
assert {k:canonical(d[k]) for k in protected}==original
assert len(d['files'])==132 and len(d['commits'])==32 and len(d['overlaps'])==24 and len(d['text_conflicts'])==17 and len(d['migrations'])==9
p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'original_verdict_hashes_unchanged':True,'published_migrations':len(published),'byte_identical':report['all_byte_identical'],'forward_fix_groups':len(records)}))
