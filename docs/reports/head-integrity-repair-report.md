# HEAD Integrity Repair Report

Date: 2026-07-30

## Baseline

| Item | Evidence |
| --- | --- |
| Branch | `feat/v7-content-intelligence-and-longform-proof` |
| Starting HEAD | `9101aef459d57c9ca570957fcfff9e7b4214561a` |
| Remote | local and origin are equal (`0 0` ahead/behind) |
| Pull | `git pull --ff-only` reported already up to date |
| Tracked tree | 1,551 files |
| Existing tracked diff | none |
| Existing untracked files | 30 |

The 30 untracked files are not discarded or overwritten. Twenty-nine are the new
files reported by the 2026-07-29 P0 implementation report; the remaining
`.idea/novel-forge.iml` is a restored IDE metadata file that commit `9101aef`
deleted. Runtime implementation and IDE metadata are handled separately.

## Confirmed integrity defect

Commit `9101aef` modified registries and imports but did not track their targets:

- `book_authority.__init__` imports `production.py` and
  `governed_scheduler.py`;
- `authority_app` imports the Book router;
- `authority_repositories` imports the Book repository;
- migration registry imports
  `v20260729_0034_unified_business_authority`;
- coverage/parity tooling imports Book follow-up definitions.

A clean `git archive HEAD` fails with:

```text
ModuleNotFoundError: novel_forge.modules.book_authority.production
ImportError: v20260729_0034_unified_business_authority
```

The current worktree, which contains the omitted files, passes:

```text
compileall = PASS
import novel_forge = PASS
import novel_forge.modules.book_authority = PASS
import novel_forge.api.authority_app = PASS
migration registry = 34 modules
authority parity = PASS (12/12)
```

This proves an incomplete commit, not a need to invent replacement architecture.

## Unmodified test baseline

| Command | Passed | Failed | Skipped | Duration |
| --- | ---: | ---: | ---: | ---: |
| unit discovery | 1,116 | 0 | 0 | 465.917s |
| architecture discovery | 47 | 1 | 0 | 11.940s |
| acceptance discovery | 2 | 0 | 0 | 0.400s |
| `make postgres-authority-test` | 114 | 0 | 0 | 82.593s |

The sole architecture failure is
`AuthorityCoverageBaselineTests.test_checked_in_baseline_matches_current_head_scan`:
the checked-in `source_tree_sha` does not include the omitted runtime files.

## Stage-1 repair decision

1. Review and track the omitted P0 runtime/config/test/doc files.
2. Keep `.idea/novel-forge.iml` outside the product repair unless repository
   policy explicitly requires restoring it.
3. Add a fail-closed HEAD integrity command covering imports, `__all__`,
   migrations, routers, definitions, handlers, and required test collection.
4. Run that command in CI on a clean checkout.
5. Regenerate HEAD-bound coverage evidence only after the complete source set is
   tracked.
6. Do not proceed to Book/Chapter behavior changes until the Stage-1 gates pass.
