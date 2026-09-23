"""Transparent attendance estimators and a deterministic capacity policy."""
from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

MODEL_KEYS = {"global": (), "source": ("lead_source",), "geography": ("geography",),
              "geography_source": ("geography", "lead_source")}
MODEL_LABELS = {"global": "Global-only", "source": "Lead source", "geography": "Geography",
                "geography_source": "Geography × lead source"}
OFFICIAL_K = 50


@dataclass(frozen=True)
class Estimator:
    kind: str
    k: float
    purpose: str
    global_counts: dict  # cohort -> (observations, joins)
    segment_counts: dict  # (normalized segment tuple, cohort) -> (observations, joins)
    fit_rows: int


@dataclass(frozen=True)
class CommercialAssumptions:
    conversion_given_joined: float = 362 / 2060
    revenue_per_conversion: float = 60000.0
    recovery_factor: float = 0.50

    def __post_init__(self):
        for name, low, high in [("conversion_given_joined", 0, 1),
                                ("recovery_factor", 0, 1),
                                ("revenue_per_conversion", 0, math.inf)]:
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid {name}.")


def _key(row, keys):
    return tuple(str(row[key]).strip().casefold() for key in keys)


def fit_estimator(frame: pd.DataFrame, kind: str = "global", k: float = OFFICIAL_K,
                  purpose: str = "evaluation") -> Estimator:
    if kind not in MODEL_KEYS or not math.isfinite(k) or k < 0:
        raise ValueError("Unknown estimator or invalid shrinkage strength.")
    scheduled = frame.loc[frame.cohort.isin(["fast", "late"])].copy()
    global_counts = {}
    for cohort in ("fast", "late"):
        values = scheduled.loc[scheduled.cohort.eq(cohort), "joined"]
        if values.empty:
            raise ValueError(f"Cannot fit: no {cohort} calibration observations.")
        global_counts[cohort] = (len(values), int(values.sum()))
    segments = {}
    keys = MODEL_KEYS[kind]
    if keys:
        for row in scheduled.to_dict("records"):
            key = (_key(row, keys), row["cohort"])
            n, joins = segments.get(key, (0, 0))
            segments[key] = (n + 1, joins + int(row["joined"]))
    return Estimator(kind, k, purpose, global_counts, segments, len(scheduled))


def estimate_rates(frame: pd.DataFrame, model: Estimator) -> pd.DataFrame:
    records = []
    keys = MODEL_KEYS[model.kind]
    columns = [f"{prefix}{c}" for c in ("fast", "late")
               for prefix in ("p_", "n_", "joins_", "raw_", "global_", "weight_", "fallback_")]
    for row in frame.to_dict("records"):
        record = {}
        for cohort in ("fast", "late"):
            gn, gj = model.global_counts[cohort]
            global_rate = gj / gn
            n, joined = (model.segment_counts.get((_key(row, keys), cohort), (0, 0))
                         if keys else (gn, gj))
            fallback = bool(keys and n == 0)
            weight = (n / (n + model.k) if n else 0.0) if keys else 1.0
            raw = joined / n if n else float("nan")
            rate = weight * raw + (1 - weight) * global_rate if n else global_rate
            record.update({f"p_{cohort}": rate, f"n_{cohort}": n,
                           f"joins_{cohort}": joined, f"raw_{cohort}": raw,
                           f"global_{cohort}": global_rate, f"weight_{cohort}": weight,
                           f"fallback_{cohort}": fallback})
        records.append(record)
    return pd.DataFrame(records, index=frame.index, columns=columns)


