# OS Envelope Enforcement Audit

生成时间：2026-07-03

| Path | Type | Mutates Production | Calls Model | Reads MKAOS | Writes MKAOS | Has OS Envelope | Has Context Bundle | Has Knowledge Pack | Has Trace | Has Cost Ledger | Has Provider Guard | Has Gate | Fallback Policy | Status | Required Fix |
| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| `mkaos.import_source_document` | service mutation | yes | no | no | yes | yes, production required | no | no | yes via `trace_span` when envelope supplied/production/bypass | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.create_knowledge_card` | service mutation | yes | no | yes | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.update_knowledge_card` | service mutation | yes | no | yes | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.create_usage_binding` | service mutation | yes | no | yes | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.update_usage_binding` | service mutation | yes | no | yes | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.create_rule_card` | service mutation | yes | no | no | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.create_template_card` | service mutation | yes | no | no | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.build_knowledge_pack` | service mutation | yes | no | yes | yes | yes, production required | planned | yes | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | Phase 4 adds Context Bundle field |
| `mkaos.record_usage_event` | service mutation | yes | no | yes | yes | yes, production required | no | yes | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.record_review_feedback` | service mutation | yes | no | yes | yes | yes, production required | no | optional | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | Phase 5 links ReviewIssue |
| `mkaos.apply_weight_update` | service mutation | yes | no | yes | yes | yes, production required | no | optional | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | Phase 3 deepens selector effect |
| `mkaos.query_knowledge` | service/API query | no | no | yes | no | yes for standard response | no | no | yes when envelope supplied/production | n/a | n/a | no | production requires envelope | enforced | Phase 3 improves scoring |
| `mkaos.convert_assets` | service/API mutation | yes | no | yes | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `mkaos.convert_rules` | service/API mutation | yes | no | yes | yes | yes, production required | no | no | yes via `trace_span` | n/a | n/a | no | production fail closed; compat allowed | enforced | none |
| `outline.generate_outline` | model service | yes | yes | yes | usage event | partial runtime/agent evidence | no | direct pack | agent/runtime traces | model gateway partial | GuardedModelAdapter | agent guards | MKAOS pack warning compat | needs_fix | Phase 4 routes via Context Builder; Phase 5/10 production fail policy |
| `chapter_plan.generate_chapter_plan` | model service | yes | yes | yes | usage event | partial runtime/agent evidence | no | direct pack | agent/runtime traces | model gateway partial | GuardedModelAdapter | agent guards | MKAOS pack warning compat | needs_fix | Phase 4 routes via Context Builder |
| `drafting.draft` | model service | yes | yes | yes | usage event | partial runtime/agent evidence | yes | direct separate pack | agent/runtime traces | generation run/model evidence | GuardedModelAdapter | RAG quality/stability gates | MKAOS pack warning compat | partial | Phase 4 folds MKAOS into Context Bundle |
| `review.review` | model service | yes | yes | yes | usage event/feedback | partial runtime/agent evidence | no | direct pack | agent/runtime traces | model evidence | GuardedModelAdapter | review issues local | MKAOS pack warning compat | needs_fix | Phase 5 unifies ReviewIssue and blocking |
| `audit.create_release_package` | publishing mutation | yes | no | no | no | runtime policy exists, no MKAOS envelope | no | no | agent/runtime traces | n/a | n/a | publish gate | publish gate blocks status | partial | Phase 10 enforces envelope + ReviewIssue blocking |

## Summary

Phase 2 enforces OS Envelope for MKAOS-owned production mutation and Query/Convert surfaces. Generation services still have mixed AgentExecutionContext/runtime evidence and direct MKAOS pack usage; they are intentionally left for Phase 4 Context Builder and Phase 5 ReviewIssue to avoid mixing broad production-flow rewrites into the MKAOS envelope commit.
