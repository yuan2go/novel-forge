# Typed Empty State Producer Authority

`chapter.state.initialize_empty` consumes frozen `state_absence_evidence`, rejects an
incomplete Canon Reduction, and materializes one of eleven typed empty Snapshot roles.
Production resolution verifies the AssetVersion is bound to a SUCCEEDED initializer
Operation; content claims alone are not trusted. Existing non-empty state wins, wrong
chapter/project fails, and empty differs from missing throughout Manifest, Context,
Canon and Quality.

Evidence: Content codec/domain, PostgreSQL resolver binding and chapter-2 integration
test. Commit `165d179`.