def score_live_queue(frame: pd.DataFrame, model: Estimator, as_of: pd.Timestamp,
                     commercial: CommercialAssumptions | None = None) -> pd.DataFrame:
    """Input must have passed load_live. Excluded rows retain reasons, not values."""
    commercial = commercial or CommercialAssumptions()
    clock = pd.Timestamp(as_of)
    if clock.tzinfo is None:
        raise ValueError("as_of must be timezone aware after input validation.")
    result = frame.copy().reset_index(drop=True)
    result["lead_age_hours"] = (clock - result.created_at).dt.total_seconds() / 3600
    if result.lead_age_hours.lt(0).any():
        raise ValueError("Creation cannot follow as_of.")
    result["deadline"] = result.created_at + pd.Timedelta(hours=48)
    result["hours_remaining"] = 48 - result.lead_age_hours
    at_risk = result.demo_scheduled_at.isna() | result.demo_delay_hours.ge(48)
    result["eligible"] = (result.lead_status.eq("open") & result.lead_age_hours.lt(48) & at_risk)
    result["queue_state"] = "Excluded"
    result["reason"] = "Current status: " + result.lead_status
    open_mask = result.lead_status.eq("open")
    protected = open_mask & ~at_risk
    result.loc[protected, "queue_state"] = "Inside window"
    result.loc[protected, "reason"] = "Already scheduled inside 48h; attendance not inferred."
    stale = protected & result.demo_scheduled_at.le(clock)
    result.loc[stale, "queue_state"] = "Status review"
    result.loc[stale, "reason"] = "Inside-window slot has passed; confirm current status."
    breached = open_mask & at_risk & result.lead_age_hours.ge(48)
    result.loc[breached, "queue_state"] = "Breached"
    result.loc[breached, "reason"] = "48h window expired; handle separately as rescue/escalation."
    eligible = result.eligible
    result.loc[eligible, "queue_state"] = "Eligible"
    result.loc[eligible & result.demo_scheduled_at.isna(), "reason"] = "Open, unscheduled, still inside 48h."
    result.loc[eligible & result.demo_scheduled_at.notna(), "reason"] = "Open, late slot, still time to offer pull-forward."
    result["tier"] = "—"
    result["tier_order"] = 99
    for name, order, lower, upper in [("Expiring", 0, 0, 6), ("Soon", 1, 6, 24),
                                      ("Standard", 2, 24, 48)]:
        mask = eligible & result.hours_remaining.gt(lower) & result.hours_remaining.le(upper)
        result.loc[mask, ["tier", "tier_order"]] = [name, order]
    rates = estimate_rates(result, model)
    result = pd.concat([result, rates], axis=1)
    result["raw_attendance_gap"] = result.p_fast - result.p_late
    result["nonnegative_attendance_gap"] = result.raw_attendance_gap.clip(lower=0)
    # Historical estimates exist for every segment, but ineligible rows carry no recovery claim.
    result["observational_value_ceiling"] = (
        result.nonnegative_attendance_gap * commercial.conversion_given_joined
        * commercial.revenue_per_conversion
    ).where(eligible, 0.0)
    result["base_case_recoverable_value"] = result.observational_value_ceiling * commercial.recovery_factor
    result["scenario_additional_joins"] = (
        result.nonnegative_attendance_gap * commercial.recovery_factor
    ).where(eligible, 0.0)
    result["scenario_additional_conversions"] = (
        result.scenario_additional_joins * commercial.conversion_given_joined
    )
    result["recommendation"] = result.reason
    result.loc[eligible & result.demo_scheduled_at.isna(), "recommendation"] = "Offer a slot starting before the deadline."
    result.loc[eligible & result.demo_scheduled_at.notna(), "recommendation"] = "Offer pull-forward to a slot before the deadline."
    return result


def allocate_capacity(scored: pd.DataFrame, capacity: int) -> pd.DataFrame:
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("Capacity must be a nonnegative integer.")
    eligible = scored.loc[scored.eligible].sort_values(
        ["tier_order", "base_case_recoverable_value", "hours_remaining", "lead_id"],
        ascending=[True, False, True, True], kind="stable"
    ).copy()
    eligible["rank"] = range(1, len(eligible) + 1)
    eligible["allocated"] = eligible["rank"].le(capacity)
    excluded = scored.loc[~scored.eligible].sort_values("lead_id").copy()
    excluded["rank"] = pd.NA
    excluded["allocated"] = False
    result = pd.concat([eligible, excluded], ignore_index=True)
    result["rank"] = result["rank"].astype("Int64")
    return result
