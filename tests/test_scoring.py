import datetime

import pytest

from app.scoring import recency, score, tier

TODAY = datetime.date(2026, 11, 24)


def ago(days):
    return (TODAY - datetime.timedelta(days=days)).isoformat()


@pytest.mark.parametrize("days,expected", [(0, 1.0), (365, 1.0), (1095, 0.6), (5000, 0.6)])
def test_recency_bounds(days, expected):
    assert recency(ago(days), TODAY) == pytest.approx(expected)


def test_recency_midpoint():
    assert recency(ago(730), TODAY) == pytest.approx(0.8, abs=0.001)


def test_recency_just_past_365_drops():
    assert recency(ago(366), TODAY) < 1.0


def test_recency_future_date_is_fresh():
    assert recency("2027-01-01", TODAY) == 1.0


@pytest.mark.parametrize("bad", ["", "not a date", "2026-13-40", None])
def test_recency_unparseable_gets_floor(bad):
    assert recency(bad, TODAY) == 0.6


def test_score_formula():
    assert score(70, 0.5, ago(10), TODAY) == 62  # 0.6*70 + 40*0.5


def test_score_decays_with_age():
    assert score(70, 0.5, ago(1095), TODAY) == round(62 * 0.6)


def test_score_email_bonus_only_when_valid():
    base = score(70, 0.5, ago(10), TODAY)
    assert score(70, 0.5, ago(10), TODAY, "valid") == base + 5
    assert score(70, 0.5, ago(10), TODAY, "risky") == base


def test_score_clamps():
    assert score(100, 1.0, ago(0), TODAY, "valid") == 100
    assert score(-50, 0.0, ago(0), TODAY) == 0


@pytest.mark.parametrize("s,t", [(0, "C"), (49, "C"), (50, "B"), (69, "B"), (70, "A"), (100, "A")])
def test_tier_boundaries(s, t):
    assert tier(s) == t
