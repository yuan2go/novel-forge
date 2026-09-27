import json,os,sys
from pathlib import Path
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.content_authority.registry import ContentHandlerRegistry
from novel_forge.modules.command_kernel.dispatch_control import process_dispatch_suspended
private=json.loads(Path('/tmp/novel-forge-real-prose-20260927/service-environment.json').read_text())
os.environ.update(private)
operation_id=sys.argv[1]
with AuthorityUnitOfWork(private['NOVEL_FORGE_DATABASE_URL']) as uow:
    uow.cursor.execute('SELECT current_database()'); assert uow.cursor.fetchone()[0].startswith('nf_p0_')
    uow.cursor.execute('SELECT project_id,definition_name,command_payload FROM authority_operation WHERE operation_id=%s',[operation_id]); project,definition,payload=uow.cursor.fetchone()
    assert definition=='creative.brief.create'
    assert payload['payload']['brief']['constraints']==['仅作作者接口测试']
    uow.cursor.execute('SELECT count(*) FROM authority_external_effect_dispatch');before=uow.cursor.fetchone()[0]
assert process_dispatch_suspended()
result=ContentAuthorityScheduler(private['NOVEL_FORGE_DATABASE_URL'],registry=ContentHandlerRegistry()).run_or_recover(operation_id=operation_id,project_id=project)
with AuthorityUnitOfWork(private['NOVEL_FORGE_DATABASE_URL']) as uow:
    uow.cursor.execute('SELECT count(*) FROM authority_external_effect_dispatch');assert uow.cursor.fetchone()[0]==before
print(json.dumps({'operation_id':operation_id,'executed':'exact isolated non-model Content command','model_dispatch_delta':0}))
