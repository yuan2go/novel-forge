from pathlib import Path
import subprocess

root = Path('/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge')
path = 'src/novel_forge/modules/book_authority/creation_runtime.py'
evidence = Path(__file__).parent
for ref, name in [('e2064ede', 'creation-base.tmp'), ('ad1c229d', 'creation-source.tmp')]:
    (evidence/name).write_bytes(subprocess.check_output(['git','-C',str(root),'show',f'{ref}:{path}']))
merged = subprocess.run(['git','merge-file','-p',str(root/path),str(evidence/'creation-base.tmp'),str(evidence/'creation-source.tmp')],capture_output=True)
assert merged.returncode == 0
(root/path).write_bytes(merged.stdout)
