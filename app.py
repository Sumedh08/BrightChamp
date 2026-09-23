"""Run locally: streamlit run app.py"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from data import DataError, load_historical, load_live, parse_as_of
from scoring import (CommercialAssumptions, MODEL_KEYS, MODEL_LABELS, OFFICIAL_K, allocate_capacity,
                     estimate_rates, fit_estimator, score_live_queue)
from validation import (cohort_summary, evaluate_candidates, monthly_opportunity,
                        refit_deployment, split_evaluation)

ROOT = Path(__file__).resolve().parent
SAMPLE_AS_OF = "2026-08-03 12:00:00"
CAVEAT = (
    "Values are scenarios derived from observational attendance differences. "
    "Recovery factor is an assumption, and 100% observed-gap recovery is not a proven causal upper bound. "
    "Parent intent and slot availability are unobserved; revenue impact needs prospective measurement."
)


@st.cache_data(show_spinner="Comparing June-fitted estimators on July…")
def prepare_history(raw: bytes):
    history = load_historical(BytesIO(raw))
    evaluation = evaluate_candidates(history)
    deployment = refit_deployment(history, evaluation)
    return history, evaluation, deployment


def money(value):
    return f"₹{value:,.0f}"


def scenario_name(commercial):
    if commercial == CommercialAssumptions():
        return "Base-case scenario (50% observed-gap recovery)"
    return f"Selected scenario ({commercial.recovery_factor:.0%} observed-gap recovery)"


def sidebar_controls(mode):
    """Presentation only: keep the same control defaults, bounds and input contracts."""
    options = {"raw": None, "sample": False, "as_of": None, "crm_timezone": "UTC", "capacity": 4}
    sensitivity = ("source", 50)
    operational = mode == "Operational Queue"
    with st.sidebar:
        if operational:
            source = st.radio("Queue source", ["Use synthetic demo", "Upload live/open-leads CSV"])
            options["sample"] = source == "Use synthetic demo"
            if options["sample"]:
                options["raw"] = (ROOT / "sample_live_queue.csv").read_bytes()
            else:
                upload = st.file_uploader("Live CSV", type=["csv"])
                options["raw"] = upload.getvalue() if upload is not None else None
                st.session_state.setdefault("live_clock", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
                options["as_of"] = st.text_input("Snapshot as_of (system timezone)", key="live_clock")
            options["capacity"] = int(st.number_input("Available early-slot capacity", min_value=0, value=4, step=1))
            with st.expander("CSV templates"):
                st.download_button("Download live CSV template", (ROOT / "live_queue_template.csv").read_bytes(),
                                   "live_queue_template.csv", "text/csv")
                st.download_button("Download synthetic example", (ROOT / "sample_live_queue.csv").read_bytes(),
                                   "sample_live_queue.csv", "text/csv")
        with st.expander("Advanced assumptions", expanded=False):
            revenue = st.number_input("Revenue per conversion (₹)", min_value=0.0,
                                      value=60000.0, step=1000.0, format="%.0f", key="revenue")
            st.caption("Average revenue from one converted customer.")
            conversion = st.number_input("Conversion after demo join (%)", min_value=0.0,
                                         max_value=100.0, value=100 * 362 / 2060,
                                         format="%.4f", step=.1, key="conversion")
            st.caption("Historically, 17.57% of joined demos converted (362 / 2,060).")
            recovery = st.slider("Assumed gap recovery (%)", 0, 100, 50, 5, key="recovery")
            st.caption("Base case assumes the intervention captures 50% of the observed attendance gap. "
                       "This is an assumption, not a rate estimated from the data.")
            if operational:
                if options["sample"]:
                    options["as_of"] = st.text_input("Demo as_of (UTC)", SAMPLE_AS_OF, key="demo_clock")
                    st.caption("The synthetic example uses a fixed UTC clock so it stays reproducible.")
                else:
                    options["crm_timezone"] = st.text_input("CRM/system timezone", "UTC",
                        help="All timestamps and the snapshot time use this IANA zone, e.g. Asia/Kolkata. Parent timezone is informational.")
            else:
                st.markdown("**Model sensitivity only**")
                sensitivity_kind = st.selectbox("Sensitivity estimator", ["source", "geography", "geography_source"],
                                                  format_func=MODEL_LABELS.get)
                sensitivity_k = st.slider("Sensitivity k", 0, 500, 50, 10)
                sensitivity = (sensitivity_kind, sensitivity_k)
                st.caption("Results appear in Technical validation. Official k remains 50; "
                           "these controls do not change selection or deployment.")
    return CommercialAssumptions(conversion / 100, revenue, recovery / 100), options, sensitivity


def summary_metrics(items):
    """Four native cards; scoped CSS wraps them into two columns in narrow previews."""
    with st.container(key="summary_metrics"):
        for column, (label, value) in zip(st.columns(4), items):
            column.metric(label, value)


def value_label(commercial):
    return "Base-case" if commercial == CommercialAssumptions() else "Selected scenario"


def assumptions_panel(commercial):
    st.markdown("**Observed evidence → estimated attendance → assumed recovery → operational policy**")
    st.dataframe(pd.DataFrame([
        {"Type": "Observed", "Input": "Attendance by scheduled slot timing", "Treatment": "Calculated from case CSV"},
        {"Type": "Estimated", "Input": "Estimator class", "Treatment": "June fit, July selection, then full-history refit"},
        {"Type": "Assumed", "Input": "Conversion given joined", "Treatment": f"{commercial.conversion_given_joined:.4%}; case default 362 / 2,060"},
        {"Type": "Assumed", "Input": "Revenue per conversion", "Treatment": money(commercial.revenue_per_conversion)},
        {"Type": "Assumed", "Input": "Observed-gap recovery", "Treatment": f"{commercial.recovery_factor:.0%}"},
        {"Type": "Policy", "Input": "Expiry risk", "Treatment": "Expiring (≤6h), Soon (≤24h), Standard (≤48h) remaining"},
        {"Type": "Policy", "Input": "Capacity", "Treatment": "Tier first; scenario value within tier; deadline and ID break ties"},
    ]), hide_index=True, width="stretch")
    st.write("Slot timing is observational, not randomized. " + CAVEAT)
    st.write("The demo timestamp records the scheduled slot, not the booking action. "
             "The ₹900 acquisition cost is already incurred and is not subtracted from marginal recovery value.")
    st.write("For unscheduled leads, the scenario assumes successful contact, agreement, and a feasible slot. "
             "No scheduling-acceptance probability is estimated. A capacity count does not verify calendars.")


def pilot_plan():
    st.write("Offer earlier slots with parent agreement. Record offered slot, acceptance, actual slot, "
             "attendance, and delay/override reason: parent preference, capacity, rep availability, "
             "timezone constraint, unreachable, or other. Prefer randomized offers or a defined concurrent comparison.")
    st.write("Track attendance, completed demos and mature conversions; preserve original assignment groups. "
             "Guardrails: cancellations, reschedules, rep utilization and parent friction. "
             "The download provides blank fields for operations to record decisions outside the app.")


def technical_validation(history, evaluation, deployment, sensitivity):
    st.subheader("July out-of-time holdout evaluation / model-selection period")
    a, b, c = st.columns(3)
    a.metric("June calibration slots", f"{evaluation.calibration_rows:,}")
    b.metric("June-created July slots excluded", f"{evaluation.excluded_june_slots:,}")
    c.metric("July holdout slots", f"{evaluation.holdout_rows:,}")
    st.code("Calibration: created_at >= 2026-06-01 AND created_at < 2026-07-01\n"
            "             AND demo_scheduled_at < 2026-07-01\n"
            "Holdout:     July-created scheduled leads; no further split\n"
            "Official k:  50, fixed for every segmented candidate")
    st.write("Select the simplest candidate with ≥2% relative Brier improvement over global-only "
             "and no more than 1 percentage-point deterioration in absolute calibration error "
             "within either timing cohort. Simplicity order: source → geography → geography × source. "
             "Otherwise retain global-only. These are predeclared engineering guardrails, not significance tests.")
    table = evaluation.comparison.copy()
    table["model"] = table.model.map(MODEL_LABELS)
    st.dataframe(table.style.format({"brier": "{:.6f}", "relative_brier_improvement": "{:.2%}",
        "predicted_join_rate": "{:.2%}", "observed_join_rate": "{:.2%}", "calibration_error": "{:+.2%}",
        "fast_calibration_error": "{:+.2%}", "late_calibration_error": "{:+.2%}",
        "fallback_share": "{:.2%}", "low_support_share": "{:.2%}"}),
        hide_index=True, width="stretch")
    st.success(f"Selected estimator class: {MODEL_LABELS[evaluation.selected_kind]}")
    st.download_button("Download official model comparison", evaluation.comparison.to_csv(index=False),
                       "official_model_comparison.csv", "text/csv")
    st.write("Calibration error is predicted minus observed attendance; compare absolute errors for the guardrail. "
             "Fallback share counts unseen segments in the relevant cohort; low support means fewer than 10 June rows. "
             "Global-only uses all June observations in that timing cohort, so segment fallback is not needed.")
    with st.expander("Cohort diagnostics, sample coverage, and stability", expanded=False):
        st.dataframe(evaluation.diagnostics, hide_index=True, width="stretch")
        st.dataframe(evaluation.stability_coverage, hide_index=True, width="stretch")
        st.caption("Stability uses raw attendance gaps in cells with ≥10 rows in each timing cohort "
                   "in both corrected June calibration and July. Coverage shows which July rows those cells represent.")
        st.dataframe(evaluation.stability, hide_index=True, width="stretch")
    diagnostic_model = st.selectbox("Reliability view", list(MODEL_LABELS), format_func=MODEL_LABELS.get)
    reliability = evaluation.reliability.loc[evaluation.reliability.model.eq(diagnostic_model)]
    st.scatter_chart(reliability, x="predicted", y="observed", color="cohort", size="n",
                     x_label="Mean predicted probability", y_label="Observed join rate")
    st.dataframe(reliability, hide_index=True, width="stretch")
    st.caption("Fixed 20-percentage-point probability bins; empty bins omitted. Calibration lies on observed = predicted. "
               "With coarse/global estimates, only a few bins have support.")
    st.markdown("**Evaluation fitting and deployment refitting are separate.**")
    parameter_rows = []
    for model in [evaluation.evaluation_models[evaluation.selected_kind], deployment]:
        for cohort, (n, joins) in model.global_counts.items():
            parameter_rows.append({"Purpose": model.purpose, "Cohort": cohort, "Rows": n,
                                   "Joins": joins, "Global rate / shrinkage prior": joins / n})
    st.dataframe(pd.DataFrame(parameter_rows).style.format({"Global rate / shrinkage prior": "{:.2%}"}),
                 hide_index=True, width="stretch")
    st.warning("July participates in model selection. These results provide temporal robustness evidence, "
               "not independent final validation of the selected model. July metrics use only June-fitted "
               "parameters and are never overwritten by the full-history deployment refit.")
    st.caption("The calibration cutoff excludes July demo slots. Actual attendance recording timestamps are unavailable; "
               "we assume outcomes for slots before July were observable. Prediction accuracy for observed timing "
               "cohorts does not validate causal recovery from changing a slot.")
    with st.expander("Shrinkage sensitivity only — official k remains 50"):
        sensitivity_kind, sensitivity_k = sensitivity
        june, _, _ = split_evaluation(history)
        sensitivity_model = fit_estimator(june, sensitivity_kind, sensitivity_k, purpose="sensitivity only")
        segments = june[list(MODEL_KEYS[sensitivity_kind])].drop_duplicates().reset_index(drop=True)
        estimates = estimate_rates(segments, sensitivity_model)
        st.dataframe(pd.concat([segments, estimates], axis=1), hide_index=True, width="stretch")
        st.caption("This panel only explores June segment estimates. It does not rerun selection, "
                   "change deployment, or alter the official holdout metrics.")


def historical_view(history, evaluation, deployment, commercial, sensitivity):
    st.caption("HISTORICAL EVIDENCE · June–July 2026")
    st.subheader("Where is BrightChamps losing attendance?")
    opportunity = monthly_opportunity(history, commercial)
    summary_metrics([
        ("<48h demo attendance", f"{opportunity['fast_rate']:.2%}"),
        ("≥48h demo attendance", f"{opportunity['late_rate']:.2%}"),
        ("Attendance gap", f"{100 * (opportunity['fast_rate'] - opportunity['late_rate']):.2f} pp"),
        (f"{value_label(commercial)} monthly opportunity", f"₹{opportunity['base_case_value'] / 100000:.2f} lakh"),
    ])
    st.caption(scenario_name(commercial) + ".")
    summary = cohort_summary(history)
    rates = summary.copy()
    rates["Month"] = rates.creation_month.map({"2026-06": "June", "2026-07": "July"})
    rates["Timing"] = rates.cohort.map({"fast": "Slot <48h", "late": "Slot ≥48h"})
    rates["Attendance (%)"] = rates.join_rate * 100
    timing_order = ["Slot <48h", "Slot ≥48h"]
    attendance_chart = alt.Chart(rates).mark_bar().encode(
        x=alt.X("Month:N", sort=["June", "July"], axis=alt.Axis(labelAngle=0), title=None),
        xOffset=alt.XOffset("Timing:N", sort=timing_order),
        y=alt.Y("Attendance (%):Q", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("Timing:N", scale=alt.Scale(domain=timing_order, range=["#0f766e", "#c68b42"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["Month:N", "Timing:N", alt.Tooltip("Attendance (%):Q", format=".2f"),
                 alt.Tooltip("scheduled:Q", title="Scheduled leads")],
    ).properties(height=220)
    st.altair_chart(attendance_chart, use_container_width=True)
    st.caption("Scenario values are based on observational historical differences and should be validated prospectively.")

    st.subheader("Does segmentation improve the decision?")
    if evaluation.selected_kind == "global":
        global_brier = evaluation.comparison.loc[evaluation.comparison.model.eq("global"), "brier"].iloc[0]
        if global_brier <= evaluation.comparison.brier.min():
            st.write("**Global-only performed best on the July out-of-time holdout.** Adding lead source or geography "
                     "did not materially improve prediction, so the operational tool uses the simpler global estimator.")
        else:
            st.write("**Segmentation did not meet the documented improvement rule.** The operational tool retains "
                     "the simpler global estimator.")
    else:
        st.write(f"**{MODEL_LABELS[evaluation.selected_kind]} qualified under the documented holdout rule.** "
                 "It was the simplest qualifying estimator and is used by the operational tool.")
    compact = evaluation.comparison[["model", "brier", "relative_brier_improvement", "selected"]].copy()
    compact["model"] = compact.model.map(MODEL_LABELS)
    compact["selected"] = compact.selected.map({True: "Selected", False: "—"})
    compact = compact.rename(columns={"model": "Estimator", "brier": "July Brier score",
                                      "relative_brier_improvement": "Improvement vs global", "selected": "Decision"})
    st.dataframe(compact.style.format({"July Brier score": "{:.6f}", "Improvement vs global": "{:+.2%}"}),
                 hide_index=True, width="stretch")
    st.caption("Lower Brier scores mean more accurate attendance probabilities on observed July slots.")
    with st.expander("Technical validation"):
        technical_validation(history, evaluation, deployment, sensitivity)
    with st.expander("Historical funnel and scenario calculation"):
        counts = [len(history), history.demo_scheduled_at.notna().sum(), history.joined.sum(),
                  history.completed.sum(), history.conversion.sum()]
        funnel = pd.DataFrame({"Stage": ["Leads", "Scheduled", "Joined", "Completed", "Converted"], "Leads": counts})
        st.dataframe(funnel, hide_index=True, width="stretch")
        st.bar_chart(funnel.set_index("Stage"), color="#0f766e")
        st.dataframe(summary.style.format({"join_rate": "{:.2%}"}), hide_index=True, width="stretch")
        st.caption("Descriptive counts retain all June-created leads, including those with July slots. "
                   "The official June calibration excludes those later slots.")
        a, b = st.columns(2)
        a.metric(scenario_name(commercial) + " / month", f"₹{opportunity['base_case_value'] / 100000:.2f} lakh")
        b.metric("Full observed-gap scenario (100%) / month", f"₹{opportunity['full_observed_gap_value'] / 100000:.2f} lakh")
        st.caption(f"{opportunity['late_leads_per_month']:,.1f} late-slot leads/month × "
                   f"({opportunity['fast_rate']:.2%} − {opportunity['late_rate']:.2%}) attendance gap × "
                   f"{commercial.conversion_given_joined:.4%} conversion given joined × "
                   f"{money(commercial.revenue_per_conversion)}. Two-month volume divided by two.")
        scenarios = pd.DataFrame({"Gap recovery": ["25%", "50%", "75%", "100%"],
            "Monthly scenario (₹)": [opportunity["full_observed_gap_value"] * factor for factor in [.25, .5, .75, 1]]})
        st.bar_chart(scenarios.set_index("Gap recovery"), color="#0f766e")
    with st.expander("Limitations and assumptions"):
        assumptions_panel(commercial)
    with st.expander("How we would validate this in production"):
        pilot_plan()


def readable_remaining(hours):
    minutes = int(hours * 60)
    if minutes < 1:
        return "<1m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def operational_actions(frame):
    """Use the consistent public action labels without coupling them to allocation status."""
    actions = frame.recommendation.copy()
    open_eligible = frame.eligible
    unscheduled = open_eligible & frame.demo_scheduled_at.isna()
    scheduled_late = open_eligible & frame.demo_scheduled_at.notna()
    actions.loc[unscheduled] = "Offer early demo slot"
    actions.loc[scheduled_late] = "Pull existing demo forward"
    return actions


def queue_display(frame):
    # Display copy only: do not alter rank, allocation, actions or exports in the scored frame.
    display = pd.DataFrame(index=frame.index)
    display["Priority"] = frame["rank"]
    display["Lead ID"] = frame.lead_id
    display["Time remaining"] = frame.hours_remaining.map(readable_remaining)
    display["Current state"] = frame.demo_scheduled_at.isna().map(
        {True: "Unscheduled", False: "Scheduled beyond 48h"})
    display["Recommended action"] = operational_actions(frame)
    display["Est. opportunity"] = frame.base_case_recoverable_value
    display["Allocation status"] = frame.allocated.map({True: "Allocated", False: "Waiting"})

    return display


def queue_table(frame):
    display = queue_display(frame)
    st.dataframe(display, hide_index=True, width="stretch", height=350,
                 column_config={"Priority": st.column_config.NumberColumn(width="small"),
                                "Time remaining": st.column_config.TextColumn(width="medium"),
                                "Recommended action": st.column_config.TextColumn(width="large"),
                                "Est. opportunity": st.column_config.NumberColumn(
                                    format="₹%.2f", width="small",
                                    help="Shared estimated opportunity under the current assumptions; it is not a standalone priority score."),
                                "Current state": st.column_config.TextColumn(width="small"),
                                "Allocation status": st.column_config.TextColumn(width="small")})


def lead_explanation(queue, deployment, commercial):
    if queue.empty:
        st.info("No leads in this snapshot.")
        return
    identity = st.selectbox("Explain a lead", queue.lead_id.tolist())
    lead = queue.loc[queue.lead_id.eq(identity)].iloc[0]
    st.write(f"**{lead.lead_id} · {lead.queue_state} · {lead.tier}**")
    st.caption(f"{lead.geography} · {lead.lead_source} · Parent timezone: {lead.parent_timezone or 'not supplied'}")
    st.write(lead.reason)
    st.write(lead.recommendation)
    if not lead.eligible:
        st.info("Excluded from preservation allocation; no recovery value is assigned.")
        return
    st.caption(f"Deadline: {lead.deadline} · {lead.hours_remaining:.2f} hours remaining · "
               f"Rank {lead['rank']} · {'Allocated candidate' if lead.allocated else 'Waiting for capacity'}")
    support = []
    for cohort in ("fast", "late"):
        support.append({"Timing cohort": "<48h" if cohort == "fast" else "≥48h",
            "Deployment observations": int(lead[f"n_{cohort}"]), "Joins": int(lead[f"joins_{cohort}"]),
            "Raw rate": lead[f"raw_{cohort}"], "Global rate": lead[f"global_{cohort}"],
            "Segment weight": lead[f"weight_{cohort}"], "Estimated rate": lead[f"p_{cohort}"],
            "Unseen cohort fallback": bool(lead[f"fallback_{cohort}"])})
    st.dataframe(pd.DataFrame(support).style.format({"Raw rate": "{:.2%}", "Global rate": "{:.2%}",
                 "Segment weight": "{:.2%}", "Estimated rate": "{:.2%}"}, na_rep="—"),
                 hide_index=True, width="stretch")
    st.caption(f"{MODEL_LABELS[deployment.kind]} · full-history deployment fit ({deployment.fit_rows:,} scheduled leads). "
               + ("Global-only uses cohort-wide rates; no segment weighting is required." if deployment.kind == "global"
                  else "Adjusted rate = (segment joins + 50 × global rate) / (segment observations + 50)."))
    st.code(f"Raw attendance gap = {lead.p_fast:.6f} − {lead.p_late:.6f} = {lead.raw_attendance_gap:.6f}\n"
            f"Value gap = max(raw gap, 0) = {lead.nonnegative_attendance_gap:.6f}\n"
            f"Full observed-gap scenario = {lead.nonnegative_attendance_gap:.6f} × "
            f"{commercial.conversion_given_joined:.8f} × ₹{commercial.revenue_per_conversion:,.0f}\n"
            f"                           = ₹{lead.observational_value_ceiling:,.2f}\n"
            f"Selected scenario = ₹{lead.observational_value_ceiling:,.2f} × {commercial.recovery_factor:.2f}\n"
            f"                  = ₹{lead.base_case_recoverable_value:,.2f}\n"
            f"Ordering: {lead.tier} tier → scenario value → deadline → lead ID")
    if lead.base_case_recoverable_value == 0:
        st.warning("This lead has zero value under the current scenario. Any allocation is an SLA policy action, "
                   "not evidence of financial benefit.")


def queue_export(queue):
    """Presentation copy for the recommendation download; values in queue stay full precision."""
    export = queue.rename(columns={
        "observational_value_ceiling": "full_observed_gap_scenario_value",
        "base_case_recoverable_value": "Est. opportunity",
        "recommendation": "Recommended action",
        "allocated": "Allocation status",
    }).copy()
    export["Recommended action"] = operational_actions(queue)
    allocation_status = pd.Series("Excluded", index=queue.index, dtype="string")
    allocation_status.loc[queue.eligible & ~queue.allocated] = "Waiting"
    allocation_status.loc[queue.allocated] = "Allocated"
    export["Allocation status"] = allocation_status
    export["Est. opportunity"] = queue.base_case_recoverable_value.map(lambda value: f"{value:.2f}")
    return export


def downloads(queue, selected, sample, clock, crm_timezone, capacity, commercial, history_raw, raw, evaluation, deployment):
    export = queue_export(queue)
    export["snapshot_as_of_utc"] = str(clock)
    export["synthetic_demo"] = sample
    export["deployment_model"] = deployment.kind
    export["recovery_factor"] = commercial.recovery_factor
    export["conversion_given_joined"] = commercial.conversion_given_joined
    export["revenue_per_conversion"] = commercial.revenue_per_conversion
    for column in ["operator_decision", "delay_or_override_reason", "offered_slot", "parent_accepted", "actual_slot"]:
        export[column] = ""
    st.download_button("Download queue & decision log", export.to_csv(index=False), "recovery_queue.csv", "text/csv")
    receipt = {"policy_version": "1.0", "synthetic_demo": sample, "as_of_utc": str(clock),
        "system_timezone": crm_timezone, "capacity": capacity, "commercial_assumptions": asdict(commercial),
        "history_sha256": hashlib.sha256(history_raw).hexdigest(), "live_csv_sha256": hashlib.sha256(raw).hexdigest(),
        "evaluation": {"period": "June-created slots before July 1; July model-selection holdout",
            "fit_rows": evaluation.calibration_rows, "holdout_rows": evaluation.holdout_rows,
            "excluded_june_slots": evaluation.excluded_june_slots, "official_k": OFFICIAL_K,
            "comparison": evaluation.comparison.to_dict("records")},
        "deployment": {"selected_class": deployment.kind, "fit_rows": deployment.fit_rows,
            "purpose": deployment.purpose, "k": deployment.k, "global_counts": deployment.global_counts},
        "allocation": {"order": "tier, value descending, hours remaining, lead_id",
                       "eligible": int(queue.eligible.sum()), "allocated": len(selected)}}
    st.download_button("Download assumptions & model receipt", json.dumps(receipt, indent=2),
                       "decision_receipt.json", "application/json")
    st.caption("Downloads capture the queue and assumptions. The app does not persist uploads or operator edits to disk.")


def operational_view(history_raw, evaluation, deployment, commercial, options):
    raw, sample = options["raw"], options["sample"]
    as_of, crm_timezone, capacity = options["as_of"], options["crm_timezone"], options["capacity"]
    if sample:
        st.caption(f"Synthetic demo reference time: {as_of} UTC · Invented leads")
    else:
        st.caption(f"Queue evaluated as of: {as_of} ({crm_timezone})")
    if raw is None:
        st.info("Upload a live/open-leads CSV using the template in the sidebar. All timestamps must use one CRM/system timezone.")
        with st.expander("Limitations and assumptions"):
            assumptions_panel(commercial)
        return
    live = load_live(BytesIO(raw), as_of, crm_timezone)
    clock = parse_as_of(as_of, crm_timezone)
    queue = allocate_capacity(score_live_queue(live, deployment, clock, commercial), capacity)
    selected = queue.loc[queue.allocated]
    eligible = queue.loc[queue.eligible]
    excluded = queue.loc[~queue.eligible]
    summary_metrics([
        ("Eligible leads at risk", str(int(queue.eligible.sum()))),
        ("Early-slot capacity", str(capacity)),
        ("Leads allocated", str(len(selected))),
        ("Base-case scenario value of allocated leads" if value_label(commercial) == "Base-case"
         else "Selected scenario value of allocated leads", money(selected.base_case_recoverable_value.sum())),
    ])
    st.caption(scenario_name(commercial) + ". Value shown is for this allocated batch.")
    st.subheader("Recommended actions")
    if deployment.kind == "global":
        st.info("Global estimator selected: historical evidence did not support reliable source/geography differentiation. "
                "All eligible leads therefore share the same estimated opportunity value under the current assumptions. "
                "Because the estimated opportunity is identical across eligible leads, priority is driven by time remaining "
                "before the 48-hour window expires.")
    queue_table(eligible)
    if eligible.empty:
        st.info("No leads currently qualify for demo-slot recovery. Review other leads and escalations below.")
    elif capacity == 0:
        st.caption("No early slots are available. Eligible leads remain in priority order, waiting for capacity.")
    if not eligible.empty and eligible.base_case_recoverable_value.eq(0).all():
        st.warning("All eligible values are zero under these assumptions. The queue still follows the SLA policy; "
                   "it implies no financial benefit.")
    st.subheader("Why these leads?")
    st.write("Historical data shows substantially higher attendance for demo slots within 48 hours of lead creation. "
             "The queue protects leads closest to the deadline first and uses estimated economic value within each urgency tier.")
    st.caption("Scenario values are based on observational historical differences and should be validated prospectively.")
    with st.expander(f"Other leads and escalations ({len(excluded)})"):
        other = excluded[["lead_id", "lead_status", "queue_state", "reason", "lead_age_hours"]].copy()
        other["Recommended action"] = excluded.recommendation
        other.loc[excluded.queue_state.eq("Breached"), "Recommended action"] = "Breached — escalate separately"
        st.dataframe(other.rename(columns={"lead_id": "Lead ID", "lead_status": "Status", "queue_state": "Current state",
                                          "reason": "Reason", "lead_age_hours": "Age (hours)"}),
                     hide_index=True, width="stretch")
        st.caption("Joined, completed, converted and cancelled leads are always excluded. "
                   "Breached leads require a separate rescue decision; passed slots with open status need review.")
    with st.expander("Inspect a lead"):
        lead_explanation(queue, deployment, commercial)
    with st.expander("How recommendations are calculated"):
        st.write("Only open leads younger than 48 hours with no slot or a slot at/after 48 hours qualify. "
                 "Tiers are Expiring (up to 6h remaining), Soon (up to 24h), then Standard (up to 48h). "
                 "Within a tier, higher scenario value comes first, followed by less time remaining and lead ID.")
        st.write("Urgency represents operational expiry risk and has no monetary multiplier. This policy does not "
                 "mathematically maximize revenue across tiers.")
        st.code("Full observed-gap scenario = max(P_fast − P_late, 0) × conversion after join × revenue\n"
                "Selected scenario = full observed-gap scenario × assumed gap recovery")
        st.caption(f"Deployment estimator: {MODEL_LABELS[deployment.kind]} · "
                   f"Refit on all {deployment.fit_rows:,} historical scheduled leads. "
                   "June evaluation parameters and July holdout metrics remain separate.")
        a, b = st.columns(2)
        a.metric(scenario_name(commercial), money(selected.base_case_recoverable_value.sum()))
        b.metric("Full observed-gap scenario (100%)", money(selected.observational_value_ceiling.sum()))
        st.write(f"Allocated-batch scenario: {selected.scenario_additional_joins.sum():.2f} additional joins → "
                 f"{selected.scenario_additional_conversions.sum():.2f} conversions. These are scenario expectations, "
                 "not observed results or a monthly forecast.")
    with st.expander("Limitations and assumptions"):
        assumptions_panel(commercial)
        st.write("Confirm that every offered slot starts before that lead's deadline and suits the parent. "
                 "Allocation recommends candidates against a slot count; it does not book appointments or verify calendars.")
    with st.expander("Downloads"):
        downloads(queue, selected, sample, clock, crm_timezone, capacity, commercial, history_raw, raw, evaluation, deployment)


def main():
    st.set_page_config(page_title="BrightChamps · 48H Recovery", page_icon="⏱", layout="wide")
    st.markdown("""<style>
        .block-container {padding-top:1.5rem; max-width:1500px;}
        .block-container h1 {font-size:clamp(1.6rem,2.5vw,2.25rem);}
        .block-container h2 {font-size:1.35rem;}
        [data-testid="stMetric"] {border:1px solid #82968d55; padding:12px; border-radius:8px;}
        [data-testid="stMetricLabel"] p {white-space:normal; overflow:visible;}
        [data-testid="stMetricValue"] {font-size:1.65rem;}
        @media (max-width:1100px) {
            .st-key-summary_metrics [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
            .st-key-summary_metrics [data-testid="stColumn"] {
                flex:1 1 calc(50% - 1rem) !important; min-width:calc(50% - 1rem) !important;
            }
        }
        </style>""", unsafe_allow_html=True)
    st.title("48H Demo Recovery Optimizer")
    st.write("Protect time-sensitive demo opportunities before their 48-hour window expires.")
    st.sidebar.title("Recovery workspace")
    mode = st.sidebar.radio("Mode", ["Operational Queue", "Historical Evidence"])
    commercial, options, sensitivity = sidebar_controls(mode)
    try:
        history_raw = (ROOT / "brightchamps.csv").read_bytes()
        history, evaluation, deployment = prepare_history(history_raw)
        if mode == "Operational Queue":
            operational_view(history_raw, evaluation, deployment, commercial, options)
        else:
            historical_view(history, evaluation, deployment, commercial, sensitivity)
    except DataError as exc:
        st.error(str(exc))
        st.dataframe(exc.errors, hide_index=True, width="stretch")
        st.info("No allocation is produced from an invalid file.")
    except (ValueError, OSError) as exc:
        st.error(f"Cannot calculate recommendations: {exc}")


if __name__ == "__main__":
    main()
