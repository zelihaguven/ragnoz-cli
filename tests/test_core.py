from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragnoz.cache import StageCache
from ragnoz.diagnosis import discover_architecture
from ragnoz.evaluation import evaluate_item
from ragnoz.schemas import GoldenItem, QuestionTrace


class CoreTests(unittest.TestCase):
    def test_cache_is_content_addressed_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = StageCache(directory)
            key = cache.key("retrieve", {"q": "x"}, {"model": "a"})
            cache.put(key, {"ids": [1]})
            self.assertEqual(cache.get(key), {"ids": [1]})
            self.assertIsNone(cache.get(cache.key("retrieve", {"q": "x"}, {"model": "b"})))
            self.assertEqual(cache.stats()["hits"], 1)

    def test_numerical_error_with_context_attributes_to_generation(self):
        item = GoldenItem(id="Q1", question="How high?", type="numeric", expected_answer="8848.86 m",
                          expected_values=[{"value": "8848.86"}], evidence=[{"doc_id": "ev", "quote": "8,848.86 m"}])
        trace = QuestionTrace(question_id="Q1", answer="8,488 m", observability="L1",
                              context=[{"doc_id": "ev", "text": "The height is 8,848.86 m."}])
        result = evaluate_item(item, trace)
        self.assertEqual(result.attribution, "GEN_NUMBER_EXTRACTION")

    def test_naive_versus_modular_classification(self):
        naive = discover_architecture([], {"flow": "linear", "modules": {"retrieval": {"bm25": True}}})
        modular = discover_architecture([], {"flow": "conditional", "modules": {"orchestration": {"routing": "rule"}}})
        self.assertEqual(naive.paradigm, "Naive")
        self.assertEqual(modular.paradigm, "Modular")


if __name__ == "__main__":
    unittest.main()
