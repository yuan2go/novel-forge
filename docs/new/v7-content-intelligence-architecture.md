# V7 Content Intelligence Architecture

Updated: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`

---

## 1. Architecture Goal

This document defines the target architecture for the V7 Content Intelligence Layer.

The design must extend the existing Novel OS runtime instead of creating a separate writing system.

Required integration points:

```text
Schema-backed Asset System
LocalStorage / PostgreSQL write-through
Context Builder
MKAOS Production Gate
Canon Graph / Novel KG
Long Memory L0-L5
ModelRouter / ModelGateway
PromptRegistry
ToolGateway
Agent Scheduler
Loop Kernel
Evaluation Center
ReviewIssue / RevisionTask
Publish Gate / Release Package
Trace / Cost / Runtime Ledger
Web Admin Console
```

---

## 2. Layered Architecture

```text
Web Admin / CLI / API
  ↓
Product Workflow Layer
  - Genre Workflow
  - Style Workflow
  - Quality Eval Workflow
  - Long-chain Proof Workflow
  - Publishing Feedback Workflow
  ↓
Content Intelligence Layer
  - Genre OS
  - Style OS
  - Canon Graph 2.0 Plugins
  - Quality Eval 2.0
  - Long-chain Proof Center
  - Publishing/Feedback Adapter 2.0
  ↓
Novel OS Runtime Layer
  - Workflow Engine
  - Agent Scheduler
  - Loop Kernel
  - ModelRouter / PromptRegistry / ToolGateway
  - Context Builder
  - MKAOS Gate
  - Canon Graph / Novel KG
  - Long Memory / pgvector / Qdrant / local retrieval
  ↓
Evidence And Storage Layer
  - JSON assets
  - PostgreSQL index/write-through
  - pgvector projection
  - Qdrant optional service
  - MinIO optional object copy
  - TraceSpan / GateResult / ModelCallLog / CostLedger
```

---

## 3. Module Map

## 3.1 New Modules

```text
src/novel_forge/modules/genre_os/
  __init__.py
  service.py
  taxonomy.py
  strategy_pack.py
  risk_gate.py
  platform_matrix.py
  template_binding.py

src/novel_forge/modules/style_os/
  __init__.py
  service.py
  fingerprint.py
  profile.py
  drift_gate.py
  rewrite_policy.py
  sample_ingestion.py

src/novel_forge/modules/quality_eval/
  __init__.py
  service.py
  rubrics.py
  suite_runner.py
  judges.py
  calibration.py

src/novel_forge/modules/long_chain_proof/
  __init__.py
  service.py
  runner.py
  trend_analyzer.py
  acceptance.py
  fixtures.py

src/novel_forge/modules/publishing_feedback_adapters/
  __init__.py
  service.py
  upload_package.py
  receipt.py
  status.py
  metric_import.py
  comment_cluster.py
  dropoff.py
  mutation_proposal.py
