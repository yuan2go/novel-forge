#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_forge.modules.provider_qualification import D0ProbeConfig, run_d0_probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/provider/d0-openai-probe.json")
    args = parser.parse_args()
    payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = run_d0_probe(D0ProbeConfig.from_mapping(payload))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.status == "PASSED" else 2 if report.status.startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
