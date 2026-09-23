from io import StringIO

import pandas as pd
import pytest

from data import DataError, load_historical, load_live, parse_as_of

HEADER = "lead_id,lead_source,geography,created_at,demo_scheduled_at,lead_status\n"


def test_case_funnel(history):
    assert len(history) == 5000
    assert history.demo_scheduled_at.notna().sum() == 3229
    assert history.joined.sum() == 2060
    assert history.completed.sum() == 1786
    assert history.conversion.sum() == 362


@pytest.mark.parametrize("row,field", [
    ("A,Meta,USA,2026-08-02 12:00,,wrong", "lead_status"),
    ("A,Meta,USA,2026-08-04 12:00,,open", "created_at"),
    ("A,Meta,USA,2026-08-02 12:00,2026-08-01 12:00,open", "demo_scheduled_at"),
    ("A,Meta,USA,bad,,open", "created_at"),
    ("A,,USA,2026-08-02 12:00,,open", "lead_source"),
    ("A,Meta,USA,2026-08-02T12:00:00Z,,open", "created_at"),
])
def test_invalid_live_blocks_allocation(row, field):
    with pytest.raises(DataError) as error:
        load_live(StringIO(HEADER + row), "2026-08-03 12:00")
    assert field in error.value.errors.field.values
    assert 2 in error.value.errors.csv_row.values


def test_duplicate_ids_rejected():
    row = "A,Meta,USA,2026-08-02 12:00,,open\n"
    with pytest.raises(DataError):
        load_live(StringIO(HEADER + row * 2), "2026-08-03 12:00")


def test_history_cannot_be_live(history):
    with pytest.raises(DataError):
        load_live(StringIO(history.to_csv(index=False)), "2026-08-03 12:00")
    modified = history.copy()
    modified["lead_status"] = "open"
    with pytest.raises(DataError):
        load_live(StringIO(modified.to_csv(index=False)), "2026-08-03 12:00")


def test_funnel_inconsistency_rejected(history):
    raw = history.iloc[:3].copy()
    raw.loc[raw.index[0], "demo_completed"] = "Y"
    raw.loc[raw.index[0], "demo_joined"] = "N"
    with pytest.raises(DataError) as error:
        load_historical(StringIO(raw.to_csv(index=False)))
    assert "Completed without joining." in error.value.errors.issue.values


def test_consistent_timezone_and_parent_ignored():
    data = HEADER.rstrip() + ",parent_timezone\nA,Meta,USA,2026-08-02 12:00,2026-08-04 12:00,open,America/New_York"
    frame = load_live(StringIO(data), "2026-08-03 12:00", "Asia/Kolkata")
    assert frame.created_at.iloc[0] == pd.Timestamp("2026-08-02 06:30Z")
    assert frame.demo_delay_hours.iloc[0] == 48


@pytest.mark.parametrize("date", ["2026-03-08 02:30", "2026-11-01 01:30"])
def test_dst_invalid_local_time(date):
    with pytest.raises(DataError):
        load_live(StringIO(HEADER + f"A,Meta,USA,{date},,open"),
                  "2026-12-01 12:00", "America/New_York")


def test_header_only_live_is_valid_empty():
    assert load_live(StringIO(HEADER), "2026-08-03 12:00").empty


def test_as_of_timezone_error():
    with pytest.raises(DataError):
        parse_as_of("2026-08-03 12:00", "Not/AZone")
