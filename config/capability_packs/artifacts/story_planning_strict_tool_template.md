Stage: {{stage}}
Target: {{target_scope}}
Frozen input manifest: {{input_manifest}}
Frozen context bundle: {{context_bundle}}
Required output schema: {{output_schema_ref}}

Produce the complete task result using exactly one submit_structured_result function
call. Its arguments must be the JSON object required by the frozen output schema.
Keep all original business constraints, identifiers, source boundaries and minimum
content requirements. The transport schema is a formatting aid; it does not replace
the full frozen schema or authorize omission of any required meaning.

Do not return the result as assistant message prose, a JSON schema declaration, an API
parameter, or multiple function calls. Do not copy instructional text into story fields.
No function executes story mutations: the native validator and owning Authority still
decide eligibility, approval and activation after receiving the complete candidate.
