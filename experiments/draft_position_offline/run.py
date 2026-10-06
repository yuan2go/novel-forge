"""CONSTRAINT: offline artifacts only; no client, credentials, DB, or network dispatch."""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))
POSITIONS = ("front", "middle", "end")
METRICS = ("fact_recall", "knowledge_boundary", "due_obligation", "causal_constraint", "execution_consistency")
QUALITY_DIMENSION_MAP = {"fact_recall": "canon_consistency", "knowledge_boundary": "epistemic_consistency",
                         "due_obligation": "promise_payoff_debt", "causal_constraint": "causal_consistency",
                         "execution_consistency": "basic_prose_integrity"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_identity(relative):
    return {"path": relative, "sha256": digest((ROOT / relative).read_bytes())}


def native_baseline():
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt

    relative = "reports/audits/2026-10-05-quality-context-e2e/context-native-snapshot.json.gz"
    snapshot = json.loads(gzip.decompress((ROOT / relative).read_bytes()))
    tables = snapshot["tables"]
    effect = next(x for x in tables["authority_external_effect"] if x["capability"] == "model.draft")
    payload = effect["request_payload"]
    metadata = payload["_production_execution"]
    runtime = metadata["capability_runtime"]
    asset = next(x for x in tables["authority_asset_version"] if x["asset_version_id"] == runtime["materialization_asset_version_id"])
    materialization = asset["content"]["contract"]
    scope = {"scope_kind": "chapter", "scope_id": f"{metadata['book_id']}:chapter:{metadata['chapter']}",
             "project_id": metadata["project_id"], "book_id": metadata["book_id"], "chapter_number": metadata["chapter"]}
    prompt, evidence = _materialize_production_codex_prompt(target_scope=scope, stage="draft", inputs=payload["input"], materialization=materialization)
    expected = runtime["routing_decision"]["task"]["input_hash"]
    if digest(prompt) != expected:
        raise ValueError("NATIVE_RENDER_REPLAY_MISMATCH")
    admission_asset = next(x for x in tables["authority_asset_version"] if x["asset_version_id"] == runtime["provider_admission_asset_version_id"])
    admission = admission_asset["content"]["contract"]
    quality_rubric = next(x for x in tables["authority_asset_version"] if x["asset_type"] == "quality_rubric")
    return prompt, evidence, materialization, {
        "schema_version": "draft-position-native-baseline.v1", "evidence_class": snapshot["evidence_class"],
        "snapshot_source_implementation_commit": snapshot["implementation_commit"], "checked_main_sha": read(HERE / "policy.json")["frozen_main_sha"],
        "snapshot_identity": file_identity(relative), "effect_id": effect["external_effect_id"],
        "operation_id": effect["operation_id"], "attempt_id": metadata["attempt_id"],
        "project_id": metadata["project_id"], "workspace_id": metadata["workspace_id"], "book_id": metadata["book_id"],
        "target_scope": scope, "inputs": payload["input"], "materialization_asset_version_id": asset["asset_version_id"],
        "materialization_content_hash": asset["content_hash"], "native_task_context_receipt": materialization["context_selection"][0]["content"]["task_context_receipt"],
        "native_admission": admission, "replayed_input_hash": digest(prompt), "expected_input_hash": expected,
        "replay_status": "MATCH", "native_provider": effect["provider"], "native_model": effect["model_id"],
        "real_provider_calls": 0, "production_acceptance": "NOT_CLAIMED",
        "quality_rubric_source": {key: quality_rubric[key] for key in ("asset_version_id", "schema_version", "content_hash", "content")},
        "original_quality_scores_reused": False,
    }


def evidence_text(case):
    gate = "已满足，允许本章开门" if case["prerequisite"] else "未满足，本章不得开门，也不得虚构已缴付或已批准的 accepted event"
    return (f"【已冻结故事证据：{case['case_id']}】\n"
            f"Story Truth / {case['fact_id']}：{case['object']}保存在{case['location']}，这是当前事实，未经移动。\n"
            f"Character Knowledge：{case['hero']}已由上一章亲眼检查，KNOWN {case['fact_id']}。\n"
            f"Story Truth / {case['secret_id']}：{case['secret']}。{case['witness']} KNOWN；{case['hero']} UNKNOWN；"
            "本章没有获知渠道或披露许可，不能让主角据此行动或说出答案。世界真相不等于人物知识。\n"
            f"Narrative Obligation / {case['obligation_id']}：OPEN，HIGH，due chapter=21；"
            f"必须在{case['deadline']}，由{case['hero']}实际把{case['object']}交还{case['witness']}，承诺、计划、旁白自报或藏起物品都不算完成。\n"
            f"Causal requirement：证人处的关门只能在通行前提满足后打开。accepted prerequisite：{case['prerequisite_text']}；"
            f"当前状态{gate}。归还物品不等于满足该通行前提。\n"
            f"执行目标：正文先从既定位置取出物品，再在期限前当面交还；随后按已满足或未满足的前提决定门是否打开。\n")


def fixture_inputs(native, case):
    from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract

    inputs = {"style": deepcopy(native["inputs"]["style"])}
    plan = dict(chapter=21, title="归还", premise="在时间限制下完成归还并面对通行条件。",
                cast=[case["hero"], case["witness"]], chapter_intent="取出指定物品，当面归还，然后处理门的通行条件。",
                required_obligation_ids=[case["obligation_id"]], required_long_distance_fact_ids=[case["fact_id"]],
                knowledge_boundaries=[{"layer": "CHARACTER_KNOWLEDGE", "subject_id": case["hero"], "fact_id": case["fact_id"], "status": "KNOWN"}])
    plan["scene_plan"] = [{"scene_id": "s1", "goal": plan["chapter_intent"], "participants": plan["cast"],
                           "focalization": case["hero"], "accessible_knowledge": [case["fact_id"]],
                           "beats": ["寻找", "交还", "处理通行条件"]}]
    plan["source_chapter_plan_asset_version_id"] = f"offline:{case['case_id']}:chapter-plan:v1"
    plan["source_chapter_plan_content_hash"] = digest(canonical(plan))
    inputs["plan"] = plan
    inputs["chapter_memo"] = {"creative_guidance": {"narrative": "用简体中文写一个连贯场景，人物必须通过可观察的动作执行目标。"}, "scene_directives": []}
    inputs.pop("execution_intent", None)
    inputs["realization_contract"] = compile_realization_contract(plan, inputs["style"])
    return inputs


def segment(source):
    return {"asset_version_id": source.asset_version_id, "asset_type": source.asset_type,
            "narrative_function": source.narrative_function, "safe_summary": source.safe_summary,
            "structured_facts": [], "allowed_use": source.allowed_use, "compression_method": "none"}


def frozen_sources(case, target_length):
    from novel_forge.modules.context_contracts import ContextCandidate
    from novel_forge.modules.context_builder.task_compression import compile_task_context

    boundary = {"accepted_through_chapter": 20, "story_state_snapshot_version": "offline:state:20", "canon_snapshot_version": "offline:canon:20"}
    project = "offline:position:project"
    book = "offline:position:book"
    filler = (ROOT / "tests/fixtures/long_project/clockverse_long_fixture.txt").read_text(encoding="utf-8").strip()
    per_source = target_length // 11
    filler = (filler + "\n") * max(1, math.ceil(per_source / len((filler + "\n").encode("utf-8"))))
    sources = []
    for index in range(12):
        text = evidence_text(case) if index == 0 else f"【另一故事的既有档案 {index:02d}；不是本章人物的知识】\n" + filler
        sources.append(ContextCandidate(asset_version_id=f"offline:{case['case_id']}:source:{index:02d}:v1",
            asset_type="chapter_episodic_summary", project_id=project, book_id=book, estimated_tokens=1,
            content_digest=digest(text), safe_summary=text, required=True, compression_method="none",
            accepted_boundary=boundary, narrative_function="required_task_related_history",
            provenance={"authority_asset_version_id": f"offline:{case['case_id']}:source:{index:02d}:v1", "evidence_class": "OFFLINE_FIXTURE"}))
    task = {"stage": "draft", "chapter": 21, "accepted_boundary": boundary, "character_ids": [case["hero"], case["witness"]],
            "memo_fingerprint": digest("offline-memo"), "required_long_distance_fact_ids": [case["fact_id"]]}
    selected, receipt = compile_task_context(sources, task=task, token_budget=512000, required_asset_types=(),
        model_call=lambda *_: (_ for _ in ()).throw(ValueError("UNAUTHORIZED_MODEL_CALL")))
    if not receipt["fast_path"] or len(selected) != 12:
        raise ValueError("OFFLINE_SOURCES_NOT_LOSSLESS")
    by_id = {x.asset_version_id: x for x in selected}
    return [by_id[x.asset_version_id] for x in sources], receipt, boundary


def context_bundle(sources, receipt, boundary):
    # WHY: this is a new fixture receipt; native production receipt is never attached to changed inputs.
    return {"context_profile_version": "draft-context-profile-v4", "token_budget": 512000,
            "context_segments": [segment(x) for x in sources], "estimated_tokens": receipt["after_estimated_tokens"],
            "task_context_receipt": receipt, "context_manifest": {
                "narrative_position": {"book_id": "offline:position:book", "chapter": 21},
                "authority_state_boundary": boundary, "task_context_receipt": receipt}}


def probe(prompt, case):
    start = prompt.index("<stage_semantic_contract>")
    questions = {"fact_location": f"{case['fact_id']} 的物品当前在哪里？",
                 "hero_secret_status": f"{case['hero']} 对 {case['secret_id']} 的知识状态是什么？",
                 "obligation_id": "本章到期的 obligation identity 是什么？",
                 "obligation_deadline": "必须在什么时间前实际交还？",
                 "gate_may_open": "冻结前提是否允许本章开门？不得虚构新事件。"}
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "fact_location": {"type": "string"}, "hero_secret_status": {"enum": ["KNOWN", "SUSPECTED", "UNKNOWN", "FORGOTTEN"]},
        "obligation_id": {"type": "string"}, "obligation_deadline": {"type": "string"}, "gate_may_open": {"type": "boolean"}},
        "required": list(questions)}
    # WHY: a separate diagnostic task cannot prime the Draft arm with retrieved answers.
    return prompt[:start] + "<stage_semantic_contract>\n离线召回探针，仅回答下列问题；不生成正文。只输出所列 JSON schema。\n" + canonical(questions) + "\n</stage_semantic_contract>\n\n<output_schema>\n" + canonical(schema) + "\n</output_schema>", schema


