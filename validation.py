"""Corrected June evaluation fitting, July model selection, separate deployment refit."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from scoring import (CommercialAssumptions, Estimator, MODEL_KEYS, OFFICIAL_K,
                     estimate_rates, fit_estimator)

JUNE_START = pd.Timestamp("2026-06-01")
JULY_START = pd.Timestamp("2026-07-01")
AUGUST_START = pd.Timestamp("2026-08-01")


@dataclass(frozen=True)
class EvaluationResult:
    comparison: pd.DataFrame
    diagnostics: pd.DataFrame
    reliability: pd.DataFrame
    stability: pd.DataFrame
    stability_coverage: pd.DataFrame
    evaluation_models: dict[str, Estimator]
    selected_kind: str
    calibration_rows: int
    holdout_rows: int
    excluded_june_slots: int


def split_evaluation(history: pd.DataFrame):
    scheduled = history.demo_scheduled_at.notna()
    june_created = history.created_at.ge(JUNE_START) & history.created_at.lt(JULY_START)
    calibration = history.loc[june_created & scheduled & history.demo_scheduled_at.lt(JULY_START)].copy()
    july = history.loc[scheduled & history.created_at.ge(JULY_START)
                       & history.created_at.lt(AUGUST_START)].copy()
    excluded = int((june_created & scheduled & history.demo_scheduled_at.ge(JULY_START)).sum())
    if july.empty or set(july.cohort) != {"fast", "late"}:
        raise ValueError("July holdout needs scheduled observations in both timing cohorts.")
    return calibration, july, excluded


def _predictions(frame, model):
    rates = estimate_rates(frame, model)
    fast = frame.cohort.eq("fast")
    result = frame.copy()
    result["prediction"] = rates.p_fast.where(fast, rates.p_late)
    result["support_n"] = rates.n_fast.where(fast, rates.n_late)
    result["fallback"] = rates.fallback_fast.where(fast, rates.fallback_late).astype(bool)
    return result


def _metric(frame):
    predicted, observed = frame.prediction.mean(), frame.joined.mean()
    return {"n": len(frame), "brier": float(((frame.prediction - frame.joined) ** 2).mean()),
            "predicted_join_rate": float(predicted), "observed_join_rate": float(observed),
            "calibration_error": float(predicted - observed),
            "fallback_share": float(frame.fallback.mean()),
            "low_support_share": float(frame.support_n.lt(10).mean())}


def select_estimator(comparison: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Fixed guardrails, followed by fixed simplicity order. Never tuned on July."""
    table = comparison.copy()
    global_row = table.loc[table.model.eq("global")].iloc[0]
    baseline = global_row.brier
    table["relative_brier_improvement"] = ((baseline - table.brier) / baseline if baseline > 0 else 0.0)
    table["calibration_pass"] = (
        table.fast_calibration_error.abs().le(abs(global_row.fast_calibration_error) + .01)
        & table.late_calibration_error.abs().le(abs(global_row.late_calibration_error) + .01)
    )
    table["qualifies"] = (table.model.ne("global") & table.relative_brier_improvement.ge(.02)
                           & table.calibration_pass)
    selected = "global"
    for kind in ("source", "geography", "geography_source"):
        if bool(table.loc[table.model.eq(kind), "qualifies"].iloc[0]):
            selected = kind
            break
    table["selected"] = table.model.eq(selected)
    return selected, table


