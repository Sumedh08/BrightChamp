# BrightChamps FDA Case — CONTEXT

## Objective

This repository supports the BrightChamps **Forward Deployed Associate** take-home case.

Current conclusion:

- **Primary leak:** demo attendance deteriorates sharply when the scheduled demo slot is 48+ hours after lead creation.
- **Primary lever:** a 48-hour demo-slot SLA supported by a capacity-aware prioritization system.
- **Prototype:** a runnable **48H Demo Recovery Optimizer** that scores at-risk leads by expected recoverable revenue and recommends which leads should receive scarce near-term demo slots first.
- **Key rejected alternative:** hard rep-by-geography routing looked promising in aggregate but failed out-of-time persistence validation.

---

## 1. Assignment

Dataset: 5,000 anonymized leads from June–July 2026.

Deliverables:

1. **The leak** — Where does the funnel lose the most money, and how much per month?
2. **The lever** — One intervention deployable within two weeks with no engineering sprint; explain chosen vs rejected alternatives.
3. **The build** — A working executable/watchable prototype of one component.
4. **Memo** — One page max covering lever, rupee number, biggest adoption risk, measurement and baseline.

Case economics:

- Revenue per converted customer: **₹60,000**
- Blended marketing cost: **₹900/lead**

---

## 2. Dataset schema

```sql
CREATE TABLE leads (
    lead_id VARCHAR(20) PRIMARY KEY,
    lead_source VARCHAR(50),
    geography VARCHAR(100),
    parent_timezone VARCHAR(100),
    created_at DATETIME,
    demo_scheduled_at DATETIME NULL,
    rep_assigned VARCHAR(50),
    rep_shift VARCHAR(50),
    follow_up_attempts INT,
    demo_joined CHAR(1),
    demo_completed CHAR(1),
    converted CHAR(1)
);
```

### Critical timestamp caveat

`demo_scheduled_at` is the **scheduled demo slot timestamp**, not the timestamp when the booking action occurred.

Use wording like:

> demo scheduled/held for a slot within 48 hours of lead creation

Do **not** claim:

> the demo was booked within 48 hours

because booking-action time is not in the dataset.

---

## 3. Baseline funnel

- Leads: **5,000**
- Demo scheduled: **3,229**
- Demo joined: **2,060**
- Demo completed: **1,786**
- Converted: **362**

Rates:

- Lead → scheduled: **64.58%**
- Scheduled → joined: **63.80%**
- Joined → completed: **86.70%**
- Completed → converted: **20.27%**
- Overall lead → conversion: **7.24%**

Raw drops:

- Lead → scheduled: **1,771**
- Scheduled → joined: **1,169**
- Joined → completed: **274**
- Completed → converted: **1,424**

Data quality checks passed:

- joined without schedule = 0
- completed without joining = 0
- converted without completion = 0

### Monthly stability

June:
- 2,504 leads
- 1,621 scheduled
- 1,030 joined
- 900 completed
- 188 converted
- lead→schedule 64.74%
- schedule→join 63.54%
- join→complete 87.38%
- complete→convert 20.89%

July:
- 2,496 leads
- 1,608 scheduled
- 1,030 joined
- 886 completed
- 174 converted
- lead→schedule 64.42%
- schedule→join 64.05%
- join→complete 86.02%
- complete→convert 19.64%

Interpretation: the major funnel behavior is systemic rather than caused by one anomalous month.

---

## 4. Lead source findings

Overall conversion:

| Source | Leads | Overall conversion |
|---|---:|---:|
| Referral | 276 | 11.23% |
| Organic | 495 | 9.70% |
| Meta | 2,101 | 7.19% |
| Google | 1,197 | 7.10% |
| Affiliate | 448 | 6.03% |
| DSA | 483 | 4.14% |

Completed-demo close rates:

- Referral 30.39%
- Organic 26.52%
- Google 20.43%
- Meta 20.21%
- Affiliate 16.88%
- DSA 11.11%

Important limitation: only **blended CPL = ₹900** is supplied.

Do not recommend shifting marketing spend purely from conversion rate because source/geography-specific CAC, marginal CAC, scale limits and LTV are unknown.

---

## 5. Geography findings

Overall lead conversion:

| Geography | Leads | Overall conversion |
|---|---:|---:|
| USA | 1,661 | 9.51% |
| Australia | 310 | 9.35% |
| Singapore | 284 | 8.10% |
| UAE | 438 | 7.53% |
| Saudi Arabia | 420 | 7.14% |
| UK | 574 | 6.45% |
| Vietnam | 797 | 4.27% |
| India | 516 | 3.49% |

