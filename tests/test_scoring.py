import pandas as pd
import pytest

from scoring import (CommercialAssumptions, allocate_capacity, estimate_rates,
                     fit_estimator, score_live_queue)


def toy_model(kind="source", k=50):
    # Fast: A 1/2, B 3/3 -> global 4/5. Late: A 0/1, B 1/3 -> global 1/4.
    frame = pd.DataFrame({"lead_source": ["A"] * 2 + ["B"] * 3 + ["A"] + ["B"] * 3,
                          "cohort": ["fast"] * 5 + ["late"] * 4,
                          "joined": [1, 0, 1, 1, 1, 0, 1, 0, 0]})
    return fit_estimator(frame, kind, k)


def test_shrinkage_hand_calculation_and_unseen():
    rates = estimate_rates(pd.DataFrame({"lead_source": ["A", "unknown"]}), toy_model())
    assert rates.p_fast.iloc[0] == pytest.approx((1 + 50 * .8) / 52)
    assert rates.p_late.iloc[0] == pytest.approx(50 * .25 / 51)
    assert rates.p_fast.iloc[1] == .8
    assert rates.p_late.iloc[1] == .25
    assert rates.fallback_fast.iloc[1]


def test_zero_k_and_missing_one_cohort():
    frame = pd.DataFrame({"lead_source": ["A", "B"], "cohort": ["fast", "late"], "joined": [1, 0]})
    rates = estimate_rates(pd.DataFrame({"lead_source": ["A", "C"]}), fit_estimator(frame, "source", 0))
    assert rates.p_fast.tolist() == [1, 1]
    assert rates.p_late.tolist() == [0, 0]
    assert rates.fallback_late.all()


def test_missing_global_cohort_fails():
    with pytest.raises(ValueError):
        fit_estimator(pd.DataFrame({"cohort": ["fast"], "joined": [1]}))


def test_statuses_boundaries_and_actions(live, clock, history):
    result = score_live_queue(live, fit_estimator(history), clock).set_index("lead_id")
    assert result.eligible.sum() == 10
    assert result.loc["DEMO-003", "tier"] == "Expiring"  # Exactly six hours remaining.
    assert result.loc["DEMO-006", "tier"] == "Soon"  # Exactly 24 hours.
    assert result.loc["DEMO-008", "tier"] == "Standard"  # Age zero.
    assert result.loc["DEMO-010", "queue_state"] == "Breached"  # Exactly age 48.
    assert result.loc["DEMO-017", "eligible"]  # Slot exactly 48 hours from creation.
    assert result.loc["DEMO-016", "queue_state"] == "Status review"
    for identity in ["DEMO-009", "DEMO-012", "DEMO-013", "DEMO-014", "DEMO-015"]:
        assert not result.loc[identity, "eligible"]
        assert result.loc[identity, "base_case_recoverable_value"] == 0


@pytest.mark.parametrize("capacity", [0, 1, 4, 10, 100])
def test_capacity_and_deterministic_shuffle(live, clock, history, capacity):
    scored = score_live_queue(live, fit_estimator(history), clock)
    a = allocate_capacity(scored, capacity)
    b = allocate_capacity(scored.sample(frac=1, random_state=71), capacity)
    assert a.lead_id.tolist() == b.lead_id.tolist()
    assert a.allocated.sum() == min(capacity, 10)
    assert a.loc[a.allocated, "lead_status"].eq("open").all()
    assert a.loc[a.eligible, "lead_id"].tolist()[:2] == ["DEMO-001", "DEMO-018"]


def test_tier_then_value_then_deadline(live, clock, history):
    scored = score_live_queue(live, fit_estimator(history), clock)
    scored.loc[scored.lead_id.eq("DEMO-004"), "base_case_recoverable_value"] = 1e9  # Soon
    scored.loc[scored.lead_id.eq("DEMO-002"), "base_case_recoverable_value"] = 2e4  # Expiring
    result = allocate_capacity(scored, 2)
    assert result.iloc[0].lead_id == "DEMO-002"
    assert "DEMO-004" not in result.loc[result.allocated, "lead_id"].values


def test_values_use_full_rates_and_recovery_factor(live, clock, history):
    model = fit_estimator(history)
    base = score_live_queue(live, model, clock)
    full = score_live_queue(live, model, clock, CommercialAssumptions(recovery_factor=1))
    expected = (1457 / 1944 - 603 / 1285) * (362 / 2060) * 60000
    assert base.observational_value_ceiling.iloc[0] == pytest.approx(expected)
    assert base.base_case_recoverable_value.iloc[0] == pytest.approx(expected * .5)
    pd.testing.assert_series_equal(base.base_case_recoverable_value * 2, full.base_case_recoverable_value)


def test_negative_gap_and_zero_economics(live, clock):
    negative = fit_estimator(pd.DataFrame({"cohort": ["fast", "late"], "joined": [0, 1]}))
    scores = score_live_queue(live, negative, clock)
    assert scores.raw_attendance_gap.eq(-1).all()
    assert scores.base_case_recoverable_value.eq(0).all()
    assert score_live_queue(live, toy_model("global"), clock,
                            CommercialAssumptions(recovery_factor=0)).base_case_recoverable_value.eq(0).all()


@pytest.mark.parametrize("kwargs", [{"recovery_factor": -1}, {"recovery_factor": 1.1},
                                     {"conversion_given_joined": 2}, {"revenue_per_conversion": float("nan")}])
def test_invalid_economics(kwargs):
    with pytest.raises(ValueError):
        CommercialAssumptions(**kwargs)


def test_empty_queue(live, clock, history):
    assert allocate_capacity(score_live_queue(live.iloc[:0], fit_estimator(history), clock), 5).empty


@pytest.mark.parametrize("capacity", [-1, 1.5, True])
def test_invalid_capacity(live, clock, history, capacity):
    with pytest.raises(ValueError):
        allocate_capacity(score_live_queue(live, fit_estimator(history), clock), capacity)
