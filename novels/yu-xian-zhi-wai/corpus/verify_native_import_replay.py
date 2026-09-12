from pathlib import Path
import json,subprocess,psycopg
from novel_forge.modules.source_import.corpus_ingestion.contracts import IngestionManifest
R=Path(__file__).resolve().parent;E=R.parent;outdir=R/'native-replay';outdir.mkdir(exist_ok=True);env=json.loads((E/'runtime/local-environment.json').read_text());project='first-novel-pilot-20260912'
def counts():
 with psycopg.connect(env['NOVEL_FORGE_DATABASE_URL']) as c:
  c.execute('SET TRANSACTION READ ONLY');return c.execute('SELECT (SELECT count(*) FROM authority_operation WHERE project_id=%s),(SELECT count(*) FROM authority_external_effect WHERE project_id=%s),(SELECT count(*) FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s)',[project]*3).fetchone()
before=counts();records=[]
for i in json.loads((R/'native-import-summary.json').read_text())['entries']:
 if i['id'] not in ['hydraulics-01','hydraulics-07','railway-children']:continue
 assert IngestionManifest.model_validate(json.loads(Path(i['manifest']).read_text())).identity==i['manifest_hash']
 cmd=[str(E/'runtime/nf'),'corpus','import','--project-id',project,'--workspace-id','first-novel-pilot-workspace','--manifest',i['manifest'],'--run-key',i['run_key']]
 p=subprocess.run(cmd,capture_output=True,text=True);(outdir/(i['id']+'.json')).write_text(p.stdout);(outdir/(i['id']+'.stderr')).write_text(p.stderr);assert p.returncode==0,p.stderr
 v=json.loads(p.stdout);assert v['import_job_id']==i['import_job_id'];records.append({'id':i['id'],'same_job':True,'result':v})
after=counts();assert before==after,(before,after)
report={'status':'PASS','implementation_sha':env['NOVEL_FORGE_COMMIT_SHA'],'three_batch_representatives':records,'counts_before':before,'counts_after':after,'new_operations':0,'new_effects':0,'new_asset_versions':0,'new_model_calls':0,'meaning':'Exact prior import keys replay after MinIO restore without acquiring or rewriting source data'}
(outdir/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print({k:v for k,v in report.items() if k!='three_batch_representatives'})