Possible explanations such as purchasing power, pricing, localization, lead mix or product-market fit are **hypotheses**, not conclusions supported by the dataset.

---

## 6. Rep and shift findings

Aggregate shift conversion:

- US_SHIFT: **7.38%**
- IST_SHIFT: **7.27%**
- SEA_SHIFT: **6.74%**

Individual rep overall conversion:

- AD-03 8.59%
- AD-12 8.45%
- AD-05 7.83%
- AD-06 7.82%
- AD-04 7.69%
- AD-07 7.44%
- AD-09 7.31%
- AD-11 6.91%
- AD-02 6.64%
- AD-10 6.60%
- AD-01 5.95%
- AD-08 5.74%

Full-period rep×geography examples initially suggested specialization:

- AD-03 × USA = **15.53%**
  - AD-03 overall 8.59%
  - USA overall 9.51%
  - +6.02 pp vs USA baseline
  - +6.94 pp vs AD-03 overall
- AD-04 × USA = **14.81%**
- AD-05 × India = **7.27%** vs India 3.49%
- AD-06 × Vietnam = **7.35%** vs Vietnam 4.27%

This made geography-aware routing a serious candidate.

---

## 7. Rep×geography out-of-time validation

To test generalization:

- June = discovery
- July = validation
- Compare each rep×geography result relative to that month’s geography average.

Latest validation:

- **60 comparable rep×geography pairs**
- **31** were above geography average in June
- only **10 of those 31** remained above average in July
- positive-signal persistence = **32.26%**
- **21** positive June signals flipped negative in July
- **15** negative June signals flipped positive in July

Conclusion:

> Hard rep-by-geography routing is too unstable to be the primary intervention.

Some specific combinations, especially USA examples such as AD-03 / AD-04, may be real, but the broad routing rule does not generalize reliably from two months of data.

Possible future use: soft recommendation feature with shrinkage/confidence weighting.

---

## 8. Follow-up attempts

Observed overall conversion:

| Attempts | Leads | Conversion |
|---:|---:|---:|
| 0 | 767 | 7.17% |
| 1 | 1,311 | 7.40% |
| 2 | 1,254 | 7.26% |
| 3 | 868 | 7.14% |
| 4 | 462 | 6.93% |
| 5 | 208 | 8.65% |
| 6 | 81 | 7.41% |
| 7 | 28 | 3.57% |
| 8 | 18 | 0.00% |
| 9 | 3 | 0.00% |

Do not conclude attempt #7 causes deterioration.

Reasons:
- tiny sample at 7+
- strong reverse causality/endogeneity: harder leads likely receive more attempts because they are harder

---

# 9. Core finding: lead-to-demo-slot latency

Detailed buckets:

| Delay from lead creation to demo slot | Scheduled | Join rate | Completion rate | Conversion rate |
|---|---:|---:|---:|---:|
| 0–24h | 1,477 | 74.14% | 63.85% | 12.25% |
| 24–48h | 467 | 77.52% | 67.02% | 12.42% |
| 48–72h | 186 | 43.55% | 39.25% | 5.38% |
| 72–96h | 346 | 52.60% | 45.66% | 13.01% |
| 96–120h | 292 | 48.97% | 43.15% | 9.25% |
| 120–144h | 224 | 45.98% | 41.07% | 9.38% |
| 144–168h | 113 | 35.40% | 30.97% | 5.31% |

The strongest break occurs around **48 hours**.

0–24h and 24–48h have similarly strong attendance; 48–72h collapses. This is why the 48-hour threshold is data-driven rather than arbitrary.

---

## 10. Main 48-hour comparison

### Demo slot within 48h
- scheduled = **1,944**
- joined = **1,457**
- no-shows = 487
- join rate = **74.95%**
- completed = 1,256
- converted = 239
- scheduled→conversion = 12.29%
- joined→completed = 86.20%
- completed→converted = 19.03%
- joined→converted = 16.40%

### Demo slot at/after 48h
- scheduled = **1,285**
- joined = **603**
- no-shows = 682
- join rate = **46.93%**
- completed = 530
- converted = 123
- scheduled→conversion = 9.57%
- joined→completed = 87.89%
- completed→converted = 23.21%
- joined→converted = 20.40%

Interpretation:

> The deterioration is concentrated at **scheduled → joined**.

Once late-scheduled parents actually join, downstream completion and conversion are not worse.

