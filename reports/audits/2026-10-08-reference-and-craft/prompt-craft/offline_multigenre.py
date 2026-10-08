from pathlib import Path
import sys,json,socket,subprocess,os,builtins,io,hashlib
A=Path(__file__).parent;R=A/'main';E=A/'evidence';sys.dont_write_bytecode=True;sys.path.insert(0,str(R/'src'))
def deny(*a,**k):raise RuntimeError('AUDIT_EXTERNAL_IO_BLOCKED')
socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny;subprocess.Popen=deny;os.system=deny
orig=builtins.open;iorig=io.open
def guard(fn):
 def f(path,mode='r',*args,**kw):
  if isinstance(path,(str,bytes,os.PathLike)) and any(x in mode for x in 'wax+'):
   p=Path(path).resolve()
   if A not in p.parents or p==R or R in p.parents:raise RuntimeError('AUDIT_WRITE_BLOCKED')
  return fn(path,mode,*args,**kw)
 return f
builtins.open=guard(orig);io.open=guard(iorig)
import psycopg
psycopg.connect=deny;psycopg.Connection.connect=deny
from novel_forge.modules.mkaos_authority.craft import core_catalog
from novel_forge.modules.mkaos_authority.craft_selection import craft_candidate_assessment,validate_craft_policy
from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed,select_narrative_intelligence
from novel_forge.modules.capability_pack_authority.application import _select_capability_skill
from novel_forge.modules.chapter_authority.prompt_methods import project_skill_method
from novel_forge.modules.chapter_authority.chapter_plan_views import _method_requirements
from novel_forge.modules.chapter_quality_authority.work_semantics import finalize_work_dimension
from novel_forge.modules.chapter_quality_authority.domain import _longitudinal_dimensions
cards=core_catalog();policy=validate_craft_policy();method=next(x for x in cards if x['mechanism_id']=='intentional-gap')
(E/'multigenre-core-catalog.json').write_text(json.dumps(cards,ensure_ascii=False,indent=2)+'\n')
checks=[]
def check(name,actual,expected):checks.append({'id':name,'actual':actual,'expected':expected,'pass':actual==expected})
assessment=[]
for name,context in [
 ('genre_only_xuanhuan',{'genre':['xuanhuan']}),
 ('genre_only_romance',{'genre':['romance']}),
 ('same_problem_xuanhuan',{'genre':['xuanhuan'],'style':['省去说明'],'pov':['limited']}),
 ('same_problem_romance',{'genre':['romance'],'style':['省去说明'],'pov':['limited']}),
 ('same_genre_first_person',{'genre':['xuanhuan'],'style':['省去说明'],'pov':['first_person']}),
 ('same_genre_omniscient',{'genre':['xuanhuan'],'style':['省去说明'],'pov':['omniscient']}),
 ('pov_only_first_person',{'pov':['first_person']}),
 ('pov_only_omniscient',{'pov':['omniscient']}),
]:
 result=craft_candidate_assessment(method,context=context,recent_usage=(),policy=policy);assessment.append({'case':name,'context':context,'score':result['score'],'rejection_reason':result['rejection_reason'],'match_reasons':result['match_reasons']})
bycase={x['case']:x for x in assessment}
check('genre_alone_matches_generic_gap',bycase['genre_only_xuanhuan']['rejection_reason'],'')
check('other_genre_alone_not_match',bycase['genre_only_romance']['rejection_reason'],'CRAFT_NO_CONTEXT_MATCH')
check('method_usable_in_other_genre_with_same_problem',bycase['same_problem_romance']['rejection_reason'],'')
empty=select_narrative_intelligence(NarrativeIntelligenceNeed(scope='STORY',target_stage='creative.candidates.generate'),())
check('no_optional_cards_not_a_domain_selection_error',len(empty['selected']),0)
try:select_narrative_intelligence(NarrativeIntelligenceNeed(scope='STORY',target_stage='creative.candidates.generate',required_card_asset_version_ids=('author-required-card',)),())
except Exception as ex:check('author_selected_required_card_keeps_gate',getattr(ex,'code',type(ex).__name__),'MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE')
p=json.load(open(E/'current-code-profiles.json'));bindings=p['story_planning_pack']['skill_binding']['skills']
selected=_select_capability_skill(bindings,capability_id='creative.proposal.generate',input_contract_ref='unmatched-audit-input',output_contract_ref='unmatched-audit-output')
check('generic_creative_skill_fallback_without_genre_skill',selected['skill_ref'],'topic-development')
prose=(R/'skills/prose-generation/SKILL.md').read_text();proj=project_skill_method(prose,ref='prose-generation',version='prose-generation-v4',stage='draft',targeted=False)
check('draft_projection_excludes_screenplay_and_revision','## Screenplay' in proj or '## Full revision' in proj,False)
plan={'chapter_contract_schema_version':'chapter-mission-scene.v4','runtime_projection_version':'3.0.0','primary_function':'ordinary','promise_action':None,'reward_action':None,'reward_setup':[],'reward_payoff':[],'ending_hook':None,'serialization_function':None,'antagonist_actions':[],'emotional_curve':[],'suspense_curve':[],'protagonist_charm_mechanism':None}
requirements=_method_requirements(plan,{})
check('unselected_reward_not_applicable_to_evaluation',requirements['reward']['status'],'NOT_APPLICABLE')
check('unselected_hook_not_applicable_to_evaluation',requirements['chapter_hook']['status'],'NOT_APPLICABLE')
report={'dimension':'reward','gate_status':'FAILED','score':20,'calibration_status':'PROVIDER_UNCALIBRATED','blocking':True,'weight':1.0,'threshold':80,'revision_strategy':['invent reward']}
final=finalize_work_dimension(report,policy={'policy_digest':'audit','thresholds':{},'dimension_weights':{}},requirement=requirements['reward'],baseline_digest='audit')
check('quality_cannot_require_unselected_reward',(final['gate_status'],final['score'],final['blocking'],final['revision_strategy']),('NOT_APPLICABLE',None,False,[]))
longitudinal=_longitudinal_dimensions([{'chapter_number':i,'average_sentence_length':10+i*10,'reader_reward_count':0} for i in range(1,8)],work_requirements=True)
check('current_longitudinal_reward_cadence_is_measurement',next(x['status'] for x in longitudinal if x['dimension']=='reader_reward_rhythm'),'MEASURED')
result={'evidence_class':'SYNTHETIC_OFFLINE_CODE_ONLY','baseline_main':'7540c51fe587266b8083ef4168271aa5a4ff9f3e','core_catalog_count':len(cards),'non_wuxia_xuanhuan_families':sum(x['family']!='WUXIA_XUANHUAN' for x in cards),'affinity_genre_sets':sorted({tuple(x['affinity']['genre']) for x in cards}),'affinity_pov_sets':sorted({tuple(x['affinity']['pov']) for x in cards}),'same_method_assessments':assessment,'checks':checks,'provider_calls':0,'book_activation':0,'literary_effect':'UNVERIFIED','scope_note':'Empty optional selection is not full production admission; real author required cards and schema/source gates remain binding.'}
(E/'multigenre-offline-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
