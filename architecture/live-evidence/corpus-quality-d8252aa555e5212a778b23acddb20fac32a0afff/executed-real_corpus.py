import os,json,subprocess,time,resource
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from bs4 import BeautifulSoup
from novel_forge.modules.project_authority import ProjectAuthorityApplication,ProjectAuthorityCommand
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.cli.corpus import run_corpus_command
base_dir=Path('/tmp/nf-corpus-wp3c-20260909');root=base_dir/('real-'+os.environ.get('CORPUS_CAMPAIGN','development-1'));root.mkdir(exist_ok=True)
project='corpus-real-'+uuid4().hex;workspace='workspace-'+uuid4().hex
from novel_forge.tools.implementation_tree_identity import build_implementation_tree_identity
sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
os.environ['NOVEL_FORGE_DATABASE_URL']=json.loads((base_dir/'sample-environment.json').read_text())['database_url']
os.environ.update(NOVEL_FORGE_APPLICATION_BUILD_ID='corpus-quality-real',NOVEL_FORGE_COMMIT_SHA=sha,NOVEL_FORGE_ENVIRONMENT='test',NOVEL_FORGE_MODEL_PROVIDER='mock',NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND='local',NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT=str(root/'objects'),NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE=project,NOVEL_FORGE_CORPUS_CACHE_ROOT=str(root/'cache'),NOVEL_FORGE_CORPUS_LOCAL_ROOTS=json.dumps([str(base_dir/'public')]),NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT=str(root/'git'))
url=os.environ['NOVEL_FORGE_DATABASE_URL'];settings=IndustrialSettings(root=root,environment='test',database_url=url)
ProjectAuthorityApplication(url,application_build_id='corpus-quality-real',commit_sha=sha).execute(ProjectAuthorityCommand(definition_name='project_lifecycle.create',project_id=project,workspace_id=workspace,actor_id='local-validation-operator',idempotency_key=project,trace_id=project,correlation_id=project,payload={'title':'中文资料库确定性验收'}))
base=dict(project_id=project,workspace_id=workspace,manifest=None,run_key='',job_id='',after='',limit=100,max_stages=30,reason='source-linked verification',edition_id='',processing_id='',compare_to='',decision=None,work_id='',corpus_id='',revision_id='',historical=False)
records=[];summary={'tested_sha':sha,'implementation_identity':build_implementation_tree_identity('.')['implementation_tree_sha'],'project_id':project,'workspace_id':workspace,'samples':[],'annotation':'AGENT_INSPECTION_NOT_INDEPENDENT_HUMAN','provider_calls':0}
def save():
 (root/'operations.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,default=str))
 summary['peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
def run(action,**kw):
 started=time.monotonic()
 try:
  result=run_corpus_command(settings,SimpleNamespace(**{**base,'action':action,**kw}));records.append({'action':action,'seconds':time.monotonic()-started,'result':result});save();return result
 except Exception as exc:
  records.append({'action':action,'error':repr(exc),'seconds':time.monotonic()-started});save();raise

def file(name,data):
 p=root/(name+'.json');p.write_text(json.dumps(data,ensure_ascii=False,indent=2));return p

def decision(action,data,key): return run(action,decision=file(key,data),run_key=key)
receipts={r['name']:r for r in json.loads((base_dir/'public/receipts.json').read_text())}
soup=BeautifulSoup((base_dir/'public/catalogue-5401635.html').read_bytes(),'html.parser')
toc=[a.parent.get_text(' ',strip=True) for a in soup.select('.mw-parser-output a') if a.get_text().startswith('第')]
toc_ref='https://zh.wikisource.org/w/index.php?oldid=5401635;sha256:'+receipts['catalogue-5401635.html']['sha256']
for number,title,author,fmt in [('23950','三國志演義','羅貫中','txt'),('23962','西遊記','吳承恩','txt'),('24264','紅樓夢','曹雪芹','txt'),('24264','紅樓夢','曹雪芹','epub')]:
 started=time.monotonic();key=number+'-'+fmt
 parser={'version':'corpus-parser.v3','format':fmt,'encoding':('utf-8-sig' if fmt=='txt' else 'utf-8'),'constants':{'work_id':'gutenberg:'+number,'work_title':title,'author':author},'normalization':{'version':'chinese-longform.v2','min_body_chars':80,'work_completion':'UNKNOWN','external_work_ids':['gutenberg:'+number]},'completeness':'UNKNOWN'}
 if number=='23950': parser['normalization'].update(expected_toc=toc,toc_evidence=toc_ref)
 receipt=receipts[number+'.'+fmt]
 manifest={'source':{'kind':'LOCAL','location':str(base_dir/'public'/(number+'.'+fmt))},'parser':parser,'budget':{'max_files':400},'purpose':'RESEARCH','rights':{'dataset_license':'Project Gutenberg License','scope':'ALL_WORKS_IN_SNAPSHOT','underlying_rights':'PUBLIC_DOMAIN','allowed_purposes':['RESEARCH'],'allowed_uses':['LOCAL_PROCESSING','SOURCE_ANALYSIS'],'evidence_refs':['https://www.gutenberg.org/ebooks/'+number+'#bibrec','sha256:'+receipt['sha256']],'copyright_boundary':'Historical Chinese work; Gutenberg catalogue declares US public domain. Isolated research; no prose generation permission inferred.'},'analyze':False}
 try:
  admitted=run('import',manifest=file(key+'-manifest',manifest),run_key=key);run('run',job_id=admitted['import_job_id']);lineage=run('lineage',job_id=admitted['import_job_id']);edition=lineage['editions'][0]['edition_id'];first=run('inspect',edition_id=edition)
  decisions=[{'issue_id':i['issue_id'],'resolution':'MARK_NON_BODY','reason':'Agent checked exact source frame: publisher header, license, preface or container cover; source retained.'} for i in first['assessment']['issues'] if i['code']=='NON_BODY_UNIT' and any(e['locator'].get('original_byte_offset')==0 or 'END OF THE PROJECT GUTENBERG' in next((u['title'] for u in first['assessment']['units'] if u['unit_id']==e['unit_id']),'') for e in i['evidence'])]
  if decisions:
   decision('review',{'action':'review_processing','processing_id':first['processing_id'],'decisions':decisions,'reason':'Exclude verified framing only; no blanket waiver.'},key+'-framing')
   re=run('reprocess',edition_id=edition,manifest=file(key+'-parser',parser),run_key=key+'-reviewed');run('run',job_id=re['import_job_id'])
  final=run('inspect',edition_id=edition)
  sample={'key':key,'title':title,'edition_id':edition,'initial_processing_id':first['processing_id'],'processing_id':final['processing_id'],'acquisition':receipt,'chapter_count':final['assessment']['chapter_count'],'unit_count':final['assessment']['unit_count'],'structure_usable':final['assessment']['structure_usable'],'coverage':final['assessment']['coverage'],'issues':final['assessment']['issues'],'seconds':time.monotonic()-started,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'job_id':admitted['import_job_id']}
  summary['samples'].append(sample);save();print(key,sample['chapter_count'],sample['coverage'],sample['seconds'],flush=True)
 except Exception as exc:
  summary['samples'].append({'key':key,'status':'FAILED','error':repr(exc),'seconds':time.monotonic()-started});save();print(key,'FAILED',repr(exc),flush=True)
print('saved',root,flush=True)
