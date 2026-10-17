import argparse,hashlib,json,subprocess
from dataclasses import asdict
from pathlib import Path
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.context_builder.task_compression import compile_task_context
from novel_forge.modules.narrative_state.reality import narrative_hash
p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--output',required=True);p.add_argument('--semantic',action='store_true');a=p.parse_args()
gold=json.loads(Path(a.gold).read_text());boundary={'kind':'FROZEN_STAGE_INPUTS','project_id':'p','book_id':'b','sources':[{'asset_version_id':'frozen-context','content_hash':narrative_hash(gold)}]}
protected={(s['id'],index) for s in gold['sources'] for index,paragraph in enumerate(s['paragraphs']) if any(paragraph in quote or (paragraph.endswith(quote.split('\n\n')[0]) and '\n\n' in quote) for quote in gold['preserve_quotes'])}
required=set()
for q in gold['questions']:
 for item in q.get('sources') or [q]:required.update((item['source'],index) for index in item['paragraphs'])
quotes=gold['preserve_quotes']+[s['paragraphs'][i] for s in gold['sources'] for i in range(len(s['paragraphs'])) if (s['id'],i) in required-protected]
candidates=[]
for s in gold['sources']:
 text='\n\n'.join(s['paragraphs']+[f'背景杂事第{i}项，街口没有新的必要消息。' for i in range(100)])
 candidates.append(ContextCandidate(asset_version_id=s['id'],asset_type='historical_expression_projection',project_id='p',book_id='b',estimated_tokens=1,relevance_score=1,safe_summary=text,content_digest=narrative_hash(text),provenance={'frozen_input_boundary':boundary,'source_status':s['status']}))
task={'stage':'draft','frozen_input_boundary':boundary,'source_projection_hash':narrative_hash([asdict(x) for x in candidates]),'preserve_quotes':quotes,'task_context':{'questions':[q['question'] for q in gold['questions']]}}
if a.semantic:task['semantic_contract']='source-unit-dependency-and-final-composition.v2'
calls=[]
def counter(value):return len(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def call(stage,chunk):
 calls.append(stage)
 if stage=='context_compress':return {'selected_unit_ids':chunk['required_unit_ids']}
 return {'supported':True,'coverage_complete':True,'missing_unit_ids':[],'distorted_unit_ids':[]}
selected,receipt=compile_task_context(candidates,task=task,token_budget=11000,required_asset_types=(),model_call=call,compression_input_tokens=16000,chunk_fits=lambda chunk:counter(chunk)<=16000,token_counter=counter,token_accounting_method='SCRIPTED_UTF8_BYTES_EXACT_V1')
byid={x.asset_version_id:x.safe_summary for x in selected};sources={s['id']:s for s in gold['sources']};questions=[]
for q in gold['questions']:
 refs=q.get('sources') or [q];support=[{'source':r['source'],'paragraph':i,'present':sources[r['source']]['paragraphs'][i] in byid[r['source']]} for r in refs for i in r['paragraphs']]
 questions.append({**q,'exact_original_support_complete':all(x['present'] for x in support),'support':support})
quote_proof=[{'quote':q,'present_in_one_original_source':any(q in text for text in byid.values())} for q in gold['preserve_quotes']]
result={'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'evidence_class':'PRODUCTION_FUNCTION_CONTROLLED_SELECTION_WITH_FIXED_ORIGINAL_GOLD_AND_SYNTHETIC_CAPACITY_LOAD','semantic_comprehension':'NOT_VERIFIED','gold_sha256':hashlib.sha256(Path(a.gold).read_bytes()).hexdigest(),'input_hash':narrative_hash([asdict(x) for x in candidates]),'task_without_algorithm_hash':narrative_hash({k:v for k,v in task.items() if k!='semantic_contract'}),'capacity_unit':'CONTROLLED_SERIALIZED_UTF8_BYTES_NOT_REAL_MODEL_TOKENS','limit':11000,'before_bytes':sum(counter({'safe_summary':x.safe_summary,'structured_facts':[]}) for x in candidates),'after_bytes':sum(counter({'safe_summary':x.safe_summary,'structured_facts':[]}) for x in selected),'model_calls':len(calls),'call_stages':calls,'questions':questions,'explicit_quotes':quote_proof,'receipt':receipt,'final_sources':byid}
Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str));print({k:result[k] for k in ['source_sha','before_bytes','after_bytes','model_calls']});print('support',sum(q['exact_original_support_complete'] for q in questions),'/',len(questions),'quotes',sum(x['present_in_one_original_source'] for x in quote_proof))
