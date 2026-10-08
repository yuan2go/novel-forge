from pathlib import Path
import json, os, subprocess
from psycopg.conninfo import make_conninfo
service = Path(__file__).parent.parent
config = json.loads((service / "recovery-env.private.json").read_text())
release = Path(config["NOVEL_FORGE_ROOT"])
env = {k:v for k,v in os.environ.items() if not k.startswith(("NOVEL_FORGE_", "OPENAI_", "DEEPSEEK_", "ANTHROPIC_", "CODEX_"))}
env.update(config)
env["NOVEL_FORGE_NO_MODEL_DISPATCH"] = "1"
env["NOVEL_FORGE_DATABASE_URL"] = make_conninfo(config["NOVEL_FORGE_DATABASE_URL"], options="-c default_transaction_read_only=on", connect_timeout=5)
command = ["/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python", "-m", "novel_forge.cli.authority", "authority-creation", "status", "--project-id", "qid-learning-prose-01", "--book-id", "book:qinglan-wendao-20261008", "--formation-run-id", "story-formation:0a8aa0c2dc447a252fad800a5a31b0663fd6f167087d18bfeb5a980a8afe261d", "--repository-root", str(release)]
result = subprocess.run(command, cwd=release, env=env, capture_output=True, text=True, timeout=60)
if result.returncode:
    raise RuntimeError("Original native status read failed; preserve its identity and inspect local runtime diagnostics")
parsed=json.loads(result.stdout)
(Path(__file__).parent / "original-native-cli-status.json").write_text(json.dumps(parsed,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({key:parsed.get(key) for key in ("project_id", "book_id", "formation_run_id", "author_state", "next_action", "responsible_party", "production", "unresolved_external_effects")},ensure_ascii=False,indent=2))
