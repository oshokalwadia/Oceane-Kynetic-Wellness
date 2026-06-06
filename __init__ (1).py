"""
OpenAI coaching layer.

Takes the full day's metrics (biometrics + computed macros/hydration/PMC) and
returns a concise, athlete-facing recommendation written like a real endurance
coach: what today's numbers mean and exactly what to do about training,
fuelling, hydration and recovery.

In DRY_RUN (or with no API key) it falls back to a rules-based summary so the
pipeline always produces output.
"""
import json

from config import config

SYSTEM = (
    "You are an elite endurance coach and sports nutritionist. You read an "
    "athlete's daily WHOOP recovery, HRV, sleep, strain and TrainingPeaks "
    "CTL/ATL/TSB, plus their computed calorie/macro/hydration targets. "
    "Give a short, direct, actionable daily briefing (max ~150 words). "
    "Cover: (1) how to train today given recovery & form, (2) fuelling/macro "
    "emphasis, (3) hydration, (4) one recovery action. Be specific and "
    "encouraging, never alarmist. No markdown headers."
)


def generate(payload: dict) -> str:
    if config.DRY_RUN or not config.OPENAI_API_KEY:
        return _fallback(payload)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            temperature=0.5,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:                        # never let the API break the run
        return _fallback(payload) + f"\n\n(Note: OpenAI call failed: {e})"


def _fallback(p: dict) -> str:
    rec = p.get("recovery_pct")
    tsb = p.get("tsb")
    m = p.get("macros", {})
    h = p.get("hydration", {})

    if rec is None:
        load = "Train to feel."
    elif rec >= 67:
        load = "Green recovery — good day for a key/quality session or intervals."
    elif rec >= 34:
        load = "Yellow recovery — moderate aerobic work; keep intensity in check."
    else:
        load = "Red recovery — prioritise easy Z1–Z2 or rest. Don't force it."

    form = ""
    if tsb is not None:
        if tsb < -20:
            form = " You're carrying heavy fatigue (low TSB) — watch for overreaching."
        elif tsb > 10:
            form = " You're fresh (high TSB) — a good window to race or test."

    return (
        f"{load}{form} "
        f"Fuel ~{m.get('calories','?')} kcal: {m.get('protein_g','?')}g protein, "
        f"{m.get('carbs_g','?')}g carbs, {m.get('fat_g','?')}g fat"
        f"{' (carb-load / refuel day)' if m.get('refuel_day') else ''}. "
        f"Hydrate to ~{h.get('water_l','?')}L with ~{h.get('sodium_mg','?')}mg sodium; "
        f"{h.get('electrolytes_note','').lower()}. "
        f"Recovery: protect sleep tonight — aim to clear any sleep debt "
        f"({p.get('sleep_debt_hours','?')}h) with an earlier lights-out."
    )
