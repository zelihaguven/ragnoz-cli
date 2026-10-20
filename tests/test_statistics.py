"""Tests for the RAGnoz statistical comparison helpers."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Keep the test runnable directly from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragnoz.statistics import (
    mcnemar_exact_p_value,
    paired_bootstrap_ci,
    paired_bootstrap_mean_difference_ci,
    wilson_ci,
)


class WilsonCiTests(unittest.TestCase):
    def test_empty_sample_returns_uninformative_interval(self) -> None:
        self.assertEqual(wilson_ci(0, 0), (0.0, 1.0))

    def test_zero_and_one_proportions_stay_inside_unit_interval(self) -> None:
        zero_lower, zero_upper = wilson_ci(0, 10)
        one_lower, one_upper = wilson_ci(10, 10)
        self.assertEqual(zero_lower, 0.0)
        self.assertEqual(one_upper, 1.0)
        self.assertGreater(zero_upper, 0.0)
        self.assertLess(one_lower, 1.0)
        self.assertAlmostEqual(zero_upper, 0.2775327998628892, places=12)
        self.assertAlmostEqual(one_lower, 0.7224672001371107, places=12)

    def test_invalid_success_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wilson_ci(4, 3)


class McNemarTests(unittest.TestCase):
    def test_no_discordant_pairs_has_p_value_one(self) -> None:
        self.assertEqual(mcnemar_exact_p_value(0, 0), 1.0)

    def test_symmetric_counts_have_equal_p_values(self) -> None:
        self.assertEqual(
            mcnemar_exact_p_value(2, 7),
            mcnemar_exact_p_value(7, 2),
        )

    def test_equal_discordant_counts_have_p_value_one(self) -> None:
        self.assertEqual(mcnemar_exact_p_value(5, 5), 1.0)

    def test_small_exact_tail(self) -> None:
        # For (b, c) = (0, 2), 2 * P[X = 0] = 2 * (1 / 4).
        self.assertAlmostEqual(mcnemar_exact_p_value(0, 2), 0.5)


class PairedBootstrapTests(unittest.TestCase):
    def test_seed_makes_interval_deterministic(self) -> None:
        differences = (-2.0, -1.0, 1.0, 3.0)
        first = paired_bootstrap_ci(differences, reps=500, seed=1234)
        second = paired_bootstrap_ci(differences, reps=500, seed=1234)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first)), list(first))

    def test_all_zero_differences_have_zero_interval(self) -> None:
        self.assertEqual(
            paired_bootstrap_ci([0.0, 0.0, 0.0], reps=100, seed=9),
            (0.0, 0.0),
        )

    def test_two_paired_sequences_are_supported(self) -> None:
        interval = paired_bootstrap_mean_difference_ci(
            [1.0, 2.0, 4.0], [2.0, 4.0, 7.0], reps=100, seed=3
        )
        self.assertLessEqual(interval[0], interval[1])
        self.assertGreaterEqual(interval[0], 0.0)

    def test_empty_differences_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([], reps=10)


if __name__ == "__main__":
    unittest.main()
