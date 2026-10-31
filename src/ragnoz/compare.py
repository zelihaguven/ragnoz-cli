from __future__ import annotations

from collections import Counter
from typing import Any

from ragnoz.statistics import mcnemar_exact_p_value, paired_bootstrap_ci, wilson_ci


def compare_evaluations(before: dict[str, Any], after: dict[str, Any], seed: int = 0) -> dict[str, Any]:
    left = {row["question_id"]: row for row in before.get("items", [])}
    right = {row["question_id"]: row for row in after.get("items", [])}
    common = sorted(left.keys() & right.keys())
    correct_before = [left[q].get("correct") is True for q in common]
    correct_after = [right[q].get("correct") is True for q in common]
    b = sum(a and not z for a, z in zip(correct_before, correct_after))
    c = sum(not a and z for a, z in zip(correct_before, correct_after))
    differences = [float(z) - float(a) for a, z in zip(correct_before, correct_after)]
    acc_a = sum(correct_before) / len(common) if common else None
    acc_b = sum(correct_after) / len(common) if common else None
    correct_transition: Counter[str] = Counter()
    error_transition: Counter[str] = Counter()
    changed: list[dict[str, Any]] = []
    question_rows: list[dict[str, Any]] = []
    for q in common:
        old, new = left[q], right[q]
        old_ok, new_ok = old.get("correct") is True, new.get("correct") is True
        correct_transition[f"{'correct' if old_ok else 'wrong'}→{'correct' if new_ok else 'wrong'}"] += 1
        error_transition[f"{old.get('attribution', 'unknown')}→{new.get('attribution', 'unknown')}"] += 1
        transition = "fixed" if not old_ok and new_ok else "regressed" if old_ok and not new_ok else "unchanged"
        question_rows.append({"question_id": q, "transition": transition,
                              "before_correct": old_ok, "after_correct": new_ok,
                              "before_attribution": old.get("attribution"),
                              "after_attribution": new.get("attribution")})
        if old_ok != new_ok or old.get("attribution") != new.get("attribution"):
            changed.append({"question_id": q, "before_correct": old_ok, "after_correct": new_ok,
                            "before_attribution": old.get("attribution"), "after_attribution": new.get("attribution")})
    bootstrap = paired_bootstrap_ci(differences, reps=3000, seed=seed) if differences else None
    return {
        "n": len(common), "before_accuracy": acc_a, "after_accuracy": acc_b,
        "accuracy_delta": (acc_b - acc_a) if acc_a is not None and acc_b is not None else None,
        "before_accuracy_ci95": list(wilson_ci(sum(correct_before), len(common))) if common else None,
        "after_accuracy_ci95": list(wilson_ci(sum(correct_after), len(common))) if common else None,
        "paired_accuracy_delta_ci95": list(bootstrap) if bootstrap else None,
        "mcnemar": {"b_before_correct_after_wrong": b, "c_before_wrong_after_correct": c,
                     "p_value_exact": mcnemar_exact_p_value(b, c)},
        "correctness_transitions": dict(correct_transition), "attribution_transitions": dict(error_transition),
        "question_transitions": question_rows, "changed_questions_first": changed,
        "only_before": sorted(left.keys() - right.keys()),
        "only_after": sorted(right.keys() - left.keys()),
    }
