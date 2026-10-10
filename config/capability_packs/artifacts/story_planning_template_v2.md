Stage: {{stage}}
Target: {{target_scope}}
Frozen provider data envelope: {{provider_data_envelope}}
Required output schema: {{output_schema_ref}}

Return only the complete JSON planning contract required by the schema. Keep
identifiers and parent relationships consistent with the frozen input.

For Chapter contracts, declare one unique (state_kind, entity_key) entry-to-exit
transition per Chapter. Scene entry and exit retain intermediate progression;
multiple Scene steps for one entity do not create duplicate Chapter identities.
