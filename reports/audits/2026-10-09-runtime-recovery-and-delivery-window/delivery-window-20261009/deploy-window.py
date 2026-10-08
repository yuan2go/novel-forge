from pathlib import Path
import hashlib,io,json,os,shutil,signal,subprocess,sys,tarfile,time,urllib.request
os.umask(0o077)
base=Path(__file__).parent
service=base.parent
repo=Path('/Users/yuan/.codex/worktrees/work-adaptation-reader-prose-01/novel-forge')
python='/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python'
def git(*args):return subprocess.check_output(['git',*args],cwd=repo)
sha=git('rev-parse','HEAD').decode().strip()
paths=sorted(set(git('diff','--name-only','HEAD').decode().splitlines()+git('ls-files','--others','--exclude-standard').decode().splitlines()))
files={p:hashlib.sha256((repo/p).read_bytes()).hexdigest() for p in paths if (repo/p).is_file()}
digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
release=service/'releases'/f'{sha}-delivery-window-{digest[:12]}'
assert not release.exists()
release.mkdir(mode=0o700)
with tarfile.open(fileobj=io.BytesIO(git('archive',sha)),mode='r:') as archive:archive.extractall(release,filter='data')
for p in paths:
 target=release/p
 if (repo/p).is_file():
  target.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(repo/p,target)
 elif target.exists(): target.unlink()
for p,h in files.items(): assert hashlib.sha256((release/p).read_bytes()).hexdigest()==h
manifest={'base_sha':sha,'patch_sha256':digest,'release_root':str(release),'modified_files':files,'git_commit_created':False,'model_dispatches':0}
(base/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
configs={name:json.loads((service/name).read_text()) for name in ['api-env.private.json','recovery-env.private.json']}
for name in configs: shutil.copy2(service/name,base/('before-'+name))
pid=int((service/'api.pid').read_text().strip())
command=subprocess.check_output(['ps','-p',str(pid),'-o','command=']).decode()
assert 'novel_forge.cli.authority serve-api' in command and '--port 8144' in command
os.kill(pid,signal.SIGTERM)
for _ in range(40):
 try:os.kill(pid,0)
 except ProcessLookupError:break
 time.sleep(.25)
else:raise RuntimeError('Original API did not stop gracefully')
new_configs={}
for name,config in configs.items():
 new=dict(config);new.update(NOVEL_FORGE_ROOT=str(release),PYTHONPATH=str(release/'src'),NOVEL_FORGE_APPLICATION_BUILD_ID=f'delivery-window-{digest[:12]}',NOVEL_FORGE_COMMIT_SHA=sha,NOVEL_FORGE_NO_MODEL_DISPATCH='1')
 new_configs[name]=new
runtime_env={**os.environ,**new_configs['recovery-env.private.json']}
code='''import json,os
from psycopg.conninfo import make_conninfo
from novel_forge.storage.migrations import run_migrations
url=make_conninfo(os.environ['NOVEL_FORGE_DATABASE_URL'],options='-c default_transaction_read_only=off',connect_timeout=5)
result=run_migrations(url)
print(json.dumps(result,indent=2,default=str))
assert result['ok'], result
'''
try:
 with (base/'native-migration.json').open('w') as out,(base/'native-migration.stderr').open('w') as err:
  subprocess.run([python,'-c',code],cwd=release,env=runtime_env,stdout=out,stderr=err,check=True,timeout=90)
except Exception:
 with (service/'api.log').open('a') as log:
  old=subprocess.Popen([python,'-m','novel_forge.cli.authority','serve-api','--host','127.0.0.1','--port','8144'],cwd=configs['api-env.private.json']['NOVEL_FORGE_ROOT'],env={**os.environ,**configs['api-env.private.json']},stdout=log,stderr=log,start_new_session=True)
 (service/'api.pid').write_text(str(old.pid)+'\n')
 raise
for name,new in new_configs.items():(service/name).write_text(json.dumps(new,indent=2)+'\n')
with (base/'api.log').open('a') as log:
 api=subprocess.Popen([python,'-m','novel_forge.cli.authority','serve-api','--host','127.0.0.1','--port','8144'],cwd=release,env={**os.environ,**new_configs['api-env.private.json']},stdout=log,stderr=log,start_new_session=True)
(service/'api.pid').write_text(str(api.pid)+'\n')
manifest['api_pid']=api.pid
(base/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for _ in range(60):
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8144/health',timeout=2) as response:health=json.load(response)
  break
 except Exception:
  if api.poll() is not None:raise RuntimeError('Replacement API exited; inspect private API log')
  time.sleep(.5)
else:raise RuntimeError('Replacement API health timed out')
(base/'health.json').write_text(json.dumps(health,indent=2)+'\n')
assert health['provider_dispatch_suspended'] is True
print(json.dumps({'release_root':str(release),'patch_sha256':digest,'api_pid':api.pid,'health':health},indent=2))
