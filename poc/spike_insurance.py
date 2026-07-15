"""spike ביטוח: הזרימה מקצה לקצה מהמאק — resolve קבוע (פספורטכארד) → browser-use
על Browserbase ב-DRY_RUN → הדפסת ActionResult + נתיב יומן הצעדים.

חוקי ברזל של האבטיפוס:
- DRY_RUN תמיד (מקודד קשיח כאן, לא פרמטר, עם נעילה שמסרבת לכל עקיפה) — לעולם לא
  ממלאים פרטי תשלום ולא סוגרים פוליסה. עצירה כנה ב-CARD_REQUIRED / MISSING מרובה /
  FAILED (כולל blocked — האתר מחזיר 403 ל-fetch רגיל, ייתכן WAF גם מול Browserbase)
  היא הצלחה של האבטיפוס.
- נתוני דמה בלבד — אף פרט אמיתי של לקוח לא נכנס לספייק.
- session חי שחזר (קיר-כרטיס/MISSING משאירים keepAlive) — משוחרר תמיד ב-finally.

הרצה (מתוך שורש ה-worktree, בשביל ה-.env):
    .venv/bin/python poc/spike_insurance.py ["יעד"] [DD.MM יציאה] [DD.MM חזרה]
ברירות מחדל: "אירופה", מחר, מחר+14. הנוסעים: שני בגירים עם תאריכי לידה דמה.
"""

import asyncio
import glob
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.browser_book import book_table_bu, release_session  # noqa: E402
from app.automation.resolve import resolve_insurance_url  # noqa: E402
from app.config import settings  # noqa: E402

DRY_RUN = True  # חוק ברזל: הספייק מסרב לרוץ אחרת (assert למטה) — אין כאן פרמטר

_TOMORROW = date.today() + timedelta(days=1)
_RETURN = date.today() + timedelta(days=15)


def _arg(i: int, default: str) -> str:
    return sys.argv[i] if len(sys.argv) > i and sys.argv[i] else default


async def main() -> None:
    assert DRY_RUN is True, "הספייק רץ רק ב-DRY_RUN — אין מסלול commit באבטיפוס"
    destination = _arg(1, "אירופה")
    depart = _arg(2, f"{_TOMORROW.day:02d}.{_TOMORROW.month:02d}")
    ret = _arg(3, f"{_RETURN.day:02d}.{_RETURN.month:02d}")

    if settings.bu_browser != "browserbase":
        print(f"אזהרה: BU_BROWSER={settings.bu_browser!r} (לא browserbase) — רץ לפי ה-.env")

    found = await resolve_insurance_url()
    print("resolve:", json.dumps(found, ensure_ascii=False, indent=2), flush=True)

    print(
        f"quote (DRY_RUN): {destination}, {depart} → {ret}, 2 נוסעים → {found['url']}",
        flush=True,
    )
    res = None
    try:
        res = await book_table_bu(
            restaurant=f"ביטוח נסיעות ל{destination}",
            page_url=found["url"],
            platform=found.get("platform") or "",
            date=depart,
            time="",
            party_size=2,
            # נתוני דמה מלאים — כדי להגיע רחוק ככל האפשר לפני עצירת MISSING כנה.
            name="אלון ישראלי",
            email="alon.test@example.com",
            phone="0501234567",
            dry_run=DRY_RUN,  # חוק ברזל: לעולם לא False באבטיפוס
            task_type="insurance",
            insurance={
                "destination": destination,
                "return_date": ret,
                "travelers": ["15.05.1990", "20.11.1992"],
                "health": "אין",
                "addons": "",
            },
        )

        print("\n================ SPIKE RESULT ================")
        print("success:", res.success)
        print("summary:", res.summary)
        print("details:", json.dumps(res.details, ensure_ascii=False, indent=2))

        # נתיב יומן הצעדים (steps_<run_id>.log) — נכתב ל-record_dir, או /tmp בלי הקלטה.
        result_dir = res.details.get("record_dir") or "/tmp"
        logs = sorted(glob.glob(os.path.join(result_dir, "steps_*.log")), key=os.path.getmtime)
        print("steps log:", logs[-1] if logs else "(לא נמצא)")
    finally:
        # חוק ברזל: סשן חי שחזר משוחרר תמיד — גם אם ההדפסות למעלה נפלו.
        session_id = ((res.details or {}) if res else {}).get("session_id")
        if session_id:
            await release_session(session_id)
            print("released browserbase session:", session_id)


if __name__ == "__main__":
    asyncio.run(main())
