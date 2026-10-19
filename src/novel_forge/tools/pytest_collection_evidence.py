from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pytest


SCHEMA_VERSION = "novel-forge.pytest-collection.v1"
OPTION = "--novel-forge-collection-report"
COLLECTION_ERRORS: list[dict[str, str]] = []
FAILURE_REPORT_PATH: Path | None = None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("novel-forge-qualification")
    group.addoption(
        OPTION,
        action="store",
        default="",
        metavar="PATH",
        help="write atomic machine-readable pytest collection evidence",
    )


def pytest_configure(config: pytest.Config) -> None:
    global FAILURE_REPORT_PATH
    COLLECTION_ERRORS.clear()
    output = str(config.getoption(OPTION) or "").strip()
    FAILURE_REPORT_PATH = Path(output).resolve().with_suffix(".failures.jsonl") if output else None


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if not report.failed:
        return
    COLLECTION_ERRORS.append(
        {
            "node_id": str(report.nodeid),
            "outcome": str(report.outcome),
        }
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if FAILURE_REPORT_PATH is None or not report.failed:
        return
    from .backend_qualification_contract import sanitize_evidence

    path = FAILURE_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": "novel-forge.pytest-failure-event.v1",
        "node_id": str(report.nodeid),
        "phase": str(report.when),
        "failure": sanitize_evidence(report.longreprtext),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "process_id": os.getpid(),
    }
    if getattr(report, "context", None) is not None:
        event["subtest_context"] = sanitize_evidence(str(report.context))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _relative_source(item: pytest.Item, root: Path) -> str:
    source = Path(str(item.path)).resolve()
    try:
        return source.relative_to(root).as_posix()
    except ValueError:
        return Path(os.path.relpath(source, root)).as_posix()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    output = str(session.config.getoption(OPTION) or "").strip()
    if not output:
        return
    root = Path(str(session.config.rootpath)).resolve()
    node_ids = sorted(str(item.nodeid) for item in session.items)
    source_files = sorted({_relative_source(item, root) for item in session.items})
    report = {
        "schema_version": SCHEMA_VERSION,
        "collected_count": len(node_ids),
        "node_ids": node_ids,
        "source_files": source_files,
        "collection_errors": list(COLLECTION_ERRORS),
        "pytest_exit_status": int(exitstatus),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(Path(output).resolve(), report)


__all__ = ["OPTION", "SCHEMA_VERSION"]
