# Longform 12 Chapter Pressure Acceptance

Fixture: generated chapters `chapter_100.md` through `chapter_111.md`, copied into an isolated `.local` workspace with deterministic pressure injectors for drift, metadata leaks, repetition, motif overload and weak villain presence.
Workspace: `/Users/yuan/projects/novel-forge/.local/longform-12ch-pressure-runs/run-20260702012247`

Overall acceptance: `warning`
Blocked chapters: `12/12`
Revision tasks: `12`

| Chapter | Pass/Fail | Gate | Reasons | Revision Tasks | Canonical Written |
|---:|---|---|---|---:|---:|
| 100 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 沈砚; canon_forbidden_alias: forbidden alias appears in chapter: 北档房; canon_forbidden_alias: forbidden alias appears in chapter: 夜档库; canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_ | 12 | False |
| 101 | fail | blocked | json_wrapper_detected: chapter body is wrapped in a JSON text field; metadata_leak: JSON wrapper contains forbidden metadata key: notes; metadata_leak: JSON wrapper contains forbidden metadata key: metadata; metadata_leak: chapter body contains forbidden marke | 12 | False |
| 102 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 有字可查衙署; canon_unregistered_entity: potential core entity is not registered in canon: 跑五处印房; chapter_state: draft has no  | 12 | False |
| 103 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 义平仓归仓曹; canon_unregistered_entity: potential core entity is not registered in canon: 又像官署; canon_unregistered_entity: po | 12 | False |
| 104 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 沈砚; canon_forbidden_alias: forbidden alias appears in chapter: 北档房; canon_forbidden_alias: forbidden alias appears in chapter: 夜档库; canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_ | 12 | False |
| 105 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 工料局; chapter_state: draft has no chapter_state generated after drafting; pattern_similarity: three consecutive chapters  | 12 | False |
| 106 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 又像官署; chapter_state: draft has no chapter_state generated after drafting; pattern_similarity: three consecutive chapters | 12 | False |
| 107 | fail | blocked | json_wrapper_detected: chapter body is wrapped in a JSON text field; metadata_leak: JSON wrapper contains forbidden metadata key: notes; metadata_leak: JSON wrapper contains forbidden metadata key: metadata; metadata_leak: chapter body contains forbidden marke | 12 | False |
| 108 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 沈砚; canon_forbidden_alias: forbidden alias appears in chapter: 北档房; canon_forbidden_alias: forbidden alias appears in chapter: 夜档库; canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_ | 12 | False |
| 109 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 坊正署; canon_unregistered_entity: potential core entity is not registered in canon: 是坊正署; canon_unregistered_entity: poten | 12 | False |
| 110 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 又是巡遗司; canon_unregistered_entity: potential core entity is not registered in canon: 城课司; canon_unregistered_entity: pote | 12 | False |
| 111 | fail | blocked | canon_forbidden_alias: forbidden alias appears in chapter: 有人; canon_unregistered_entity: potential core entity is not registered in canon: 也懂仓库; canon_unregistered_entity: potential core entity is not registered in canon: 做的人懂账房; canon_unregistered_entity: po | 12 | False |

## Required Acceptance Questions

1. pass/fail: 0 pass, 12 fail.
2. JSON / notes / metadata intercepted: yes.
3. Chapter template repetition identified: yes.
4. Motif overload identified: yes.
5. Expansion without payoff identified: yes, through arc progress and foreshadowing acceptance checks.
6. revision_task generated: yes.
7. fail chapters canonical promotion blocked: yes, no ready release/canonical chapter asset is written for blocked rows.
8. inactive gates: none observed in this fixture; failures are represented by publishing gate blocking issues.

## Acceptance Summary

```json
{
  "check_count": 14,
  "passed_count": 11,
  "warning_count": 3,
  "failed_count": 0,
  "score": 79
}
```
