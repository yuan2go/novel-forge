import subprocess,os,json,sys
from pathlib import Path
from novel_forge.tools.implementation_tree_identity import build_implementation_tree_identity
root=Path('/tmp/nf-corpus-wp3c-20260909');out=root/'frozen-checks';out.mkdir(exist_ok=True)
env=dict(os.environ);env['NOVEL_FORGE_DATABASE_URL']=json.loads((root/'environment.json').read_text())['database_url'];sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();env['CORPUS_TESTED_SHA']=sha;env['CORPUS_EVIDENCE_DIR']=str(out)
commands=[['make','validate'],[sys.executable,'-m','novel_forge.tools.head_integrity','--repo-root','.'],[sys.executable,'-m','pytest','-q','tests/unit/test_corpus_admission.py','tests/unit/test_corpus_ingestion_formats.py','tests/unit/test_corpus_ingestion_transports.py','tests/unit/test_source_import_domain.py','tests/unit/test_classical_corpus_parser.py','tests/unit/test_source_import_worker_permissions.py','tests/unit/test_source_import_deadline_contract.py','tests/integration/test_corpus_foundation_postgres.py','tests/integration/test_corpus_ingestion_postgres.py','tests/integration/test_source_import_runtime_postgres.py','--junitxml='+str(out/'focused.xml')],[sys.executable,'-m','pytest','-q','tests/integration/test_corpus_migrations_postgres.py','-k','0126 or 0001','--junitxml='+str(out/'migration.xml')]]
report={'tested_sha':sha,'source_tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],text=True).strip(),'implementation':build_implementation_tree_identity('.'),'commands':[]}
(out/'identity.json').write_text(json.dumps(report,indent=2))
for index,cmd in enumerate(commands):
 with (out/f'{index}.log').open('w') as log:
  r=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
 report['commands'].append({'argv':cmd,'exit_code':r.returncode,'log':f'{index}.log'});(out/'results.json').write_text(json.dumps(report,indent=2));print(index,r.returncode,flush=True)
