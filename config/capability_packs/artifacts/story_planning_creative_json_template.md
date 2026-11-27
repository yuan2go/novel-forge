Stage: {{stage}}
Target: {{target_scope}}
Frozen input manifest: {{input_manifest}}
Frozen context bundle: {{context_bundle}}
Required output schema: {{output_schema_ref}}

Return only the complete JSON planning contract required by the schema. Keep
identifiers and parent relationships consistent with the frozen input.

For creative.candidates.generate, the following is a JSON output-format example,
not a story candidate, source material, or an approved creative decision. Replace
all instructional values with original content grounded in the frozen inputs.
If the frozen schema adds required fields, include those fields as well.
For other stages, follow that stage's frozen schema instead of these example keys.

<creative_json_output_example>
{
  "objective": "根据本次冻结输入填写具体内容",
  "target_reader": "根据本次冻结输入填写具体内容",
  "why_worth_writing": "根据本次冻结输入填写具体内容",
  "genre": "根据本次冻结输入填写具体内容",
  "subgenre": "根据本次冻结输入填写具体内容",
  "core_desire": "根据本次冻结输入填写具体内容",
  "core_fear": "根据本次冻结输入填写具体内容",
  "core_conflict": "根据本次冻结输入填写具体内容",
  "narrative_engine": "根据本次冻结输入填写具体内容",
  "differentiation": "根据本次冻结输入填写具体内容",
  "emotional_contract": "根据本次冻结输入填写具体内容",
  "serialization_potential": "根据本次冻结输入填写具体内容",
  "constraints": [
    "根据输入填写约束"
  ],
  "prohibited_outcomes": [
    "根据输入填写禁止结果"
  ],
  "style_profile": {
    "narrator": "根据输入填写叙述方式",
    "pov": "根据输入填写视角",
    "genre_conventions": [
      "根据输入填写类型约定"
    ],
    "constraints": [
      "根据输入填写风格约束"
    ],
    "original_examples": [
      {
        "purpose": "根据本次创作目的填写",
        "example": "为本次输入创作原创表达",
        "explanation": "说明该原创表达如何服务本次目标"
      }
    ]
  }
}
</creative_json_output_example>

Return exactly one JSON object containing the requested task result. Begin with
its opening brace and end with its closing brace. Do not emit an API parameter
descriptor, a schema declaration, a second object, markdown fences, or commentary
before or after that object. API configuration is not part of the task output.
