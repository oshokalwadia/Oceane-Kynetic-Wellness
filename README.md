"""
Endurance Coach — daily pipeline.

  WHOOP + TrainingPeaks  ->  compute TDEE / macros / hydration / PMC
  ->  OpenAI coaching brief  ->  Google Sheet (your dashboard source)

Usage:
    python main.py                # process today
    python main.py 2026-06-05     # process a specific date
    python main.py --backfill 14  # process the last 14 days
"""
import argparse
import datetime as dt

from config import config
from clients.whoop import WhoopClient
from clients.trainingpeaks import TrainingPeaksClient
from clients.sheets import SheetStore
from pipeline import build_row


def process_day(day, whoop, tp, store, prev_ctl, prev_atl):
    row, ctl, atl = build_row(day, whoop, tp, prev_ctl, prev_atl)
    store.upsert(row)
    _print_briefing(row)
    return ctl, atl


def _print_briefing(row):
    print("\n" + "═" * 64)
    print(f"  {config.athlete.name.upper()} — DAILY BRIEFING  ·  {row['date']}")
    print("═" * 64)
    print(f"  Recovery {row['recovery_pct']}%   HRV {row['hrv_ms']}ms   "
          f"RHR {row['resting_hr']}   Strain {row['strain']}")
    print(f"  Sleep {row['sleep_hours']}h ({row['sleep_performance_pct']}%)   "
          f"Debt {row['sleep_debt_hours']}h   Resp {row['respiratory_rate']}")
    print(f"  TSS {row['tss']}   CTL {row['ctl']}  ATL {row['atl']}  TSB {row['tsb']}")
    print("-" * 64)
    print(f"  Fuel   {row['cal_target']} kcal  ·  "
          f"P {row['protein_g']}  C {row['carbs_g']}  F {row['fat_g']}")
    print(f"  Hydrate {row['water_l']} L  ·  {row['sodium_mg']} mg sodium")
    print("-" * 64)
    print("  COACH:")
    for line in _wrap(row["recommendation"], 60):
        print("   ", line)
    print("═" * 64 + "\n")


def _wrap(text, width):
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--backfill", type=int, help="process the last N days")
    args = ap.parse_args()

    whoop = None if config.DRY_RUN else WhoopClient()
    tp = TrainingPeaksClient()
    store = SheetStore()
    ctl, atl = store.latest_pmc()

    if args.backfill:
        today = dt.date.today()
        days = [today - dt.timedelta(days=i) for i in range(args.backfill - 1, -1, -1)]
    elif args.date:
        days = [dt.date.fromisoformat(args.date)]
    else:
        days = [dt.date.today()]

    mode = "DRY RUN (mock data)" if config.DRY_RUN else "LIVE"
    print(f"Endurance Coach · {mode} · {len(days)} day(s)")
    for day in days:
        ctl, atl = process_day(day, whoop, tp, store, ctl, atl)


if __name__ == "__main__":
    main()
