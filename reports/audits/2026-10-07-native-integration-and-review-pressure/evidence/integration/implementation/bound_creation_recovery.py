from pathlib import Path
p=Path('src/novel_forge/modules/book_authority/creation_runtime.py')
s=p.read_text()
start=s.index('def drive_book(')
end=s.index('\n\ndef continue_creation',start)
f=s[start:end]
f=f.replace('def drive_book(', 'def _drive_book(' ,1)
f=f.replace('    for _ in range(maximum_ticks):', '''    recovery_actions = 0

    def recover(action: Callable[[], bool]) -> bool:
        nonlocal recovery_actions
        execution_probe()
        if not continuation_live():
            composition.authority.cancel(book_run_id, reason="Original creation cancellation", principal=composition.principal)
            raise _RecoveryCheckpoint("CANCELLED")
        current = composition.authority.require(book_run_id)
        worker.require("book.authority.execute", current["project_id"])
        if current["state"] == "COMPLETED":
            raise _RecoveryCheckpoint("COMPLETED")
        if current["state"] in {"ABORTED", "CANCELLED"}:
            raise _RecoveryCheckpoint("CANCELLED")
        if monotonic() >= deadline or recovery_actions >= maximum_ticks:
            raise _RecoveryCheckpoint("YIELDED_CHECKPOINT")
        changed = action()
        if changed:
            recovery_actions += 1
        return changed

    for _ in range(maximum_ticks):''',1)
import re
f=re.sub(r'(recover_\w+|recover_timeout)\(composition.authority, book_run_id=book_run_id, principal=composition.principal\)',r'recover(lambda: \1(composition.authority, book_run_id=book_run_id, principal=composition.principal))',f)
f=re.sub(r'(recover_\w+)\(\s*composition.authority, book_run_id=book_run_id, principal=composition.principal\s*\)',r'recover(lambda: \1(composition.authority, book_run_id=book_run_id, principal=composition.principal))',f)
f=f.replace('if resume_rejected_book_plan(composition,book,worker=worker):','if recover(lambda: resume_rejected_book_plan(composition, composition.authority.require(book_run_id), worker=worker, execution_probe=execution_probe)):')
# The public boundary translates finite/cancellation checkpoints without absorbing lease errors.
wrapper='''class _RecoveryCheckpoint(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def drive_book(*, composition: Any, chapter: Any, book_run_id: str, worker: Any,
               maximum_ticks: int, deadline: float, continuation_live: Callable[[], bool] = lambda: True, execution_probe: Callable[[], object] = lambda: None, events: Callable[[dict[str, Any]], None] = lambda _: None) -> str:
    try:
        return _drive_book(composition=composition, chapter=chapter, book_run_id=book_run_id,
            worker=worker, maximum_ticks=maximum_ticks, deadline=deadline,
            continuation_live=continuation_live, execution_probe=execution_probe, events=events)
    except _RecoveryCheckpoint as checkpoint:
        return checkpoint.reason


'''
s=s[:start]+wrapper+f+s[end:]
p.write_text(s)
