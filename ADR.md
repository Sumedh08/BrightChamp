# ADR-001: Transparent attendance estimates and capacity-aware recovery policy

## Status

Accepted, updated to incorporate the approved calibration cutoff and deployment refit.

## Context

Historical attendance is associated with demo-slot latency. The timestamps describe
the slot, not the booking action. Parent intent and the cause of delay are unobserved.
The prototype must make an explainable operational decision without claiming causal lift.

## Decision

1. Compare global-only, source, geography, and geography × source. Official evaluation
   calibration requires creation in June 2026 and a non-null demo slot strictly before
   July 1. The 122 June-created July slots remain descriptive evidence only for this step.
2. Fit each candidate on those 1,499 eligible June rows, with fixed `k = 50` for all
   segmented candidates. Shrink separately toward the corresponding global timing cohort.
   Unseen segment/cohort combinations fall back directly to that global rate.
3. Use July-created scheduled leads as the out-of-time holdout evaluation / model-selection
   period. Choose the simplest candidate with ≥2% relative Brier improvement and no more
   than 1pp worse absolute calibration error in either timing cohort. Source precedes
   geography, then the joint model. Otherwise retain global-only. These are predeclared
   engineering thresholds. Report coverage and stability alongside the selection.
4. After selection, refit only the selected class on all 3,229 historical scheduled leads
   for deployment. Keep the June evaluation models and July diagnostics separate and
   unchanged. Do not rerun holdout metrics with deployment parameters. On the bundled data,
   global-only wins and deployment rates are 1,457/1,944 fast and 603/1,285 late.
5. Compute full observed-gap value as `max(P_fast - P_late, 0) × (362/2060) × 60000`.
   The default base-case scenario multiplies this by 0.50. Commercial inputs are explicit
   assumptions; they never enter fitting or selection. UI wording uses "Full observed-gap
   scenario (100%)" and "Base-case scenario (50% observed-gap recovery)". Neither is causal.
6. Allocate only open leads younger than 48h that are unscheduled or have a slot at/after
   48h. Joined/completed/converted/cancelled leads never receive recovery capacity.
   Separate already protected, breached and stale-status rows with explanations.
7. Rank Expiring (≤6h remaining), Soon (≤24h), then Standard (≤48h), with value descending
   within each tier, followed by remaining time and lead ID. No urgency multiplier.
   Zero-value eligible rows still follow the SLA policy without implying financial benefit.
8. Keep historical evidence and current operational CSVs separate. Provide a clearly
   synthetic fixed-clock sample and template. Use one CRM/system timezone for live inputs;
   parent timezone is informational. Historical durations use supplied timestamps directly.
9. Preserve official `k = 50`; the sensitivity panel cannot alter selection or deployment.

## Consequences

- Low operational complexity: local Python/pandas/Streamlit, transparent equations,
  deterministic allocation and downloadable assumptions.
- Global-only is a legitimate result. Under common economics it assigns equal values,
  so expiry and deadline ordering drive recommendations.
- Tier-first allocation is an operational policy, not mathematical revenue maximization.
- Calendar feasibility, parent agreement and contactability require operator confirmation.
  Unscheduled-lead values assume successful scheduling, which is not estimated by the data.
- The slot cutoff limits outcome-availability leakage; recording timestamps are still
  absent. July selection provides temporal robustness evidence, not an independent final
  validation. Observed-cohort probability accuracy does not validate causal intervention value.
- Full-history refitting improves available deployment estimates without contaminating the
  saved evaluation. A prospective randomized/concurrent-control pilot is the next evidence step.

## Rejected alternatives

- **Forced geography × source segmentation:** none of the segmented candidates meets the
  holdout rule on the corrected data. Complexity must earn its place.
- **Urgency multiplied into money:** gives an operational heuristic a false monetary meaning.
- **Unrestricted June-created calibration:** includes outcomes for 122 July demo slots.
- **Deployment parameters used to rescore July:** would overwrite the holdout with in-sample results.
- **Hard rep-geography routing:** earlier case analysis found only 32.26% persistence of
  June positive signals into July.
- **Black-box conversion ML:** limited observational features, two months of data and weak
  causal identification do not justify the complexity or loss of explainability.
- **Marketing optimization:** source/geography CAC, marginal CAC and scale constraints absent.
- **Follow-up cutoff rules:** tiny high-attempt cells and reverse causality undermine the claim.
- **Historical rows relabelled live:** booking state is unavailable and cannot be reconstructed.

The original `CONTEXT.md` is preserved as case evidence; this ADR and README record the
later approved methodological and operational corrections.