def _stability(june, july, kind):
    keys = list(MODEL_KEYS[kind])
    a, b = june.copy(), july.copy()
    if not keys:
        keys = ["segment"]
        a["segment"] = b["segment"] = "All leads"
    else:
        for key in keys:
            a[key] = a[key].str.casefold()
            b[key] = b[key].str.casefold()
    stats = []
    for frame, period in [(a, "june"), (b, "july")]:
        pivot = frame.groupby(keys + ["cohort"]).joined.agg(["size", "mean"]).unstack("cohort")
        pivot.columns = [f"{period}_{metric}_{cohort}" for metric, cohort in pivot.columns]
        stats.append(pivot)
    merged = stats[0].join(stats[1], how="outer")
    count_cols = [f"{p}_size_{c}" for p in ("june", "july") for c in ("fast", "late")]
    comparable = merged[count_cols].fillna(0).ge(10).all(axis=1)
    detail = merged.loc[comparable].copy()
    detail["june_gap"] = detail.june_mean_fast - detail.june_mean_late
    detail["july_gap"] = detail.july_mean_fast - detail.july_mean_late
    detail["same_direction"] = detail.june_gap.map(lambda v: (v > 0) - (v < 0)).eq(
        detail.july_gap.map(lambda v: (v > 0) - (v < 0)))
    detail["model"] = kind
    coverage = {"model": kind, "comparable_segments": len(detail),
                "july_rows_covered": int(detail[["july_size_fast", "july_size_late"]].sum().sum()),
                "july_coverage_share": float(detail[["july_size_fast", "july_size_late"]].sum().sum() / len(july)),
                "same_direction_share": float(detail.same_direction.mean()) if len(detail) else float("nan")}
    return detail.reset_index(), coverage


def evaluate_candidates(history: pd.DataFrame) -> EvaluationResult:
    june, july, excluded = split_evaluation(history)
    comparisons, diagnostics, reliability, stability, coverage, models = [], [], [], [], [], {}
    for kind in MODEL_KEYS:
        model = fit_estimator(june, kind, OFFICIAL_K, purpose="evaluation: June slots before July 1")
        models[kind] = model
        predictions = _predictions(july, model)
        overall = _metric(predictions)
        row = {"model": kind, **overall}
        for cohort in ("fast", "late"):
            group = predictions.loc[predictions.cohort.eq(cohort)].copy()
            metric = _metric(group)
            diagnostics.append({"model": kind, "cohort": cohort, **metric})
            row[f"{cohort}_calibration_error"] = metric["calibration_error"]
            group["probability_bin"] = pd.cut(group.prediction, [0, .2, .4, .6, .8, 1], include_lowest=True)
            for bin_label, subset in group.groupby("probability_bin", observed=True):
                reliability.append({"model": kind, "cohort": cohort, "bin": str(bin_label),
                                    "n": len(subset), "predicted": subset.prediction.mean(),
                                    "observed": subset.joined.mean()})
        comparisons.append(row)
        detail, summary = _stability(june, july, kind)
        stability.append(detail)
        coverage.append(summary)
    selected, table = select_estimator(pd.DataFrame(comparisons))
    return EvaluationResult(table, pd.DataFrame(diagnostics), pd.DataFrame(reliability),
                            pd.concat(stability, ignore_index=True), pd.DataFrame(coverage),
                            models, selected, len(june), len(july), excluded)


def refit_deployment(history: pd.DataFrame, evaluation: EvaluationResult) -> Estimator:
    """Refit only the selected class; never recompute or mutate holdout diagnostics."""
    return fit_estimator(history, evaluation.selected_kind, OFFICIAL_K,
                         purpose="deployment: full historical scheduled dataset")


def cohort_summary(history: pd.DataFrame) -> pd.DataFrame:
    return history.loc[history.cohort.notna()].groupby(
        ["creation_month", "cohort"], as_index=False
    ).agg(scheduled=("joined", "size"), joined=("joined", "sum"),
          join_rate=("joined", "mean"), converted=("conversion", "sum"))


def monthly_opportunity(history: pd.DataFrame, commercial: CommercialAssumptions | None = None) -> dict:
    commercial = commercial or CommercialAssumptions()
    fast = history.loc[history.cohort.eq("fast"), "joined"]
    late = history.loc[history.cohort.eq("late"), "joined"]
    if fast.empty or late.empty:
        raise ValueError("Both timing cohorts are required.")
    gap = max(float(fast.mean() - late.mean()), 0)
    full_joins = len(late) / 2 * gap
    full_value = full_joins * commercial.conversion_given_joined * commercial.revenue_per_conversion
    return {"fast_rate": float(fast.mean()), "late_rate": float(late.mean()),
            "late_leads_per_month": len(late) / 2, "full_additional_joins": full_joins,
            "full_observed_gap_value": full_value,
            "base_case_value": full_value * commercial.recovery_factor}
