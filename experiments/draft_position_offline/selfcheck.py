"""CONSTRAINT: synthetic harness checks do not measure a model's narrative behavior."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("position_runner", Path(__file__).with_name("run.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class OfflineHarnessCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(sys.argv[1])
        cls.manifest = runner.read(cls.directory / "manifest.json")
        cls.policy = runner.read(cls.directory / "policy.json")
        cls.case = runner.read(cls.directory / "cases.json")[0]
        cls.request = runner.read(cls.directory / cls.manifest["requests"][0]["path"])
        cls.trial = next(t for t in cls.manifest["schedule"] if t["request_id"] == cls.request["request_id"])

    def response(self):
        text = f"{self.case['hero']}从{self.case['location']}取出{self.case['object']}，在{self.case['deadline']}交给{self.case['witness']}。条件尚未满足，门仍关闭。"
        return {"trial_id": self.trial["trial_id"], "input_hash": self.request["input_hash"], "wire_input_hash": self.request["input_hash"],
                "wire_input_text": self.request["input_text"], "provider": "scripted-selfcheck", "model": "no-model", "model_revision": "fixture-v1",
                "provider_request_id": "fixture-no-call", "trace_id": "fixture-trace", "span_id": "fixture-span",
                "request_settings": {"protocol": "SCRIPTED_ONLY", "reasoning_effort": None, "temperature": None, "seed": None, "max_output_tokens": 16384, "cache_policy": "none"},
                "usage": {"input_tokens": 0, "output_tokens": 0}, "cost": {"amount": "0", "currency": "USD"},
                "admission": {"status": "ADMITTED", "complete_request_coverage": ["scripted-selfcheck-only"], "input_hash": self.request["input_hash"], "total_reserved": 0, "applicable_limit": 1},
                "finish_reason": "completed", "output": {"scene_artifacts": [{"slot_id": "s1:skeleton", "text": text, "used_fact_ids": [self.case["fact_id"]]}]}}

    def review(self, response):
        text = response["output"]["scene_artifacts"][0]["text"]
        return {"output_hash": runner.digest(runner.canonical(response["output"])), "rubric_version": "draft-position-prose-rubric.v1",
                "reviewer_id": "synthetic-reviewer", "reviewer_kind": "HUMAN", "blinded": True,
                "judgments": {metric: {"status": "PASSED", "rationale": "Scripted validator protocol exercise only.",
                    "evidence": [{"start": 0, "end": len(text), "quote": text}]} for metric in runner.METRICS}}

    def test_all_frozen_triples_have_only_one_position_difference(self):
        result = runner.verify(self.directory)
        self.assertEqual(result["requests"], 48)
        self.assertTrue(result["identical_remainder_bytes"])

    def test_native_render_replays_exact_receipt_hash(self):
        _, _, _, native = runner.native_baseline()
        self.assertEqual(native["replayed_input_hash"], native["expected_input_hash"])
        self.assertEqual(native["evidence_class"], "MOCK_E2E")
        self.assertEqual(native["real_provider_calls"], 0)

    def test_duplicate_or_missing_evidence_cannot_enter_metric(self):
        for text in (self.request["input_text"].replace(self.request["target_block"], ""), self.request["input_text"] + self.request["target_block"]):
            with self.assertRaises(ValueError):
                runner.block_offsets(text, self.request["target_block"])

    def test_wire_drift_and_truncation_do_not_count_as_position_failures(self):
        for field, value in (("wire_input_text", "changed"), ("finish_reason", "length")):
            response = self.response()
            response[field] = value
            with self.assertRaises(ValueError):
                runner.assess(self.directory, self.trial, response, self.case, self.request)

    def test_host_rejects_out_of_scope_self_reported_fact(self):
        response = self.response()
        response["output"]["scene_artifacts"][0]["used_fact_ids"] = [self.case["secret_id"]]
        with self.assertRaises(Exception) as captured:
            runner.assess(self.directory, self.trial, response, self.case, self.request)
        self.assertEqual(captured.exception.code, "REALIZATION_EPISTEMIC_SCOPE_VIOLATION")

    def test_unknown_review_and_unverifiable_quote_cannot_pass(self):
        response = self.response()
        for mode in ("UNKNOWN", "BAD_QUOTE"):
            review = self.review(response)
            if mode == "UNKNOWN":
                review["judgments"]["fact_recall"]["status"] = "UNKNOWN"
            else:
                review["judgments"]["fact_recall"]["evidence"][0]["quote"] = "not a literal quote"
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                runner.write(directory / "reviews" / (self.trial["trial_id"] + ".json"), review)
                with self.assertRaises(ValueError):
                    runner.assess(directory, self.trial, response, self.case, self.request)

    def test_failed_prose_verdict_is_preserved_not_overridden_by_fact_ids(self):
        response = self.response()
        review = self.review(response)
        review["judgments"]["knowledge_boundary"]["status"] = "FAILED"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            runner.write(directory / "reviews" / (self.trial["trial_id"] + ".json"), review)
            scores = runner.assess(directory, self.trial, response, self.case, self.request)
            self.assertEqual(scores["knowledge_boundary"], 0)
            self.assertEqual(scores["fact_recall"], 1)

    def test_repeats_do_not_inflate_independent_case_count(self):
        rows = [{"provider": "fixture", "model": "fixture", "model_revision": "v1", "arm": "draft", "length_bytes_target": 60000,
                 "case_id": f"case-{case}", "repeat": repeat, "position": position, "scores": {m: float(position != "middle") for m in runner.METRICS}}
                for case in range(4) for repeat in range(3) for position in runner.POSITIONS]
        summaries = runner.aggregate(rows, self.policy)
        self.assertEqual(summaries[0]["independent_cases"], 4)
        self.assertEqual(summaries[0]["metrics"]["fact_recall"]["gaps"]["edge_mean_minus_middle"]["estimate"], 1)
        self.assertEqual(runner.mcnemar_exact([(1, 0)] * 6)["p"], 0.03125)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python selfcheck.py FROZEN_DIRECTORY")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OfflineHarnessCheck)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
