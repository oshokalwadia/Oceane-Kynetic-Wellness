"""
Google Sheets storage.

Each run appends (or updates) one row per day in a worksheet called "Daily".
The row carries every metric + the AI recommendation so the sheet doubles as
your historical database and dashboard source.

Setup (see README): create a service account, download its JSON key, share the
target spreadsheet with the service-account email as Editor.
"""
import datetime as dt

from config import config

HEADERS = [
    "date", "recovery_pct", "hrv_ms", "resting_hr", "strain",
    "calories_burned", "tdee", "sleep_hours", "sleep_performance_pct",
    "sleep_debt_hours", "respiratory_rate", "tss", "ctl", "atl", "tsb",
    "cal_target", "protein_g", "carbs_g", "fat_g",
    "water_l", "sodium_mg", "recommendation",
]


class SheetStore:
    def __init__(self):
        self.ws = None
        if not config.DRY_RUN:
            self._connect()

    def _connect(self):
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(config.GOOGLE_SA_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        try:
            sh = gc.open(config.GOOGLE_SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(config.GOOGLE_SHEET_NAME)
        try:
            self.ws = sh.worksheet("Daily")
        except gspread.WorksheetNotFound:
            self.ws = sh.add_worksheet("Daily", rows=400, cols=len(HEADERS))
        # Ensure header row.
        if self.ws.row_values(1) != HEADERS:
            self.ws.update("A1", [HEADERS])

    def latest_pmc(self) -> tuple[float, float]:
        """Return (CTL, ATL) from the most recent row, or (0, 0)."""
        if self.ws is None:
            return 0.0, 0.0
        records = self.ws.get_all_records()
        if not records:
            return 0.0, 0.0
        last = records[-1]
        return float(last.get("ctl") or 0), float(last.get("atl") or 0)

    def read_recent(self, n: int = 14) -> list[dict]:
        """Return the last `n` rows as dicts (newest last). [] if empty/DRY_RUN."""
        if self.ws is None:
            return []
        records = self.ws.get_all_records()
        return records[-n:]

    def upsert(self, row: dict):
        ordered = [row.get(h, "") for h in HEADERS]
        if self.ws is None:                      # DRY_RUN: print instead of write
            print("[DRY_RUN] would write row to Google Sheet 'Daily':")
            for h in HEADERS:
                print(f"    {h:22} {row.get(h, '')}")
            return
        # Update existin