from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urljoin,unquote
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parent
RAW=ROOT/'raw';RAW.mkdir(exist_ok=True)
META=ROOT/'acquisition';META.mkdir(exist_ok=True)
def fetch(identity,url,ext='html'):
 path=RAW/(identity+'.'+ext);meta=META/(identity+'.json')
 if path.exists() and meta.exists():
  old=json.loads(meta.read_text())
  if old.get('sha256')==hashlib.sha256(path.read_bytes()).hexdigest():return path,old
 try:
  with urlopen(url,timeout=30) as response:
   data=response.read(8_000_001)
   if len(data)>8_000_000:raise ValueError('bounded acquisition exceeds eight MB')
   record={'id':identity,'requested_url':url,'resolved_url':response.url,'format':ext,'status':'ACQUIRED','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'acquired_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'etag':response.headers.get('ETag'),'last_modified':response.headers.get('Last-Modified'),'raw_path':str(path)}
  path.write_bytes(data);meta.write_text(json.dumps(record,ensure_ascii=False,indent=2));return path,record
 except Exception as e:
  record={'id':identity,'requested_url':url,'status':'ACQUISITION_FAILED','error':type(e).__name__+': '+str(e)};meta.write_text(json.dumps(record,indent=2));return None,record
base='https://eng.libretexts.org/Courses/Northeast_Wisconsin_Technical_College/Fluids_2%3A_Basic_Hydraulics_%28NWTC%29'
rootpath,_=fetch('nwtc-hydraulics-index',base)
if not rootpath:raise SystemExit('source index unavailable')
soup=BeautifulSoup(rootpath.read_bytes(),'html.parser')
chapters=[]
for a in soup.select('.mt-content-container a[href]'):
 u=urljoin(base,a['href']);title=a.get_text(' ',strip=True)
 if u.startswith(base.replace('%28','(').replace('%29',')')) or u.startswith(base):
  tail=unquote(u).rstrip('/').rsplit('/',1)[-1]
  if ':' in tail and tail.split(':')[0].isdigit() and int(tail.split(':')[0]) in [2,5,9,10,11,12,13,14,15,18]:
   if not any(x[0]==u for x in chapters):chapters.append((u,title))
leaves=[]
for idx,(url,title) in enumerate(chapters):
 path,record=fetch('hydraulics-index-'+str(idx+1),url)
 if not path:continue
 doc=BeautifulSoup(path.read_bytes(),'html.parser')
 matched=[]
 for a in doc.select('.mt-content-container a[href]'):
  target=urljoin(url,a['href']);label=a.get_text(' ',strip=True)
  if target.startswith(url.rstrip('/')+'/') and ':' in label and target not in [x[0] for x in matched]:matched.append((target,label))
 leaves.extend(matched[:2] or [(url,title)])
 print('index',title,'selected',len(matched[:2] or [title]),flush=True)
entries=[]
for i,(url,title) in enumerate(leaves[:17]):
 identity=f'hydraulics-{i+1:02d}';path,record=fetch(identity,url)
 entry=record|{'title':title,'language':'en','work_identity':'NWTC-Fluids2-BasicHydraulics-JessyHaid','unit_kind':'INDEPENDENTLY_LOCATABLE_SECTION','topics':['hydraulic mechanism','resource constraint','failure condition'],'creative_value':'对泵站行动可行性、力与流量、阻力损耗和保护动作建模；仅提炼抽象机制','model_analysis':'NOT_RUN','batch_id':f'pilot-materials-{i//6+1:02d}'}
 if path:
  doc=BeautifulSoup(path.read_bytes(),'html.parser');content=doc.select_one('.mt-content-container')
  entry.update({'license_links':[a.get('href') for a in doc.select('a[href*="creativecommons.org/licenses/"]')],'text_characters':len(content.get_text(' ',strip=True)) if content else 0,'image_count':len(content.select('img')) if content else 0,'table_count':len(content.select('table')) if content else 0,'math_count':len(content.select('math,.math')) if content else 0,'iframe_count':len(content.select('iframe')) if content else 0,'source_selector':'.mt-content-container'})
  entry['structure_status']='REVIEW_REQUIRED'
 entries.append(entry);print(identity,entry['status'],entry.get('text_characters'),flush=True)
fiction=[('railway-children','1874','The Railway Children','E. Nesbit (1858–1924)','悬念、身份隐瞒、有限资源、选择代价与跨章帮助兑现'),('thirty-nine-steps','558','The Thirty-Nine Steps','John Buchan (1875–1940)','限知视角、信息差、线索误读与追逐节奏'),('study-in-scarlet','244','A Study in Scarlet','Arthur Conan Doyle (1859–1930)','观察与推断分离、未知保持及线索因果')]
for i,(identity,number,title,author,value) in enumerate(fiction):
 path,record=fetch(identity,'https://www.gutenberg.org/cache/epub/'+number+'/pg'+number+'.txt','txt')
 _,lic=fetch(identity+'-catalogue','https://www.gutenberg.org/ebooks/'+number)
 entries.append(record|{'title':title,'author':author,'language':'en','work_identity':'gutenberg:'+number,'unit_kind':'WHOLE_WORK','topics':['narrative craft'],'creative_value':value,'model_analysis':'NOT_RUN','batch_id':'pilot-materials-04','catalogue_evidence':lic.get('raw_path'),'structure_status':'REVIEW_REQUIRED','rights_note':'Original English public-domain work; Gutenberg USA declaration plus author identity preserved. Abstract craft only; no prose/characters/unique scene combinations into creation.'})
 print(identity,record['status'],flush=True)
(ROOT/'catalogue.json').write_text(json.dumps({'schema':'operator-corpus-acquisition-catalogue.v1','authority':'OPERATOR_INPUT_AND_EXPORT_ONLY; native import status in PostgreSQL','entries':entries},ensure_ascii=False,indent=2))
print('TOTAL',len(entries),flush=True)
