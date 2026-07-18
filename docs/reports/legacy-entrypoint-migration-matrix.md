# Legacy Entrypoint Migration Matrix

Date: 2026-07-18. This matrix describes execution authority, not feature presence.

| Area | Legacy entry | Current production path | Status | Remaining action |
|---|---|---|---|---|
| Chapter production | LocalStorage Chapter Production Bus | Chapter command -> durable Saga -> worker | production-blocked / adapter-backed | retire development callers after projection parity |
| Context | local Context Builder services | preparation + `chapter.context.build` frozen inputs | migrated for chapter authority | migrate non-chapter legacy tools separately |
| Draft | local draft services | `chapter.draft.generate` ExternalEffect | migrated for chapter authority | legacy editor remains development-only |
| Review | local review writes | review + revision + independent re-review assets | migrated for chapter authority | legacy Review Center is compatibility UI/read path |
| Canon | local Canon/KG updates | extraction + reduction + nine snapshots | migrated for chapter authority | real-provider semantic extraction proof pending |
| Quality | local quality loop | 15 evidence versions + aggregate | migrated for chapter authority | parallel evidence child Saga pending |
| Publishing | local release/export records | publish gate -> verified Blob -> final release gate | migrated for internal release | real platform submit remains deferred |
| Content intelligence | direct domain calls | Content Authority API/worker | product-entrypoint-integrated | minimal Cockpit UI pending |
| Project/asset administration | legacy product service | legacy local-first surface | mapped / development-only | outside this production-chain slice |
| Local import/export and fixtures | LocalStorage | non-authoritative tools | development-only | retain as rebuild/import/export utility |

Production selects `novel_forge.api.authority_app` when storage authority is
PostgreSQL; this surface does not import LocalStorage. `start_chapter_production()`
also raises `LEGACY_CHAPTER_BUS_PRODUCTION_DISABLED` in production. Legacy JSON
assets are therefore not accepted as success for the chapter Authority chain.

The repository-wide generated coverage still records legacy reads, fallbacks, sync
and administration routes. Their presence is not claimed as migration completion.
