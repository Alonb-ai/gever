"""nav_bench — קו הבסיס של הנווט: סט קבוע של משימות הזמנה אמיתיות (DRY_RUN, נעצר
לפני תשלום) על המודל הנוכחי. מחליפים מודל → מריצים שוב את אותו סט → משווים.

מדדים לכל משימה: תוצאה (summary/card=הצלחה), צעדים (מיומן ה-runner), זמן.
ריצה סדרתית בכוונה — זיהוי קובץ יומן-הצעדים החדש ב-/tmp הוא לפי snapshot לפני/אחרי.

הרצה:  .venv/bin/python poc/nav_bench.py          # ~30-50 דק', פלט markdown ל-stdout
"""

import asyncio
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.browser_book import book_table_bu  # noqa: E402
from app.automation.resolve import resolve_reservation_url  # noqa: E402
from app.config import settings  # noqa: E402

# הסט הקבוע — לא לשנות בין ריצות השוואה. תאריך/שעה/סועדים זהים לכולן.
RESTAURANTS = [
    "אסה איזקאיה תל אביב",
    "טאיזו תל אביב",
    "קלארו תל אביב",
    "רוסטיקו בזל תל אביב",
    "מסא תל אביב",
    "אנימאר תל אביב",
    "הדסון ראשון לציון",
    "OCD תל אביב",
]
DATE, TIME, PARTY = "2026-07-21", "20:00", 2
# פרטים מלאים כמו שהפייפליין בפרוד אוסף מראש (intake) — בלעדיהם הריצה עוצרת
# עצירת MISSING כנה על אזור ישיבה/שם משפחה במקום להגיע עד הסיכום (לקח ריצה 1).
# פרטים אמיתיים-למראה באישור אלון (16.7): אונטופו ופספורטכארד דוחים נתוני דמה
# קנוניים (0501234567 / example.com) בצד השרת. DRY_RUN — שום הזמנה לא נסגרת.
DETAILS = {
    "name": "אלון בזק",
    "phone": "0544820137",
    "email": "abazak@gmail.com",
    "notes": "ישיבה בפנים או מה שנוח, אין העדפות מיוחדות",
}


def _count_steps(tail: str) -> int | None:
    nums = [int(m) for m in re.findall(r"Step (\d+)", tail)]
    return max(nums) if nums else None


def _outcome(details: dict) -> str:
    if details.get("card_required"):
        return "card_wall"
    if details.get("summary_reached"):
        return "summary"
    if details.get("missing"):
        return f"missing:{details['missing']}"
    if details.get("failed"):
        return f"failed:{details['failed']}"
    return f"other:{details.get('stage', '')[:40]}"


async def _resolve_retry(name: str) -> dict:
    """Brave נחנק ב-429 בקריאות צפופות (בפרוד השיחה מרווחת אותן) — עד 3 ניסיונות."""
    for attempt in range(3):
        try:
            return await resolve_reservation_url(name)
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            await asyncio.sleep(10)
    raise RuntimeError("unreachable")


async def bench_one(name: str) -> dict:
    row = {"restaurant": name, "model": settings.model_name}
    res = await _resolve_retry(name)
    if res.get("status") == "many" and res.get("candidates"):
        # בפרוד הלקוח בוחר סניף מהרשימה; בבנצ' — המועמד הראשון (ה-match החזק ביותר)
        top = res["candidates"][0]
        res = {"status": "one", "url": top["url"], "platform": top.get("platform", "")}
        row["picked"] = top.get("title", "")[:40]
    if res.get("status") != "one":
        row["outcome"] = f"resolve:{res.get('status')}"  # לא נספר כניווט
        return row
    row["platform"] = res.get("platform")
    t0 = time.time()
    result = await book_table_bu(
        restaurant=name,
        page_url=res["url"],
        platform=res.get("platform", ""),
        date=DATE,
        time=TIME,
        party_size=PARTY,
        time_flex=True,
        **DETAILS,
    )
    row["seconds"] = round(time.time() - t0)
    tail = result.details.get("steps_tail") or ""
    row["steps"] = _count_steps(tail)
    row["tail"] = tail  # פורנזיקה איכותנית — הקבצים ב-/tmp לא שורדים את ה-sandbox
    row["outcome"] = _outcome(result.details)
    return row


async def main() -> None:
    rows = []
    for name in RESTAURANTS:
        await asyncio.sleep(5)  # מרווח נשימה ל-Brave בין משימות
        print(f"⏳ {name} ...", file=sys.stderr, flush=True)
        try:
            row = await bench_one(name)
        except Exception as e:  # noqa: BLE001 — משימה שקרסה נרשמת, הבנצ' ממשיך
            row = {"restaurant": name, "outcome": f"crash:{e}"}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), file=sys.stderr, flush=True)

    nav = [r for r in rows if not str(r["outcome"]).startswith(("resolve:", "crash:"))]
    ok = [r for r in nav if r["outcome"] in ("card_wall", "summary")]
    honest = [r for r in nav if str(r["outcome"]).startswith("missing:")]
    print(f"\n## קו בסיס נווט — {settings.model_name} — {time.strftime('%d.%m.%Y')}\n")
    print("| מסעדה | פלטפורמה | תוצאה | צעדים | שניות |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['restaurant']} | {r.get('platform', '—')} | {r['outcome']} "
            f"| {r.get('steps', '—')} | {r.get('seconds', '—')} |"
        )
    if nav:
        steps = [r["steps"] for r in ok if r.get("steps")]
        secs = [r["seconds"] for r in ok if r.get("seconds")]
        print(
            f"\n**הגיעו לסיכום/קיר-כרטיס: {len(ok)}/{len(nav)} "
            f"({100 * len(ok) // len(nav)}%) · עצירות MISSING כנות: {len(honest)}**"
        )
        if steps and secs:
            print(
                f"ממוצע למשימה מוצלחת: {sum(steps) / len(steps):.0f} צעדים, "
                f"{sum(secs) / len(secs) / 60:.1f} דק' ({sum(secs) / sum(steps):.1f} שנ'/צעד)"
            )
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
