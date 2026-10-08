import json,os,sys,subprocess,traceback
from pathlib import Path
from types import SimpleNamespace
import psycopg
repo=Path('/Users/yuan/.codex/worktrees/creative-input-isolation-01/novel-forge')
sys.path[:0]=[str(repo/'src'),str(repo)]
case=sys.argv[1]
root=Path('/Users/yuan/.codex/creative-input-isolation-01-live/20261008')/case
root.mkdir(parents=True,exist_ok=True)
original=Path(Path('/tmp/nf-author-live-root').read_text().strip())
env=json.loads((original/'env.json').read_bytes())
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
project='project:input-isolation-01:'+case
workspace='workspace:input-isolation-01:'+case
book='book:input-isolation-01:'+case
for name in ('workspace','executions','objects'):(root/name).mkdir(exist_ok=True)
env.update(NOVEL_FORGE_DATABASE_URL='postgresql:///nf_creative_input_isolation_20261008_live',
 NOVEL_FORGE_ROOT=str(repo),NOVEL_FORGE_APPLICATION_BUILD_ID='creative-input-isolation-01:'+sha,
 NOVEL_FORGE_COMMIT_SHA=sha,NOVEL_FORGE_CODEX_WORKSPACE=str(root/'workspace'),
 NOVEL_FORGE_CODEX_EXECUTION_ROOT=str(root/'executions'),NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT=str(root/'objects'),
 NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE=project,NOVEL_FORGE_ENVIRONMENT='production')
os.environ.update(env)
os.environ.pop('DEEPSEEK_API_KEY',None)
# Executor bounds are deliberately outside the selected creative request.
(root/'env.json').write_text(json.dumps(env));(root/'env.json').chmod(0o600)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.cli.authority import _authority_parser,main
from novel_forge.cli.creation import run_creation_command
from novel_forge.modules.book_authority.creation_runtime import ensure_creation_scope
from novel_forge.api.authority_dependencies import build_trusted_principal_resolver,build_content_authority_application
from novel_forge.modules.content_authority.application import ContentOperationRequest
settings=IndustrialSettings.from_env()
if '--migrate' in sys.argv:
 main(['authority-migrate']);sys.exit()
principal=build_trusted_principal_resolver().resolve_api_principal()
ensure_creation_scope(settings,SimpleNamespace(project_id=project,workspace_id=workspace,book_id=book,idempotency_key='evaluation-case:'+case),
 principal=principal,title='WP input isolation evaluation '+case,build_id=env['NOVEL_FORGE_APPLICATION_BUILD_ID'],sha=sha)
selection={'contract_version':'creative-input-selection.v1','book_id':book,'source_kind':'CURRENT_AUTHOR_INPUT',
 'purpose':'CREATIVE_EVALUATION','intent_ref':'WP-CREATIVE-INPUT-ISOLATION-01:authorized-distinct-narrative-validation'}
parent_brief={'creative_brief_contract_version':'creative-brief-v2','idea':'为WP-CREATIVE-INPUT-ISOLATION-01明确选择不同叙事方式的非探案输入，并保留一个明确悬疑输入作正向对照。授权AI依据当前任务形成原创测试方案。',
 'genre':'本次明确选择的原创创作能力评测','audience':'成年中文读者','constraints':['人物行动、冲突推进和阅读回报遵从各自选定输入'],
 'source_boundaries':['历史试产简报、其他作品资产和工程实验条件不作为当前作者要求']}
parent=build_content_authority_application(settings).execute(ContentOperationRequest(definition_name='creative.brief.create',project_id=project,
 workspace_id=workspace,actor_id=principal.principal_id,idempotency_key='current-task-input:'+case,trace_id='trace:input:'+case,
 correlation_id=book,payload={'brief':parent_brief,'input_selection':selection}),principal=principal)
request=json.loads((repo/'config/evaluation/creative-inputs/isolation-01'/f'{case}.json').read_bytes())
request['input_selection']={**selection,'source_kind':'TASK_GENERATED','parent_input':{'asset_version_id':parent.asset_version_id,'content_hash':parent.content_hash}}
input_path=root/'selected-request.json';input_path.write_text(json.dumps(request,ensure_ascii=False,indent=2)+'\n')
parser=_authority_parser()
args=parser.parse_args(['authority-creation','start','--project-id',project,'--workspace-id',workspace,'--book-id',book,
 '--input-file',str(input_path),'--idempotency-key','selected-evaluation:'+case,'--repository-root',str(repo),
 '--maximum-ticks','1','--work-window-seconds','240','--yield-after-window','--foreground'])
for window in range(24):
 try:
  result=run_creation_command(settings,args)
  (root/f'window-{window:02}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
  print(json.dumps({'case':case,'window':window,'stop_reason':result.get('stop_reason'),'reason_code':result.get('reason_code'),'formation_run_id':result.get('formation_run_id')},ensure_ascii=False),flush=True)
  with psycopg.connect(settings.database_url) as c:
   saved=c.execute("select count(*) from authority_operation where project_id=%s and definition_name='chapter.draft.generate' and status='SUCCEEDED'",[project]).fetchone()[0]
   calls=c.execute('select count(*) from authority_external_effect where project_id=%s',[project]).fetchone()[0]
  if saved or calls>=32:break
  if result.get('stop_reason') not in ('YIELDED_CHECKPOINT','WORKER_OWNS_CONTINUATION','WAITING_LEASE_OR_DEPENDENCY'):break
  args.action='continue';args.formation_run_id=result['formation_run_id']
 except Exception as error:
  (root/f'error-{window:02}.json').write_text(json.dumps({'type':type(error).__name__,'code':getattr(error,'code',''),'message':str(error)},ensure_ascii=False,indent=2))
  print(type(error).__name__,str(error),flush=True);traceback.print_exc();break
print('evidence-root',root,flush=True)
