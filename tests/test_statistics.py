"""Tests for the RAGnoz statistical comparison helpers."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Keep the test runnable directly from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragnoz.statistics import (
    exact_mcnemar_pvalue,
    mcnemar_exact_p_value,
    paired_bootstrap_ci,
    paired_bootstrap_mean_difference_ci,
    wilson_ci,
    wilson_interval,
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

    def test_bool_count_is_rejected_even_though_bool_is_an_int_subclass(self) -> None:
        with self.assertRaises(TypeError):
            wilson_ci(True, 10)

    def test_non_integer_count_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            wilson_ci(1.5, 10)  # type: ignore[arg-type]

    def test_negative_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wilson_ci(-1, 10)

    def test_out_of_range_confidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wilson_ci(1, 10, confidence=1.0)

    def test_non_finite_confidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wilson_ci(1, 10, confidence=float("nan"))

    def test_wilson_interval_alias_matches_wilson_ci(self) -> None:
        self.assertEqual(wilson_interval(5, 20), wilson_ci(5, 20))


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

    def test_known_exact_tail_for_one_and_three(self) -> None:
        # Binomial(4, 0.5): P[X<=1] = (C(4,0)+C(4,1))/16 = 5/16; p = 2 * 5/16 = 0.625.
        self.assertAlmostEqual(mcnemar_exact_p_value(1, 3), 0.625)

    def test_exact_mcnemar_pvalue_alias_matches_mcnemar_exact_p_value(self) -> None:
        self.assertEqual(exact_mcnemar_pvalue(3, 9), mcnemar_exact_p_value(3, 9))


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

    def test_zero_reps_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([1.0], reps=0)

    def test_non_finite_difference_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap_ci([1.0, float("inf")], reps=10)

    def test_mismatched_sequence_lengths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap_mean_difference_ci([1.0, 2.0], [1.0])

    def test_single_replicate_short_circuits_percentile_lookup(self) -> None:
        # With reps=1 there is exactly one bootstrap mean; both percentile
        # endpoints must resolve to that single value regardless of alpha.
        differences = (1.0, 2.0, 3.0)
        lower, upper = paired_bootstrap_ci(differences, reps=1, seed=0)
        self.assertEqual(lower, upper)

    def test_percentile_position_lands_exactly_on_an_index(self) -> None:
        # reps=41 at the default 95% confidence gives alpha=0.025 and
        # position = 0.025 * 40 = 1.0 exactly, hitting the no-interpolation
        # branch of the percentile lookup on both tails.
        differences = [float(i) for i in range(41)]
        lower, upper = paired_bootstrap_ci(differences, reps=41, seed=0)
        self.assertLessEqual(lower, upper)


if __name__ == "__main__":
    unittest.main()
