import json,pathlib
r=pathlib.Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
def read(p): return json.loads((r/p).read_text())
def save(p,d): (r/p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
ai=read('architecture/manifests/ai-instruction-manifest.yaml')
embedded=next(s for s in ai['sources'] if s['id']=='runtime-embedded-instructions')['patterns']
for p in ['src/novel_forge/modules/story_planning_runtime/world_preparation.py','src/novel_forge/modules/chapter_authority/candidate_repair.py']:
 if p not in embedded:embedded.append(p)
save('architecture/manifests/ai-instruction-manifest.yaml',ai)
q=read('architecture/manifests/backend-qualification-manifest.yaml')
for p in ['tests/integration/test_creative_validation_integration_upgrade_postgres.py','tests/unit/test_migration_history_admission.py']:
 if p not in q['semantic_slices']['migration_matrix']:q['semantic_slices']['migration_matrix'].append(p)
q['semantic_slices']['creative_validation_bounded_recovery']=[
 'tests/unit/test_derived_step_revalidation.py','tests/unit/test_book_execution_recovery.py','tests/unit/test_native_stage_repair_bound.py','tests/unit/test_native_planning_repair_routing.py',
 'tests/unit/test_creative_execution_template.py','tests/unit/test_codex_execution_evidence.py','tests/unit/test_planning_runtime_continuation.py','tests/unit/test_cost_aware_routing.py',
 'tests/unit/test_world_causal_preparation.py','tests/unit/test_creation_coordination.py','tests/integration/test_synthesis_formation_postgres.py','tests/integration/test_creation_cli_postgres.py',
 'tests/integration/test_external_effect_runtime_postgres.py','tests/integration/test_creative_validation_admission_postgres.py']
save('architecture/manifests/backend-qualification-manifest.yaml',q)
t=read('architecture/manifests/test-manifest.yaml')
rules=[
 {'id':'creative-recovery-derived-contract','patterns':['tests/unit/test_derived_step_revalidation.py'],'classification':'CURRENT_RUNTIME_CONTRACT','owner':'command-kernel','capability':'creative-validation-bounded-recovery','production_target':'src/novel_forge/modules/command_kernel/derived_step_revalidation.py','qualification_role':'CURRENT_BUSINESS_SUPPORT','proof_ceiling':'IN_PROCESS_CONTRACT_ONLY'},
 {'id':'creative-recovery-controlled-protocol','patterns':['tests/unit/test_book_execution_recovery.py','tests/unit/test_native_stage_repair_bound.py','tests/unit/test_native_planning_repair_routing.py'],'classification':'FIXTURE_PROTOCOL','owner':'runtime-authorities','capability':'creative-validation-bounded-recovery','production_target':'AUTO_FROM_TEST_IMPORTS','qualification_role':'CURRENT_BUSINESS_SUPPORT','proof_ceiling':'FIXTURE_CONTROL_ONLY'},
 {'id':'creative-validation-integration-upgrade','patterns':['tests/integration/test_creative_validation_integration_upgrade_postgres.py','tests/unit/test_migration_history_admission.py'],'classification':'MIGRATION_COMPATIBILITY','owner':'migration-authority','capability':'fresh-install-and-supported-upgrade','production_target':'src/novel_forge/storage/migrations/runner.py','qualification_role':'COMPATIBILITY_ONLY','proof_ceiling':'MIGRATION_COMPATIBILITY_ONLY'}]
existing={x['id'] for x in t['classification_rules']};t['classification_rules']= [x for x in rules if x['id'] not in existing]+t['classification_rules']
t['semantic_slice_policy']['creative_validation_bounded_recovery']={'role':'CURRENT_BUSINESS_CAPABILITY','production_targets':['src/novel_forge/modules/command_kernel/derived_step_revalidation.py','src/novel_forge/modules/command_kernel/step_successor.py'],'proof_ceiling':'CURRENT_CONTRACT_NO_REAL_PROVIDER'}
save('architecture/manifests/test-manifest.yaml',t)
p=read('architecture/manifests/production-entry-manifest.yaml')
existing={x['name'] for x in p['entries']}
for name,mod,call in [
 ('story_planning.result_admission.recover','result_admission','register_result_admission_recovery'),
 ('story_planning.gateway_result.revalidate','gateway_result_recovery','_terminal_generation_replay'),
 ('story_planning.world_preparation.defer','world_optional','_terminal_generation_replay')]:
 if name not in existing:
  entry={'name':name,'source':'src/novel_forge/modules/story_planning_runtime/application.py','application_source':f'src/novel_forge/modules/story_planning_runtime/{mod}.py','classification':'transaction_command','dispatch':'inline_atomic','api_call':f'StoryPlanningGenerationApplication.{call}'}
  if mod=='result_admission':entry['definition_factory']='novel_forge.modules.story_planning_runtime.result_admission:definition_for'
  p['entries'].append(entry)
save('architecture/manifests/production-entry-manifest.yaml',p)
wpath=r/'architecture/manifests/worker-manifest.yaml';w=wpath.read_text();old='"name": "book-authority", "path": "src/novel_forge/workers/book_authority.py", "entrypoint": "novel_forge.workers.book_authority:cli", "deployment_unit": "book-authority-worker", "execution_class": "saga", "queue": "authority.book", "health": "postgres-worker-heartbeat"'
new=old+', "recovery_protocol": "native-creation-lease-cancellation-bounded-successor-v1", "retry_identity": "frozen-creation-reference-and-versioned-domain-successor"'
assert old in w;wpath.write_text(w.replace(old,new))
e=read('architecture/reality-evidence.json');e['migration_head']='20261007_0168_derived_step_revalidation'
newids=[
 '20261007_0160_planning_result_admission','20261007_0161_planning_capacity_lineage','20261007_0162_planning_input_order_recovery','20261007_0163_optional_world_continuation',
 '20261007_0164_gateway_result_revalidation','20261007_0165_stage_repair_policy','20261007_0166_failed_step_successor','20261007_0167_execution_contract_continuation','20261007_0168_derived_step_revalidation']
def ref(mod,sym):return {'path':f'src/novel_forge/modules/{mod}.py','symbol':sym}
def migration(mid):
 path=f'src/novel_forge/storage/migrations/versions/v{mid}.py'
 text=(r/path).read_text();loc=next(l for l in text.splitlines() if l.startswith('MIGRATION_ID ='))
 return {'path':path,'locator':loc,'id':mid}
pg=next(c for c in e['capabilities'] if c['concept']=='postgresql-persistence-and-migrations')
known={x['id'] for x in pg['migrations']}
for mid in newids:
 if mid not in known:pg['migrations'].append(migration(mid))
newcap={
 'concept':'creative-validation-bounded-recovery','fact_type':'CURRENT_RUNTIME_FACT','owner':'Domain recovery Authorities with Command Kernel successor lifecycle',
 'production_entries':[ref('book_authority/creation_runtime','drive_book'),ref('story_planning_runtime/application','StoryPlanningGenerationApplication._terminal_generation_replay')],
 'application':[ref('story_planning_runtime/result_admission','recover'),ref('story_planning_runtime/gateway_result_recovery','recover'),ref('story_planning_runtime/world_optional','follow_optional_failure'),ref('book_authority/execution_recovery','recover_timeout'),ref('chapter_authority/candidate_repair','recover_length_frontier'),ref('chapter_authority/derived_recovery','recover_derived_frontier')],
 'domain_symbols':[ref('story_planning_runtime/stage_repairs','stage_ordinal'),ref('chapter_quality_authority/revalidation','quality_revalidation_evidence'),ref('chapter_quality_authority/foundation_context','frozen_world_evidence')],
 'commands_operations':[ref('story_planning_runtime/application','StoryPlanningGenerationApplication.register_result_admission_recovery'),ref('command_kernel/step_successor','replace_failed_step'),ref('command_kernel/execution_window','continue_candidate_execution_window'),ref('command_kernel/derived_step_revalidation','replace_derived_step')],
 'state_ownership':{'owned_state':['Planning retained-result admission and continuation bindings','Kernel failed/derived step successor and execution-window journals','Book Chapter request replacement references'],
 'write_rule':'Command Kernel alone owns lifecycle journals; Planning and Book validate and mutate only their native domain records. Old terminal and accepted history remain immutable.',
 'evidence':[ref('command_kernel/step_successor','replace_failed_step'),ref('story_planning_runtime/result_admission','recover'),ref('book_authority/execution_recovery','recover_timeout')]},
 'mutation_boundary':[ref('command_kernel/step_successor','replace_failed_step'),ref('command_kernel/derived_step_revalidation','replace_derived_step'),ref('story_planning_runtime/result_admission','recover'),ref('book_authority/execution_recovery','recover_timeout')],
 'persistence':[{'path':'src/novel_forge/storage/authority_uow.py','symbol':'AuthorityUnitOfWork'},ref('command_kernel/step_successor','replace_failed_step'),ref('story_planning_runtime/result_admission','recover')],
 'migrations':[migration(mid)for mid in newids],
 'external_effects':{'mode':'INDIRECT','rule':'Local revalidation does not resend; admitted successors use ordinary governed Provider dispatch outside business transactions. Unknown outcomes require reconciliation.',
 'evidence':[ref('story_planning_runtime/execution','native_planning_repair_receipt'),ref('chapter_authority/execution_gateway','ProductionChapterExecutionGateway')]},
 'upstream_dependencies':['command-attempt-lease-fence','external-effect-provider-control','postgresql-persistence-and-migrations','book-production-coordination'],
 'downstream_consumers':['chapter-production-saga','review-revision-quality','book-chapter-acceptance'],
 'tests':[{'path':'tests/unit/test_derived_step_revalidation.py','symbol':'test_chapter_recovery_rejects_closed_foreign_or_cancelled_frontier'},
 {'path':'tests/unit/test_book_execution_recovery.py','symbol':'test_only_known_preprose_member_timeout_is_eligible'},
 {'path':'tests/unit/test_native_stage_repair_bound.py','symbol':'test_stage_ordinal_retains_world_spend_and_monotonic_counter_without_spending_main_repairs'},
 {'path':'tests/unit/test_migration_history_admission.py','symbol':'test_foreign_or_discontinuous_history_is_rejected_before_pending_ddl'}],
 'qualification_state':'WIRED','qualification_run_ids':[],'proof_ceiling':'STATIC_NATIVE_WIRING_NO_INTEGRATED_RELEASE_OR_REAL_PROVIDER_PROOF'}
assert all(c['concept']!=newcap['concept']for c in e['capabilities']);e['capabilities'].append(newcap)
e['semantic_constraints'].extend([
 {'id':'creative-stage-repair-versioned-bounds','classification':'CONFIGURABLE_POLICY','statement':'Frozen planning-route-repair.v1 retains its lineage-wide bound; new v2 receipts bind explicit creative v4-v6 policy, Provider stage, stage ordinal and complete unchanged input scope. Per-stage two and global four repairs do not reset counters or replace dispatch-time native admission. Historical branch evidence is readable only.','design_review_required':False,'evidence':[ref('story_planning_runtime/execution','native_planning_repair_receipt'),ref('story_planning_runtime/stage_repairs','stage_ordinal')]},
 {'id':'migration-history-prefix-admission','classification':'CURRENT_RUNTIME_FACT','statement':'Pending migration DDL accepts only an exact prefix of the registered main identity chain. Foreign branch IDs and holes are refused; applied IDs and published migrations are not rewritten.','design_review_required':False,'evidence':[{'path':'src/novel_forge/storage/migrations/runner.py','symbol':'pending_migrations'},{'path':'tests/unit/test_migration_history_admission.py','symbol':'test_foreign_or_discontinuous_history_is_rejected_before_pending_ddl'}]},
 {'id':'creative-successor-live-unaccepted-frontier','classification':'CURRENT_RUNTIME_FACT','statement':'Versioned Chapter and derived recovery requires the original actor and exact live unaccepted frontier, settled Effects and no held lease or committed downstream state. Book and Group update references; Kernel preserves terminal lifecycle and charges.','design_review_required':False,'evidence':[ref('command_kernel/step_successor','require_live_chapter_frontier'),ref('command_kernel/derived_step_revalidation','replace_derived_step')]}])
save('architecture/reality-evidence.json',e)
print('Updated assigned manifests/reality; preserved main historical qualification records and projection_source digest for final root refresh.')
