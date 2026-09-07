import json,hashlib
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
from tests.integration.authority_postgres_support import insert_definition, insert_operation
from novel_forge.storage.migrations import run_migrations
base=Path('/tmp/nf-production-synthesis-20260907');scope=json.loads((base/'upgrade-scope.json').read_text());url='postgresql://novel_forge:isolated_synthesis@127.0.0.1:50085/novel_forge_synthesis_upgrade_test'
def rows():
 with psycopg.connect(url) as c,c.cursor() as x:
  x.execute('SELECT to_jsonb(g) FROM authority_story_planning_generation g ORDER BY generation_id');return [r[0] for r in x.fetchall()]
def digest(r):return hashlib.sha256(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest()
with psycopg.connect(url) as c,c.cursor() as x:
 insert_definition(x,'migration-generation')
 for index,(name,kind) in enumerate([('book_plan.generate','BOOK'),('volume_plan.generate','VOLUME'),('arc_plan.generate','ARC'),('chapter_group_plan.generate','CHAPTER_GROUP'),('chapter_plan.generate','CHAPTER')]):
  op=f'migration-planning:{index}'
  insert_operation(x,operation_id=op,definition_name='migration-generation',project_id=scope['project_id'],workspace_id=scope['workspace_id'],command_payload={'payload':{'book_id':scope['book_id']}})
  x.execute('''INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,book_id,generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ADMITTED')''',[op,op,scope['project_id'],scope['workspace_id'],scope['book_id'],name,kind,op,Jsonb([]),'sha256:'+'1'*64])
before=rows();status=run_migrations(url);after=rows();assert before==after
report={'previous_source_sha':'8b2c48372b20301d88d6d00cceae9e070ce63549','previous_head':'20260907_0119_grounded_chapter_acceptance','after_head':status['current'],'applied_count':len(status['applied']),'existing_generations':len(before),'before_data_hash':digest(before),'after_data_hash':digest(after),'unchanged':before==after,'ok':status['ok'],'proof_ceiling':'MIGRATION_COMPATIBILITY_ONLY'}
assert report['ok'] and report['applied_count']==120
(base/'migration-upgrade.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
