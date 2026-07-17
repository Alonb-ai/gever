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

# מדד "יעד נכון" (דוח השוואת המודלים 17.7): מדד "הגעה לסיכום" עיוור ליעד ותיגמל
# נחיתות שגויות (אסה→גייג'ין, בזל→רוטשילד, ראשל"צ→לילינבלום). לכל מסעדה תת-מחרוזות
# כותרת (מנורמלות _norm) שלפחות אחת חייבת להופיע בכותרת היעד הנבחר.
EXPECTED = {
    "אסה איזקאיה תל אביב": ("אסה", "asa"),
    "טאיזו תל אביב": ("טאיזו", "taizu"),
    "קלארו תל אביב": ("קלארו", "claro"),
    "רוסטיקו בזל תל אביב": ("בזל", "basel"),
    # מסא = MAZA באונטופו, מסומן out_of_business (אומת 17.7) — התוצאה הנכונה כיום
    # היא none (טלפון), אבל אם יחזור לחיים היעד חייב להיות MAZA.
    "מסא תל אביב": ("מסא", "masa", "maza"),
    "אנימאר תל אביב": ("אנימאר", "animar"),
    # אין סניף הדסון בראשון לציון בשום פלטפורמה (אומת מול החיפוש הפנימי, 17.7) —
    # התוצאה הנכונה היא many של סניפי הדסון בלבד (הלקוח בוחר), לא בחירה שקטה.
    "הדסון ראשון לציון": ("הדסון", "hudson"),
    "OCD תל אביב": ("ocd",),
}


def _target_ok(name: str, title: str) -> bool:
    from app.automation.resolve import _norm

    nt = _norm(title)
    return any(_norm(e) in nt for e in EXPECTED.get(name, ()))


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
    if "picked" not in row:  # status=one ישיר — הכותרת מהמועמד שנבחר, למדד "יעד נכון"
        row["picked"] = next(
            (c["title"] for c in res.get("candidates", []) if c["url"] == res["url"]), ""
        )[:40]
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
    print("| מסעדה | פלטפורמה | תוצאה | יעד נכון | צעדים | שניות |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        target = "✓" if _target_ok(r["restaurant"], r.get("picked", "")) else "✗"
        print(
            f"| {r['restaurant']} | {r.get('platform', '—')} | {r['outcome']} | {target} "
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


async def resolve_only_main() -> None:
    """NAV_BENCH_RESOLVE_ONLY=1 — רק שלב ה-resolve על כל הסט, בלי דפדפן: זול, מהיר,
    ומודד את הבאג המרכזי (יעד שגוי) בבידוד. מדפיס לכל מסעדה את היעד הנבחר + יעד נכון."""
    rows = []
    for name in RESTAURANTS:
        await asyncio.sleep(4)  # מרווח נשימה ל-Brave (429 בקריאות צפופות)
        print(f"⏳ {name} ...", file=sys.stderr, flush=True)
        try:
            res = await _resolve_retry(name)
        except Exception as e:  # noqa: BLE001 — resolve שקרס נרשם, הבנצ' ממשיך
            rows.append({"restaurant": name, "status": f"crash:{e}"})
            continue
        cands = res.get("candidates") or []
        # ב-one הרשימה היא כל מועמדי הפלטפורמה — היעד שנבחר הוא זה שה-URL שלו נבחר
        top = next((c for c in cands if c.get("url") == res.get("url")), (cands or [{}])[0])
        row = {
            "restaurant": name,
            "status": res.get("status"),
            "via": res.get("via", "—"),
            "picked": (top.get("title") or "")[:60],
            "url": (res.get("url") or top.get("url") or "")[:120],
            "candidates": [c.get("title", "")[:60] for c in cands],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), file=sys.stderr, flush=True)

    print(f"\n## resolve-only — {time.strftime('%d.%m.%Y %H:%M')}\n")
    print("| מסעדה | status | מסלול | יעד נבחר (top) | יעד נכון |")
    print("|---|---|---|---|---|")
    for r in rows:
        ok = "✓" if _target_ok(r["restaurant"], r.get("picked", "")) else "✗"
        mark = ok if r.get("status") == "one" else f"{r.get('status')}·top:{ok}"
        print(
            f"| {r['restaurant']} | {r.get('status')} | {r.get('via', '—')} "
            f"| {r.get('picked', '')} | {mark} |"
        )
    print()
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    if os.environ.get("NAV_BENCH_RESOLVE_ONLY"):
        asyncio.run(resolve_only_main())
    else:
        asyncio.run(main())
