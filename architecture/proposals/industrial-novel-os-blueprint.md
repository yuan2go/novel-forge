# Industrial Novel OS unresolved narrative design

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED**
>
> **NOT_RUNTIME_AUTHORITY**

This retained proposal contains unresolved design input only. Executable contracts,
PostgreSQL migrations, runtime wiring, and current Reality determine implemented facts.
The scoped review below invalidates when a relevant contract changes. A proposal with
no remaining decisions must be projected into current documentation and deleted.

<!-- proposal-lifecycle
{
  "schema_version": "proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reality_baseline": {
    "commit_sha": "4c6ebdb774052e1d46f72d0cfbc0541aed22fc52",
    "implementation_tree_sha": "sha256:4fea9493881f8bacb57f3d0117c77b35f25aa13ccf6cda2371e3abc950a628ae"
  },
  "scope": [
    "src/novel_forge/modules/book_authority/completion.py",
    "src/novel_forge/modules/book_design_authority/foundation.py",
    "src/novel_forge/modules/context_builder/governance.py",
    "src/novel_forge/modules/hierarchical_planning/chapter_contracts.py",
    "src/novel_forge/modules/hierarchical_planning/definitions.py",
    "src/novel_forge/modules/hierarchical_planning/realization_domain.py",
    "src/novel_forge/modules/hierarchical_planning/window_policy.py",
    "src/novel_forge/modules/reader_calibration/application.py",
    "src/novel_forge/modules/reader_calibration/proxy_policy.py",
    "src/novel_forge/modules/story_design_authority/domain.py"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/story_design_authority/domain.py",
      "symbol": "DesignScope"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/realization_domain.py",
      "symbol": "NarrativeRealizationContract"
    },
    {
      "path": "src/novel_forge/modules/context_builder/governance.py",
      "symbol": "compile_effective_context_policy"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/window_policy.py",
      "symbol": "ChapterWindowPolicy"
    },
    {
      "path": "src/novel_forge/modules/book_authority/completion.py",
      "symbol": "assess_whole_book_completion"
    },
    {
      "path": "src/novel_forge/modules/reader_calibration/proxy_policy.py",
      "symbol": "ReaderProxyPolicy"
    },
    {
      "path": "src/novel_forge/modules/book_design_authority/foundation.py",
      "symbol": "FoundationBinding"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/chapter_contracts.py",
      "symbol": "compile_chapter_contracts"
    },
    {
      "path": "src/novel_forge/modules/reader_calibration/application.py",
      "symbol": "run_calibration"
    },
    {
      "path": "src/novel_forge/modules/reader_calibration/application.py",
      "symbol": "resolve_profile"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    {
      "id": "trajectory-portfolio",
      "decision": "DESIGN_REVIEW_REQUIRED: choose typed character, relationship and thematic trajectory payloads and accepted-actual delta contracts before replacing generic Arc representation.",
      "evidence_refs": [
        "src/novel_forge/modules/hierarchical_planning/definitions.py",
        "src/novel_forge/modules/hierarchical_planning/realization_domain.py"
      ]
    },
    {
      "id": "whole-book-acceptance",
      "decision": "DESIGN_REVIEW_REQUIRED: define typed authoritative Ending/Reader Promise/trajectory closure evaluation and independent editorial acceptance criteria; completion assessment must not promote terminal cursor or chapter acceptance into whole-book acceptance.",
      "evidence_refs": [
        "src/novel_forge/modules/book_authority/completion.py"
      ]
    },
    {
      "id": "reader-calibration-dataset-lineage",
      "decision": "DESIGN_REVIEW_REQUIRED: define an authoritative typed calibration dataset binding each prediction/outcome to exact Reader exposure and outcome-event identities. Aggregate scope counts cannot qualify arbitrary caller observations; historical unbound VALID profiles are not admissible calibration evidence.",
      "evidence_refs": [
        "src/novel_forge/modules/reader_calibration/application.py"
      ]
    }
  ],
  "reviewed_sources": [
    {
      "path": "src/novel_forge/modules/story_design_authority/domain.py",
      "symbol": "DesignScope",
      "sha256": "b4aa3c34d92b98f5369c63469f5dc304ee4a00376f3253e4f29cd5d09f6d067b"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/realization_domain.py",
      "symbol": "NarrativeRealizationContract",
      "sha256": "c2da296ab085c05d01d5a7ccf5f605c57d44be1a06477c8bb65856eef7094c49"
    },
    {
      "path": "src/novel_forge/modules/context_builder/governance.py",
      "symbol": "compile_effective_context_policy",
      "sha256": "5ac7d3b8d063df4f0c98b565889a1ab666807179650a4684b14c0e82a29bf231"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/window_policy.py",
      "symbol": "ChapterWindowPolicy",
      "sha256": "8181276162b538df0b899ac61751baa37f07301502b3c7e45052a5e5696603e0"
    },
    {
      "path": "src/novel_forge/modules/book_authority/completion.py",
      "symbol": "assess_whole_book_completion",
      "sha256": "5786dea14c4251ba7db9b6230936549d118a77989a38d4d3a83d09dc0bbb3b5c"
    },
    {
      "path": "src/novel_forge/modules/reader_calibration/proxy_policy.py",
      "symbol": "ReaderProxyPolicy",
      "sha256": "f167bceee6f7dd0ce4ada5ea720d48c123280718287d684e7387c45089c36085"
    },
    {
      "path": "src/novel_forge/modules/book_design_authority/foundation.py",
      "symbol": "FoundationBinding",
      "sha256": "e7d44c00edbf70088d73003f8fe3bda761bec6a5379f4c91f8ad390e5df950b6"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/chapter_contracts.py",
      "symbol": "compile_chapter_contracts",
      "sha256": "e0c4af60654ec4eb1b97c009e78af812f6dec77940cc2a46ea643fd5533bf622"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/definitions.py",
      "sha256": "779a71c06410bfbfb1f802b099699832f1d022b8fdb688a8548f8f54d0f56572"
    },
    {
      "path": "src/novel_forge/modules/reader_calibration/application.py",
      "symbol": "run_calibration",
      "sha256": "79556ec5abee0c1757dfe7653e759498354f32314c0ca4be649211ee5faa99a6"
    },
    {
      "path": "src/novel_forge/modules/reader_calibration/application.py",
      "symbol": "resolve_profile",
      "sha256": "0d379b111aecb5d0dc11f168b94a74e1925d7d4fde36616aecf36bebad96a410"
    }
  ]
}
-->

