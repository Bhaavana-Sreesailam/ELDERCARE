"""
ElderCare Guardian - Health analytics (pandas).

Turns the raw stream of readings into the human-friendly summaries the
dashboard shows: today's heart-rate range, resting average, a simple
wellness score, and per-day trends.
"""

import pandas as pd

import config
import database as db


def _frame(hours):
    """Load readings into a DataFrame with a parsed timestamp index."""
    rows = db.get_readings_since(hours=hours)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    # Keep only physiologically meaningful heart-rate values.
    frame.loc[frame["heart_rate"] < config.HR_VALID_MIN, "heart_rate"] = pd.NA
    return frame


def summary(hours=24):
    """Headline numbers for the dashboard cards."""
    frame = _frame(hours)
    if frame.empty or frame["heart_rate"].dropna().empty:
        return {
            "samples": 0,
            "hr_min": None, "hr_max": None, "hr_avg": None, "hr_resting": None,
            "alerts": len(db.get_alerts(limit=1000)),
            "wellness": None,
        }

    hr = frame["heart_rate"].dropna()
    # "Resting" approximated as the 20th percentile of recent readings.
    resting = float(hr.quantile(0.20))

    return {
        "samples": int(len(frame)),
        "hr_min": float(hr.min()),
        "hr_max": float(hr.max()),
        "hr_avg": float(hr.mean()),
        "hr_resting": resting,
        "alerts": len(db.get_alerts(limit=1000)),
        "wellness": _wellness_score(hr, resting),
    }


def _wellness_score(hr, resting):
    """
    A light-touch 0-100 indicator, NOT a medical metric. It rewards a
    resting rate inside a healthy band and penalises time spent outside
    the warning thresholds. Useful as a glanceable trend, nothing more.
    """
    score = 100.0

    # Penalise an out-of-band resting rate.
    if resting < config.HR_WARNING_LOW:
        score -= (config.HR_WARNING_LOW - resting) * 1.5
    elif resting > config.HR_WARNING_HIGH:
        score -= (resting - config.HR_WARNING_HIGH) * 1.5

    # Penalise the share of readings outside the warning band.
    out = ((hr < config.HR_WARNING_LOW) | (hr > config.HR_WARNING_HIGH)).mean()
    score -= out * 40

    return max(0, min(100, round(score)))


def hourly_trend(hours=24):
    """
    Average heart rate per hour, for a trend chart. Returns parallel
    lists of labels and values so the frontend can plot them directly.
    """
    frame = _frame(hours)
    if frame.empty or frame["heart_rate"].dropna().empty:
        return {"labels": [], "values": []}

    frame = frame.set_index("timestamp")
    hourly = frame["heart_rate"].resample("1h").mean().dropna()

    return {
        "labels": [ts.strftime("%b %d %H:%M") for ts in hourly.index],
        "values": [round(float(v), 1) for v in hourly.values],
    }


def daily_trend(days=7):
    """Min / average / max heart rate per day for the last `days` days."""
    frame = _frame(hours=days * 24)
    if frame.empty or frame["heart_rate"].dropna().empty:
        return []

    frame = frame.set_index("timestamp")
    grouped = frame["heart_rate"].resample("1D").agg(["min", "mean", "max"]).dropna()

    return [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "min": round(float(row["min"]), 1),
            "avg": round(float(row["mean"]), 1),
            "max": round(float(row["max"]), 1),
        }
        for idx, row in grouped.iterrows()
    ]