def block_offsets(prompt, block):
    if prompt.count(block) != 1:
        raise ValueError("TARGET_MISSING_OR_DUPLICATED")
    start = prompt.index(block)
    end = start + len(block)
    total = len(prompt.encode("utf-8"))
    byte_start = len(prompt[:start].encode("utf-8"))
    byte_end = len(prompt[:end].encode("utf-8"))
    return {"unicode_start": start, "unicode_end": end, "utf8_start": byte_start, "utf8_end": byte_end,
            "normalized_utf8_midpoint": (byte_start + byte_end) / 2 / total,
            "token_start": None, "token_end": None, "normalized_token_midpoint": None,
            "token_measurement": "NOT_RUN_MODEL_TOKENIZER_REQUIRED"}


def build(args):
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt

    destination = args.output.resolve()
    if destination.exists():
        raise ValueError("OUTPUT_EXISTS_USE_NEW_VERSIONED_DIRECTORY")
    policy = read(HERE / "policy.json")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if sha != policy["frozen_main_sha"]:
        raise ValueError("BASELINE_SHA_DRIFT")
    cases = read(args.cases or HERE / "cases.json")
    if len({x["case_id"] for x in cases}) != len(cases):
        raise ValueError("CASE_IDS_NOT_UNIQUE")
    native_prompt, native_evidence, materialization, native = native_baseline()
    write(destination / "native-baseline.json", native)
    write(destination / "native-materialization.json", materialization)
    write(destination / "native-render-evidence.json", native_evidence)
    (destination / "native-input.txt").write_text(native_prompt, encoding="utf-8")
    write(destination / "cases.json", cases)
    write(destination / "policy.json", policy)
    requests = []
    for case in cases:
        inputs = fixture_inputs(native, case)
        write(destination / "fixtures" / f"{case['case_id']}-inputs.json", inputs)
        for length in policy["content_lengths_bytes"]:
            sources, receipt, boundary = frozen_sources(case, length)
            fixture_id = f"{case['case_id']}-{length}"
            write(destination / "fixtures" / f"{fixture_id}-compiler-receipt.json", receipt)
            write(destination / "fixtures" / f"{fixture_id}-sources.json", [segment(x) for x in sources])
            target = sources[0]
            distractors = sources[1:]
            slots = {"front": 0, "middle": 5, "end": len(distractors)}
            for position, index in slots.items():
                ordered = [*distractors[:index], target, *distractors[index:]]
                experiment_materialization = deepcopy(materialization)
                context = context_bundle(ordered, receipt, boundary)
                experiment_materialization["materialization_hash"] = digest(canonical({"native_hash": materialization["materialization_hash"], "inputs": inputs, "context": context}))
                experiment_materialization["context_selection"] = [{"asset_version_id": "offline:context:v1", "content": context}]
                scope = {"scope_kind": "chapter", "scope_id": "offline:position:book:chapter:21", "project_id": "offline:position:project", "book_id": "offline:position:book", "chapter_number": 21}
                prompt, evidence = _materialize_production_codex_prompt(target_scope=scope, stage="draft", inputs=inputs, materialization=experiment_materialization)
                # WHY: the writer view may omit storage-only fields; freeze its exact rendered object.
                from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view, build_provider_task_view
                view = build_provider_context_view("draft", context, build_provider_task_view("draft", inputs, compact_contract=True, project_methods=True, instruction_cleanup=True, work_requirements=True), writer_projection_version="accepted-writer-history.v2")
                target_row = next(x for x in view["segments"] if x["asset_version_id"] == target.asset_version_id)
                target_block = canonical(target_row)
                for arm in ("draft", "probe"):
                    arm_prompt, schema = (prompt, materialization["output_schema"]["content"]) if arm == "draft" else probe(prompt, case)
                    identity = f"{fixture_id}-{position}-{arm}"
                    offsets = block_offsets(arm_prompt, target_block)
                    lo, hi = policy["position_bands"][position]
                    if not lo <= offsets["normalized_utf8_midpoint"] <= hi:
                        raise ValueError(f"POSITION_UNREACHABLE:{identity}:{offsets}")
                    path = f"requests/{identity}.json"
                    record = {"schema_version": "draft-position-request.v1", "request_id": identity,
                        "case_id": case["case_id"], "fixture_id": fixture_id, "length_bytes_target": length,
                        "position": position, "arm": arm, "evidence_class": "OFFLINE_FIXTURE",
                        "project_id": "offline:position:project", "workspace_id": "offline:position:workspace", "book_id": "offline:position:book",
                        "main_sha": sha, "input_text": arm_prompt, "input_hash": digest(arm_prompt),
                        "total_utf8_bytes": len(arm_prompt.encode("utf-8")), "target_block": target_block,
                        "target_hash": digest(target_block), "offsets": offsets,
                        "ordered_source_ids": [x.asset_version_id for x in ordered],
                        "source_membership_hash": digest(canonical(sorted(x.asset_version_id for x in ordered))),
                        "compiler_receipt_hash": receipt["receipt_hash"], "native_receipt_reused_for_mutated_input": False,
                        "output_schema": schema, "output_schema_hash": digest(canonical(schema)),
                        "realization_contract": inputs["realization_contract"] if arm == "draft" else None,
                        "route": {"provider": None, "model": None, "model_revision": None, "reasoning_effort": None,
                                  "temperature": None, "seed": None, "max_output_tokens": policy["output_reserve_tokens"],
                                  "route_status": "BLOCKED_UNBOUND_MODEL", "cache_policy": "cold_or_balanced_record_hits"},
                        "provider_admission": "NOT_RUN_REQUIRES_FRESH_ADMISSION_PER_VARIANT",
                        "answer_canaries": [case["location"], case["deadline"], case["secret"], case["prerequisite_text"]],
                        "production_prompt_changed": False, "position_intervention": "EXPERIMENT_ONLY_CONTEXT_SEGMENT_PERMUTATION"}
                    write(destination / path, record)
                    requests.append({k: record[k] for k in ("request_id", "case_id", "fixture_id", "position", "arm", "input_hash", "total_utf8_bytes", "offsets") } | {"path": path})
    rng = random.Random(policy["randomization_seed"])
    schedule = []
    grouped = defaultdict(list)
    for request in requests:
        grouped[(request["fixture_id"], request["arm"])].append(request)
    for repeat in range(policy["repetitions"]):
        groups = list(grouped.values())
        rng.shuffle(groups)
        for group in groups:
            order = list(group)
            rng.shuffle(order)
            for request in order:
                schedule.append({"trial_id": f"{request['request_id']}-repeat-{repeat}", "repeat": repeat,
                                 "request_id": request["request_id"], "path": request["path"], "input_hash": request["input_hash"],
                                 "dispatch_status": "NOT_RUN", "fresh_idempotency_key": f"offline:{request['request_id']}:repeat:{repeat}"})
    source_paths = ["src/novel_forge/modules/chapter_authority/execution_gateway.py", "src/novel_forge/modules/chapter_authority/provider_views.py",
                    "src/novel_forge/modules/chapter_authority/provider_output_contracts.py", "src/novel_forge/modules/chapter_authority/realization_composition.py",
                    "src/novel_forge/modules/context_builder/task_context.py", "src/novel_forge/modules/context_builder/task_compression.py",
                    "src/novel_forge/modules/provider_control/openai_v2.py", "src/novel_forge/modules/provider_control/deepseek.py",
                    "src/novel_forge/modules/production_execution/backends.py", "src/novel_forge/modules/production_execution/provider_admission.py",
                    "config/capability_packs/chapter_generation_pack.json", "architecture/manifests/migration-manifest.yaml",
                    "tests/fixtures/long_project/clockverse_long_fixture.txt"]
    write(destination / "manifest.json", {"schema_version": "draft-position-experiment.v1", "main_sha": sha,
        "requests": requests, "schedule": schedule, "source_files": [file_identity(x) for x in source_paths],
        "package_files": [{"path": x.name, "sha256": digest(x.read_bytes())} for x in sorted(HERE.iterdir()) if x.is_file() and x.name != "validation.json"],
        "case_count": len(cases), "requests_count": len(requests), "planned_calls": len(schedule), "real_provider_calls": 0,
        "status": "NOT_RUN", "evidence_ceiling": "EXECUTABLE", "case_design": "SMOKE_FOUR_AUTHORED_SCENARIOS_NOT_A_CLEARANCE_SAMPLE"})
    write(destination / "verification.json", verify(destination))
    print(json.dumps({"output": str(destination), "requests": len(requests), "planned_calls": len(schedule), "real_provider_calls": 0}, ensure_ascii=False))


