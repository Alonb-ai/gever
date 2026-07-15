"""spike קולנוע: הזרימה מקצה לקצה מהמאק — resolve (Brave) → browser-use על Browserbase
ב-DRY_RUN → הדפסת ActionResult + נתיב יומן הצעדים.

חוקי ברזל של האבטיפוס:
- DRY_RUN תמיד (מקודד כאן, לא פרמטר) — לעולם לא ממלאים פרטי תשלום. עצירה כנה
  ב-CARD_REQUIRED/MISSING/OPTIONS/FAILED היא הצלחה של האבטיפוס.
- אם חזר details.session_id — משחררים את הסשן מיד (לא מדליפים keepAlive של Browserbase).

הרצה (מתוך שורש ה-worktree, בשביל ה-.env):
    .venv/bin/python poc/spike_cinema.py ["שם סרט"] ["עיר"] [DD.MM] [HH:MM] [כרטיסים]
ברירות מחדל: "האודיסאה", "ראשון לציון", מחר, 20:00, 2.
"""

import asyncio
import glob
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.browser_book import book_table_bu, release_session  # noqa: E402
from app.automation.resolve import resolve_cinema_url  # noqa: E402
from app.config import settings  # noqa: E402

_TOMORROW = date.today() + timedelta(days=1)


def _arg(i: int, default: str) -> str:
    return sys.argv[i] if len(sys.argv) > i and sys.argv[i] else default


async def main() -> None:
    movie = _arg(1, "האודיסאה")
    city = _arg(2, "ראשון לציון")
    when = _arg(3, f"{_TOMORROW.day}.{_TOMORROW.month}")
    at = _arg(4, "20:00")
    party = int(_arg(5, "2"))

    if settings.bu_browser != "browserbase":
        print(f"אזהרה: BU_BROWSER={settings.bu_browser!r} (לא browserbase) — רץ לפי ה-.env")

    print(f"spike cinema: resolve('{movie}')...", flush=True)
    found = await resolve_cinema_url(movie)
    print("resolve:", json.dumps(found, ensure_ascii=False, indent=2), flush=True)
    if found["status"] != "one":
        print(f"resolve לא חד-משמעי (status={found['status']}) — אין ריצת דפדפן.")
        return

    print(
        f"booking (DRY_RUN): {party} כרטיסים, {city}, {when} ~{at} → {found['url']}",
        flush=True,
    )
    res = await book_table_bu(
        restaurant=movie,
        page_url=found["url"],
        platform=found.get("platform") or "",
        date=when,
        time=at,
        party_size=party,
        # פרטי בדיקה מלאים (שם פרטי + משפחה) — כדי לעבור את טופס הפרטים עד קיר-הכרטיס.
        name="אלון ישראלי",
        email="alon.test@example.com",
        phone="0501234567",
        dry_run=True,  # חוק ברזל: לעולם לא False באבטיפוס
        task_type="cinema",
        movie=movie,
        city=city,
    )

    print("\n================ SPIKE RESULT ================")
    print("success:", res.success)
    print("summary:", res.summary)
    print("details:", json.dumps(res.details, ensure_ascii=False, indent=2))

    # נתיב יומן הצעדים (steps_<run_id>.log) — נכתב ל-record_dir, או /tmp בלי הקלטה.
    result_dir = res.details.get("record_dir") or "/tmp"
    logs = sorted(glob.glob(os.path.join(result_dir, "steps_*.log")), key=os.path.getmtime)
    print("steps log:", logs[-1] if logs else "(לא נמצא)")

    # חוק ברזל: סשן חי שחזר (קיר-כרטיס/MISSING משאירים keepAlive) — משוחרר מיד בספייק.
    session_id = (res.details or {}).get("session_id")
    if session_id:
        await release_session(session_id)
        print("released browserbase session:", session_id)


if __name__ == "__main__":
    asyncio.run(main())
