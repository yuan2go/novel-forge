from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from novel_forge.modules.production_execution import (
    ArtifactPointer,
    CommitPolicy,
    ContextPolicy,
    InputManifest,
    PromptBundle,
    SkillBundle,
    SourcePolicy,
    ValidationPolicy,
)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class ProductionExecutionBundleTests(unittest.TestCase):
    def test_prompt_bundle_is_versioned_round_trippable_and_hash_stable(self) -> None:
        bundle = PromptBundle(
            prompt_bundle_id="prompt:chapter-draft:v3",
            prompt_version="v3",
            domain="prose",
            capability="prose.chapter.draft",
            system_instruction_hash=_sha("system"),
            template_hash=_sha("template"),
            input_schema_ref="schema:execution-input:prose-chapter-draft:v1",
            output_schema_ref="schema:execution-output:prose-chapter-draft:v1",
            skill_bundle_ref="skill:chapter-draft:v2",
            context_policy_ref="context-policy:prose-chapter-draft:v1",
            source_policy_ref="source:prose-chapter-draft:v1",
            compiler_version="chapter-prompt-compiler:v1",
            created_by_operation_id="operation:prompt-compile:1",
        )

        restored = PromptBundle.from_dict(bundle.to_dict())

        self.assertEqual(restored.content_hash, bundle.content_hash)
        self.assertNotEqual(
            replace(bundle, prompt_version="v4").content_hash,
            bundle.content_hash,
        )

    def test_prompt_bundle_rejects_raw_or_secret_bearing_values(self) -> None:
        values = {
            "prompt_bundle_id": "prompt:chapter-draft:v3",
            "prompt_version": "v3",
            "domain": "prose",
            "capability": "prose.chapter.draft",
            "system_instruction_hash": "write the chapter directly",
            "template_hash": _sha("template"),
            "input_schema_ref": "schema:input:v1",
            "output_schema_ref": "schema:output:v1",
            "skill_bundle_ref": "skill:chapter:v1",
            "context_policy_ref": "context:chapter:v1",
            "source_policy_ref": "source:chapter:v1",
            "compiler_version": "compiler:v1",
            "created_by_operation_id": "operation:1",
        }
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            PromptBundle.from_dict(values)
        values["system_instruction_hash"] = _sha("system")
        values["compiler_version"] = "Bearer secret-token"
        with self.assertRaisesRegex(ValueError, "secret"):
            PromptBundle.from_dict(values)

    def test_skill_bundle_freezes_skill_versions_and_content_hashes(self) -> None:
        bundle = SkillBundle(
            skill_bundle_id="skill:chapter-draft:v2",
            skill_version="v2",
            domain="prose",
            capability="prose.chapter.draft",
            skill_refs=("skill:prose-generation:v5", "skill:chapter-outline:v3"),
            skill_content_hashes=(_sha("prose"), _sha("outline")),
            tool_policy_ref="tools:chapter-draft:v1",
            created_by_operation_id="operation:skill-compile:1",
        )
        self.assertEqual(
            SkillBundle.from_dict(bundle.to_dict()).content_hash,
            bundle.content_hash,
        )
        with self.assertRaisesRegex(ValueError, "one content hash"):
            replace(bundle, skill_content_hashes=(_sha("prose"),))

    def test_execution_policies_are_versioned_and_domain_commit_stays_external(self) -> None:
        context = ContextPolicy(
            policy_id="context-policy:prose-chapter-draft:v1",
            policy_version="v1",
            maximum_tokens=16000,
            allowed_asset_types=("chapter_plan", "context_bundle"),
            compression_policy_ref="compression:chapter:v2",
            source_policy_ref="source:prose-chapter-draft:v1",
        )
        source = SourcePolicy(
            policy_id="source:prose-chapter-draft:v1",
            policy_version="v1",
            allowed_eligibility=("PRODUCTION_ELIGIBLE",),
            allow_raw_reference_sources=False,
            requires_lineage=True,
            isolation_mode="ABSTRACT_ASSETS_ONLY",
        )
        validation = ValidationPolicy(
            policy_id="validation:prose-chapter-draft:v1",
            policy_version="v1",
            structural_schema_ref="schema:execution-output:prose-chapter-draft:v1",
            semantic_validator_refs=("validator:chapter-draft:v1",),
            maximum_repair_attempts=2,
            requires_domain_validation=True,
        )
        commit = CommitPolicy(
            policy_id="commit:prose-chapter-draft:v1",
            policy_version="v1",
            candidate_asset_type="generation_candidate",
            requires_validation_manifest=True,
            requires_approval=True,
            activation_mode="DOMAIN_AUTHORITY_ONLY",
        )

        self.assertGreater(context.maximum_tokens, 0)
        self.assertFalse(source.allow_raw_reference_sources)
        self.assertTrue(validation.requires_domain_validation)
        self.assertEqual(commit.activation_mode, "DOMAIN_AUTHORITY_ONLY")
        self.assertEqual(
            CommitPolicy.from_dict(commit.to_dict()).content_hash,
            commit.content_hash,
        )
        with self.assertRaisesRegex(ValueError, "boolean"):
            CommitPolicy.from_dict(
                {
                    **commit.to_dict(),
                    "requires_approval": "true",
                }
            )

    def test_input_manifest_freezes_all_versions_and_asset_version_ids(self) -> None:
        artifact = ArtifactPointer(
            artifact_ref="asset-version:chapter-plan:42",
            asset_version_id="chapter-plan:42",
            artifact_type="chapter_plan",
            content_hash=_sha("plan"),
            schema_version="chapter-plan.v3",
            source_eligibility="PRODUCTION_ELIGIBLE",
        )
        manifest = InputManifest(
            manifest_id="input-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=9,
            project_id="project:1",
            book_id="book:1",
            target_scope={
                "scope_kind": "chapter",
                "scope_id": "book:1:chapter:7",
                "chapter_number": 7,
            },
            context_bundle_ref="asset-version:context:8",
            prompt_bundle_ref="prompt:chapter-draft:v3",
            skill_bundle_ref="skill:chapter-draft:v2",
            context_bundle_version="context:8",
            prompt_bundle_version="v3",
            skill_bundle_version="v2",
            canon_snapshot_version="canon:12",
            story_state_version="story-state:19",
            planning_version="chapter-plan:42",
            quality_profile_version="quality:5",
            source_policy_ref="source:prose-chapter-draft:v1",
            source_eligibility="PRODUCTION_ELIGIBLE",
            canon_version_refs=("canon:12",),
            arc_version_refs=("arc:4",),
            input_artifacts=(artifact,),
            read_set=(artifact.artifact_ref,),
        )

        restored = InputManifest.from_dict(manifest.to_dict())

        self.assertEqual(restored.content_hash, manifest.content_hash)
        self.assertEqual(
            restored.input_artifacts[0].asset_version_id,
            "chapter-plan:42",
        )
        self.assertEqual(restored.story_state_version, "story-state:19")

    def test_input_manifest_rejects_path_only_or_unqualified_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "AssetVersion"):
            ArtifactPointer(
                artifact_ref="./chapter-plan.json",
                asset_version_id="",
                artifact_type="chapter_plan",
                content_hash=_sha("plan"),
                schema_version="chapter-plan.v3",
                source_eligibility="PRODUCTION_ELIGIBLE",
            )
        with self.assertRaisesRegex(ValueError, "source eligibility"):
            ArtifactPointer(
                artifact_ref="asset-version:chapter-plan:42",
                asset_version_id="chapter-plan:42",
                artifact_type="chapter_plan",
                content_hash=_sha("plan"),
                schema_version="chapter-plan.v3",
                source_eligibility="UNKNOWN",
            )


if __name__ == "__main__":
    unittest.main()
