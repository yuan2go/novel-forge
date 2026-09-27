import json,os
from pathlib import Path
from dataclasses import replace
from novel_forge.api.authority_dependencies import authority_release_identity,build_trusted_principal_resolver
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.capability_pack_authority.application import CapabilityPackAuthorityApplication
from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
from novel_forge.modules.capability_packs.validation_deployment import _pack_command
from novel_forge.modules.command_kernel.dispatch_control import process_dispatch_suspended,dispatch_control_status
from novel_forge.modules.story_planning_runtime.application import story_planning_generation_definition
from novel_forge.storage.authority_repositories import definition_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
settings=IndustrialSettings.from_env();build,sha=authority_release_identity();assert process_dispatch_suspended()
project='narrative-closure-02-admission-20260927';workspace='ws:zheng-deng:sampling:20260927'
assert dispatch_control_status(settings.database_url,project_id=project)['state']=='PAUSED'
principal=build_trusted_principal_resolver().resolve_api_principal();compiler=replace(principal,principal_type=PrincipalType.SERVICE)
definition=story_planning_generation_definition(application_build_id=build,commit_sha=sha)
pack_id='wp02-planning-diagnostic-'+sha[:12]+'-native-retry'
profile=build_story_planning_pack_profile(Path(os.environ['NOVEL_FORGE_ROOT']),operation_definition_hash=definition_hash(definition),pack_id=pack_id)
retry_constraints=[node['retry_policy'] for node in profile.manifest['workflow_template']['nodes']]
with AuthorityUnitOfWork(settings.database_url) as uow:
    uow.cursor.execute('SELECT current_database()');assert uow.cursor.fetchone()[0]=='novel_forge_REDACTED_PRIVATE_IDENTIFIER_test'
    uow.cursor.execute('SELECT count(*) FROM authority_external_effect_dispatch');before=uow.cursor.fetchone()[0]
    uow.repositories.definitions.register(definition);uow.commit()
app=CapabilityPackAuthorityApplication(settings.database_url,application_build_id=build,commit_sha=sha)
common=dict(project_id=project,workspace_id=workspace,pack_id=pack_id,stable_suffix='author-entry-'+sha)
registration=_pack_command(app,compiler,action='capability_pack.manifest.register',pack_version='',payload={'manifest':profile.manifest,'artifact_catalog':dict(profile.artifact_catalog),'release_channel':'VALIDATION','owner_scope_type':'PROJECT','owner_project_id':project,'dependencies':[]},**common)
compilation_id='compilation:author-entry:'+pack_id
compiled=_pack_command(app,compiler,action='capability_pack.compile',pack_version=profile.manifest['identity']['version'],compilation_id=compilation_id,payload={'target_runtime_profile':'validation','novel_forge_version':'6.0.0','release_sha':sha,'release_channel':'VALIDATION'},**common)
with AuthorityUnitOfWork(settings.database_url) as uow:
    uow.cursor.execute('SELECT count(*) FROM authority_external_effect_dispatch');assert before==uow.cursor.fetchone()[0]
result={'state':'COMPILED_PENDING_INDEPENDENT_APPROVAL','commit_sha':sha,'pack_id':pack_id,'compilation_id':compilation_id,'compiler':compiler.principal_id,'registration':registration,'compilation':compiled,'project_id':project,'book_id':'duanchao-guan-zheng-deng-reference-01','authority_retry_constraints':retry_constraints,'diagnostic_call_limit_per_grant':1,'diagnostic_dispatch_status':'PENDING_NATIVE_GRANTS_AND_INDEPENDENT_APPROVAL','real_model_calls':0,'agents_registered':0,'approval_recorded':False,'deployment_created':False,'activation_created':False}
p=Path('/tmp/novel-forge-real-prose-20260927/reviewable-pack.json');p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str));p.chmod(0o600)
print(json.dumps({k:result[k] for k in ('state','pack_id','compilation_id','compiler','real_model_calls','agents_registered')},ensure_ascii=False))