## Decisions superseded by current contracts

Story Design remains the semantic owner of Foundation facts. Independent services for
World, Character, and Relationship are not prerequisites for correct ownership. Six
Foundation roles already bind independent exact versions, hashes, upstream dependencies,
activation and qualification evidence; Planning validates their current binding gate.

Narrative Realization remains a Planning-owned causal and execution-readiness contract.
Command Kernel already owns attempts, leases, fences and ExternalEffects. Moving the
Planning contract wholesale into Production Execution would duplicate ownership; that
proposed move is rejected. Generated prose remains a candidate until Book acceptance.

ChapterGroup is an execution window. `ChapterWindowPolicy` owns configurable positive
window bounds; no universal 3–8 narrative invariant follows. Reader proxy thresholds
belong to versioned Reader policy, and fixture observations remain fixture evidence.

A whole-book completion assessment is separate from terminal cursor completion and
chapter acceptance. The implemented assessment cannot grant whole-book acceptance
without the missing typed closure and independent editorial evidence contracts.

## Remaining review questions

1. Character, relationship, and thematic trajectories need typed payloads and explicit
   Accepted Actual deltas. Generic Arc references and current character/relationship
   progression do not define independent typed portfolio acceptance. Resolve the source
   type and reference-integrity contract before replacing generic Arc representation.
   Structural containment, trajectory, planning dependency, execution dependency and
   accepted-fact projection remain different relations.
2. Whole-book acceptance needs authoritative Ending and Reader Promise closure criteria,
   trajectory/obligation closure evaluation, and an independent editorial decision.
   Define evidence requirements and revision semantics before allowing the assessment
   owner to issue acceptance. Lack of those contracts is `DESIGN_REVIEW_REQUIRED`.

3. Reader calibration has no authoritative observation-to-event dataset binding.
   Scope-level exposure counts cannot attribute arbitrary caller observations to real
   behavior. The admission path now rejects `BEHAVIOR_CALIBRATED`, and historical
   unbound `VALID` profiles cannot resolve. Define typed dataset lineage and its evidence
   verification before allowing calibrated probability claims; fixture diagnostics remain
   non-production evidence.

Every affected implementation must preserve immutable Accepted Actual, future-only
replanning, PostgreSQL authority, and separate engineering, narrative correctness,
human editorial, reader, longitudinal and production evidence. No open question
permits a fixed chapter-count ladder to become the validation hierarchy.
