from pathlib import Path
import json,hashlib,re
from bs4 import BeautifulSoup
from novel_forge.modules.source_import.corpus_ingestion.contracts import IngestionManifest
R=Path(__file__).resolve().parent
catalog=json.loads((R/'catalogue.json').read_text());out=R/'manifests';out.mkdir(exist_ok=True)
issues=[];plans=[]
for e in catalog['entries']:
 path=Path(e['raw_path']);data=path.read_bytes();digest='sha256:'+hashlib.sha256(data).hexdigest()
 if e['format']=='html':
  if e['license_links']!=['https://creativecommons.org/licenses/by/4.0']:
   issues.append({'id':e['id'],'code':'LICENSE_REVIEW_REQUIRED'});continue
  parser={'version':'corpus-parser.v3','format':'html','html_body_selector':'.mt-content-container','constants':{'work_id':e['id'],'title':e['title'],'author':'Jessy Haid / Northeast Wisconsin Technical College'},'normalization':{'version':'chinese-longform.v2','segmentation':'EXPLICIT','min_body_chars':80},'completeness':'EXCERPT','expected_units':1}
  rights={'dataset_license':'CC-BY-4.0','underlying_rights':'LICENSED','underlying_license':'CC-BY-4.0: exact section by Jessy Haid / NWTC; page-specific license footer retained','scope':'ALL_WORKS_IN_SNAPSHOT','evidence_refs':[e['requested_url'],digest,str(path)],'copyright_boundary':'Retain author/source/license attribution. Abstract mechanisms only after exact Candidate review; original prose and diagrams cannot enter fiction requests. Figures and table layout are retained in original HTML but not qualified as read text.'}
  if e.get('image_count') or e.get('table_count'):
   issues.append({'id':e['id'],'code':'VISUAL_CONTEXT_NOT_PARSED','images':e['image_count'],'tables':e['table_count'],'status':'EXCLUDE_FROM_INITIAL_ANALYSIS','raw_preserved':str(path)})
  if e['id']=='hydraulics-09':
   issues.append({'id':e['id'],'code':'SOURCE_UNIT_CONTRADICTION','location':'500 psi calculation followed by "This 500 kPa"','status':'QUARANTINED_FROM_ANALYSIS','raw_preserved':str(path)})
  e['analysis_selection']='SELECTED_PENDING_AUTHORIZATION' if e['id'] in ['hydraulics-12','hydraulics-14','hydraulics-16'] else 'NOT_SELECTED'
 else:
  matches=list(re.finditer(rb'(?mi)^chapter ([IVXLCDM]+)\.[^\r\n]*',data))
  chapters_expected={'railway-children':14,'thirty-nine-steps':10,'study-in-scarlet':14}[e['id']]
  if len(matches)!=chapters_expected:raise ValueError((e['id'],'unexpected chapter markers',len(matches)))
  end=re.search(rb'(?mi)^\*\*\* END OF THE PROJECT GUTENBERG',data)
  if end is None:raise ValueError('Gutenberg footer boundary missing')
  bounds=[{'start':0,'end':matches[0].start(),'title':'Publisher identity, front matter and rights','kind':'AUTHOR_NOTE'}]
  for i,m in enumerate(matches):
   volume='Part II' if e['id']=='study-in-scarlet' and i>=7 else 'Part I' if e['id']=='study-in-scarlet' else ''
   bounds.append({'start':m.start(),'end':matches[i+1].start() if i+1<len(matches) else end.start(),'title':m.group(0).decode(),'kind':'CHAPTER','number':i+1 if e['id']!='study-in-scarlet' else i%7+1,'volume':volume})
  bounds.append({'start':end.start(),'end':len(data),'title':'Project Gutenberg license and trailing metadata','kind':'AUTHOR_NOTE'})
  for b in bounds:b.update(path=path.name,checksum=digest,evidence=e['requested_url']+'; exact UTF-8 byte markers reviewed; front matter and license retained as nonchapter units')
  parser={'version':'corpus-parser.v3','format':'txt','constants':{'work_id':e['id'],'title':e['title'],'author':e['author']},'normalization':{'version':'chinese-longform.v2','segmentation':'EXPLICIT','min_body_chars':80,'boundaries':bounds,'work_completion':'FINISHED'},'completeness':'COMPLETE','expected_units':len(bounds)}
  rights={'dataset_license':'Project Gutenberg License; exact original English work public domain','underlying_rights':'PUBLIC_DOMAIN','scope':'ALL_WORKS_IN_SNAPSHOT','evidence_refs':[e['requested_url'],'https://www.gutenberg.org/ebooks/'+e['work_identity'].split(':')[1],str(e['catalogue_evidence']),digest],'copyright_boundary':'Original English works by authors deceased by 1940; Project Gutenberg USA public domain evidence preserved. No modern translation, trademark endorsement, protected expression, characters, scenes or distinctive plot combinations enter creation; abstract craft only after review.'}
  e['analysis_selection']='CHAPTERS_2_THROUGH_7_PENDING_AUTHORIZATION' if e['id']=='railway-children' else 'NOT_SELECTED'
  e['structure_counts']={'main_chapters':len(matches),'nonchapter_units':2,'all_raw_bytes_accounted':True,'independent_completeness':'NOT_EXTERNALLY_VERIFIED'}
 rights.update(allowed_purposes=['PRODUCTION_REFERENCE'],allowed_uses=['LOCAL_PROCESSING','SOURCE_ANALYSIS','ABSTRACT_GENERATION'])
 manifest={'purpose':'PRODUCTION_REFERENCE','analyze':False,'source':{'kind':'LOCAL','location':str(path),'files':[{'path':path.name,'checksum':digest}]},'parser':parser,'rights':rights}
 validated=IngestionManifest.model_validate(manifest)
 dest=out/(e['id']+'.json');dest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 plans.append({'id':e['id'],'batch_id':e['batch_id'],'run_key':e['batch_id']+':'+e['id']+':v1','manifest':str(dest),'manifest_hash':validated.identity,'source_hash':digest})
 e['manifest']=str(dest);e['structure_status']='TEXT_ONLY_REVIEWED' if e.get('analysis_selection')=='SELECTED_PENDING_AUTHORIZATION' else 'PRESERVED_WITH_DECLARED_LIMITS'
(R/'catalogue.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
(R/'import-plan.json').write_text(json.dumps({'native_authority':'PostgreSQL; this file holds operator input and native job references only','entries':plans},ensure_ascii=False,indent=2))
issues.extend([{'id':'usgs-streamgaging','code':'ACQUISITION_HTTP_405','status':'NOT_ACQUIRED','url':'https://www.usgs.gov/water-science-school/science/how-does-usgs-collect-streamflow-data'}, {'id':'usgs-100-year-flood','code':'ACQUISITION_TLS_FAILURE','status':'NOT_ACQUIRED','url':'https://pubs.usgs.gov/gip/106/pdf/gip106.pdf'},{'id':'openstax-college-physics-2e','code':'PURPOSE_NOT_GRANTED','status':'EXCLUDED','evidence':'https://openstax.org/books/college-physics-2e/pages/index','reason':'Current NC-SA license plus separate generative AI permission notice; do not infer production license from older names.'}])
(R/'issues.json').write_text(json.dumps(issues,ensure_ascii=False,indent=2));print('validated manifests',len(plans),'declared issues',len(issues))