```

## 3.2 Existing Modules To Extend

| Module | Required Extension |
|---|---|
| `modules/canon_graph/service.py` | Add plugin registry and typed reasoning engines |
| `modules/evaluation_center/service.py` | Reuse as base, add rubric-backed Quality Eval 2.0 |
| `modules/context_builder/service.py` | Inject genre/style/quality/canon evidence into flow bundles |
| `modules/agent_scheduler/service.py` | Register content intelligence operations |
| `modules/workflow_nodes/` or processor registry | Add workflow operations for genre/style/quality/long-chain/publishing feedback |
| `modules/publishing/` | Consume upload package and receipt state |
| `modules/feedback/` | Consume metric/comment adapters and mutation proposals |
| `schemas/assets.py` | Add schema-backed assets |
| `api/routers/` | Add product routes |
| `web/admin/app/` | Add feature consoles |

---

## 4. Data Model Design

## 4.1 Genre OS Assets

### genre_profile

```json
{
  "type": "genre_profile",
  "content": {
    "genre_id": "fantasy_xianxia",
    "genre_name": "仙侠",
    "parent_genre_id": "fantasy",
    "reader_promises": [],
    "core_pleasures": [],
    "required_systems": [],
    "common_risks": [],
    "status": "active"
  },
  "metadata": {
    "project_id": "",
    "use_in_generation_rag": false
  }
}
```

### subgenre_mechanic

```json
{
  "type": "subgenre_mechanic",
  "content": {
    "subgenre_id": "xianxia_fanren",
    "genre_id": "fantasy_xianxia",
    "mechanics": ["resource_scarcity", "realm_pressure", "slow_growth"],
    "opening_requirements": [],
    "chapter_beats": [],
    "longform_risks": [],
    "anti_patterns": [],
    "innovation_axes": []
  }
}
```

### genre_strategy_pack

```json
{
  "type": "genre_strategy_pack",
  "content": {
    "pack_id": "genre_strategy_pack_xxx",
    "project_id": "project_xxx",
    "platform_id": "qidian",
    "genre_id": "fantasy_xianxia",
    "subgenre_id": "xianxia_fanren",
    "reader_promise": {},
    "opening_strategy": {},
    "worldbuilding_requirements": [],
    "character_requirements": [],
    "outline_constraints": [],
    "chapter_beat_policy": {},
    "risk_controls": [],
    "review_rules": [],
    "context_contract": {}
  }
}
```

### genre_risk_gate

```json
{
  "type": "genre_risk_gate",
  "content": {
    "gate_id": "genre_risk_gate_xxx",
    "target_asset_id": "",
    "target_asset_type": "outline|chapter_plan|draft_chapter|review_report",
    "genre_id": "",
    "risks": [],
    "blocking_issue_count": 0,
    "recommendation": "continue|revise|block"
  }
}
```

---

## 4.2 Style OS Assets

### style_sample

```json
{
  "type": "style_sample",
  "content": {
    "sample_id": "style_sample_xxx",
    "project_id": "",
    "sample_text": "",
    "rights": {
      "authorization": "project_owned|licensed|public_domain|manual_excerpt",
      "allow_downstream_generation": false
    },
    "source_policy": {
      "raw_text_in_generation_allowed": false
    }
  }
}
```

### style_fingerprint

```json
{
  "type": "style_fingerprint",
  "content": {
    "fingerprint_id": "style_fp_xxx",
    "source_sample_id": "",
    "avg_sentence_length": 0,
    "sentence_length_distribution": {},
    "dialogue_ratio": 0,
    "description_ratio": 0,
    "psychological_ratio": 0,
    "rhetoric_density": 0,
    "emotion_distribution": {},
    "narrative_distance": "close|medium|distant",
    "pov": "first|third_limited|omniscient",
    "rhythm_profile": {},
    "ai_flavor_markers": [],
    "confidence": 0
  }
}
```

### style_profile

```json
{
  "type": "style_profile",
  "content": {
    "style_id": "cold_mystery_hardboiled",
    "style_name": "冷峻悬疑硬派风",
    "generation_policy": {},
    "review_rules": [],
    "forbidden_patterns": [],
    "rewrite_policy": {},
    "target_fingerprint": {}
  }
}
```

### style_drift_report

```json
{
  "type": "style_drift_report",
  "content": {
    "target_style_id": "",
    "target_asset_id": "",
    "observed_fingerprint": {},
    "drift_scores": {},
    "drift_level": "low|medium|high|critical",
    "issues": [],
    "rewrite_task_candidate": {}
  }
}
```

---

## 4.3 Canon Graph Plugin Assets

Existing `canon_graph_snapshot` should be kept. Add plugin outputs:

```text
power_scale_conflict_report
timeline_conflict_report
evidence_chain_report
relationship_state_report
world_rule_conflict_report
faction_network_report
```

Each report must include:

```json
{
  "type": "power_scale_conflict_report",
  "content": {
    "target_asset_id": "",
    "project_id": "",
    "chapter_no": 0,
    "conflicts": [],
    "issue_candidates": [],
    "blocking_issue_count": 0,
    "evidence_refs": []
  }
}
```

---

## 4.4 Quality Eval 2.0 Assets

### quality_rubric_pack

```json
{
  "type": "quality_rubric_pack",
  "content": {
    "rubric_id": "qidian_fantasy_opening_v1",
    "platform_id": "qidian",
    "genre_id": "fantasy_xianxia",
    "style_id": "",
    "scope": "chapter|opening_3|golden_10|volume_30|longform_100",
    "dimensions": [],
    "weights": {},
    "thresholds": {
      "pass": 0.72,
      "revise": 0.55,
      "block": 0.40
    },
    "judge_policy": {
      "local_heuristic": true,
      "model_judge": "optional|required",
      "human_annotation": "optional|required"
    }
  }
}
```

### quality_regression_report

```json
{
  "type": "quality_regression_report",
  "content": {
    "suite_id": "",
    "case_count": 0,
    "passed_count": 0,
    "failed_count": 0,
    "score_delta": {},
    "blocked_assets": [],
    "recommendation": "pass|revise|block"
  }
}
```

---

## 4.5 Long-chain Proof Assets

### long_chain_run

```json
{
  "type": "long_chain_run",
  "content": {
    "run_id": "long_chain_run_xxx",
    "project_id": "",
    "mode": "deterministic_50|mock_100|simulation_300|provider_30",
    "target_chapter_count": 50,
    "status": "running|succeeded|failed|waiting_human|rolled_back",
    "current_chapter": 0,
    "checkpoints": [],
    "trace_id": ""
  }
}
```

### long_chain_acceptance_report

```json
{
  "type": "long_chain_acceptance_report",
  "content": {
    "run_id": "",
    "target_chapter_count": 100,
    "observed_chapter_count": 100,
    "coverage": {
      "context_bundle": 0,
      "chapter_state": 0,
      "evaluation_result": 0,
      "cost_ledger": 0
    },
    "trends": {
      "quality": [],
      "canon_conflict": [],
      "style_drift": [],
      "reader_fatigue": [],
      "cost": []
    },
    "blocking_issue_count": 0,
    "recommendation": "pass|revise|block"
  }
}
```

---

## 4.6 Publishing Feedback Adapter Assets

### platform_upload_package

```json
{
  "type": "platform_upload_package",
  "content": {
    "platform_id": "fanqie",
    "release_package_path": "",
    "book_metadata": {},
    "chapter_payloads": [],
    "manual_upload_steps": [],
    "checklist": [],
    "sensitive_check": {},
    "status": "ready|blocked"
  }
}
```

### platform_publish_receipt

```json
{
  "type": "platform_publish_receipt",
  "content": {
    "platform_id": "",
    "platform_book_id": "",
    "platform_chapter_id": "",
    "submitted_at": "",
    "review_status": "submitted|approved|rejected|needs_revision|unknown",
    "receipt_raw": {},
    "operator_note": ""
  }
}
```

### feedback_plan_mutation_proposal

```json
{
  "type": "feedback_plan_mutation_proposal",
  "content": {
    "proposal_id": "",
    "source_feedback_paths": [],
    "target_assets": [],
    "proposed_changes": [],
    "risk_assessment": {},
    "human_gate": {
      "required": true,
      "status": "waiting_human"
    }
  }
}
```

---

## 5. API Design

Add product routes:

```text
/product/genre/*
/product/style/*
/product/quality/*
/product/long-chain-proof/*
/product/publishing-adapters/*
/product/feedback-adapters/*
```

### Genre API

```text
POST /product/genre/profiles
GET  /product/genre/profiles
POST /product/genre/subgenres
POST /product/genre/strategy-pack/build
POST /product/genre/risk-gate/run
GET  /product/genre/platform-fit
```

### Style API

```text
POST /product/style/samples
POST /product/style/fingerprints/extract
POST /product/style/profiles/build
POST /product/style/drift/run
POST /product/style/rewrite-task/create
```

### Quality API

```text
POST /product/quality/rubrics
POST /product/quality/suites/opening-3/run
POST /product/quality/suites/golden-10/run
POST /product/quality/suites/volume-30/run
POST /product/quality/suites/longform-100/run
POST /product/quality/gate/run
GET  /product/quality/dashboard
```

### Long-chain Proof API

```text
POST /product/long-chain-proof/runs
GET  /product/long-chain-proof/runs/{run_id}
POST /product/long-chain-proof/runs/{run_id}/resume
POST /product/long-chain-proof/runs/{run_id}/rollback
GET  /product/long-chain-proof/reports
```

### Publishing/Feedback Adapter API

```text
POST /product/publishing-adapters/upload-package/build
POST /product/publishing-adapters/receipts
GET  /product/publishing-adapters/status
POST /product/feedback-adapters/metrics/import
POST /product/feedback-adapters/comments/import
POST /product/feedback-adapters/comments/cluster
POST /product/feedback-adapters/dropoff/analyze
POST /product/feedback-adapters/mutation-proposals
```

---

## 6. Context Builder Integration

Every content-intelligence output must be consumable by Context Builder.

### Required bundle additions

```json
{
  "genre_context": {
    "genre_strategy_pack_id": "",
    "genre_requirements": [],
    "genre_risks": []
  },
  "style_context": {
    "style_profile_id": "",
    "generation_policy": {},
    "forbidden_patterns": []
  },
  "quality_context": {
    "rubric_pack_id": "",
    "quality_thresholds": {},
    "known_weaknesses": []
  },
  "canon_graph_context": {
    "snapshot_id": "",
    "active_conflicts": [],
    "required_constraints": []
  }
}
```

### Flow requirements

| Flow | Required Context |
|---|---|
| topic | genre + platform + MKAOS |
| world | genre + canon seed + MKAOS |
| characters | genre + style + canon seed |
| outline | genre + platform + canon + memory |
| chapter_outline | genre + style + memory + canon |
| prose | genre + style + memory + canon + quality |
| review | genre + style + canon + quality + platform |
| revision | review issues + style drift + canon conflicts |
| recap | canon + long memory + quality trends |
| publish | quality + platform + review issue + source isolation |
| feedback | release package + platform receipt + metrics + comments |

---

## 7. Agent Operation Contracts

Add AgentOperationRegistry entries:

```text
build-genre-strategy-pack
run-genre-risk-gate
ingest-style-sample
extract-style-fingerprint
build-style-profile
run-style-drift-gate
run-canon-graph-plugin
run-quality-suite
run-quality-gate
run-long-chain-proof
build-platform-upload-package
record-platform-receipt
import-platform-metrics
cluster-platform-comments
create-feedback-mutation-proposal
```

Each operation contract must declare:

```text
input_types
output_types
required_tool
checkpoint_strategy
rollback_strategy
sla_seconds
mkaos_context_requirement
context_builder_requirement
evaluation_gate_requirement
```

---

## 8. Workflow Processor Operations

Add workflow processor aliases:

```text
genre_strategy_pack
genre_risk_gate
style_sample_ingestion
style_fingerprint
style_profile
style_drift_gate
quality_suite_run
quality_gate
long_chain_proof_run
platform_upload_package
platform_publish_receipt
platform_metric_import
comment_cluster
feedback_mutation_proposal
```

All processors must:

1. Use LocalStorage.
2. Write schema-backed assets.
3. Record TraceSpan.
4. Respect OS Envelope in production mode.
5. Create ReviewIssue on blocking failure.
6. Return output asset paths.

---

## 9. Gate Semantics

### Production mode fail-closed gates

| Gate | Blocking Condition |
|---|---|
| Genre Risk Gate | target misses required genre mechanics or violates hard anti-pattern |
| Style Drift Gate | critical style drift or AI flavor risk |
| Canon Graph Gate | critical contradiction, impossible timeline, power scale conflict |
| Quality Eval Gate | score below threshold or model/human judge blocks |
| MKAOS Gate | source leakage, weak pack, unresolved blocking issue |
| Publish Gate | missing release evidence or unresolved ReviewIssue |
| Provider Gate | no model route, timeout, cancel, token/cost hard-stop |

---

## 10. Testing Strategy

### Unit tests

```text
tests/unit/test_genre_os.py
tests/unit/test_style_os.py
tests/unit/test_canon_graph_plugins.py
tests/unit/test_quality_eval_v2.py
tests/unit/test_long_chain_proof.py
tests/unit/test_publishing_feedback_adapters.py
```

### Integration tests

```text
tests/integration/test_content_intelligence_context_builder.py
tests/integration/test_genre_style_quality_to_draft_chain.py
tests/integration/test_feedback_to_mutation_proposal.py
tests/integration/test_long_chain_50_chapter_content_intelligence.py
```

### Slow tests

```text
tests/slow/test_long_chain_100_mock.py
tests/slow/test_long_chain_300_state_simulation.py
tests/slow/test_provider_30_chapter_content_intelligence.py
```

### Web tests

```text
web/admin/tests/content-intelligence-architecture.test.mjs
web/admin/tests/genre-style-quality-console.test.mjs
```

---

## 11. Migration Strategy

1. Do not rename existing modules.
2. Add new modules with stable facades.
3. Keep legacy topic/style paths working in compat mode.
4. In production/operating_system mode, require content-intelligence gates before release.
5. Move heuristic scoring behind a clear `local_heuristic` mode.
6. Add docs and tests with every durable module.

---

## 12. Definition Of Done

A development cycle is done only when:

1. New schemas are added to `SCHEMA_CLASSES` and storage directory mapping.
2. Services write valid assets with `validate_common_fields`.
3. Product API routes exist and are tested.
4. Agent and Workflow operation contracts exist.
5. Context Builder can include the new asset type.
6. Relevant gate can create ReviewIssue.
7. UI route exists or docs explicitly mark UI as deferred.
8. Unit and integration tests pass.
9. Docs index is updated.
10. No new parallel generation path exists.
