from pathlib import Path
import subprocess, json, hashlib, re
from datetime import datetime, timezone

A=Path(__file__).parent
P=Path('/Volumes/DevSSD/Development/Workspace/projects/novel-forge')
E=A/'evidence'
def git(*args):
    return subprocess.check_output(['git','-C',str(P),*args],text=True)
base=json.loads((A/'baseline.json').read_text())
status=git('status','--porcelain=v1')
expanded_status=git('status','--porcelain=v1','--untracked-files=all')
diff=git('diff','--no-ext-diff')
remote=git('ls-remote','origin','refs/heads/main').split()[0]
head=git('rev-parse','HEAD').strip()
(A/'status-supplement-final.txt').write_text(status)
(A/'status-supplement-expanded.txt').write_text(expanded_status)
(A/'diff-supplement-final.txt').write_text(diff)
boundary=json.loads((E/'final-boundaries.json').read_text())
boundary.update(captured_utc=datetime.now(timezone.utc).isoformat(),branch_head=head,remote_main=remote,
    remote_unchanged=remote==base['remote_main'],head_unchanged=head==base['local_head'],
    status_identical=status==(A/'status.txt').read_text(),
    tracked_diff_identical=diff==(A/'diff.txt').read_text(),
    supplementary_offline_checks=11,supplementary_method_context_cases=8,
    status_comparison_mode='porcelain-v1 normal, same as opening; expanded inventory retained separately',
    new_provider_calls=0,production_mutations_by_audit=0)
(E/'multigenre-final-boundaries.json').write_text(json.dumps(boundary,ensure_ascii=False,indent=2)+'\n')
missing=[];checked=0
for p in sorted(A.glob('0*.md')):
    for m in re.finditer(r'\]\(([^)]+)\)',p.read_text()):
        target=m.group(1).split('#')[0].strip('<>')
        if target.startswith(('http:','https:')):continue
        target=re.sub(r':\d+$','',target)
        if not target:continue
        f=Path(target) if target.startswith('/') else p.parent/target
        checked+=1
        if not f.exists():missing.append({'report':p.name,'target':target})
(E/'report-link-check.json').write_text(json.dumps({'checked':checked,'missing':missing},ensure_ascii=False,indent=2)+'\n')
files=[]
for p in sorted(A.rglob('*')):
    if not p.is_file() or p==A/'MANIFEST.json' or A/'main' in p.parents or '__pycache__' in p.parts:continue
    data=p.read_bytes();files.append({'path':str(p.relative_to(A)),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
manifest={'schema':'read-only-prompt-craft-audit.manifest.v1','baseline_main':base['remote_main'],
    'new_provider_calls':0,'production_mutations_by_audit':0,'files':files}
(A/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'boundaries':boundary,'link_checked':checked,'missing_links':missing,'manifest_files':len(files)},ensure_ascii=False))
