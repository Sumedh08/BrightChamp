import pandas as pd
import pytest

from scoring import MODEL_KEYS, fit_estimator
from validation import (evaluate_candidates, monthly_opportunity, refit_deployment,
                        select_estimator, split_evaluation)


def test_june_slot_cutoff_and_no_future_outcome_leak(history):
    june, july, excluded = split_evaluation(history)
    assert len(june) == 1499
    assert len(july) == 1608
    assert excluded == 122
    assert june.demo_scheduled_at.lt("2026-07-01").all()
    assert june.created_at.ge("2026-06-01").all()
    assert june.created_at.lt("2026-07-01").all()
    changed = history.copy()
    outside = ~changed.index.isin(june.index)
    changed.loc[outside, "joined"] = 1 - changed.loc[outside, "joined"]
    corrected, _, _ = split_evaluation(changed)
    for kind in MODEL_KEYS:
        assert fit_estimator(june, kind) == fit_estimator(corrected, kind)


def test_slot_exactly_july_start_excluded(history):
    single = history.iloc[:1].copy()
    single["created_at"] = pd.Timestamp("2026-06-30 12:00")
    single["demo_scheduled_at"] = pd.Timestamp("2026-07-01")
    augmented = pd.concat([history, single], ignore_index=True)
    june, _, excluded = split_evaluation(augmented)
    assert len(june) == 1499
    assert excluded == 123


def test_deployment_refit_preserves_holdout_and_class(history):
    evaluation = evaluate_candidates(history)
    frozen = evaluation.comparison.copy(deep=True)
    models = evaluation.evaluation_models.copy()
    deployment = refit_deployment(history, evaluation)
    assert deployment.kind == evaluation.selected_kind
    assert deployment.fit_rows == 3229
    assert deployment.global_counts == {"fast": (1944, 1457), "late": (1285, 603)}
    assert deployment.purpose.startswith("deployment")
    assert all(m.fit_rows == 1499 and m.k == 50 for m in models.values())
    pd.testing.assert_frame_equal(frozen, evaluation.comparison)
    assert evaluation.evaluation_models == models


def test_sensitivity_does_not_change_official_result(history):
    evaluation = evaluate_candidates(history)
    frozen = evaluation.comparison.copy(deep=True)
    fit_estimator(history, "geography_source", 0, purpose="sensitivity only")
    pd.testing.assert_frame_equal(evaluation.comparison, frozen)


def test_holdout_metrics_match_independent_june_rate_calculation(history):
    june, july, _ = split_evaluation(history)
    evaluation = evaluate_candidates(history)
    rates = june.groupby("cohort").joined.mean()
    predictions = july.cohort.map(rates).astype(float)
    expected_brier = ((predictions - july.joined) ** 2).mean()
    row = evaluation.comparison.set_index("model").loc["global"]
    assert row.brier == pytest.approx(expected_brier)
    for cohort in ["fast", "late"]:
        expected_error = rates[cohort] - july.loc[july.cohort.eq(cohort), "joined"].mean()
        assert row[f"{cohort}_calibration_error"] == pytest.approx(expected_error)


def candidates(briers):
    return pd.DataFrame({"model": list(MODEL_KEYS), "brier": briers,
                         "fast_calibration_error": [0., 0., 0., 0.],
                         "late_calibration_error": [0., 0., 0., 0.]})


@pytest.mark.parametrize("briers,winner", [([.2, .199, .199, .199], "global"),
    ([.2, .19, .18, .17], "source"), ([.2, .199, .19, .18], "geography"),
    ([.2, .199, .199, .19], "geography_source")])
def test_predeclared_simplicity_rule(briers, winner):
    assert select_estimator(candidates(briers))[0] == winner


def test_calibration_guardrail_and_zero_brier():
    frame = candidates([.2, .18, .2, .2])
    frame.loc[frame.model.eq("source"), "fast_calibration_error"] = .02
    assert select_estimator(frame)[0] == "global"
    assert select_estimator(candidates([0, 0, 0, 0]))[0] == "global"


def test_case_monthly_scenarios(history):
    result = monthly_opportunity(history)
    assert result["full_observed_gap_value"] == pytest.approx(1898333.23, abs=.01)
    assert result["base_case_value"] == pytest.approx(949166.61, abs=.01)
