from pathlib import Path
import subprocess
import sys

root = Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
evidence = Path(__file__).parent
paths = [
'src/novel_forge/modules/authority_handler_runtime/policy_commands.py',
'src/novel_forge/modules/authority_handler_runtime/routing_feedback.py',
'src/novel_forge/modules/book_authority/execution_recovery.py',
'src/novel_forge/modules/book_authority/production.py',
'src/novel_forge/modules/command_kernel/external_effect_runtime.py',
'src/novel_forge/modules/command_kernel/routing_bootstrap.py',
'src/novel_forge/modules/chapter_authority/context_compression_provider.py',
'config/execution_templates/creative_validation.json',
'src/novel_forge/storage/world_preparation_repositories.py',
'tests/integration/creative_validation_production_support.py',
'tests/integration/test_book_to_chapter_authority_vertical_postgres.py',
'tests/integration/test_creation_cli_postgres.py',
'tests/integration/test_creative_validation_admission_postgres.py',
'tests/integration/test_external_effect_runtime_postgres.py',
'tests/integration/test_synthesis_formation_postgres.py',
'tests/unit/test_authority_asset_locator.py',
'tests/unit/test_authority_worker_execution.py',
'tests/unit/test_book_execution_recovery.py',
'tests/unit/test_codex_execution_evidence.py',
'tests/unit/test_context_compression_provider.py',
]
for path in paths:
    source = subprocess.check_output(['git','-C',str(root),'show',f'ad1c229d:{path}'])
    base = subprocess.run(['git','-C',str(root),'show',f'e2064ede:{path}'],capture_output=True)
    target = root/path
    if base.returncode:
        if target.exists():
            raise RuntimeError(f'unexpected added path {path}')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source)
        print('ADD',path)
        continue
    baseline = evidence/'merge-base.tmp'
    incoming = evidence/'merge-source.tmp'
    baseline.write_bytes(base.stdout)
    incoming.write_bytes(source)
    merged = subprocess.run(['git','merge-file','-p',str(target),str(baseline),str(incoming)],capture_output=True)
    if merged.returncode:
        (evidence/(Path(path).name+'.conflict')).write_bytes(merged.stdout)
        print('CONFLICT_RETAIN_MAIN',path)
    else:
        target.write_bytes(merged.stdout)
        print('MERGE_DELTA',path)
