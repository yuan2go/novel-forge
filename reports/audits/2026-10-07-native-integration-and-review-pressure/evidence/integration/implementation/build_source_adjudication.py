import subprocess,json,re,hashlib,pathlib
repo='/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge'
out=pathlib.Path('/tmp/novel-forge-pr133-audit-20261007/implementation')
root=out.parent
base='e2064ede68920f680204c40486bf69f1901fb770';main='f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609';source='ad1c229d4b17db45fa14c73dcc6569e8655c82c9'
def git(*args,check=True):return subprocess.run(['git',*args],cwd=repo,capture_output=True,check=check).stdout.decode()
def blob(ref,path):
 p=subprocess.run(['git','show',f'{ref}:{path}'],cwd=repo,capture_output=True)
 if p.returncode:return None
 b=p.stdout
 return {'git_blob':git('rev-parse',f'{ref}:{path}').strip(),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
paths=root.joinpath('pr133-paths.txt').read_text().splitlines();paths132=set(root.joinpath('pr132-paths.txt').read_text().splitlines());overlaps=sorted(set(paths)&paths132)
preview=out.joinpath('three-way-conflict-preview.txt').read_text();path=None;conflicts=[]
for line in preview.splitlines():
 m=re.match(r'  (?:our|their)\s+\d+ [a-f0-9]+ (.+)',line)
 if m:path=m.group(1)
 if '<<<<<<<' in line and path not in conflicts:conflicts.append(path)
assert len(paths)==132 and len(overlaps)==24 and len(conflicts)==17
specific={
'architecture/manifests/migration-manifest.yaml':('PORT_DELTA','Retain main published head and 0157-0159; regenerate contiguous 0160-0168 chain; old branch chain remains immutable historical input.'),
'architecture/reality-evidence.json':('PORT_DELTA','Regenerate checked projection from integrated owner/entrypoint/tests; retain native production closure topology and evidence ceilings.'),
'docs/current-system.md':('PORT_DELTA','Reconcile canonical semantics with actual integrated owner contracts; retain current main unresolved constraints and evidence ceilings.'),
'docs/runtime-operations.md':('PORT_DELTA','Reconcile migration head and bounded recovery operating commands; main cancellation, lease, capacity and P0 rules retain priority.'),
'src/novel_forge/cli/creation.py':('KEEP_MAIN','Retain main start/continue/cancel and scoped worker lease path; port only necessary actor binding and bounded recovery access.'),
'src/novel_forge/modules/book_authority/creation_runtime.py':('KEEP_MAIN','Keep main execution_probe, continuation_live, cancellation reconciliation, scoped formation scheduling and deadlines; add bounded recovery hooks only after these checks.'),
'src/novel_forge/modules/book_authority/production.py':('KEEP_MAIN','Retain main atomic acceptance, cancellation and query behavior; add versioned reconciliation keys and proven same-scope successor journal resolution.'),
'src/novel_forge/modules/command_kernel/external_effect_runtime.py':('KEEP_MAIN','Keep main FAILED_FINAL plus DEAD_LETTER known-success reader and unresolved-effect block; port rejected-result and native successor readers without mutating Effects.'),
'src/novel_forge/modules/command_kernel/worker_execution.py':('KEEP_MAIN','Keep model capacity metadata UNKNOWN as MANUAL_INTERVENTION and repair bound as owner wait; port deterministic World local failures before generic UNKNOWN; true external UNKNOWN still blocks.'),
'src/novel_forge/modules/production_execution/routing_runtime.py':('KEEP_MAIN','Keep sole main governed_repair native receipt construction and dispatch-time revalidation; add stage and complete role-artifact scope evidence; do not authorize via a parallel branch-native rule.'),
'src/novel_forge/modules/production_execution/planning_repair_routing.py':('RETIRE_DUPLICATE','Retire parallel new-run route authorization; preserve versioned historical evidence codec and port stage ordinal/role-artifact checks into main governed repair path.'),
'src/novel_forge/modules/story_planning_runtime/result_recovery.py':('KEEP_MAIN','Main raw-result repair is equivalent core and preserves DEAD_LETTER plus unresolved Effect guard; port exact Context/author projection and legal admission mode only.'),
'src/novel_forge/modules/story_planning_runtime/runtime_continuation.py':('KEEP_MAIN','Keep main PRE_SEND_CAPACITY path, two-successor limit, framing/output allowance and repair-origin cause; add exact raw/preflight branches without generalizing terminal states.'),
'src/novel_forge/modules/story_planning_runtime/world_preparation.py':('KEEP_MAIN','Keep main typed transition, causal rejection reproduction, Director settled receipt and retained selected action; port exact references, local checkpoint and explicit OPTIONAL deferral only.'),
'src/novel_forge/modules/story_planning_runtime/world_result_recovery.py':('RETIRE_DUPLICATE','Retire branch parallel typed/causal repair permission; preserve compatible helper evidence and add precise identifier/schema checkpoint diagnostics to main selected-action recovery.'),
'src/novel_forge/modules/worldbuilding/production_schema.py':('KEEP_MAIN','Keep main native typed time/causal payload semantics; add exact Arc/obligation references and reject unknown identities without relaxing hard predicates.'),
'src/novel_forge/storage/migrations/versions/__init__.py':('KEEP_MAIN','Retain every main published migration blob and register new contiguous 0160-0168 identities after main0159; never import old branch 0157-0165.'),
'src/novel_forge/modules/story_planning_runtime/application.py':('KEEP_MAIN','Preserve main operation admission/replay, single recovery owner and capacity wiring; add lawful Foundation admission, input-order, stage and local gateway entrypoints.'),
'src/novel_forge/modules/story_planning_runtime/execution.py':('KEEP_MAIN','Preserve main native receipt and lineage construction; add stage evidence without resetting monotonic repair_number or changing immutable v1 receipt semantics.'),
'src/novel_forge/modules/story_planning_runtime/foundation_generation.py':('KEEP_MAIN','Preserve main Foundation production execution and exact retained-result handling; add valid result-admission Candidate creation with no new send and ordinary author approval.'),
'src/novel_forge/modules/story_planning_runtime/result_admission.py':('PORT_DELTA','Add LOCAL_OPERATOR lawful retained Foundation result admission: exact frozen Context/Pack/Fence/input, settled success, explicit reason, CANDIDATE/INELIGIBLE, zero resend.'),
'src/novel_forge/modules/story_planning_runtime/preflight_continuation.py':('PORT_DELTA','Add exact zero-send input-order/blocked-route preflight evidence with same role-artifact map and route/account/counter bindings; main capacity source remains a distinct cause.'),
'src/novel_forge/modules/story_planning_runtime/gateway_result_recovery.py':('PORT_DELTA','Add local literal-null result revalidation from complete original process/result/schema/hash receipt; retain failed terminal history, cost and no additional send.'),
'src/novel_forge/modules/story_planning_runtime/world_optional.py':('PORT_DELTA','Add explicit REQUIRED/OPTIONAL/DISABLED governed policy and settled DEFER; accepted preparation commitments, actor experiments and causal/malformed rejection remain blocked.'),
'src/novel_forge/modules/story_planning_runtime/stage_repairs.py':('PORT_DELTA','Add authorized v4-v6 per-stage ordinal with monotonic global counter, two stage repairs/four total; v1-v3 retain old frozen policy and UNKNOWN stops.'),
'src/novel_forge/modules/book_authority/execution_recovery.py':('PORT_DELTA','Add settled known member Memo timeout replacement through Kernel cancellation, Book request append and Group reference update; accepted/prose/success/live/UNKNOWN reject.'),
'src/novel_forge/modules/command_kernel/step_successor.py':('PORT_DELTA','Add durable same-scope failed Saga step successor journal preserving terminal old step, successful siblings, actual fees and native lifecycle ownership.'),
'src/novel_forge/modules/command_kernel/execution_window.py':('PORT_DELTA','Add authorized bounded unfinished root window continuation with before/after journal, child timeout/no-progress evidence and unchanged author deadline.'),
'src/novel_forge/modules/command_kernel/derived_step_revalidation.py':('PORT_DELTA','Add exact v6 derived correction journal preserving old successful output/Effects and rejecting accepted/downstream/held/UNKNOWN scope.'),
'src/novel_forge/modules/chapter_authority/candidate_repair.py':('PORT_DELTA','Add scene/information/review/length and no-send Canon capacity/protocol successors preserving measured frozen candidate inputs, counters, sibling successes and normal quality gates.'),
'src/novel_forge/modules/chapter_authority/contract_recovery.py':('PORT_DELTA','Add versioned scene-core realization recovery with exact frozen Memo/Context and failed-step successor; no blanket resampling.'),
'src/novel_forge/modules/chapter_authority/derived_recovery.py':('PORT_DELTA','Add unaccepted-frontier Canon/Quality revalidation routed through Kernel durable evidence; preserve atomic Book acceptance and original successful Effects.'),
'src/novel_forge/modules/chapter_quality_authority/revalidation.py':('PORT_DELTA','Add v6 grounded Canon/applicability correction from exact frozen contracts and sources; prevent accepted frontier or downstream state mutation.'),
'src/novel_forge/modules/production_execution/codex_configuration.py':('PORT_DELTA','Add exact nullable wire schema projection and strict canonical transport decode/hash evidence; host canonical schema remains authoritative.'),
'src/novel_forge/modules/production_execution/backends.py':('PORT_DELTA','Add frozen canonical JSON transport decode followed by normal host validation; preserve accountable process and Provider completion evidence.'),
'src/novel_forge/storage/world_preparation_repositories.py':('PORT_DELTA','Persist optional preparation/reference evidence using main same-frontier and accepted-state guards; repositories remain UoW mechanics.'),
}
migration_map={
'20261006_0157_planning_result_admission':'20261007_0160_planning_result_admission',
'20261006_0158_planning_capacity_lineage':'20261007_0161_planning_capacity_lineage',
'20261006_0159_planning_input_order_recovery':'20261007_0162_planning_input_order_recovery',
'20261006_0160_optional_world_continuation':'20261007_0163_optional_world_continuation',
'20261006_0161_gateway_result_revalidation':'20261007_0164_gateway_result_revalidation',
'20261006_0162_stage_repair_policy':'20261007_0165_stage_repair_policy',
'20261006_0163_failed_step_successor':'20261007_0166_failed_step_successor',
'20261006_0164_execution_contract_continuation':'20261007_0167_execution_contract_continuation',
'20261007_0165_derived_step_revalidation':'20261007_0168_derived_step_revalidation'}

def classify(path):
 if path in specific:return specific[path]
 if '/storage/migrations/versions/v20' in path:
  old=path.rsplit('/v',1)[1][:-3]
  return 'HISTORICAL',f'Keep exact old source identity {old} and blob as history; port independent schema responsibility into {migration_map[old]} using explicit composed guards that retain main DEAD_LETTER/capacity causation; do not register old module.'
 if path.startswith('tests/'):
  name=path.rsplit('/',1)[-1]
  return 'PORT_DELTA',f'Port necessary regression deltas from {name}, retaining main test cases in overlapping files; rerun against integration and independently merge SHA, old PASS is source history only.'
 if path.startswith('architecture/'):
  return 'PORT_DELTA','Regenerate final checked instruction projection from integrated contract versions and blob hashes; no source history becomes runtime reachability evidence.'
 if path.startswith('config/capability_packs/'):
  return 'PORT_DELTA','Port new Chapter contract/Pack/template versions with exact deployment and materialization hashes; preserve historical frozen versions and main native runtime policies.'
 if path.startswith('config/execution_templates/'):
  return 'PORT_DELTA','Port explicit creative v2-v6 policy successor settings with stage/window/World/Canon semantics; preserve strict and historical v1 policy.'
 if '/chapter_authority/' in path:
  return 'PORT_DELTA','Port Chapter contract/schema/version and successor runtime wiring; preserve frozen old sampling, Memo/Context inputs, native Context Router gates and accountable lifecycle.'
 if '/chapter_quality_authority/' in path:
  return 'PORT_DELTA','Port exact applicability/foundation/grounded quality context and revalidation semantics; human author disposition remains separate and accepted state does not change directly.'
 if '/capability_packs/' in path:
  return 'PORT_DELTA','Port new compatible Chapter Pack artifact/contracts/version admission; keep historical frozen contract materialization and all main deployment gates.'
 if '/canon_graph/' in path:
  return 'PORT_DELTA','Port versioned grounded Canon support taxonomy and exact legacy validation recovery; preserve actual source grounding and atomic accepted Canon authority.'
 if '/story_design_authority/' in path:
  return 'PORT_DELTA','Port explicit creative policy/author projection checks; raw generator output remains Candidate and Story Design owns semantic approval.'
 if '/production_execution/' in path:
  return 'PORT_DELTA','Port exact backend/capacity/template contract metadata and compatible successor policy; retain main single native routing admission, cost and UNKNOWN boundaries.'
 if '/authority_handler_runtime/' in path:
  return 'PORT_DELTA','Port versioned closed policy configuration and repair feedback evidence; main native routing owner and original actor permission remain authoritative.'
 if '/command_kernel/' in path:
  return 'PORT_DELTA','Port required durable step/window/revalidation supporting integration while Kernel retains Attempt/Lease/Fence/Effect ownership and append-only history.'
 if '/revision/' in path:return 'PORT_DELTA','Port measured frozen length correction requirements and exact candidate recovery inputs; keep normal revision/quality admission gates.'
 if '/review/' in path:return 'PORT_DELTA','Port review scope evidence based on cards actually delivered; correction retains old receipt and normal quality gates.'
 if '/hierarchical_planning/' in path:return 'PORT_DELTA','Port explicit stage repair and actor-aware rejected-plan continuation; active typed plan changes remain Hierarchical Planning-owned.'
 return 'PORT_DELTA','Port reviewed branch delta only with native main Authority/accepted-state and cancellation boundaries; source blob is retained separately as historical evidence.'

commit_notes={
'679d3fe3':('KEEP_MAIN','Main owns capacity metadata MANUAL_INTERVENTION; retire branch output-capacity UNKNOWN final-failure classification. Retain only deterministic local classifier ordering additions.'),
'd8eadef4':('PORT_DELTA','Preserve explicit native validation reasoning authorization at exact task Context gate; retain main membership/runtime continuation authorization.'),
'74e98e61':('KEEP_MAIN','Main raw invalid-result repair owns core behavior; add original Context/hash author-adoption diagnostics rather than parallel recovery authority.'),
'8cc07dff':('PORT_DELTA','Add valid retained Foundation result admission without resend; map old0157 to new0160 and preserve author approval.'),
'bea12793':('PORT_DELTA','Add durable generation runtime continuation lineage/counter preservation; map old0158 to new0161 and keep main capacity cause registration.'),
'0265c69a':('RETIRE_DUPLICATE','Retire branch independent repair routing permission for new calls; port explicit bounded policy and evidence scope checks into main governed_repair.'),
'c3ce9ac6':('PORT_DELTA','Version expanded closed creative policy configuration, retaining immutable earlier definition versions.'),
'fcf0a3ac':('PORT_DELTA','Preserve exact ordered input hashes/role-artifact map and terminal history for zero-send input-order successor; map old0159 to new0162.'),
'7e8ed101':('PORT_DELTA','Replay unselected completed candidates and admission successors across releases without mutating their admitted payloads or sending again.'),
'91c92efc':('KEEP_MAIN','Main typed World payload and causal repair already own main behavior; port precise contract/reference rejection diagnostics only.'),
'b6f6b0da':('PORT_DELTA','Port exact World Arc/obligation references and settled local checkpoint recovery while retaining main causal rejection/Director receipt/action reuse.'),
'eec2bd5f':('PORT_DELTA','Add explicit optional future World preparation and settled DEFER; map old0160 to new0163 with accepted dependency and strict gates.'),
'9731beac':('PORT_DELTA','Add local complete frozen Codex literal-null revalidation without resend; map old0161 to new0164 and preserve terminal cost/history.'),
'5fd172e2':('PORT_DELTA','Add v4 per-provider stage ordinal and finite allowance; map old0162 to new0165, retaining global counters and main native route authority.'),
'26f15b10':('PORT_DELTA','Original Planning actor owns execution authorization; scheduling worker lease must not become author/operator authority.'),
'edb519a4':('PORT_DELTA','Version Memo execution and add known pre-prose timeout Book replacement; preserve settled member grant, old fee and live/UNKNOWN refusal.'),
'26802dd1':('PORT_DELTA','Retain frozen sampling/Chapter historical codecs and define Chapter3.9 successors rather than rewrite older contracts.'),
'a3b52ff3':('PORT_DELTA','Add exact versioned scene-core successor with Memo/Context reuse; map old0163 to new0166 and preserve old step/siblings.'),
'd84a0927':('PORT_DELTA','Port exact scene information-flow repair and settled candidate successor journals; do not erase successful evidence.'),
'a66f6a96':('PORT_DELTA','Bind review judgments to actually delivered knowledge cards and repair only rejected review scope.'),
'f8a251c7':('PORT_DELTA','Bind chapter length correction to measured frozen requirements and actual latest candidate.'),
'fa0effce':('PORT_DELTA','Continue only bounded length retry with native successor, accountable costs and no repair counter reset.'),
'e5ba260b':('PORT_DELTA','Add bounded execution-window/no-send recovery evidence; map old0164 to new0167, preserve real author deadline and no-progress bound.'),
'b8776495':('PORT_DELTA','Version Book reconciliation status keys and require native same-scope successor evidence for supersession.'),
'c75ef53f':('PORT_DELTA','Factor exact Canon provider schemas and no-send capacity successor; native Pack/deployment gates remain required.'),
'7606a14d':('PORT_DELTA','Version Pack successor for no-send Canon capacity failure without reusing failed historical execution identity.'),
'90a5eff0':('PORT_DELTA','Preserve nullable canonical Schema semantics and resume accounted Canon retry with exact reversible wire evidence.'),
'2c2447c8':('PORT_DELTA','Preserve terminal Canon protocol failures via versioned schema successors; no terminal Effect rewrite.'),
'fe0d06a9':('PORT_DELTA','Strict canonical JSON transport decode plus host schema validation; exact receipt recovery preserves original Provider result/fee.'),
'9a154f25':('PORT_DELTA','Bind independent Canon support taxonomy and settled legacy reviews without accepting invented support or bypassing independence.'),
'ed56a46a':('PORT_DELTA','Version grounded Canon validation and exact affected derived quality revalidation; map old0165 to new0168.'),
'ad1c229d':('PORT_DELTA','Repair internal quality disposition and frozen World assessment interpretation while preserving accepted frontier and main selected action.'),
}
commits=[]
for line in git('log','--reverse','--format=%H%x09%s',f'{base}..{source}').splitlines():
 sha,subject=line.split('\t',1);category,rationale=commit_notes[sha[:8]]
 cp=git('diff-tree','--no-commit-id','--name-only','-r',sha).splitlines()
 commits.append({'commit':sha,'subject':subject,'decision':category,'rationale':rationale,'changed_paths':cp,'source_blobs':{p:blob(sha,p) for p in cp},'historical_commit_retained':True})
assert len(commits)==32
files=[]
for path in paths:
 category,rationale=classify(path)
 item={'path':path,'decision':category,'rationale':rationale,'source':blob(source,path),'main':blob(main,path),'ancestor':blob(base,path),'overlap_pr132':path in overlaps,'text_conflict':path in conflicts,'contributing_commits':[c['commit'] for c in commits if path in c['changed_paths']],'source_content_evidence':str(root/'pr133'/path),'main_content_evidence':str(root/'main'/path),'new_run_authorization_from_branch':False if category=='RETIRE_DUPLICATE' else 'requires integrated native admission'}
 if '/storage/migrations/versions/v20' in path:
  old=path.rsplit('/v',1)[1][:-3];item['old_migration_id']=old;item['new_migration_id']=migration_map[old]
 files.append(item)
protection_log=(out/'main-native-protection-baseline.log').read_text()
summary=protection_log.splitlines()[-1]
payload={'schema_version':'pr133-source-adjudication.v1','fixed_sources':{'main':main,'pr133':source,'merge_base':base},'evidence_ceiling':'EXECUTABLE_OFFLINE_UNIT_FOR_LISTED_TESTS_ONLY','source_mapping_scope':'32 original commits and 132 final PR changed paths; no original commit or blob rewritten','counts':{'commits':32,'paths':132,'overlaps':24,'text_conflicts':17},'files':files,'commits':commits,'overlaps':[{'path':p,'decision':classify(p)[0],'rationale':classify(p)[1]} for p in overlaps],'text_conflicts':[{'path':p,'decision':classify(p)[0],'rationale':classify(p)[1]} for p in conflicts],'migrations':[{'old_id':old,'new_id':new,'source_commit':source,'source_blob':blob(source,f'src/novel_forge/storage/migrations/versions/v{old}.py'),'historical_identity_retained':True}for old,new in migration_map.items()],'baseline_evidence':[
{'run':'contract-counterexamples','source_sha':main,'state':'FAIL_EXPECTED','result':'5 failed, 5 passed','log':str(out/'baseline-contract-counterexamples.log'),'scope':'Existing main codex_output_schema nullable object/enum/const behavior and closed template validator against precise source tests. Offline functions only, no provider sends.'},
{'run':'migration-preflight-counterexamples','source_sha':main,'state':'FAIL_EXPECTED','result':'2 failed','log':str(out/'baseline-migration-preflight-counterexamples.log'),'scope':'pending_migrations executable helper accepts a foreign old-branch ID and a hole ledger. No database, no DDL proof.'},
{'run':'main-native-protection','source_sha':main,'state':'PASS','result':summary,'log':str(out/'main-native-protection-baseline.log'),'scope':'Native capacity/cancellation/worker/World protection offline unit cases. Not production or integration proof.'}],
'integration_hazards':[
'Branch result_recovery removes DEAD_LETTER and unresolved Effect check; retain main exact terminal recovery guards.',
'Branch runtime_continuation removes main PRE_SEND_CAPACITY implementation and restricts FAILED_FINAL to input-order; compose mutually exclusive source modes rather than replace.',
'Branch world_preparation removes main validate_retained_generation, causal Director receipt/reproduction and retained_action; preserve these and do not convert causal/malformed refusal into optional DEFER.',
'Branch creation_runtime removes execution_probe, continuation_live, cancellation reconciliation and scoped scheduling; retain main and bound every recovery loop with deadline/ticks/progress/cancellation/lease.',
'Frozen planning-route-repair.v1 global limit must not silently become per-stage; add a receipt version and keep historical codec.',
'New migration guards must preserve main0159 DEAD_LETTER and main0158 registered capacity-cause behavior at every intermediate head.',
'Legacy branch ledger requires fail-closed pre-DDL prefix validation; never rewrite ledger or auto-convert source schema.'],
'real_provider':'NOT_RUN','database_or_services':'NOT_RUN','integrated_verification':'NOT_RUN','merge_sha_verification':'NOT_RUN'}
out.joinpath('source-adjudication.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'output':str(out/'source-adjudication.json'),'counts':payload['counts'],'main_protection':summary},ensure_ascii=False))
