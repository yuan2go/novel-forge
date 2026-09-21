"""CONSTRAINT: Blinded responses are subjective evidence and never qualify or activate Craft policies."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import secrets

from novel_forge.modules.reader_calibration.blind_export import (
    BlindComparisonSubject, BlindEvaluator, export_blind_evaluation_packs,
)
from novel_forge.modules.reader_calibration.domain import (
    BlindScope, EvaluatorIdentityClass, HumanBlindDecision,
)
from scripts.compare_creation_exports import chapter_results
from scripts.creation_freeze import _json_bytes, _read_regular, _write_file
from scripts.narrative_closure_campaign import CRAFT_OBSERVATIONS, digest, validate_campaign


PROTOCOL = "narrative-closure-independent-tasks.v1"
EVALUATION = "narrative-closure-editorial-axes.v1"


def export_packs(*, manifest: dict, results: Path, destination: Path,
                 reviewers: tuple[str, str]) -> dict:
    validate_campaign(manifest)
    report = json.loads(_read_regular(results / "campaign-result.json"))
    if report.get("campaign_hash") != digest(manifest) or report.get("status") not in {
        "PILOT_AWAITING_NATIVE_READING_DECISIONS", "EXPLORATION_EXECUTED_NOT_QUALITY_PROVEN",
    }:
        raise ValueError("Blind export requires a complete exact frozen campaign stage")
    subjects = []
    observations = []
    for sample in manifest["samples"]:
        directories = {name: results / sample["sample_id"] / name for name in ("A", "B")}
        if not any(directory.exists() for directory in directories.values()):
            continue
        candidates = {}
        for name, directory in directories.items():
            result = json.loads(_read_regular(directory / "result.json"))
            if result.get("status") != "ACCEPTED_TARGET":
                raise ValueError("Rejected and failed candidates remain in exports; incomplete pairs cannot enter preference evaluation")
            chapters, errors = chapter_results(directory)
            number = sample["arms"][name]["chapter_command"]["chapter_number"]
            if errors or number not in chapters:
                raise ValueError("Blind prose must follow exact immutable native acceptance")
            candidates[name] = chapters[number]["candidate"]
            observations.append({"sample_id": sample["sample_id"], "arm": name,
                "candidate_asset_version_id": candidates[name]["asset_version_id"],
                "delivery": "READ_NATIVE_CONTEXT_AND_REQUEST_RECEIPTS",
                "realization": "READ_LOCATED_CRAFT_REVIEW_EVIDENCE",
                "model_effectiveness": "MODEL_PROXY_ONLY",
                "independent_reader_preference": "NOT_RUN", "dispositions": [],
                "allowed_dispositions": list(CRAFT_OBSERVATIONS)})
        subjects.append(BlindComparisonSubject(
            subject_id=sample["sample_id"], scope_type=BlindScope.CHAPTER, chapter_start=number, chapter_end=number,
            canonical_asset_version_id=candidates["B"]["asset_version_id"],
            baseline_asset_version_id=candidates["A"]["asset_version_id"],
            canonical_text=candidates["B"]["content"]["text"], baseline_text=candidates["A"]["content"]["text"],
            arc_plan_version_ids=(),
        ))
    if len(subjects) not in {2, 6}:
        raise ValueError("Blind export requires the two pilot or six exploration pairs")
    bundle = export_blind_evaluation_packs(
        campaign_token=secrets.token_hex(16), campaign_version=1, protocol_version=PROTOCOL,
        evaluation_version=EVALUATION, campaign_secret=secrets.token_hex(32),
        evaluators=[BlindEvaluator(reviewer, EvaluatorIdentityClass.EXPERIENCED_READER) for reviewer in reviewers],
        subjects=subjects, subject_population="INDEPENDENT_TASKS",
    )
    destination.mkdir(parents=True, exist_ok=False)
    private = destination / "private"
    private.mkdir(mode=0o700)
    mappings = {}
    for index, (reviewer, pack) in enumerate(bundle.packs.items(), start=1):
        name = f"reader-{index}.json"
        _write_file(destination / name, _json_bytes(pack.public_payload))
        _write_file(destination / f"reader-{index}-response.json", _json_bytes({
            "reviewer_id": reviewer, "pack_hash": digest(pack.public_payload),
            "evidence_class": "NOT_SUBMITTED", "attestation": "",
            "responses": [{"pair_token": pair["pair_token"], **pair["response"]} for pair in pack.public_payload["pairs"]],
        }))
        mappings[name] = {"reviewer_id": reviewer, "public_hash": digest(pack.public_payload),
                          "mapping": [asdict(item) for item in pack.private_mapping]}
    _write_file(private / "bindings.json", _json_bytes({"campaign_hash": digest(manifest), "packs": mappings}))
    _write_file(private / "craft-observations.json", _json_bytes(observations))
    status = {"status": "EXPORTED_HUMAN_NOT_RUN", "campaign_hash": digest(manifest),
              "intervention": manifest["intervention"], "treatment_scope": "REVIEW_REVISION_OF_FIXED_AUTHOR_INPUT",
              "human_editorial": "NOT_RUN", "craft_effectiveness": "HYPOTHESIS", "public_files": list(mappings),
              "disagreement_policy": "KEEP_RAW_DECISIONS_AND_REPORT_DISAGREEMENT; NO_AUTOMATIC_MAJORITY_OR_POLICY_CHANGE"}
    _write_file(private / "status.json", _json_bytes(status))
    return status


def evaluate_responses(*, directory: Path, responses: list[Path], destination: Path) -> dict:
    bindings = json.loads(_read_regular(directory / "private" / "bindings.json"))
    if len(responses) != 2:
        raise ValueError("Two independently completed reader responses are required")
    by_subject: dict[str, list[dict]] = {}
    identities = set()
    for path in responses:
        submitted = json.loads(_read_regular(path))
        reviewer = submitted.get("reviewer_id")
        matches = [(name, value) for name, value in bindings["packs"].items() if value["reviewer_id"] == reviewer]
        if len(matches) != 1 or reviewer in identities or submitted.get("evidence_class") != "HUMAN_SUBMITTED" or not submitted.get("attestation"):
            raise ValueError("Responses require distinct assigned humans and explicit authorship attestations")
        identities.add(reviewer)
        name, binding = matches[0]
        public = json.loads(_read_regular(directory / name))
        if digest(public) != binding["public_hash"] or submitted.get("pack_hash") != binding["public_hash"]:
            raise ValueError("Reviewer response differs from the assigned frozen pack")
        incoming = submitted.get("responses")
        if not isinstance(incoming, list) or len(incoming) != len(public["pairs"]):
            raise ValueError("Every assigned pair needs an explicit response, including CANNOT_JUDGE")
        rows = {row["pair_token"]: row for row in incoming}
        if len(rows) != len(incoming) or set(rows) != {pair["pair_token"] for pair in public["pairs"]}:
            raise ValueError("Response pairs are missing, duplicated or foreign")
        private = {row["pair_token"]: row for row in binding["mapping"]}
        for pair in public["pairs"]:
            response = rows[pair["pair_token"]]
            decision = HumanBlindDecision(
                decision_id=digest(response), pair_token=pair["pair_token"], reviewer_id=reviewer,
                evaluator_identity_class=public["evaluator_identity_class"], protocol_version=public["protocol_version"],
                evaluation_version=public["evaluation_version"], scope_type=pair["scope"]["type"],
                chapter_start=pair["scope"]["chapter_start"], chapter_end=pair["scope"]["chapter_end"],
                choice=response["choice"], dimension_scores=response["dimension_scores"], confidence=response["confidence"],
                rationale=response["rationale"], evidence_spans=tuple(response["evidence_spans"]),
            )
            for span in decision.evidence_spans:
                prose = pair["candidate_a" if span["candidate"] == "A" else "candidate_b"]
                if span["end"] > len(prose) or prose[span["start"]:span["end"]] != span.get("quote"):
                    raise ValueError("Human evidence must quote exact Unicode code-point spans")
            mapping = private[pair["pair_token"]]
            choice = decision.choice.value
            aligned = ("TREATMENT" if choice == mapping["canonical_position"] else "CONTROL") if choice in {"A", "B"} else choice
            by_subject.setdefault(mapping["subject_id"], []).append({"reviewer_id": reviewer, "aligned_choice": aligned,
                "raw_response": response, "attestation": submitted["attestation"], "source_hash": digest(submitted)})
    report = {"status": "HUMAN_RESPONSES_RECORDED_NOT_QUALIFIED", "campaign_hash": bindings["campaign_hash"],
        "evidence_class": "HUMAN_ATTESTED_SUBJECTIVE_PREFERENCE", "identity_verification": "ATTESTATION_ONLY",
        "craft_effectiveness": "HYPOTHESIS", "policy_change_authorized": False,
        "subjects": [{"subject_id": subject, "status": "AGREED" if len({row["aligned_choice"] for row in rows}) == 1 else "DISAGREED",
                      "decisions": rows, "adjudication": "NOT_RUN"} for subject, rows in sorted(by_subject.items())]}
    _write_file(destination, _json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "record"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--reviewer", action="append", default=[])
    parser.add_argument("--packs", type=Path)
    parser.add_argument("--response", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "export":
        if not args.manifest or not args.results or len(args.reviewer) != 2:
            parser.error("export requires the frozen manifest, complete stage results and two assigned reviewers")
        report = export_packs(manifest=json.loads(_read_regular(args.manifest)), results=args.results, destination=args.output, reviewers=tuple(args.reviewer))
    else:
        if not args.packs:
            parser.error("record requires the exact --packs directory")
        report = evaluate_responses(directory=args.packs, responses=args.response, destination=args.output)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