This supports an attendance/timing mechanism rather than simply “late leads are bad leads.”

---

## 11. Month stability of 48h effect

June:
- After 48h: 666 scheduled, **46.10% join**, 8.86% conversion
- Within 48h: 955 scheduled, **75.71% join**, 13.51% conversion

July:
- After 48h: 619 scheduled, **47.82% join**, 10.34% conversion
- Within 48h: 989 scheduled, **74.22% join**, 11.12% conversion

The attendance gap reproduces very closely month-to-month.

---

## 12. Lead-source stability of 48h effect

| Source | After 48h join | Within 48h join |
|---|---:|---:|
| Affiliate | 49.56% | 70.29% |
| DSA | 50.88% | 74.74% |
| Google | 44.66% | 74.95% |
| Meta | 47.48% | 76.57% |
| Organic | 40.98% | 74.04% |
| Referral | 52.11% | 72.73% |

The attendance effect holds across every acquisition source.

Direct conversion uplift is less consistent, so the strongest claim is about **attendance**, not guaranteed conversion uplift in every subgroup.

---

## 13. Rep×geography control for 48h effect

Compare <48h vs ≥48h within the same `rep_assigned × geography` cells.

Require at least 10 observations in each cohort.

Results:

- comparable cells = **51**
- cells where <48h join rate was higher = **48**
- share = **94.12%**
- pooled join rate <48h = **74.37%**
- pooled join rate ≥48h = **46.61%**
- pooled attendance uplift = **+27.76 pp**

Conversion results are much weaker:

- cells where <48h conversion was higher = 28
- 54.90% of cells
- pooled conversion <48h = 12.01%
- pooled conversion ≥48h = 9.50%

Interpretation:

> The attendance relationship remains broad after controlling descriptively for rep and geography. Direct conversion is noisier.

This is observational, not causal.

Largest unresolved confounder:

- high-intent parents may prefer earlier slots and also attend more reliably

Also unknown:

- whether late slots were due to BrightChamps capacity
- whether the parent explicitly chose a later date

---

# 14. Leak sizing

Largest raw drop:

```text
1,786 completed demos → 362 conversions
1,424 non-conversions
```

But the supplied variables cannot estimate how many of those 1,424 are realistically recoverable.

The most defensible measurable/actionable leak is the 48h attendance gap.

Late cohort over two months:

```text
1,285 scheduled at ≥48h
```

Fast cohort join rate:

```text
74.95%
```

Late cohort join rate:

```text
46.93%
```

If late cohort matched fast attendance:

```text
1,285 × 74.95% ≈ 963 joins
```

Actual:

```text
603 joins
```

Gap:

```text
≈360 joins over two months
≈180 joins/month
```

Overall joined→converted rate:

```text
362 / 2060 = 17.57%
```

Full observational upper bound:

```text
180 × 17.57% × ₹60,000
≈ ₹18.96L/month
≈ ₹19L/month
```

Do **not** call ₹19L/month proven causal loss.

Use:

> **observational upper bound**

Base-case assumption:

Recover **50%** of the observed attendance gap.

```text
₹19L × 50%
≈ ₹9.5L/month
```

Recommended headline:

> **~₹9.5 lakh/month base-case recoverable revenue opportunity, with ~₹19 lakh/month as the observational ceiling.**

Sensitivity:

| Gap recovered | Revenue opportunity/month |
|---:|---:|
| 25% | ~₹4.7L |
| 50% | ~₹9.5L |
| 75% | ~₹14.2L |
| 100% observational ceiling | ~₹19.0L |

Marketing-spend context:

```text
5,000 leads / 2 months × ₹900 = ₹22.5L/month
```

Do not subtract ₹900 from marginal recovered conversions because those acquired leads are already paid for; acquisition cost is sunk for this recovery decision.

---

# 15. Chosen lever

## 48-hour Demo-Slot SLA + Recovery Prioritization

Operating policy:

> **For every viable new lead, aim to place the demo in a slot within 48 hours of lead creation. When near-term capacity is constrained, prioritize leads with the highest expected recoverable revenue from preserving the <48h window.**

This should not be reduced to “send reminders.”

It is a **capacity-allocation decision**.

Operational states:

- unscheduled lead approaching 48h → secure near-term slot
- lead already scheduled ≥48h after creation → candidate for pull-forward if capacity opens
- parent preference can override
- record override/delay reason:
  - parent prefers later date
  - no <48h capacity
  - rep unavailable
  - timezone constraint
  - unreachable
  - other

