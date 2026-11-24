import datetime

TIERS = (("A", 70), ("B", 50))


def recency(newest_signal: str, today: datetime.date) -> float:
    """1.0 up to 365 days old, 0.6 from 1095 days, linear between; bad dates get the floor."""
    try:
        age = (today - datetime.date.fromisoformat(newest_signal)).days
    except (ValueError, TypeError):
        return 0.6
    if age <= 365:
        return 1.0
    if age >= 1095:
        return 0.6
    return 1.0 - 0.4 * (age - 365) / 730


def score(fit: int, match: float, newest_signal: str, today: datetime.date, email_status: str = "") -> int:
    s = round((0.6 * fit + 40 * match) * recency(newest_signal, today))
    if email_status == "valid":
        s += 5
    return max(0, min(100, s))


def tier(score: int) -> str:
    return next((name for name, floor in TIERS if score >= floor), "C")
