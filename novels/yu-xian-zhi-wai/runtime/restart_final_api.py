from pathlib import Path
import json,os,subprocess,signal,time
R=Path(__file__).resolve().parent
old=json.loads((R/'api-final.json').read_text());cmd=subprocess.run(['ps','-p',str(old['pid']),'-o','command='],capture_output=True,text=True).stdout
if cmd and 'novel_forge.cli.authority serve-api' not in cmd:raise RuntimeError('Unexpected owned API process')
if cmd:os.kill(old['pid'],signal.SIGTERM)
p=R/'local-environment.json';v=json.loads(p.read_text());v['NOVEL_FORGE_COMMIT_SHA']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();v['NOVEL_FORGE_APPLICATION_BUILD_ID']='first-novel-pilot-local-'+v['NOVEL_FORGE_COMMIT_SHA'][:12];p.write_text(json.dumps(v,indent=2));p.chmod(0o600)
time.sleep(1)
with (R/'api-qualified-code.log').open('ab') as log:proc=subprocess.Popen([str(R/'nf'),'serve-api','--host','127.0.0.1','--port','51009'],stdout=log,stderr=log,start_new_session=True)
(R/'api-current.json').write_text(json.dumps({'pid':proc.pid,'url':'http://127.0.0.1:51009','implementation_sha':v['NOVEL_FORGE_COMMIT_SHA'],'workers_started':False},indent=2))
print({'api_pid':proc.pid,'implementation_sha':v['NOVEL_FORGE_COMMIT_SHA'],'model_calls':0})

