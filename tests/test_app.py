from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest
from io import StringIO
from datetime import timedelta

from app import queue_display, queue_export
from data import load_live, parse_as_of
from scoring import allocate_capacity, fit_estimator, score_live_queue

APP = Path(__file__).resolve().parents[1] / "app.py"


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def comparison(app):
    return next(table.value for table in app.dataframe
                if "relative_brier_improvement" in table.value.columns)


def test_default_demo_and_capacity_controls():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert widget(app.metric, "Eligible leads at risk").value == "10"
    assert widget(app.metric, "Leads allocated").value == "4"
    assert widget(app.metric, "Early-slot capacity").value == "4"
    assert any(item.value.startswith("Synthetic demo reference time: 2026-08-03 12:00:00 UTC")
               for item in app.caption)
    table = app.dataframe[0].value
    assert "Est. opportunity" in table.columns
    assert table.loc[table["Allocation status"].eq("Allocated"), "Lead ID"].tolist() == ["DEMO-001", "DEMO-018", "DEMO-002", "DEMO-003"]
    assert any("Global estimator selected: historical evidence did not support reliable source/geography differentiation. "
               "All eligible leads therefore share the same estimated opportunity value under the current assumptions. "
               "Because the estimated opportunity is identical across eligible leads, priority is driven by time remaining "
               "before the 48-hour window expires." in item.value for item in app.info)
    widget(app.number_input, "Available early-slot capacity").set_value(0).run()
    assert not app.exception
    assert widget(app.metric, "Leads allocated").value == "0"
    assert widget(app.metric, "Early-slot capacity").value == "0"
    assert app.dataframe[0].value["Allocation status"].eq("Waiting").all()


def test_sensitivity_cannot_rewrite_selection_or_deployment():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    initial_money = widget(app.metric, "Base-case scenario (50% observed-gap recovery)").value
    widget(app.radio, "Mode").set_value("Historical Evidence").run()
    assert not app.exception
    official = comparison(app).copy(deep=True)
    widget(app.slider, "Sensitivity k").set_value(0).run()
    assert not app.exception
    pd.testing.assert_frame_equal(comparison(app), official)
    widget(app.radio, "Mode").set_value("Operational Queue").run()
    assert not app.exception
    assert widget(app.metric, "Base-case scenario (50% observed-gap recovery)").value == initial_money


def test_upload_mode_requires_separate_file():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    widget(app.radio, "Queue source").set_value("Upload live/open-leads CSV").run()
    assert not app.exception
    assert not app.metric
    assert any(item.value.startswith("Queue evaluated as of: ") for item in app.caption)
    assert any("Upload a live/open-leads CSV" in message.value for message in app.info)


def test_invalid_demo_clock_blocks_queue():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    widget(app.text_input, "Demo as_of (UTC)").set_value("not a timestamp").run()
    assert not app.exception
    assert app.error
    assert not app.metric


def test_zero_recovery_is_explicit_scenario():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    widget(app.slider, "Assumed gap recovery (%)").set_value(0).run()
    assert not app.exception
    assert widget(app.metric, "Selected scenario (0% observed-gap recovery)").value == "₹0"
    assert widget(app.metric, "Leads allocated").value == "4"
    assert widget(app.metric, "Early-slot capacity").value == "4"
    assert any("implies no financial benefit" in warning.value for warning in app.warning)


def test_1000_row_presentation_keeps_actions_allocation_and_values_separate(history):
    as_of_text = "2026-08-03 12:00:00"
    created = pd.Timestamp(as_of_text) - pd.Timedelta(hours=43)
    rows = []
    for index in range(1000):
        row_created = created
        if index < 315:
            # Alternate unscheduled and >=48h slots while keeping all eligible leads
            # at the same deadline, exercising value and lead-ID tie breaks.
            status = "open"
            slot = "" if index % 2 == 0 else (created + pd.Timedelta(hours=50)).strftime("%Y-%m-%d %H:%M:%S")
        elif index == 999:
            status = "open"
            row_created = pd.Timestamp(as_of_text) - pd.Timedelta(hours=10)
            slot = (row_created + pd.Timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            status = ["joined", "completed", "converted", "cancelled"][index % 4]
            slot = ""
        rows.append({"lead_id": f"SYN-{index:04d}", "lead_source": "Meta", "geography": "USA",
                     "created_at": row_created.strftime("%Y-%m-%d %H:%M:%S"),
                     "demo_scheduled_at": slot, "lead_status": status})
    raw = pd.DataFrame(rows).to_csv(index=False)
    live = load_live(StringIO(raw), as_of_text)
    clock = parse_as_of(as_of_text)
    scored = allocate_capacity(score_live_queue(live, fit_estimator(history), clock), 4)
    assert int(scored.eligible.sum()) == 315

    # Capture the allocation and full-precision values before making display/export copies.
    allocated_before = scored.loc[scored.allocated, ["rank", "lead_id", "base_case_recoverable_value"]].copy()
    assert allocated_before.lead_id.tolist() == [f"SYN-{index:04d}" for index in range(4)]
    assert allocated_before.base_case_recoverable_value.nunique() == 1
    eligible = scored.loc[scored.eligible]
    display = queue_display(eligible)
    pd.testing.assert_series_equal(display["Est. opportunity"],
                                   eligible.base_case_recoverable_value.rename("Est. opportunity"))
    by_id = display.set_index("Lead ID")
    assert by_id.loc["SYN-0000", "Recommended action"] == "Offer early demo slot"
    assert by_id.loc["SYN-0000", "Allocation status"] == "Allocated"
    assert by_id.loc["SYN-0001", "Recommended action"] == "Pull existing demo forward"
    assert by_id.loc["SYN-0001", "Allocation status"] == "Allocated"
    assert by_id.loc["SYN-0004", "Recommended action"] == "Offer early demo slot"
    assert by_id.loc["SYN-0004", "Allocation status"] == "Waiting"
    assert by_id.loc["SYN-0005", "Recommended action"] == "Pull existing demo forward"
    assert by_id.loc["SYN-0005", "Allocation status"] == "Waiting"

    exported = queue_export(scored).set_index("lead_id")
    assert exported.loc["SYN-0005", "Recommended action"] == "Pull existing demo forward"
    assert exported.loc["SYN-0005", "Allocation status"] == "Waiting"
    exact_value = scored.set_index("lead_id").loc["SYN-0005", "base_case_recoverable_value"]
    assert exported.loc["SYN-0005", "Est. opportunity"] == f"{exact_value:.2f}"
    assert exported.loc["SYN-0315", "Allocation status"] == "Excluded"
    assert scored.set_index("lead_id").loc["SYN-0005", "base_case_recoverable_value"] == exact_value
    pd.testing.assert_series_equal(
        exported.loc[[f"SYN-{index:04d}" for index in range(4)], "rank"].reset_index(drop=True),
        allocated_before["rank"].reset_index(drop=True), check_names=False)
    assert exported.loc[exported["Allocation status"].eq("Allocated")].index.tolist() == allocated_before.lead_id.tolist()
    pd.testing.assert_frame_equal(allocated_before,
        scored.loc[scored.allocated, ["rank", "lead_id", "base_case_recoverable_value"]])