def strip_target(request):
    text = request["input_text"]
    block = request["target_block"]
    start = text.index(block)
    end = start + len(block)
    if text[end:end + 1] == ",":
        end += 1
    elif text[start - 1:start] == ",":
        start -= 1
    else:
        raise ValueError("TARGET_NOT_A_CONTEXT_ARRAY_ELEMENT")
    return text[:start] + text[end:]


def verify(directory):
    manifest = read(directory / "manifest.json")
    policy = read(directory / "policy.json")
    groups = defaultdict(list)
    for item in manifest["source_files"]:
        if file_identity(item["path"]) != item:
            raise ValueError("FROZEN_SOURCE_DRIFT:" + item["path"])
    for item in manifest["package_files"]:
        if digest((HERE / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("FROZEN_EXPERIMENT_PACKAGE_DRIFT:" + item["path"])
    for entry in manifest["requests"]:
        request = read(directory / entry["path"])
        if digest(request["input_text"]) != entry["input_hash"] or request["input_hash"] != entry["input_hash"]:
            raise ValueError("REQUEST_HASH_DRIFT")
        offsets = block_offsets(request["input_text"], request["target_block"])
        if offsets != request["offsets"]:
            raise ValueError("EVIDENCE_OFFSET_DRIFT")
        lo, hi = policy["position_bands"][request["position"]]
        if not lo <= offsets["normalized_utf8_midpoint"] <= hi:
            raise ValueError("POSITION_BAND_DRIFT")
        context_text = request["input_text"].split("Authorized story data: ", 1)[1]
        view, _ = json.JSONDecoder().raw_decode(context_text)
        if view["segments"][request["ordered_source_ids"].index(json.loads(request["target_block"])["asset_version_id"])] != json.loads(request["target_block"]):
            raise ValueError("TARGET_CONTEXT_BOUNDARY_DRIFT")
        if "UNKNOWN" not in request["target_block"]:
            raise ValueError("EPISTEMIC_NEGATION_LOST")
        for canary in request["answer_canaries"]:
            if request["input_text"].count(canary) != 1:
                raise ValueError("ANSWER_MISSING_OR_DUPLICATED_OUTSIDE_MOVING_PACKET")
        groups[(request["fixture_id"], request["arm"])].append(request)
    for group in groups.values():
        if {x["position"] for x in group} != set(POSITIONS) or len(group) != 3:
            raise ValueError("INCOMPLETE_POSITION_TRIPLE")
        for key in ("total_utf8_bytes", "target_hash", "source_membership_hash", "compiler_receipt_hash", "output_schema_hash"):
            if len({canonical(x[key]) for x in group}) != 1:
                raise ValueError("NON_POSITION_DIFFERENCE:" + key)
        if len({strip_target(x) for x in group}) != 1:
            raise ValueError("NON_TARGET_BYTE_DRIFT")
        compare_keys = ("route", "output_schema", "realization_contract", "project_id", "workspace_id", "book_id", "native_receipt_reused_for_mutated_input")
        if any(len({canonical(x[key]) for x in group}) != 1 for key in compare_keys):
            raise ValueError("FROZEN_CONFIGURATION_DRIFT")
    result = {"status": "PASS", "triples": len(groups), "requests": len(manifest["requests"]),
              "exact_target_multiplicity": 1, "identical_remainder_bytes": True, "identical_total_bytes": True,
              "token_position": "NOT_RUN", "model_behavior": "NOT_RUN", "real_provider_calls": 0,
              "evidence_ceiling": "EXECUTABLE"}
    return result


def valid_span(text, span):
    return (isinstance(span, dict) and type(span.get("start")) is int and type(span.get("end")) is int
            and 0 <= span["start"] < span["end"] <= len(text) and text[span["start"]:span["end"]] == span.get("quote"))


def assess(directory, trial, response, case, request):
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    from novel_forge.modules.chapter_authority.realization_composition import prose_from_output, integrate_realization
    from novel_forge.modules.chapter_quality_authority.domain import QUALITY_DIMENSIONS, QUALITY_EVIDENCE_STATUSES

    if any(dimension not in QUALITY_DIMENSIONS for dimension in QUALITY_DIMENSION_MAP.values()):
        raise ValueError("QUALITY_DIMENSION_CONTRACT_DRIFT")

    required = ("trial_id", "input_hash", "wire_input_hash", "wire_input_text", "request_settings", "provider", "model", "model_revision", "provider_request_id", "trace_id", "span_id", "usage", "cost", "admission", "finish_reason", "output")
    if any(key not in response for key in required):
        raise ValueError("RESPONSE_PROVENANCE_INCOMPLETE")
    if response["trial_id"] != trial["trial_id"] or response["input_hash"] != request["input_hash"] or response["wire_input_hash"] != request["input_hash"]:
        raise ValueError("RESPONSE_INPUT_IDENTITY_DRIFT")
    if response["wire_input_text"] != request["input_text"]:
        raise ValueError("CAPTURED_WIRE_INPUT_DRIFT")
    settings = response["request_settings"]
    if any(key not in settings for key in ("protocol", "reasoning_effort", "temperature", "seed", "max_output_tokens", "cache_policy")):
        raise ValueError("DECODING_SETTINGS_NOT_FROZEN")
    if settings["max_output_tokens"] != request["route"]["max_output_tokens"]:
        raise ValueError("OUTPUT_RESERVE_DRIFT")
    if response["finish_reason"] not in {"stop", "completed"} or response["admission"].get("status") != "ADMITTED":
        raise ValueError("TRUNCATED_OR_UNADMITTED")
    if not all(response[key] for key in ("provider", "model", "model_revision", "provider_request_id", "trace_id", "span_id")):
        raise ValueError("MODEL_REVISION_OR_IDENTITY_UNKNOWN")
    if not response["admission"].get("complete_request_coverage") or response["admission"].get("input_hash") != request["input_hash"]:
        raise ValueError("ADMISSION_NOT_BOUND_TO_WIRE")
    admission = response["admission"]
    if not (type(admission.get("total_reserved")) is int and type(admission.get("applicable_limit")) is int
            and admission["total_reserved"] <= admission["applicable_limit"]):
        raise ValueError("COMPLETE_REQUEST_WINDOW_UNKNOWN_OR_EXCEEDED")
    for key in ("input_tokens", "output_tokens"):
        if type(response["usage"].get(key)) is not int or response["usage"][key] < 0:
            raise ValueError("USAGE_UNKNOWN")
    if not response["cost"].get("currency") or "amount" not in response["cost"]:
        raise ValueError("COST_UNKNOWN")
    result = validate_chapter_provider_output_against_schema(request["arm"], request["output_schema"], response["output"])
    if request["arm"] == "probe":
        return {"fact_recall": float(result["fact_location"] == case["location"]),
                "knowledge_boundary": float(result["hero_secret_status"] == "UNKNOWN"),
                "due_obligation": float(result["obligation_id"] == case["obligation_id"] and result["obligation_deadline"] == case["deadline"]),
                "causal_constraint": float(result["gate_may_open"] == case["prerequisite"])}
    text = prose_from_output(result)
    integrate_realization(contract=request["realization_contract"], artifacts=result["scene_artifacts"], text=text)
    review_path = directory / "reviews" / (trial["trial_id"] + ".json")
    if not review_path.exists():
        raise ValueError("PROSE_REVIEW_NOT_RUN")
    review = read(review_path)
    if review.get("output_hash") != digest(canonical(result)) or review.get("rubric_version") != "draft-position-prose-rubric.v1":
        raise ValueError("PROSE_REVIEW_IDENTITY_DRIFT")
    if not review.get("reviewer_id") or review.get("blinded") is not True or review.get("reviewer_kind") not in {"HUMAN", "INDEPENDENT_MODEL"}:
        raise ValueError("REVIEWER_NOT_INDEPENDENT_OR_BLINDED")
    values = {}
    for metric in METRICS:
        judgment = review.get("judgments", {}).get(metric, {})
        status = judgment.get("status")
        if status not in QUALITY_EVIDENCE_STATUSES or status not in {"PASSED", "FAILED"}:
            raise ValueError("PROSE_JUDGMENT_UNKNOWN:" + metric)
        spans = judgment.get("evidence", [])
        if not spans or not all(valid_span(text, span) for span in spans) or not judgment.get("rationale"):
            raise ValueError("PROSE_EVIDENCE_INVALID:" + metric)
        values[metric] = float(status == "PASSED")
    return values


def mcnemar_exact(pairs):
    wins = sum(a == 1 and b == 0 for a, b in pairs)
    losses = sum(a == 0 and b == 1 for a, b in pairs)
    n = wins + losses
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2 ** n)
    return {"edge_only_pass": wins, "middle_only_pass": losses, "p": p}


def aggregate(rows, policy):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["provider"], row["model"], row["model_revision"], row["arm"], row["length_bytes_target"])].append(row)
    output = []
    global_test_families = defaultdict(list)
    rng = random.Random(policy["randomization_seed"])
    for key, group in groups.items():
        metrics = [m for m in METRICS if all(m in x["scores"] for x in group)]
        report = {"stratum": list(key), "n_rows": len(group), "metrics": {}, "inference_unit": "case_cluster_not_repeat"}
        tests = []
        for metric in metrics:
            by_case = defaultdict(lambda: defaultdict(list))
            for row in group:
                by_case[row["case_id"]][row["position"]].append(row["scores"][metric])
            means = {case: {pos: sum(values) / len(values) for pos, values in positions.items()} for case, positions in by_case.items()}
            if any(set(x) != set(POSITIONS) for x in means.values()):
                raise ValueError("POSITION_STRATUM_INCOMPLETE")
            vectors = list(means.values())
            rates = {pos: sum(v[pos] for v in vectors) / len(vectors) for pos in POSITIONS}
            gaps = {"edge_mean_minus_middle": [(v["front"] + v["end"]) / 2 - v["middle"] for v in vectors],
                    "front_minus_middle": [v["front"] - v["middle"] for v in vectors],
                    "end_minus_middle": [v["end"] - v["middle"] for v in vectors]}
            ci = {}
            for name, values in gaps.items():
                samples = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(policy["bootstrap_iterations"]))
                ci[name] = {"estimate": sum(values) / len(values), "cluster_bootstrap_ci95": [samples[int(len(samples) * .025)], samples[int(len(samples) * .975)]]}
            # WHY: all-repeats-pass produces one independent binary endpoint per case for McNemar.
            for edge in ("front", "end"):
                paired = mcnemar_exact([(int(v[edge] == 1), int(v["middle"] == 1)) for v in vectors])
                tests.append((metric, edge, paired))
            report["metrics"][metric] = {"rates": rates, "gaps": ci, "best_minus_worst": max(rates.values()) - min(rates.values()),
                "floor": policy["absolute_floors"][metric], "absolute_floor_failure": any(v < policy["absolute_floors"][metric] for v in rates.values()),
                "effect_alarm": any(v["estimate"] >= policy["position_gap_alarm"] for v in ci.values()),
                "critical_counterexamples": sum(x["scores"][metric] == 0 for x in group) if metric in {"knowledge_boundary", "causal_constraint"} else 0}
        ordered = sorted(tests, key=lambda item: item[2]["p"])
        cumulative = 0.0
        for index, (metric, edge, result) in enumerate(ordered):
            cumulative = max(cumulative, min(1.0, result["p"] * (len(ordered) - index)))
            report["metrics"][metric].setdefault("paired_exact_tests", {})[edge] = result | {"holm_p_within_stratum": cumulative}
            global_test_families[key[:3]].append((report["metrics"][metric], edge))
        report["independent_cases"] = len({x["case_id"] for x in group})
        output.append(report)
    for family in global_test_families.values():
        ordered = sorted(family, key=lambda item: item[0]["paired_exact_tests"][item[1]]["p"])
        cumulative = 0.0
        for index, (metric_result, edge) in enumerate(ordered):
            test = metric_result["paired_exact_tests"][edge]
            cumulative = max(cumulative, min(1.0, test["p"] * (len(ordered) - index)))
            test["holm_p_model_family_all_arms_lengths_metrics"] = cumulative
    for report in output:
        for metric_result in report["metrics"].values():
            metric_result["position_effect_supported"] = any(
                metric_result["gaps"][edge + "_minus_middle"]["estimate"] >= policy["position_gap_alarm"]
                and metric_result["gaps"][edge + "_minus_middle"]["cluster_bootstrap_ci95"][0] > 0
                and metric_result["paired_exact_tests"][edge]["holm_p_model_family_all_arms_lengths_metrics"] < policy["alpha"]
                for edge in ("front", "end"))
    return output


