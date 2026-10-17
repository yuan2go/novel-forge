import argparse,hashlib,json,subprocess
from dataclasses import replace
from pathlib import Path
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.context_builder import semantic_units
from novel_forge.modules.context_builder.task_compression import compile_task_context
from novel_forge.modules.context_builder.domain import build_authority_context_bundle,validate_task_context_sources
from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
boundary={'accepted_through_chapter':0};access=resolve_book_knowledge_access_policy(production_profile={},project_id='p',book_id='b')
a=ContextCandidate(asset_version_id='A',asset_type='chapter_episodic_summary',project_id='p',book_id='b',estimated_tokens=10,relevance_score=1,source_identity='original:v1',source_revision='v1',content_digest='hash',safe_summary='门仍未开。',narrative_function='character_belief',semantic_representation_identity='hearsay:A',accepted_boundary=boundary,provenance={'authority':'Book'})
b=replace(a,asset_version_id='B',narrative_function='reader_knowledge',semantic_representation_identity='reader-only:B')
plan=ContextCandidate(asset_version_id='plan',asset_type='chapter_plan',project_id='p',book_id='b',estimated_tokens=10,safe_summary='继续查验。',context_class='PROTECTED',accepted_boundary=boundary,provenance={'authority':'Planning'})
inputs=[plan,a,b];admitted=validate_task_context_sources(project_id='p',book_id='b',candidates=inputs,token_budget=512000,required_asset_types=(),accepted_boundary=boundary,knowledge_access_policy=access)
calls=[]
def model(*v):calls.append(v);raise AssertionError('This capacity-in-bounds case must not call a model')
selected,receipt=compile_task_context(inputs,task={'stage':'draft','accepted_boundary':boundary,'semantic_contract':semantic_units.SEMANTIC_CONTRACT},token_budget=512000,required_asset_types=(),admitted_source_ids=admitted,defer_token_capacity=True,model_call=model)
bundle=build_authority_context_bundle(project_id='p',book_id='b',stage='draft',created_by_operation_id='op',context_profile_version='draft-context-profile-v4',candidates=selected,token_budget=512000,authority_state_boundary=boundary,knowledge_access_policy=access,task_context_receipt=receipt,defer_token_capacity=True)
def span(text,start,end):return {'source_range':{'field_path':['text'],'start':start,'end':end,'text_hash':'sha256:'+hashlib.sha256(text.encode()).hexdigest()}}
left=replace(a,safe_summary='甲乙丙丁',provenance=span('甲乙丙丁',0,4))
right=replace(left,asset_version_id='B',safe_summary='丙丁戊己',semantic_representation_identity='other-role',policy_version='other-policy',section='KNOWLEDGE',bucket='reader-only',provenance=span('丙丁戊己',2,6))
ranges,union=semantic_units.exact_deduplicate([left,right])
manifest={row['asset_version_id']:row for row in bundle['context_manifest']['selected_inputs']}
result={'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'evidence_class':'PRODUCTION_ADMISSION_COMPILATION_AND_FINAL_BUNDLE_SCOPE_REGRESSION','admitted':sorted(admitted),'selected_roles':[{'asset_version_id':row['asset_version_id'],'narrative_function':row['narrative_function'],'semantic_representation_identity':manifest[row['asset_version_id']]['semantic_representation_identity']} for row in bundle['stage_context_view']['segments'] if row['asset_version_id'] in {'A','B'}],'deduplications':receipt['deduplications'],'model_calls':len(calls),'system_context_limit':512000,'range_members_retained':[{'id':x.asset_version_id,'text':x.safe_summary,'representation':x.semantic_representation_identity,'policy':x.policy_version,'section':x.section,'bucket':x.bucket} for x in ranges],'range_union_receipts':union,'real_provider':'NOT_RUN','semantic_comprehension':'NOT_VERIFIED'}
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
provider=build_provider_context_view('draft',bundle,{'chapter':1},complete_request_capacity=True)
result['provider_visible_roles']=[{'asset_version_id':row['asset_version_id'],'narrative_function':row['narrative_function'],'text':row['safe_summary']} for row in provider['segments'] if row['asset_version_id'] in {'A','B'}]
Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result['source_sha'],len(result['selected_roles']),len(ranges),len(calls))
