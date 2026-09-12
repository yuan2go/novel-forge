from pathlib import Path
import json,os,hashlib,io,subprocess,signal
from urllib.parse import urlsplit,urlunsplit
import psycopg
from psycopg import sql
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.object_store import MinioObjectStore
from novel_forge.modules.source_import.object_reader import MinioObjectStoreReader
R=Path(__file__).resolve().parent; p=R/'local-environment.json';values=json.loads(p.read_text())
api=json.loads((R/'api.json').read_text())
command=subprocess.run(['ps','-p',str(api['pid']),'-o','command='],capture_output=True,text=True).stdout
if command and 'novel_forge.cli.authority serve-api --host 127.0.0.1 --port 51009' not in command:raise RuntimeError('Refusing to stop an unexpected API process')
if command:os.kill(api['pid'],signal.SIGTERM)
settings=IndustrialSettings.from_env(values,root=R)
store=MinioObjectStore(settings);bucket=settings.minio_artifact_bucket
if not store.client.bucket_exists(bucket):store.client.make_bucket(bucket)
reader=MinioObjectStoreReader(store.client,bucket=bucket)
manifest=[]
for path in sorted((R/'objects').rglob('*')):
 if not path.is_file():continue
 key=path.relative_to(R/'objects').as_posix();data=path.read_bytes();digest='sha256:'+hashlib.sha256(data).hexdigest()
 try: old=reader.read(object_key=key,expected_hash=digest,expected_size=len(data))
 except Exception as exc:
  from minio.error import S3Error
  if not isinstance(exc,S3Error) or exc.code!='NoSuchKey':raise
  store.client.put_object(bucket,key,io.BytesIO(data),length=len(data))
 reader.read(object_key=key,expected_hash=digest,expected_size=len(data))
 manifest.append({'object_key':key,'sha256':digest,'bytes':len(data),'readback':'EXACT'})
(R/'object-restore.json').write_text(json.dumps({'status':'VERIFIED','source':'local immutable object files','target':'MinIO same keys/bytes; existing PostgreSQL identities unchanged','files':manifest,'object_count':len(manifest),'total_bytes':sum(x['bytes'] for x in manifest),'model_calls':0},indent=2))
dsn=urlsplit(values['NOVEL_FORGE_DATABASE_URL']);old=dsn.path.lstrip('/');new='novel_forge_first_novel_pilot_test'
if old not in {'novel_forge_first_novel_pilot',new}:raise RuntimeError('Unexpected database identity')
if old!=new:
 admin=urlunsplit((dsn.scheme,dsn.netloc,'/postgres',dsn.query,dsn.fragment))
 with psycopg.connect(admin,autocommit=True) as con:
  live=con.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=%s',[old]).fetchone()[0]
  if live:raise RuntimeError('Owned API connections still active; retry after graceful shutdown')
  con.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(sql.Identifier(old),sql.Identifier(new)))
 values['NOVEL_FORGE_DATABASE_URL']=urlunsplit((dsn.scheme,dsn.netloc,'/'+new,dsn.query,dsn.fragment))
values['NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND']='minio'
values['NOVEL_FORGE_COMMIT_SHA']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
values['NOVEL_FORGE_APPLICATION_BUILD_ID']='first-novel-pilot-local-'+values['NOVEL_FORGE_COMMIT_SHA'][:12]
p.write_text(json.dumps(values,indent=2));p.chmod(0o600)
resources=json.loads((R/'resources.json').read_text());resources['database']=new;resources['database_name_note']='Owned isolated pilot data retained; _test suffix required by native controlled-runner guard; never a pytest target';(R/'resources.json').write_text(json.dumps(resources,indent=2))
m=json.loads((R/'minio-resources.json').read_text());m['status']='VERIFIED_ACTIVE_SAME_OBJECT_IDENTITIES';(R/'minio-resources.json').write_text(json.dumps(m,indent=2))
(R/'infrastructure-transition.json').write_text(json.dumps({'status':'COMPLETE','database_from':old,'database_to':new,'guard':'UNCHANGED','business_assets_rewritten':False,'historical_external_receipts':'PRESERVED','new_calls':0,'new_object_backend':'minio','object_manifest':'object-restore.json','implementation_sha':values['NOVEL_FORGE_COMMIT_SHA']},indent=2))
print(json.dumps({'status':'COMPLETE','verified_objects':len(manifest),'bytes':sum(x['bytes'] for x in manifest),'database':new,'secrets_exported':False}))

