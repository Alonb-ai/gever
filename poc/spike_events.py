"""spike הופעות: הזרימה מקצה לקצה מהמאק — resolve (Brave) → browser-use על Browserbase
ב-DRY_RUN → הדפסת ActionResult + נתיב יומן הצעדים.

חוקי ברזל של האבטיפוס:
- DRY_RUN תמיד (מקודד כאן, לא פרמטר) — לעולם לא ממלאים פרטי תשלום. עצירה כנה
  ב-CARD_REQUIRED/MISSING/OPTIONS/FAILED היא הצלחה של האבטיפוס.
- אם חזר details.session_id — משחררים את הסשן מיד (לא מדליפים keepAlive של Browserbase).

הרצה (מתוך שורש ה-worktree, בשביל ה-.env):
    .venv/bin/python poc/spike_events.py ["אמן/מופע"] [DD.MM] [כרטיסים] ["היכל/עיר"] ["העדפות"]
ברירות מחדל: "קובי פרץ" (שני מועדים קרובים בלאן — היכל מנורה 10-11/08/26, נבדק
15.07.26), בלי תאריך (מתרגל את נתיב MISSING:date+OPTIONS), 2 כרטיסים, בלי היכל.
ארגומנט 5 = notes (העדפת קטגוריית מחיר וכו') — עובר ל-task כמו בצינור האמיתי,
כדי לתרגל את ריצת-ההמשך שאחרי MISSING:price_category עד קיר-הכרטיס.
"""

import asyncio
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.browser_book import book_table_bu, release_session  # noqa: E402
from app.automation.resolve import resolve_event_url  # noqa: E402
from app.config import settings  # noqa: E402


def _arg(i: int, default: str) -> str:
    return sys.argv[i] if len(sys.argv) > i and sys.argv[i] else default


async def main() -> None:
    artist = _arg(1, "קובי פרץ")
    when = _arg(2, "")  # בלי ברירת מחדל — ריבוי מועדים אמור לעצור ב-MISSING:date
    party = int(_arg(3, "2"))
    venue = _arg(4, "")
    notes = _arg(5, "")

    if settings.bu_browser != "browserbase":
        print(f"אזהרה: BU_BROWSER={settings.bu_browser!r} (לא browserbase) — רץ לפי ה-.env")

    print(f"spike events: resolve('{artist}', venue={venue!r})...", flush=True)
    found = await resolve_event_url(artist, venue)
    print("resolve:", json.dumps(found, ensure_ascii=False, indent=2), flush=True)
    if found["status"] != "one":
        # many הוא פיצ'ר (המועמדים = המועדים) — אבל לספייק צריך URL אחד; בחר ידנית.
        print(f"resolve לא חד-משמעי (status={found['status']}) — אין ריצת דפדפן.")
        return

    print(
        f"booking (DRY_RUN): {party} כרטיסים, תאריך {when or '(לא צוין)'} → {found['url']}",
        flush=True,
    )
    res = await book_table_bu(
        restaurant=artist,
        page_url=found["url"],
        platform=found.get("platform") or "",
        date=when,
        time="",  # אין שעה מבוקשת בהופעות — נגזרת מהמופע
        party_size=party,
        # פרטי הלקוח האמיתיים (באישור אלון, סבב 4) — כדי לעבור את טופס הפרטים עד
        # קיר-הכרטיס. ת"ז/תשלום לעולם לא: אלה עוצרים MISSING:id_number/CARD_REQUIRED.
        name="אלון בזק",
        email="abazak@gmail.com",
        phone=os.getenv("SPIKE_PHONE", "0544820137"),  # מספר אמיתי לקירות OTP — רק באישור אלון
        dry_run=True,  # חוק ברזל: לעולם לא False באבטיפוס
        task_type="events",
        artist=artist,
        venue=venue,
        notes=notes,
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
    # SPIKE_KEEP=1: משאיר את הסשן חי בכוונה (מבחן לקוח-בלולאה: resume עם קוד SMS
    # אמיתי לאותו סשן; timeout 1800 הוא רשת הביטחון אם לא חוזרים אליו).
    session_id = (res.details or {}).get("session_id")
    if session_id and os.getenv("SPIKE_KEEP") == "1":
        print("session kept alive for resume:", session_id)
    elif session_id:
        await release_session(session_id)
        print("released browserbase session:", session_id)


if __name__ == "__main__":
    asyncio.run(main())
