"""CONSTRAINT: Read-only reconstruction needs the retained private Book and frozen task artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from novel_forge.modules.book_authority.manuscript import freeze_working_context, verify_working_context
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def covered(snapshot, case):
    source = next((row for row in snapshot['sources'] if row['asset_version_id'] == case['asset_version_id']), None)
    if source is None:
        return 'SOURCE_EXCLUDED'
    if source['content_hash'] != case['content_hash']:
        raise ValueError('EVIDENCE_SOURCE_CHANGED')
    cursor = case['start_codepoint']
    for passage in source['passages']:
        if passage['start'] <= cursor < passage['end']:
            cursor = min(passage['end'], case['end_codepoint'])
    return 'EXACT_SPAN_INCLUDED' if cursor == case['end_codepoint'] else 'EXACT_SPAN_MISSING'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-snapshot', type=Path, required=True)
    parser.add_argument('--critical-evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline_snapshot.read_text())
    checklist = json.loads(args.critical_evidence.read_text())
    with AuthorityUnitOfWork(os.environ['NOVEL_FORGE_DATABASE_URL']) as uow:
        uow.cursor.execute('SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s', [baseline['book_run_id']])
        book = uow.cursor.fetchone()[0]
        verify_working_context(uow, book, baseline, require_current=False)
        start = time.perf_counter()
        current = freeze_working_context(uow, book, baseline['target_chapter'],
            projection_policy={**baseline['projection_policy'], 'version': 'working-prose-projection.v10'},
            task_source_refs=[{key: row[key] for key in ('asset_version_id', 'content_hash')}
                for row in baseline['retrieval_task']['sources'] if row['plan_kind'] == 'chapter_plan'])
        elapsed = time.perf_counter() - start
        verify_working_context(uow, book, current, require_current=False)
    cases = checklist['checks']
    result = dict(boundary='READ_ONLY_FROZEN_TASK_RECONSTRUCTION_NOT_HISTORICAL_PROVIDER_DELIVERY',
        baseline_snapshot_hash=baseline['snapshot_hash'], current_snapshot_hash=current['snapshot_hash'],
        task_hash=current['retrieval_task']['task_hash'], elapsed_freeze_seconds=elapsed,
        checklist_file_sha256=hashlib.sha256(args.critical_evidence.read_bytes()).hexdigest(),
        selected_prose_codepoints=sum(len(p['text']) for row in current['sources'] for p in row['passages']),
        locator_receipt=current['context_selection']['source_locator_receipt'],
        cases=[dict(id=case['id'], chapter=case['chapter'], before=covered(baseline, case), after=covered(current, case)) for case in cases])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    try:
        main()
    except KernelError as error:
        raise SystemExit(str(error)) from error
