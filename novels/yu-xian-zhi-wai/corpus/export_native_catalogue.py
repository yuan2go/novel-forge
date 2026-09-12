from pathlib import Path
from urllib.request import build_opener,ProxyHandler
from urllib.parse import urlencode,quote
import json,datetime,hashlib,subprocess,time,html,os
R=Path(__file__).resolve().parent;E=R.parent;OUT=R/'native-final';OUT.mkdir(exist_ok=True)
project='first-novel-pilot-20260912';base='http://127.0.0.1:51009';http=build_opener(ProxyHandler({}))
def get(path,name,**params):
 url=base+path+'?'+urlencode({'project_id':project,**params});t=time.monotonic()
 with http.open(url,timeout=30) as response:body=response.read()
 p=OUT/(name+'.json');p.write_bytes(body)
 return json.loads(body),{'url':url,'path':str(p),'sha256':'sha256:'+hashlib.sha256(body).hexdigest(),'elapsed_ms':round((time.monotonic()-t)*1000,3)}
catalogue=json.loads((R/'catalogue.json').read_text())
imports={i['id']:i for i in json.loads((R/'native-import-summary.json').read_text())['entries']}
for id,v in imports.items():v.update(next(s['result'] for s in v['stage_results'] if s['result'].get('processing_id')))
for id,v in json.loads((R/'current-fiction-processing.json').read_text()).items():imports[id].update(v)
queries=[];jobs=[];after=''
while True:
 data,receipt=get('/product/source-imports','batch-jobs-page-'+str(len(queries)+1),limit=10,run_key_prefix='pilot-materials-',after=after);queries.append(receipt);jobs+=data
 if len(data)<10:break
 after=data[-1]['import_job_id']
assert len(jobs)==20 and len({j['import_job_id'] for j in jobs})==20
rows=[];failures=[]
for e in catalogue['entries']:
 try:
  proc,receipt=get('/product/source-imports/corpus/processing/'+quote(imports[e['id']]['processing_id'],safe=''),'processing-'+e['id']);queries.append(receipt)
  chapters,receipt=get('/product/source-imports/corpus/processing/'+quote(imports[e['id']]['processing_id'],safe='')+'/chapters','chapters-'+e['id'],limit=100);queries.append(receipt)
  job=next(j for j in jobs if j['import_job_id']==imports[e['id']]['job_id']) if 'job_id' in imports[e['id']] else next(j for j in jobs if j['import_job_id']==imports[e['id']]['import_job_id'])
  units=chapters['units'];row=e|{'native_import_job_id':job['import_job_id'],'native_import_status':job['status'],'current_processing_id':imports[e['id']]['processing_id'],'native_inspect_export':'native-final/processing-'+e['id']+'.json','native_chapters_export':'native-final/chapters-'+e['id']+'.json','body_units':sum(u['kind']=='chapter' and u['status']=='AVAILABLE' for u in units),'excluded_units':sum(u['status']=='EXCLUDED' for u in units),'native_structure_usable':proc.get('assessment',proc.get('integrity',{})).get('structure_usable'),'knowledge_candidate_status':'NOT_ANALYZED','knowledge_approval':'NOT_RUN','first_analysis_selection':e['id'] in ['hydraulics-12','hydraulics-14','hydraulics-16','railway-children']}
  rows.append(row)
 except Exception as exc:failures.append({'id':e['id'],'error':str(exc)})
for kind in ['knowledge-candidates','knowledge-cards']:
 data,receipt=get('/product/mkaos/'+kind,kind,limit=100);queries.append(receipt);assert not data
result={'schema_version':'first-novel-corpus-export.v1','evidence_class':'NATIVE_CORPUS_READ_ONLY_EXPORT','authority':'PostgreSQL; this is an export index only','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'implementation_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_entries':20,'bibliographic_works':4,'batches':3,'exported_entries':len(rows),'failures':failures,'entries':rows,'query_receipts':queries,'model_calls':0,'approved_card_versions':[]}
(R/'catalogue-native-export.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
assert not failures,failures
parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>雨线之外 · 原文素材目录</title><style>body{font:16px/1.65 system-ui;max-width:1400px;margin:40px auto;padding:0 20px;color:#202c35;background:#f4f1eb}h1{font-weight:600}input{padding:12px;width:70%;font:inherit;border:1px solid #899}table{width:100%;border-collapse:collapse;margin-top:24px;background:white}td,th{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #ddd}small{color:#536570}a{color:#19556a}</style><h1>雨线之外 · 原文素材目录</h1><p>20个原文条目 · 4部作品 · 3批次。已原生导入，知识解构与批准尚未运行；此页是 PostgreSQL 导出快照。</p><p>17篇为同一本专业教材的独立章节片段，3部为英文原著。图示未解析的部分不进入首批解构；hydraulics-09 的单位矛盾已从精选排除。小说前言/许可文本保留但排除分析，章节完整性仍为 UNKNOWN。</p><p><a href="catalogue-native-export.json">完整身份与查询证据</a> · <a href="issues.json">问题清单</a> · <a href="selections.json">原生精选版本</a> · <a href="next-reading-preview-final.json">实际阅读预检</a></p><label>筛选 <input id="q" placeholder="标题、批次、精选、主题" oninput="for(const r of document.querySelectorAll(\'tbody tr\'))r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase())"></label><table><thead><tr><th>来源</th><th>结构与状态</th><th>查看</th></tr></thead><tbody>']
for e in rows:
 raw='raw/'+Path(e['raw_path']).name
 parts.append('<tr><td><b>'+html.escape(e['title'])+'</b><br><small>'+html.escape(e['id'])+' · '+html.escape(str(e.get('batch_id',e.get('batch',''))))+'</small></td><td>'+html.escape(e['native_import_status'])+' · '+str(e['body_units'])+'正文单元 · '+str(e['excluded_units'])+'排除单元<br>'+('首批精选（尚未分析）' if e['first_analysis_selection'] else '保留，首批不分析')+'</td><td><a href="'+html.escape(raw,quote=True)+'">原始材料</a> · <a href="'+e['native_inspect_export']+'">检查与权利证据</a> · <a href="'+e['native_chapters_export']+'">章节位置</a> · <a href="'+html.escape(e['requested_url'],quote=True)+'">来源</a></td></tr>')
parts.append('</tbody></table><p>导出不代表知识批准、真实章节试生产或文学质量通过。</p></html>')
(R/'index.html').write_text(''.join(parts))
print(json.dumps({'exported':len(rows),'native_imported':sum(e['native_import_status']=='IMPORTED' for e in rows),'works':4,'model_calls':0,'knowledge_cards':0,'failed_exports':failures}))