def score(args):
    directory = args.directory.resolve()
    verify(directory)
    manifest = read(directory / "manifest.json")
    policy = read(directory / "policy.json")
    cases = {x["case_id"]: x for x in read(directory / "cases.json")}
    rows, missing, invalid = [], [], []
    settings_by_triple = defaultdict(set)
    for trial in manifest["schedule"]:
        path = directory / "responses" / (trial["trial_id"] + ".json")
        if not path.exists():
            missing.append(trial["trial_id"])
            continue
        request = read(directory / trial["path"])
        response = read(path)
        try:
            values = assess(directory, trial, response, cases[request["case_id"]], request)
            settings_by_triple[(request["fixture_id"], request["arm"], trial["repeat"])].add(canonical({
                **response["request_settings"], **{key: response[key] for key in ("provider", "model", "model_revision")}}))
            rows.append({**{key: request[key] for key in ("case_id", "position", "arm", "length_bytes_target")},
                         **{key: response[key] for key in ("provider", "model", "model_revision")}, "repeat": trial["repeat"], "scores": values})
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            invalid.append({"trial_id": trial["trial_id"], "reason": str(exc)})
        except Exception as exc:
            invalid.append({"trial_id": trial["trial_id"], "reason": getattr(exc, "code", type(exc).__name__)})
    for triple, settings in settings_by_triple.items():
        if len(settings) != 1:
            invalid.append({"trial_id": list(triple), "reason": "MODEL_OR_DECODING_CONFIG_CHANGED_WITH_POSITION"})
    if len({(x["provider"], x["model"], x["model_revision"]) for x in rows}) > 1:
        invalid.append({"trial_id": "ALL", "reason": "MODEL_REVISION_CHANGED_WITHIN_FROZEN_RUN_USE_NEW_RUN"})
    token_file = directory / "token-audit.json"
    token_ready = token_file.exists() and read(token_file).get("status") == "PASS"
    if token_ready:
        token_audit = read(token_file)
        token_requests = {x["request_id"]: x for x in token_audit["requests"]}
        for row in rows:
            if row["model"] != token_audit["model"] or row["model_revision"] != token_audit["model_revision"]:
                invalid.append({"trial_id": "ALL", "reason": "TOKENIZER_MODEL_REVISION_MISMATCH"})
                break
        for entry in manifest["requests"]:
            if token_requests.get(entry["request_id"], {}).get("input_hash") != entry["input_hash"]:
                invalid.append({"trial_id": entry["request_id"], "reason": "TOKEN_AUDIT_INPUT_DRIFT"})
    if rows and not token_ready:
        invalid.append({"trial_id": "ALL", "reason": "FINAL_INPUT_TOKEN_POSITION_AUDIT_NOT_RUN"})
    summaries = []
    complete = not missing and not invalid
    if complete:
        summaries = aggregate(rows, policy)
    failed = any(v["absolute_floor_failure"] or v["critical_counterexamples"] or v["effect_alarm"] for s in summaries for v in s["metrics"].values())
    counterexamples = [{"case_id": x["case_id"], "position": x["position"], "arm": x["arm"], "repeat": x["repeat"], "metric": metric}
                      for x in rows for metric in ("knowledge_boundary", "causal_constraint") if x["scores"].get(metric) == 0]
    hard_gate_codes = {"CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID", "REALIZATION_EPISTEMIC_SCOPE_VIOLATION", "REALIZATION_SLOT_COVERAGE_INVALID", "REALIZATION_INTEGRATION_DRIFT"}
    hard_gate_failures = [x for x in invalid if x["reason"] in hard_gate_codes]
    status = "NOT_RUN" if not rows and not invalid else "FAIL" if counterexamples or hard_gate_failures else "INCOMPLETE" if not complete else "FAIL" if failed else "INCONCLUSIVE"
    # WHY: four related fixture scenarios cannot support an absence-of-position-effect clearance.
    result = {"schema_version": "draft-position-result.v1", "status": status, "complete": complete,
              "planned_trials": len(manifest["schedule"]), "scored_trials": len(rows), "missing_trials": missing, "invalid_trials": invalid,
              "strata": summaries, "evidence_ceiling": "EXECUTABLE", "production_proven": False,
              "observed_critical_counterexamples": counterexamples, "hard_gate_failures": hard_gate_failures,
              "no_effect_claim": "NOT_ESTABLISHED_NEEDS_POWER_AND_INDEPENDENT_CASE_FAMILIES",
              "qualifying_models": "ONLY_THE_EXACT_RECORDED_REVISION", "downstream": "COUNTEREXAMPLE_REVIEW_OR_EXPAND_SAMPLE"}
    if args.output.exists():
        raise ValueError("RESULT_EXISTS_USE_NEW_VERSIONED_PATH")
    write(args.output, result)
    print(json.dumps({key: result[key] for key in ("status", "complete", "planned_trials", "scored_trials")}, ensure_ascii=False))


