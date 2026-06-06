"""
WHOOP API v1 client.

Pulls recovery (HRV, RHR, recovery %), sleep, strain, and workouts.

Auth: OAuth2 authorization-code flow with refresh tokens.
Run the one-time helper to authorise and capture a refresh token:

    python -m clients.whoop

It opens a browser, you log in to WHOOP, and the refresh token is printed +
saved so you can paste it into .env as WHOOP_REFRESH_TOKEN.

Docs: https://developer.whoop.com/api
"""
import datetime as dt
import json
import os
import webbrowser
from urllib.parse import urlencode

import requests

from config import config

API = "https://api.prod.whoop.com/developer/v1"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
SCOPES = "read:recovery read:sleep read:workout read:cycles read:profile read:body_measurement offline"
TOKEN_CACHE = ".whoop_token.json"


class WhoopClient:
    def __init__(self):
        self.access_token = None
        self.refresh_token = config.WHOOP_REFRESH_TOKEN or self._cached_refresh()

    # ---------- token handling ----------
    def _cached_refresh(self):
        if os.path.exists(TOKEN_CACHE):
            with open(TOKEN_CACHE) as f:
                return json.load(f).get("refresh_token")
        return None

    def _save_refresh(self, token):
        with open(TOKEN_CACHE, "w") as f:
            json.dump({"refresh_token": token}, f)

    def _refresh_access_token(self):
        if not self.refresh_token:
            raise RuntimeError(
                "No WHOOP refresh token. Run `python -m clients.whoop` once to authorise."
            )
        resp = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": config.WHOOP_CLIENT_ID,
            "client_secret": config.WHOOP_CLIENT_SECRET,
            "scope": SCOPES,
        }, timeout=30)
        resp.raise_for_status()
        tok = resp.json()
        self.access_token = tok["access_token"]
        # WHOOP rotates refresh tokens — persist the new one.
        if tok.get("refresh_token"):
            self.refresh_token = tok["refresh_token"]
            self._save_refresh(self.refresh_token)
        return self.access_token

    def _headers(self):
        if not self.access_token:
            self._refresh_access_token()
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, path, params=None):
        r = requests.get(f"{API}{path}", headers=self._headers(), params=params, timeout=30)
        if r.status_code == 401:                     # token expired mid-run
            self._refresh_access_token()
            r = requests.get(f"{API}{path}", headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ---------- data ----------
    def fetch_day(self, day: dt.date) -> dict:
        """Return a normalised dict of the metrics we care about for `day`."""
        start = dt.datetime.combine(day, dt.time.min).isoformat() + "Z"
        end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min).isoformat() + "Z"
        win = {"start": start, "end": end, "limit": 25}

        recovery = self._first(self._get("/recovery", win))
        cycle = self._first(self._get("/cycle", win))
        sleep = self._first(self._get("/activity/sleep", win))
        workouts = self._get("/activity/workout", win).get("records", [])

        rec_score = (recovery or {}).get("score", {})
        cyc_score = (cycle or {}).get("score", {})
        slp_score = (sleep or {}).get("score", {})
        stage = slp_score.get("stage_summary", {})

        sleep_needed = stage.get("sleep_needed_milli")
        sleep_total = self._sleep_total_milli(stage)
        debt_hours = None
        if sleep_needed and sleep_total is not None:
            debt_hours = round(max(0, sleep_needed - sleep_total) / 3_600_000, 1)

        return {
            "date": day.isoformat(),
            "recovery_pct": rec_score.get("recovery_score"),
            "hrv_ms": _round(rec_score.get("hrv_rmssd_milli")),
            "resting_hr": rec_score.get("resting_heart_rate"),
            "strain": _round(cyc_score.get("strain"), 1),
            "kilojoules": _round(cyc_score.get("kilojoule")),
            "calories_burned": _round((cyc_score.get("kilojoule") or 0) / 4.184),
            "sleep_performance_pct": slp_score.get("sleep_performance_percentage"),
            "sleep_hours": _round((sleep_total or 0) / 3_600_000, 1) if sleep_total else None,
            "sleep_debt_hours": debt_hours,
            "respiratory_rate": _round(slp_score.get("respiratory_rate"), 1),
            "workouts": [self._norm_workout(w) for w in workouts],
        }

    @staticmethod
    def _sleep_total_milli(stage):
        keys = ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli",
                "total_rem_sleep_time_milli")
        vals = [stage.get(k) for k in keys if stage.get(k) is not None]
        return sum(vals) if vals else None

    @staticmethod
    def _norm_workout(w):
        s = w.get("score", {})
        return {
            "sport": w.get("sport_name") or w.get("sport_id"),
            "strain": _round(s.get("strain"), 1),
            "calories": _round((s.get("kilojoule") or 0) / 4.184),
            "avg_hr": s.get("average_heart_rate"),
            "max_hr": s.get("max_heart_rate"),
            "distance_m": _round(s.get("distance_meter")),
            "duration_min": WhoopClient._duration_min(w),
        }

    @staticmethod
    def _duration_min(w):
        try:
            a = dt.datetime.fromisoformat(w["start"].replace("Z", "+00:00"))
            b = dt.datetime.fromisoformat(w["end"].replace("Z", "+00:00"))
            return round((b - a).total_seconds() / 60)
        except Exception:
            return None

    @staticmethod
    def _first(payload):
        recs = payload.get("records", []) if isinstance(payload, dict) else []
        return recs[0] if recs else None


def _round(x, n=0):
    if x is None:
        return None
    return round(x, n) if n else round(x)


# ────────────────────────── one-time auth helper ──────────────────────────
def authorise():
    """Run a local server, complete WHOOP OAuth, print the refresh token."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs

    if not (config.WHOOP_CLIENT_ID and config.WHOOP_CLIENT_SECRET):
        raise SystemExit("Set WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET in .env first.")

    code_holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            code_holder["code"] = qs.get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"WHOOP authorised. You can close this tab.")

        def log_message(self, *a):
            pass

    params = {
        "response_type": "code",
        "client_id": config.WHOOP_CLIENT_ID,
        "redirect_uri": config.WHOOP_REDIRECT_URI,
        "scope": SCOPES,
        "state": "coach",
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    print("Opening browser for WHOOP login:\n", url)
    webbrowser.open(url)

    port = int(config.WHOOP_REDIRECT_URI.rsplit(":", 1)[-1].split("/")[0])
    HTTPServer(("localhost", port), Handler).handle_request()
    code = code_holder.get("code")
    if not code:
        raise SystemExit("No authorization code received.")

    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.WHOOP_CLIENT_ID,
        "client_secret": config.WHOOP_CLIENT_SECRET,
        "redirect_uri": config.WHOOP_REDIRECT_URI,
    }, timeout=30)
    resp.raise_for_status()
    refresh = resp.json().get("refresh_token")
    WhoopClient()._save_refresh(refresh)
    print("\n✅ Success. Add this to your .env:\n")
    print(f"WHOOP_REFRESH_TOKEN={refresh}")


if __name__ == "__main__":
    authorise()
