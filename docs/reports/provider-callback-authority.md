# Provider Callback Authority

Migration `0030_provider_callback_authority` adds durable callback receipt and attempt
tables. Callback admission derives project scope from ExternalEffect, verifies the
adapter signature, persists provider message/request identity and payload hash,
quarantines unknown or invalid input, rejects same-message/different-payload conflicts,
and idempotently resumes UNKNOWN effects with budget settlement, Audit and Outbox.

Evidence: `modules/provider_callback_authority/`, callback API router and PostgreSQL
restart/replay tests. Commit `7981149`. Secrets and raw callback bodies are not placed
in generation Context.