This reason logging helps determine whether the historical relationship is operationally causal.

---

# 16. Why alternatives were rejected

## A. Hard rep-by-geography routing

Attractive because several aggregate rep-market combinations showed large lifts.

Rejected because June→July persistence was only **32.26%**.

Use later only as a soft, regularized recommendation feature.

## B. Reallocate marketing spend

Attractive because source and geography conversion differ strongly.

Rejected because only blended CPL is known. No source×geo CAC, marginal CAC, LTV or scale data.

## C. Cap follow-ups after 6–7 attempts

Attractive because observed performance deteriorates at 7+.

Rejected because sample is tiny and follow-up count is highly endogenous.

## D. Fix completed-demo→sale conversion

Attractive because it is the largest raw funnel drop.

Rejected because the dataset lacks price, objection, transcript, product, discount, competitor and loss-reason data. Mechanism cannot be diagnosed.

## E. Shift/timezone routing

Attractive because shift/timezone fields exist.

Rejected because aggregate shift differences are small and country-specific checks do not produce a reliable conversion advantage.

---

# 17. Prototype

## Name

**BrightChamps 48H Demo Recovery Optimizer**

Preferred stack:

- Python
- pandas
- Streamlit
- keep dependencies minimal
- scikit-learn only if genuinely useful

Expected run command:

```bash
pip install -r requirements.txt
streamlit run app.py
```

The prototype must be more than a dashboard.

It should answer:

> **Given limited near-term demo capacity, which leads should receive those slots first to maximize expected recovered revenue?**

---

## 18. Prototype modes

### Mode 1 — Historical validation

Use:

- June = calibration/training
- July = out-of-time validation

Show:
- 48h attendance effect by month
- segment consistency
- model diagnostics
- observed/base-case revenue opportunity

### Mode 2 — Operational scoring

Inputs:

- CSV with operational lead fields
- current timestamp
- number of available <48h demo slots
- shrinkage strength `k`
- configurable commercial assumptions

For each eligible lead calculate:

- lead age
- current demo-slot delay
- SLA status
- geography×source segment
- estimated fast join probability
- estimated late join probability
- smoothed probabilities
- attendance uplift
- expected recoverable revenue
- urgency
- final priority score
- recommended action

---

# 19. Segment model

Recommended v1:

```text
geography × lead_source
```

Estimate from June:

```text
P(join | demo slot <48h)
P(join | demo slot >=48h)
```

Use empirical shrinkage toward global rates:

```text
adjusted_rate
= (n / (n + k)) * segment_rate
+ (k / (n + k)) * global_rate
```

Suggested default:

```text
k = 50
```

Make `k` configurable.

This prevents small cells from producing extreme scores.

---

# 20. Revenue-at-risk calculation

Use overall:

```text
P(convert | joined) = 362 / 2060 = 17.57%
```

For each lead:

```text
delta_join
= P_adjusted(join | <48h)
- P_adjusted(join | >=48h)
```

Then:

```text
expected_recoverable_revenue
= max(delta_join, 0)
  × 0.1757
  × 60000
```

Example:

```text
fast join probability = 75%
late join probability = 45%
delta = 30 pp

0.30 × 0.1757 × ₹60,000
≈ ₹3,163
```

This is an expected-value prioritization heuristic, not a causal guarantee.

---

# 21. Urgency and final score

Transparent configurable urgency example:

| Status | Multiplier |
|---|---:|
| 0–24h age | 1.0 |
| 24–36h | 1.2 |
| 36–42h | 1.5 |
| 42–48h | 2.0 |
| 48h+ | rescue / breached |

These multipliers are **operational heuristics**, not statistically estimated effects.

Priority score:

```text
priority_score
= expected_recoverable_revenue
  × urgency_multiplier
```

If `N` near-term slots are available:

1. identify eligible at-risk leads
2. score them
3. sort descending
4. allocate top `N`
5. report expected additional joins, conversions and revenue

---

# 22. Eligibility logic

### Unscheduled and age <48h
Candidate if approaching SLA.

### Scheduled slot <48h from creation
Healthy; no rescue required.

### Scheduled slot ≥48h from creation
Candidate for pull-forward if earlier capacity exists.

### Age >48h and unscheduled
Breached; rescue/escalation.

### Historical completed/converted records
Exclude from live operational queue.

The provided case dataset is historical. Operational mode should either:

- support a fresh operational CSV with the same schema, or
- clearly label historical scoring as a simulation.

Do not pretend historical rows are a live CRM feed.

---

# 23. Explainability