def blind(args):
    directory = args.directory.resolve()
    manifest = read(directory / "manifest.json")
    if args.output.exists():
        raise ValueError("BLIND_OUTPUT_EXISTS")
    from novel_forge.modules.chapter_authority.realization_composition import prose_from_output
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    mapping = []
    for trial in manifest["schedule"]:
        request = read(directory / trial["path"])
        path = directory / "responses" / (trial["trial_id"] + ".json")
        if request["arm"] != "draft" or not path.exists():
            continue
        response = read(path)
        result = validate_chapter_provider_output_against_schema("draft", request["output_schema"], response["output"])
        text = prose_from_output(result)
        anonymous = digest(trial["trial_id"] + ":blind:20261006")[7:23]
        case = next(x for x in read(directory / "cases.json") if x["case_id"] == request["case_id"])
        write(args.output / f"{anonymous}.json", {"anonymous_id": anonymous, "prose": text, "story_evidence": evidence_text(case),
            "output_hash": digest(canonical(result)), "rubric_version": "draft-position-prose-rubric.v1", "reviewer_id": "",
            "reviewer_kind": "HUMAN", "blinded": True, "quality_dimension_map": QUALITY_DIMENSION_MAP,
            "judgments": {metric: {"status": "UNKNOWN", "rationale": "", "evidence": []} for metric in METRICS}})
        mapping.append({"anonymous_id": anonymous, "trial_id": trial["trial_id"]})
    write(directory / "blind-mapping-private.json", mapping)
    print(json.dumps({"blind_packets": len(mapping), "mapping": "blind-mapping-private.json_do_not_give_to_reviewer"}))


