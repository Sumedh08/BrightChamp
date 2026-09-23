"""CSV contracts and timestamp validation for two deliberately separate modes."""
from __future__ import annotations

import re
from zoneinfo import ZoneInfo

import pandas as pd

LIVE_COLUMNS = ["lead_id", "lead_source", "geography", "created_at",
                "demo_scheduled_at", "lead_status"]
HISTORICAL_COLUMNS = ["lead_id", "lead_source", "geography", "parent_timezone",
                      "created_at", "demo_scheduled_at", "rep_assigned", "rep_shift",
                      "follow_up_attempts", "demo_joined", "demo_completed", "converted"]
STATUSES = {"open", "joined", "completed", "converted", "cancelled"}
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")


class DataError(ValueError):
    """All errors are surfaced together; an invalid file cannot be allocated."""

    def __init__(self, errors: list[dict] | str):
        if isinstance(errors, str):
            errors = [{"csv_row": "file", "field": "schema", "issue": errors}]
        self.errors = pd.DataFrame(errors)
        super().__init__("Input validation failed. Correct the reported rows and reload.")


def _read(source, required: list[str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise DataError(f"Cannot read CSV: {exc}") from exc
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise DataError("Missing columns: " + ", ".join(missing))
    for column in frame.columns:
        frame[column] = frame[column].str.strip()
    return frame.reset_index(drop=True)


def _issues(errors, mask, field, issue):
    for index in mask[mask.fillna(False)].index:
        errors.append({"csv_row": int(index) + 2, "field": field, "issue": issue})


def _timestamps(frame, errors):
    for column in ("created_at", "demo_scheduled_at"):
        raw = frame[column]
        blank = raw.eq("")
        valid_format = raw.str.fullmatch(TIMESTAMP_PATTERN)
        parsed = pd.to_datetime(raw.where(valid_format), format="mixed", errors="coerce")
        invalid = (~blank & (~valid_format | parsed.isna()))
        if column == "created_at":
            invalid |= blank
        _issues(errors, invalid, column,
                "Use YYYY-MM-DD HH:MM[:SS], without timezone offsets; creation is required.")
        frame[column] = parsed


def _identity(frame, errors):
    for column in ("lead_id", "lead_source", "geography"):
        _issues(errors, frame[column].eq(""), column, "Required value is blank.")
    _issues(errors, frame.lead_id.duplicated(keep=False), "lead_id", "Duplicate lead ID.")


def _delay(frame, errors):
    frame["demo_delay_hours"] = (
        frame.demo_scheduled_at - frame.created_at
    ).dt.total_seconds() / 3600
    _issues(errors, frame.demo_delay_hours.lt(0), "demo_scheduled_at",
            "Demo slot precedes creation.")


def load_historical(source) -> pd.DataFrame:
    """Read the case evidence, preserving naive within-record time differences."""
    frame = _read(source, HISTORICAL_COLUMNS)
    errors = []
    _identity(frame, errors)
    _timestamps(frame, errors)
    _delay(frame, errors)
    if frame.empty:
        raise DataError("Historical data is empty.")
    for column, output in [("demo_joined", "joined"), ("demo_completed", "completed"),
                           ("converted", "conversion")]:
        frame[column] = frame[column].str.upper()
        _issues(errors, ~frame[column].isin(["Y", "N"]), column, "Expected Y or N.")
        frame[output] = frame[column].eq("Y").astype(int)
    _issues(errors, frame.joined.eq(1) & frame.demo_scheduled_at.isna(),
            "demo_joined", "Joined without a scheduled slot.")
    _issues(errors, frame.completed.gt(frame.joined), "demo_completed", "Completed without joining.")
    _issues(errors, frame.conversion.gt(frame.completed), "converted", "Converted without completion.")
    _issues(errors, frame.created_at.notna() & ~frame.created_at.between(
        pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-01"), inclusive="left"),
        "created_at", "This case expects June or July 2026 lead creation.")
    if errors:
        raise DataError(errors)
    frame["cohort"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    scheduled = frame.demo_scheduled_at.notna()
    frame.loc[scheduled & frame.demo_delay_hours.lt(48), "cohort"] = "fast"
    frame.loc[scheduled & frame.demo_delay_hours.ge(48), "cohort"] = "late"
    frame["creation_month"] = frame.created_at.dt.strftime("%Y-%m")
    return frame


def parse_as_of(value: str, crm_timezone: str = "UTC") -> pd.Timestamp:
    """Interpret one system clock, independent of parent display timezones."""
    try:
        ZoneInfo(crm_timezone)
        if not TIMESTAMP_PATTERN.fullmatch(str(value).strip()):
            raise ValueError("Use YYYY-MM-DD HH:MM[:SS], without offsets.")
        return pd.Timestamp(value).tz_localize(
            crm_timezone, ambiguous="raise", nonexistent="raise"
        ).tz_convert("UTC")
    except Exception as exc:
        raise DataError(f"Invalid as_of/system timezone: {exc}") from exc


def load_live(source, as_of: str, crm_timezone: str = "UTC") -> pd.DataFrame:
    """Validate a fresh CRM snapshot; historical outcomes are not a live contract."""
    clock = parse_as_of(as_of, crm_timezone)
    frame = _read(source, LIVE_COLUMNS)
    errors = []
    if {"demo_joined", "demo_completed", "converted"} & set(frame.columns):
        raise DataError("Historical outcome columns are not accepted in live mode. "
                        "Use the separate current-state live template.")
    _identity(frame, errors)
    _timestamps(frame, errors)
    frame["lead_status"] = frame.lead_status.str.lower()
    _issues(errors, ~frame.lead_status.isin(STATUSES), "lead_status",
            "Allowed: open, joined, completed, converted, cancelled.")
    for column in ("created_at", "demo_scheduled_at"):
        localized = []
        for index, value in frame[column].items():
            try:
                localized.append(value.tz_localize(crm_timezone, ambiguous="raise",
                                                  nonexistent="raise").tz_convert("UTC")
                                 if pd.notna(value) else pd.NaT)
            except Exception:
                errors.append({"csv_row": int(index) + 2, "field": column,
                               "issue": "Ambiguous/nonexistent local time; export in UTC instead."})
                localized.append(pd.NaT)
        frame[column] = pd.Series(localized, index=frame.index, dtype="datetime64[ns, UTC]")
    _delay(frame, errors)
    _issues(errors, frame.created_at.gt(clock), "created_at", "Creation is after as_of.")
    if errors:
        raise DataError(errors)
    if "parent_timezone" not in frame:
        frame["parent_timezone"] = ""
    return frame