Each recommendation should show why it was scored.

Example:

```text
Lead: L10293
Geography: Vietnam
Source: Google
Lead age: 43.1h

Adjusted P(join | <48h): 70.4%
Adjusted P(join | >=48h): 38.1%

Attendance uplift: +32.3 pp
P(convert | joined): 17.57%

Expected recoverable revenue: ₹3,405
Urgency multiplier: 2.0
Priority score: 6,810

Recommendation:
Offer / pull forward into the earliest available slot inside 48h.
```

Display disclaimer:

> This score is a prioritization heuristic derived from observational historical data, not a causal prediction. Revenue impact should be validated prospectively.

---

# 24. Suggested Streamlit UI

## Executive Summary
- funnel
- 48h attendance gap
- base-case ₹9.5L/month
- observational ceiling ~₹19L/month
- capacity input
- expected impact

## Recovery Queue
Columns:
- lead_id
- geography
- source
- timezone
- lead age
- demo-slot delay
- SLA status
- expected revenue at risk
- urgency
- priority score
- recommendation

## Why This Lead?
Lead-level explainability.

## Historical Validation
June calibration vs July validation.

## Assumptions
- ₹60,000 revenue
- 17.57% joined→converted
- shrinkage `k`
- urgency multipliers
- causal caveats

---

# 25. Biggest adoption / causal risk

The biggest unresolved issue:

> We do not know whether late demos were late because BrightChamps lacked capacity or because parents deliberately chose later slots.

Therefore:

- recommend/offer earlier slots, do not force them
- log parent preference / capacity reason
- validate prospectively

---

# 26. Measurement plan

Two-week pilot.

Primary metric:
- scheduled→joined rate

Secondary:
- completed demos
- conversions
- revenue per acquired lead
- share of demos placed inside 48h
- delay/override reason distribution

Guardrails:
- reschedules
- cancellations
- rep utilization
- parent complaints / availability friction

Prefer randomized or concurrent-control measurement if operationally feasible.

---

# 27. Design principles

1. Do not overfit.
2. Prefer transparent scoring over black-box ML.
3. Separate observed facts, assumptions, heuristics and causal uncertainty.
4. Every recommendation should be explainable.
5. Make important assumptions configurable.
6. Keep deployment friction low.
7. The build should make a business decision, not merely visualize data.

---

# 28. Recommended case narrative

> I first mapped the full funnel and tested multiple plausible drivers: source, geography, shift, follow-up intensity, rep performance, rep-market fit and scheduling latency. Several alternatives looked promising in aggregate. I then tried to falsify them. Rep-market specialization, for example, largely failed June→July out-of-time persistence, so I rejected hard routing. The one relationship that remained broad and stable was demo attendance: demos placed within 48 hours of lead creation joined at roughly 75% versus 47% after 48 hours, a pattern that repeated across months, sources and almost every comparable rep×geography cell. I therefore chose a 48-hour demo-slot policy and built a capacity-constrained recovery optimizer to prioritize the leads where an earlier slot has the highest expected revenue value.

---

# 29. Evidence file

Primary SQL transcript:

```text
SQl_terminal_bc.txt
```

It contains the MySQL queries and outputs used for the analysis.

Use the original BrightChamps CSV directly for the prototype when available.

---

# 30. Suggested repo structure

```text
brightchamps-fda/
├── app.py
├── scoring.py
├── validation.py
├── requirements.txt
├── README.md
├── CONTEXT.md
├── data/
│   └── BrightChamps_FDA_Case_Dataset.csv
└── tests/
    └── test_scoring.py
```

Implementation order:

1. Validate CSV schema.
2. Parse timestamps.
3. Add `demo_delay_hours`.
4. Build June training / July validation split.
5. Calculate global <48h / ≥48h rates.
6. Calculate geography×source segment rates.
7. Implement shrinkage.
8. Implement expected recoverable revenue.
9. Implement urgency.
10. Implement capacity-constrained ranking.
11. Build Streamlit UI.
12. Add caveats and assumption controls.
13. Add unit tests.
14. Write README with exact run command.
15. Verify every displayed metric is generated from data rather than hard-coded.

---

# 31. Avoid weaker directions

Do not regress the prototype into only:

- an SLA dashboard
- a static “older than 48h” sheet
- a generic chatbot
- hard rep routing
- marketing-budget optimization without CAC
- black-box conversion prediction

Keep it as:

> **a transparent, capacity-aware decision engine for recovering demo attendance value before the 48-hour window is lost.**
