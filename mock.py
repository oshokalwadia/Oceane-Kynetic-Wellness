"""
TrainingPeaks client.

Pulls planned + completed workouts and TSS so we can maintain the
Performance Management Chart metrics:

    CTL (Chronic Training Load)  ~ "fitness"  = 42-day EWMA of TSS
    ATL (Acute Training Load)    ~ "fatigue"  = 7-day  EWMA of TSS
    TSB (Training Stress Balance)~ "form"     = CTL_yesterday - ATL_yesterday

NOTE ON ACCESS
--------------
TrainingPeaks does not offer a self-serve public API; access requires partner
approval. If you don't have a token, leave TRAININGPEAKS_TOKEN blank — the
pipeline automatically derives a TSS estimate from your WHOOP workout strain
instead, so CTL/ATL/TSB still work. Swap in the real client whenever you get
credentials; the interface below is all main.py depends on.
"""
import datetime as dt

import requests

from config import config

BASE = "https://api.trainingpeaks.com/v1"   # adjust to your partner endpoint


class TrainingPeaksClient:
    def __init__(self):
        self.enabled = bool(config.TP_TOKEN and config.TP_ATHLETE_ID)

    def fetch_workouts(self, day: dt.date) -> list[dict]:
        """Return completed workouts for `day` with a `tss` field, or []."""
        if not self.enabled:
            return []
        headers = {"Authorization": f"Bearer {config.TP_TOKEN}"}
        url = f"{BASE}/athletes/{config.TP_ATHLETE_ID}/workouts/{day.isoformat()}"
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        out = []
        for w in r.json():
            out.append({
                "title": w.get("Title") or w.get("title"),
                "tss": w.get("TssActual") or w.get("tss"),
                "duration_min": _minutes(w.get("TotalTime") or w.get("totalTime")),
                "distance_m": w.get("DistanceInMeters") or w.get("distance"),
                "if": w.get("IntensityFactor") or w.get("if"),
            })
        return out


def estimate_tss_from_strain(strain: float | None, duration_min: float | None) -> float:
    """
    Fallback TSS when TrainingPeaks isn't connected.

    WHOOP strain is a 0-21 logarithmic scale. We map it to a daily training
    stress score using a simple, transparent heuristic: TSS ≈ strain^2 * k,
    lightly scaled by duration. It's an approximation, not gospel — but it
    keeps the CTL/ATL/TSB trend meaningful from WHOOP data alone.
    """
    if not strain:
        return 0.0
    base = (strain ** 2) * 0.5            # strain 10 -> 50, strain 15 -> ~112
    if duration_min:
        base *= min(1.5, max(0.6, duration_min / 60))
    return round(base, 1)


def pmc_update(prev_ctl: float, prev_atl: float, todays_tss: float) -> dict:
    """Advance the Performance Management Chart by one day."""
    ctl = prev_ctl + (todays_tss - prev_ctl) / 42.0
    atl = prev_atl + (todays_tss - prev_atl) / 7.0
    tsb = prev_ctl - prev_atl             # form uses *yesterday's* values
    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1)}


def _minutes(seconds_or_hours):
    if seconds_or_hours is None:
        return None
    # TP TotalTime is in hours (float); be tolerant.
    val = float(seconds_or_hours)
    return round(val * 60) if val < 24 else round(val / 60)
