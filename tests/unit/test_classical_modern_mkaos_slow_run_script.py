from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "import_classical_modern_to_mkaos.py"


class ClassicalModernMkaosSlowRunScriptTests(unittest.TestCase):
    def test_dry_run_writes_checkpoint_ledger_and_no_source_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _sample_repo(root)
            storage = root / "workspace"
            checkpoint = root / "checkpoint.json"
            ledger = root / "ledger.jsonl"
            report = root / "report.md"

            result = _run_script(
                [
                    "--repo-path",
                    str(repo),
                    "--storage-root",
                    str(storage),
                    "--project-id",
                    "slow-dry",
                    "--max-books",
                    "1",
                    "--max-files",
                    "1",
                    "--dry-run",
                    "--checkpoint-path",
                    str(checkpoint),
                    "--ledger-path",
                    str(ledger),
                    "--report-path",
                    str(report),
                ]
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertTrue(data["import"]["dry_run"])
            self.assertEqual(data["provider"]["requested"], False)
            self.assertTrue(ledger.exists())
            self.assertIn('"status": "dry_run"', ledger.read_text(encoding="utf-8"))
            self.assertTrue(report.exists())
            self.assertEqual(list((storage / "data" / "raw").glob("source-document*.json")), [])

    def test_provider_unavailable_records_ledger_and_keeps_evidence_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _sample_repo(root)
            storage = root / "workspace"
            checkpoint = root / "checkpoint.json"
            ledger = root / "ledger.jsonl"
            report = root / "report.md"

            result = _run_script(
                [
                    "--repo-path",
                    str(repo),
                    "--storage-root",
                    str(storage),
                    "--project-id",
                    "slow-provider-unavailable",
                    "--max-books",
                    "1",
                    "--max-files",
                    "1",
                    "--run-provider",
                    "--provider-max-calls",
                    "2",
                    "--codex-command",
                    str(root / "missing-codex"),
                    "--checkpoint-path",
                    str(checkpoint),
                    "--ledger-path",
                    str(ledger),
                    "--report-path",
                    str(report),
                ]
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertTrue(data["provider"]["requested"])
            self.assertEqual(data["provider"]["health"]["status"], "unavailable")
            self.assertIn('"status": "provider_unavailable"', ledger.read_text(encoding="utf-8"))
            self.assertTrue(list((storage / "data" / "raw").glob("source-document*.json")))
            self.assertIn('"provider_failures": 1', report.read_text(encoding="utf-8"))

    def test_index_only_import_writes_evidence_without_source_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _sample_repo(root)
            (repo / "古文原文" / "史记" / "项羽本纪").mkdir(parents=True)
            (repo / "古文原文" / "史记" / "项羽本纪" / "text.txt").write_text("军令、威望与误判共同推动战争转折。", encoding="utf-8")
            (repo / "古文原文" / "史记" / "重复章").mkdir(parents=True)
            (repo / "古文原文" / "史记" / "重复章" / "text.txt").write_text("礼法形成秩序压力，人物必须在名分与行动之间选择。", encoding="utf-8")
            storage = root / "workspace"
            checkpoint = root / "checkpoint.json"
            ledger = root / "ledger.jsonl"
            report = root / "report.md"

            result = _run_script(
                [
                    "--repo-path",
                    str(repo),
                    "--storage-root",
                    str(storage),
                    "--project-id",
                    "slow-index",
                    "--max-books",
                    "2",
                    "--max-files",
                    "3",
                    "--index-only",
                    "--skip-existing",
                    "--checkpoint-path",
                    str(checkpoint),
                    "--ledger-path",
                    str(ledger),
                    "--report-path",
                    str(report),
                ]
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list((storage / "data" / "raw").glob("source-document*.json")), [])
            chapters = list((storage / "data" / "raw").glob("book-chapter-source*.json"))
            self.assertEqual(len(chapters), 3)
            chapter = json.loads(chapters[0].read_text(encoding="utf-8"))
            self.assertTrue(chapter["content"]["index_only"])
            self.assertIn("content_hash", chapter["content"])
            self.assertEqual(chapter["content"]["source_isolation"]["raw_text_included"], False)
            self.assertEqual(chapter["metadata"]["use_in_generation_rag"], False)
            summary = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(summary["import"]["chapter_count"], 3)
            self.assertIn('"imported_chapters": 3', report.read_text(encoding="utf-8"))

            rerun = _run_script(
                [
                    "--repo-path",
                    str(repo),
                    "--storage-root",
                    str(storage),
                    "--project-id",
                    "slow-index",
                    "--max-books",
                    "2",
                    "--max-files",
                    "3",
                    "--index-only",
                    "--checkpoint-path",
                    str(checkpoint),
                    "--ledger-path",
                    str(ledger),
                    "--report-path",
                    str(report),
                ]
            )

            self.assertEqual(rerun.returncode, 0, rerun.stderr)
            self.assertEqual(len(list((storage / "data" / "raw").glob("book-chapter-source*.json"))), 3)

            skip_existing_rerun = _run_script(
                [
                    "--repo-path",
                    str(repo),
                    "--storage-root",
                    str(storage),
                    "--project-id",
                    "slow-index",
                    "--max-books",
                    "2",
                    "--max-files",
                    "3",
                    "--index-only",
                    "--skip-existing",
                    "--checkpoint-path",
                    str(checkpoint),
                    "--ledger-path",
                    str(ledger),
                    "--report-path",
                    str(report),
                ]
            )

            self.assertEqual(skip_existing_rerun.returncode, 0, skip_existing_rerun.stderr)
            skip_summary = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(skip_summary["import"]["chapter_count"], 3)
            self.assertEqual(len(list((storage / "data" / "raw").glob("book-chapter-source*.json"))), 3)


def _sample_repo(root: Path) -> Path:
    repo = root / "corpus"
    (repo / "古文原文" / "论语" / "学而").mkdir(parents=True)
    (repo / "古文原文" / "论语" / "学而" / "text.txt").write_text("礼法形成秩序压力，人物必须在名分与行动之间选择。", encoding="utf-8")
    (repo / "双语数据" / "论语").mkdir(parents=True)
    (repo / "双语数据" / "论语" / "bitext.txt").write_text("礼法。|||礼法。", encoding="utf-8")
    return repo


def _run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


if __name__ == "__main__":
    unittest.main()