def export_reviews(args):
    directory = args.directory.resolve()
    mapping = read(directory / "blind-mapping-private.json")
    for row in mapping:
        source = args.reviewed / (row["anonymous_id"] + ".json")
        if not source.exists():
            raise ValueError("BLIND_REVIEW_MISSING")
        destination = directory / "reviews" / (row["trial_id"] + ".json")
        if destination.exists():
            raise ValueError("REVIEW_EXISTS_APPEND_NEW_EXPERIMENT_VERSION")
        reviewed = read(source)
        if reviewed.get("anonymous_id") != row["anonymous_id"]:
            raise ValueError("BLIND_REVIEW_IDENTITY_DRIFT")
        write(destination, reviewed)
    print(json.dumps({"reviews_imported": len(mapping), "model_calls": 0}))


def audit_tokens(args):
    directory = args.directory.resolve()
    verify(directory)
    policy = read(directory / "policy.json")
    measurements = read(args.measurements)
    for key in ("model", "model_revision", "tokenizer_identity", "tokenizer_version", "tokenizer_source_hash"):
        if not measurements.get(key):
            raise ValueError("TOKENIZER_IDENTITY_UNKNOWN")
    rows = {x["request_id"]: x for x in measurements["requests"]}
    groups = defaultdict(list)
    results = []
    for entry in read(directory / "manifest.json")["requests"]:
        request = read(directory / entry["path"])
        measurement = rows[request["request_id"]]
        if measurement["input_hash"] != request["input_hash"]:
            raise ValueError("TOKENIZER_INPUT_DRIFT")
        offsets = measurement["token_unicode_offsets"]
        if not offsets:
            raise ValueError("TOKENIZER_OFFSETS_MISSING")
        covered = 0
        prior_start = 0
        for start, end in offsets:
            if not (type(start) is int and type(end) is int and 0 <= start < end <= len(request["input_text"]) and prior_start <= start <= covered):
                raise ValueError("TOKENIZER_OFFSET_GAP_OR_ORDER_DRIFT")
            covered = max(covered, end)
            prior_start = start
        if covered != len(request["input_text"]):
            raise ValueError("TOKENIZER_DID_NOT_COVER_FULL_INPUT")
        target = request["offsets"]
        relevant = [index for index, (start, end) in enumerate(offsets) if end > target["unicode_start"] and start < target["unicode_end"]]
        prefix, suffix = measurement["prefix_framing_tokens"], measurement["suffix_framing_tokens"]
        if type(prefix) is not int or type(suffix) is not int or min(prefix, suffix) < 0:
            raise ValueError("PROVIDER_FRAMING_UNKNOWN")
        total = prefix + len(offsets) + suffix
        normalized = (prefix + (relevant[0] + relevant[-1] + 1) / 2) / total
        lo, hi = policy["position_bands"][request["position"]]
        if not lo <= normalized <= hi:
            raise ValueError("TOKEN_POSITION_OUTSIDE_PRE_REGISTERED_BAND")
        result = {"request_id": request["request_id"], "input_hash": request["input_hash"], "total_input_tokens": total,
                  "target_token_start": prefix + relevant[0], "target_token_end": prefix + relevant[-1] + 1,
                  "normalized_token_midpoint": normalized}
        groups[(request["fixture_id"], request["arm"])].append(total)
        results.append(result)
    if any(len(set(values)) != 1 for values in groups.values()):
        raise ValueError("POSITION_TOKEN_LENGTH_CONFOUND")
    destination = directory / "token-audit.json"
    if destination.exists():
        raise ValueError("TOKEN_AUDIT_EXISTS_USE_NEW_EXPERIMENT_VERSION")
    write(destination, {"status": "PASS", "measurements_hash": digest(args.measurements.read_bytes()),
        **{key: value for key, value in measurements.items() if key != "requests"}, "requests": results,
        "model_behavior": "NOT_RUN", "independently_verified_tokenizer": False})
    print(json.dumps({"status": "PASS", "requests": len(results), "model_calls": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--cases", type=Path)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("directory", type=Path)
    score_parser = sub.add_parser("score")
    score_parser.add_argument("directory", type=Path)
    score_parser.add_argument("--output", type=Path, required=True)
    blind_parser = sub.add_parser("blind")
    blind_parser.add_argument("directory", type=Path)
    blind_parser.add_argument("--output", type=Path, required=True)
    token_parser = sub.add_parser("audit-token-positions")
    token_parser.add_argument("directory", type=Path)
    token_parser.add_argument("--measurements", type=Path, required=True)
    import_parser = sub.add_parser("import-blind-reviews")
    import_parser.add_argument("directory", type=Path)
    import_parser.add_argument("--reviewed", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    elif args.command == "verify":
        print(json.dumps(verify(args.directory.resolve()), ensure_ascii=False))
    elif args.command == "score":
        score(args)
    elif args.command == "audit-token-positions":
        audit_tokens(args)
    elif args.command == "import-blind-reviews":
        export_reviews(args)
    else:
        blind(args)


if __name__ == "__main__":
    main()
