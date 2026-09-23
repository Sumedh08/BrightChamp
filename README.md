# BrightChamps 48H Demo Recovery Optimizer

A capacity-aware recovery policy that protects the most time-sensitive <48h
opportunities first and prioritizes estimated economic value within each urgency tier.

This local take-home prototype produces a ranked allocation queue, lead explanations,
an auditable model comparison, and downloadable decisions. It uses transparent cohort
rates and empirical shrinkage, with no black-box ML or external services.

## Run locally

Python 3.11–3.13 recommended; verified on Python 3.13. Dependencies are pinned to the
versions used for verification. From this directory:

```bash
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
pytest
streamlit run app.py
```

If shell aliases are unavailable, use `python -m pip`, `python -m pytest`, and
`python -m streamlit run app.py`. Open the local URL printed by Streamlit.
All processing happens locally; no database or credentials are needed.

## Two-minute demonstration

1. Start the app. It opens **Operational Queue → Use synthetic demo**.
2. Keep the displayed reference time **2026-08-03 12:00:00 UTC** and capacity **4**.
   Every `DEMO-*` row is invented. Historical June/July leads are never used as live rows.
3. Read **Recommended actions**: allocated and waiting leads share one table in priority order.
   Open **Inspect a lead** for the full calculation, or **Other leads and escalations** for
   excluded statuses. Change capacity to see the recommendation change. Commercial controls
   and the editable demo clock are under **Advanced assumptions** in the sidebar.
4. Switch to **Historical Evidence** for attendance, the June/July chart and the compact
   model comparison. Expand **Technical validation** for the corrected June cutoff,
   calibration, coverage, sensitivity and evaluation-versus-deployment parameters.
5. Download the queue and model/assumption receipt from **Downloads** on Operational Queue.
   The official comparison download is in Historical Evidence → Technical validation.

The main queue displays only seven operator-facing columns; probabilities, segment counts,
fallback status and formulas remain in the lead inspection. The full observed-gap scenario,
batch joins/conversions and policy details are in **How recommendations are calculated**.
**Limitations and assumptions** preserves the detailed caveats in both modes. The pilot
plan appears near the bottom of Historical Evidence under **How we would validate this in production**.
The historical funnel and revenue sensitivity chart are in **Historical funnel and scenario calculation**.

The sample has 10 eligible leads, including exact tier boundaries and an unseen segment.
It also includes protected, breached, joined, completed, converted, cancelled, and stale
open-status examples. At capacity 4 with the current global model, the deterministic
allocation is `DEMO-001`, `DEMO-018`, `DEMO-002`, `DEMO-003`.

## Historical evidence and methodological boundaries

`brightchamps.csv` is historical evidence only. All historical timestamps are treated
as supplied for within-record differences. `demo_scheduled_at` is the **demo slot time**,
not the time the booking was made. A slot exactly 48 hours after creation is late.

The descriptive funnel retains all 5,000 rows: 3,229 scheduled, 2,060 joined,
1,786 completed and 362 converted. Unscheduled historical leads enter the funnel,
but not fast/late attendance estimation.

### 1. Evaluation fitting

Official calibration uses only scheduled outcomes from:

```text
created_at >= 2026-06-01
created_at <  2026-07-01
demo_scheduled_at < 2026-07-01
```

This yields **1,499** calibration rows: fast **707 / 936**, late **262 / 563**.
The **122** June-created leads with July slots remain in descriptive analysis but cannot
influence June-fitted parameters. Null slots are excluded. The cutoff proxies attendance
availability using the scheduled slot; actual outcome recording timestamps are absent.

Fit four candidate classes: global-only, source, geography, geography × source.
For segmented estimators, separately in each timing cohort:

```text
adjusted_probability = (segment_joins + 50 × global_probability) / (segment_n + 50)
```

Official `k = 50` is fixed, never tuned using July. Unseen segments or a segment with
no observations in one cohort use the corresponding global probability. Sparse
observed cells shrink continuously. No hierarchical fallback or small-cell deletion
is used. Model category keys trim whitespace and ignore letter case.

### 2. July out-of-time holdout evaluation / model-selection period

Evaluate on the **1,608 July-created scheduled leads**, using their observed timing
cohort and June-fitted probability. There is no additional split. Compare Brier score,
calibration, fallback and sample coverage, and supported segment-gap stability.

The predeclared qualifying rule requires both:

- At least **2% relative Brier improvement** over global-only.
- Absolute calibration-in-the-large no more than **1 percentage point worse** than
  global-only in either timing cohort.

Choose the first qualifying model in the fixed order source → geography → geography ×
source. Otherwise choose global-only. The thresholds are engineering guardrails, not
significance tests. Coverage and stability are reported diagnostics, not post-hoc overrides.

The corrected bundled-data comparison is shown below for reference. The app calculates
it from the CSV on load; these values are not constants used for selection.

| Estimator | July Brier ↓ | Fast calibration error | Late calibration error |
|---|---:|---:|---:|
| Global-only | 0.213918 | +1.318 pp | −1.283 pp |
| Lead source | 0.214089 | +1.621 pp | −1.545 pp |
| Geography | 0.214513 | +1.333 pp | −1.337 pp |
| Geography × source | 0.214659 | +1.773 pp | −1.550 pp |

Calibration error is predicted minus observed attendance. **Global-only wins**: none
of the segmented candidates improves Brier score. This is an acceptable product outcome;
the prototype does not force segmentation to create artificial differentiation.

Reliability uses fixed probability bins of width 0.2. Empty bins are omitted. Stability
compares raw June/July gaps only in cells with at least 10 rows per timing cohort in each
period, and reports the share of July covered. Small supported counts are visible.

July participates in choosing the model. Two months provide temporal robustness evidence,
**not independent final validation of the selected model**. Observed-cohort prediction
quality also does not validate an individual causal effect of moving a slot.

### 3. Deployment refit

After selecting the class, refit **only that selected class** with fixed `k = 50` on
all **3,229 historical scheduled leads**. Operational scoring uses this deployment model.
The separate June evaluation models and July diagnostic tables are retained unchanged.

With global-only, deployment probabilities are:

- Fast: **1,457 / 1,944 = 74.95%**.
- Late: **603 / 1,285 = 46.93%**.

The `k` controls in Historical Evidence → **Advanced assumptions** explore separate June
segment estimates; results appear in **Technical validation**. Sensitivity cannot
change official selection, deployment parameters, or July metrics.

## Scenario equations

Default commercial assumptions are the case-wide `362 / 2060` conversion-given-joined
rate, ₹60,000 revenue per conversion, and 50% observed-gap recovery. The pooled commercial
rate is used only in monetary calculations; it does not enter attendance fitting or selection.

```text
raw_gap = P_fast − P_late
value_gap = max(raw_gap, 0)
full_observed_gap_value = value_gap × (362 / 2060) × 60000
base_case_recoverable_value = full_observed_gap_value × recovery_factor
```

The calculation API retains the originally specified field name
`observational_value_ceiling` for the 100% formula. The UI and queue download label it
**Full observed-gap scenario (100%)**. It is not a proven causal upper bound.
At default commercial assumptions the label is **Base-case scenario (50% observed-gap recovery)**;
non-default settings are labelled a selected scenario.

The descriptive monthly calculation uses pooled fast/late rates and `1,285 / 2` late
leads per month. At default economics it produces approximately **₹18.98 lakh/month**
for full observed-gap recovery and **₹9.49 lakh/month** at 50%. This pooled business-case
calculation is separate from June-fit evaluation and from an operational batch total.

Constant positive commercial assumptions scale values but do not change economic
ranking. No ₹900 acquisition-cost deduction is made because acquisition is already paid
for. Negative observed gaps remain visible in evidence, but valuation is floored at zero.

For an allocated batch, scenario additional joins are the sum of `value_gap × recovery_factor`;
scenario conversions multiply this by conversion-given-joined. These are conditional
scenario expectations, not measured outcomes. For unscheduled leads, applying this gap
assumes contactability, agreement and successful scheduling; the dataset cannot estimate
the probability of those steps. Parent preference and operational capacity may explain
part of the historical attendance association.

## Live CSV contract

