"""spike_speed: מדידת זמן ריצה של browser-use דרך book_table_bu האמיתי (Browserbase).

שימש ל-A/B שקבע את דגלי המהירות ב-bu_runner (15.7.26): baseline ממוצע 251.5s
(23.7-34.8s לצעד) מול flash_mode+use_judge=False ממוצע 165.4s (17.4-17.5s לצעד) —
‎~34%‎ חיסכון, אותה עצירה כנה (MISSING:last_name, פרטים נכונים, בלי לופים).
נשאר ככלי מדידה: מריץ DRY_RUN recon להדסון לילינבלום (Ontopo), מחר 20:00, 2 סועדים,
ומדפיס זמן/צעדים/איכות. משחרר תמיד את סשן ה-Browserbase בסוף.

הרצה (מתוך ה-worktree):
    .venv/bin/python poc/spike_speed.py
"""

import asyncio
import glob
import os
import re
import sys
import time
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)  # ה-app של ה-worktree (לא ה-editable install של הריפו הראשי)
os.chdir(_ROOT)  # .env + .venv-bu יחסיים ל-worktree
os.environ["BU_RECORD_DIR"] = ""  # בלי GIF/וידאו — יצירת GIF מזהמת את מדידת הזמן

from app.automation import browser_book  # noqa: E402
from app.automation.browser_book import book_table_bu, release_session  # noqa: E402

URL = "https://ontopo.com/he/il/page/22512632"  # הדסון לילינבלום
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def _count_steps(started_after: float) -> tuple[int, str]:
    """מספר הצעדים מיומן steps_<run_id>.log הטרי ביותר (נכתב ל-/tmp כשאין record_dir)."""
    logs = [p for p in glob.glob("/tmp/steps_*.log") if os.path.getmtime(p) > started_after]
    if not logs:
        return -1, "(אין יומן)"
    path = max(logs, key=os.path.getmtime)
    with open(path, encoding="utf-8", errors="replace") as f:
        nums = [int(m) for m in re.findall(r"📍 Step (\d+):", f.read())]
    return max(nums) if nums else 0, path


async def main() -> None:
    browser_book.BU_TIMEOUT_S = 540  # שה-timeout הפנימי (עם release) יקדים כל kill חיצוני

    print(f"spike_speed — Ontopo הדסון, {TOMORROW} 20:00, 2 סועדים", flush=True)
    wall0 = time.time()
    t0 = time.monotonic()
    res = await book_table_bu(
        restaurant="הדסון לילינבלום",
        page_url=URL,
        platform="ontopo",
        date=TOMORROW,
        time="20:00",
        party_size=2,
        name="אלון",
        email="abazak@gmail.com",
        phone="+972542773331",
        dry_run=True,  # recon בלבד — לעולם לא סוגרים ולא מזינים תשלום
    )
    elapsed = time.monotonic() - t0
    d = res.details or {}
    # קיר-כרטיס/MISSING משאירים סשן חי בכוונה (pause-resume) — בניסוי משחררים תמיד
    if d.get("session_id"):
        await release_session(d["session_id"])
        print(f"released session {d['session_id']}", flush=True)
    steps, steps_log = _count_steps(wall0 - 1)

    print("\n================ SPEED RESULT ================")
    print(f"elapsed={elapsed:.1f}s  steps={steps}  log={steps_log}")
    print(
        f"success={res.success}  summary_reached={d.get('summary_reached')}  "
        f"card_required={d.get('card_required')}  missing={d.get('missing')!r}  "
        f"failed={d.get('failed')!r}  time={d.get('time')!r}"
    )
    print("--- דיווח סופי של ה-agent ---")
    print((res.summary or "").strip()[-1500:])


if __name__ == "__main__":
    asyncio.run(main())
