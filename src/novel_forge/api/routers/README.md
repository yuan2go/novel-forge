# Product Router Boundaries

These routers preserve the existing `/product/...` API surface while splitting HTTP registration out of `api/product.py`.

Phase 1 keeps existing service functions exported from `novel_forge.api.product` as a compatibility facade because workers and tests still import them directly. The implementation now lives under `novel_forge.api.services.product`. The `_bindings.py` bridge is transitional: later phases should split that service module into domain services and remove the bridge.

| Router | Boundary |
|---|---|
| `projects.py` | Project lifecycle, series listing, project config, project assets, project scope audit. |
| `tasks.py` | Task latest state, timeline, SSE events, retry, cancel, control limits, dead-letter listing and recovery. |
| `assets.py` | Asset detail, metadata editing, content editing, typed editing, versions/diff, graph, collections. |
| `libraries.py` | Creative asset libraries: topic, material, knowledge, setting bible, style center, and quality standards. |
| `handoffs.py` | Claude Code/Codex handoff list, source policy/license/risk/snapshot/sync governance, context eligibility, GitHub sources, handoff creation, output validation/binding, acceptance, fail/retry. |
| `system.py` | Postgres strict checks, product health, local backups/restore, task event archive, Qdrant, MinIO, browser uploads. |
| `batch.py` | Batch deconstruction, item listing, item retry/bulk retry, review gate, continue, handoff regenerate/void. |
| `drafts.py` | Draft workbench, draft editor, draft generation, save, diff, export, publish record. |
| `reviews.py` | Review run, revision plan, review issue status, revision application. |
| `audit.py` | Chapter audit, originality protection, publish gate, and release package creation. |

Do not add new V6/V7 routes to `product.py`. Add them to the appropriate router or create a new router listed in `docs/new/implementation/v6-v7-implementation-plan.md`.
