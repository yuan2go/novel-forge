import json, os, subprocess
from pathlib import Path
ids=json.loads(Path('/tmp/nf-context-router-2cb74ed-evidence/baseline-failure-nodeids.json').read_text())
env={**os.environ,'PYTHONPATH':'src'}
result=subprocess.run(['/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python','-m','pytest','-q',*ids,'--junitxml=/tmp/nf-context-router-2cb74ed-evidence/baseline-full-failures.xml'],cwd='/Volumes/DevSSD/Development/Workspace/projects/novel-forge-context-router-baseline-2cb74ed',env=env)
raise SystemExit(result.returncode)
