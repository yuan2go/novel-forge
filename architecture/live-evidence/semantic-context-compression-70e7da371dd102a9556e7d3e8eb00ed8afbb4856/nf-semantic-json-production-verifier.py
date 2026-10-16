import argparse,json,subprocess
from pathlib import Path
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.context_builder.domain import validate_task_context_sources,build_authority_context_bundle
from novel_forge.modules.context_builder.task_compression import compile_task_context
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.command_kernel.errors import KernelError
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);a=parser.parse_args()
boundary={'accepted_through_chapter':0};access=resolve_book_knowledge_access_policy(production_profile={},project_id='p',book_id='b');calls=[]
cases={'precise_quantity':'{"subject":"阿岚","conditions":["只有潮尺低于此值"],"quantity":0.123456789012345678901,"units":"尺","summary":"她尚未开闸。","provider_evidence":{"text":"内部执行信息"},"private":{"provider_visibility":"INTERNAL_QUALITY_ONLY","text":"内部质量信息"}}','duplicate_subject':'{"subject":"阿岚","subject":"读者","summary":"未曾开闸。"}'}
rows=[]
def no_model(*args):calls.append(args);raise AssertionError('Fitting source must not invoke compressor')
for name,raw in cases.items():
 source=ContextCandidate(asset_version_id='source',asset_type='chapter_episodic_summary',project_id='p',book_id='b',estimated_tokens=1,relevance_score=1,safe_summary=raw,content_digest=narrative_hash(raw),accepted_boundary=boundary,provenance={'authority':'Book'})
 plan=ContextCandidate(asset_version_id='plan',asset_type='chapter_plan',project_id='p',book_id='b',estimated_tokens=1,safe_summary='查验条件与原始记录。',context_class='PROTECTED',accepted_boundary=boundary,provenance={'authority':'Planning'})
 inputs=[plan,source];row={'case':name,'original':raw,'original_hash':source.content_digest,'system_context_limit':512000,'capacity_evidence':'BYTE_UPPER_BOUND_MATERIAL_FITS_NOT_PROVIDER_TOKEN_QUALIFICATION'}
 try:
  admitted=validate_task_context_sources(project_id='p',book_id='b',candidates=inputs,token_budget=512000,required_asset_types=(),accepted_boundary=boundary,knowledge_access_policy=access)
  selected,receipt=compile_task_context(inputs,task={'stage':'draft','chapter':1,'accepted_boundary':boundary,'writer_projection_version':'accepted-writer-history.v2','semantic_contract':'source-unit-dependency-and-final-composition.v2'},token_budget=512000,required_asset_types=(),admitted_source_ids=admitted,defer_token_capacity=True,model_call=no_model)
  bundle=build_authority_context_bundle(project_id='p',book_id='b',stage='draft',created_by_operation_id='diagnostic',context_profile_version='draft-context-profile-v4',candidates=selected,token_budget=512000,authority_state_boundary=boundary,knowledge_access_policy=access,task_context_receipt=receipt,defer_token_capacity=True)
  view=build_provider_context_view('draft',bundle,{'chapter':1},complete_request_capacity=True,writer_projection_version='accepted-writer-history.v2')
  final=next(x['safe_summary'] for x in view['segments'] if x['asset_version_id']=='source')
  row.update(status='RENDERED',final_provider_summary=final,fast_path=receipt['fast_path'],source_unchanged=source.safe_summary==raw)
 except KernelError as error:row.update(status='EXPLICIT_SOURCE_ERROR',code=error.code,message=error.message,source_unchanged=source.safe_summary==raw)
 rows.append(row)
result={'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'evidence_class':'PRODUCTION_ADMISSION_COMPILE_BUNDLE_AND_PROVIDER_VIEW_DIAGNOSTIC','cases':rows,'model_calls':len(calls),'real_provider':'NOT_RUN','real_tokens':'NOT_MEASURED','native_dispatch':'NOT_RUN_IN_THIS_DIAGNOSTIC'}
Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result['source_sha'],[(r['case'],r['status']) for r in rows],len(calls))