Use `live_queue_template.csv` (also available in the sidebar's **CSV templates**) for a separate current CRM snapshot. Do not upload the
historical dataset or infer booking state from historical outcomes.

| Column | Rule |
|---|---|
| `lead_id` | Required, unique, nonblank string |
| `lead_source` | Required string; unseen values supported |
| `geography` | Required string; unseen values supported |
| `created_at` | Required `YYYY-MM-DD HH:MM[:SS]` (space or T separator) |
| `demo_scheduled_at` | Required column, blank if unscheduled; same timestamp format |
| `lead_status` | `open`, `joined`, `completed`, `converted`, or `cancelled` |
| `parent_timezone` | Optional, informational only |

Use blank cells for missing slots, rather than a literal `NULL` or `N/A` string.
Scheduled state is inferred from `demo_scheduled_at`. Historical `demo_joined`,
`demo_completed`, and `converted` outcome columns are rejected in operational mode.

Every input timestamp and `as_of` must use **one consistent CRM/system timezone**.
Set the IANA timezone in the sidebar's **Advanced assumptions**, default UTC. Do not mix per-parent local times or
append offsets. The parser localizes the input to the configured system timezone and
normalizes to UTC before arithmetic. Ambiguous/nonexistent DST times are rejected;
export the snapshot in UTC in those cases. `parent_timezone` never changes time arithmetic.
Output deadlines and exports use UTC. Slot compliance concerns its start time.

Errors in required fields, IDs, statuses or timestamps block the entire allocation and
show CSV row numbers. Rows with creation after `as_of` or a slot before creation are
invalid. A valid header-only CSV produces an empty queue.

## Eligibility and allocation

```text
eligible = lead_status == "open"
           AND lead_age_hours < 48
           AND (slot is null OR demo_delay_hours >= 48)
```

Joined/completed/converted/cancelled leads never enter allocation. Open leads with fast
slots are excluded as already inside the window; a passed fast slot is flagged for status
review. This does not imply attendance. Breached open leads appear separately for rescue,
with no claim that the lost window can be preserved.

| Tier | Remaining time |
|---|---|
| Expiring | `0 < hours_remaining <= 6` |
| Soon | `6 < hours_remaining <= 24` |
| Standard | `24 < hours_remaining <= 48` |

Ordering is tier first, then selected scenario value descending, remaining time ascending,
and lead ID ascending. Allocate up to the nonnegative integer capacity. All eligible rows
remain in the queue; zero-value scenarios still follow the SLA policy and explicitly carry
no estimated financial benefit. Input order never affects the result.

There is no urgency multiplier. A lower-value expiring lead can precede a higher-value
standard lead, so the policy is not claimed to mathematically maximize expected revenue.
With the selected global-only estimator, all eligible values are equal and deadlines drive
the order within tiers.

Capacity is a count, not a calendar. Operations must confirm an acceptable slot starting
strictly before each lead's deadline. Recommendations do not book appointments, reserve
rep time, or force parents to reschedule.

## Decision trail and prospective pilot

Download the full queue (including exclusions), a JSON receipt of model selection and
assumptions, and the official model comparison. The receipt includes input hashes,
reference time, selected model, evaluation/deployment fit counts, economics and capacity.
The queue export contains blank fields for operator decision, delay/override reason,
offered slot, parent acceptance and actual slot; complete these in the operations workflow.
The app does not save uploads or decisions to disk. User inputs are kept only in the app
session; only the bundled historical preparation is cached.

For a two-week pilot, record reasons including parent preference, unavailable capacity,
rep availability, timezone constraint, unreachable and other. Prefer randomized offers
or a defined concurrent control, keeping original assignment groups in reporting.
Track attendance, completed demos, mature conversions and revenue per acquired lead;
guardrails include reschedules, cancellations, rep utilization and parent friction.
Conversions may need follow-up beyond the two-week intervention.

## Code layout and verification

- `data.py`: separate CSV contracts, validation and timestamps.
- `scoring.py`: estimators, explanations, valuation and allocation.
- `validation.py`: corrected June split, July selection, separate deployment refit and history summaries.
- `app.py`: Streamlit views and downloads, consuming the calculation layer.
- `tests/`: formula, cutoff, refit isolation, schema, policy and UI regression tests.
- `ADR.md`: ADR-001 with the accepted decisions and rejected alternatives.
- `CONTEXT.md` and `SQl_terminal_bc.txt`: preserved original case context and SQL evidence.

Later approved methodological corrections in this README and ADR supersede older
prototype suggestions in `CONTEXT.md`, including urgency multipliers, fixed segmentation,
historical live simulation, and causal-upper-bound wording. The source evidence is preserved.

Run `pytest` for the focused test suite. Tests cover the cutoff, all four selection paths,
deployment isolation, holdout metrics, shrinkage/fallback, nonnegative values, exact
boundaries, statuses, deterministic capacity, timezones and Streamlit mode switching.

No database, CRM API, authentication, calendar engine, automatic outreach, black-box ML,
or cloud deployment is required for this take-home.
