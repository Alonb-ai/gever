"""
מריץ את playbook המסעדה מקצה לקצה (DRY_RUN) ומדפיס את הסטטוס האמיתי.

הרצה:
    .venv/bin/python poc/book_ontopo.py                      # ברירת מחדל
    .venv/bin/python poc/book_ontopo.py "הדסון" "20:00"      # שם + שעה
    .venv/bin/python poc/book_ontopo.py "הדסון" "20:00" "25" # + תאריך (יום בחודש)
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from app.automation.ontopo import book_table
from app.automation.resolve import resolve_ontopo_url

load_dotenv()


async def notify(msg: str) -> None:
    print(f"[גבר]  {msg}", flush=True)


async def main() -> None:
    restaurant = sys.argv[1] if len(sys.argv) > 1 else "טאיזו"
    time = sys.argv[2] if len(sys.argv) > 2 else "20:00"
    date = sys.argv[3] if len(sys.argv) > 3 else ""

    print(f"→ מחפש את '{restaurant}' ב-Ontopo...", flush=True)
    found = await resolve_ontopo_url(restaurant)
    print(f"→ resolve: status={found['status']} url={found['url']}", flush=True)
    if not found["url"]:
        print("  לא נמצא / כמה סניפים:", [c["title"] for c in found["candidates"][:3]])
        return

    print(f"→ מנסה: {restaurant}, תאריך='{date or 'ברירת מחדל'}', {time}, 2 סועדים\n", flush=True)
    res = await book_table(
        restaurant=restaurant,
        page_url=found["url"],
        date=date,
        time=time,
        party_size=2,
        name="אלון",
        dry_run=True,
        notify=notify,
    )
    print("\n— תוצאה —")
    print("success:", res.success)
    print("summary:", res.summary)
    # trace קריא פר-צעד (אם יש), ואז שאר ה-details
    details = dict(res.details or {})
    trace = details.pop("trace", None)
    if trace:
        print("session_id:", details.get("session_id"))
        print("trace (per-step verify):")
        for t in trace:
            print(
                f"  · {t['action']}  [ניסיון {t['attempt']}/{t['how']}]  ok={t['ok']}  → {t.get('state')}"
            )
    print("details:", details)


if __name__ == "__main__":
    asyncio.run(main())
