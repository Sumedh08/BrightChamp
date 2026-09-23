import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data import load_historical, load_live, parse_as_of


@pytest.fixture(scope="session")
def history():
    return load_historical(ROOT / "brightchamps.csv")


@pytest.fixture
def live():
    return load_live(ROOT / "sample_live_queue.csv", "2026-08-03 12:00:00")


@pytest.fixture
def clock():
    return parse_as_of("2026-08-03 12:00:00")
