from tests.unit.mkaos_p1_helpers import MkaosP1TestCase
from novel_forge.modules import mkaos


class MkaosAbstractionQualityBenchmarkTests(MkaosP1TestCase):
    def test_benchmark_covers_professional_webnovel_and_classic_sources(self):
        report = mkaos.run_knowledge_abstraction_quality_benchmark(
            self.storage,
            {
                "project_id": self.project_id,
                "quality_threshold": 0.45,
                "max_extraction_chunks": 2,
                "max_candidates_per_source": 2,
            },
        )["data"]

        coverage = set(report["summary"]["source_kind_coverage"])
        self.assertIn("professional_book", coverage)
        self.assertIn("webnovel_analysis", coverage)
        self.assertIn("classic_novel_analysis", coverage)
        self.assertGreaterEqual(report["summary"]["candidate_count"], 3)
        self.assertTrue(report["summary"]["average_score"] > 0)
        self.assertFalse(report["source_isolation"]["raw_text_included"])
        self.assertNotIn("制度会改变资源分配", str(report))
