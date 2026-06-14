"""
מריץ את playbook המסעדה מקצה לקצה (DRY_RUN) ומדפיס את הסטטוס האמיתי.

הרצה:
    .venv/bin/python poc/book_ontopo.py                 # ברירת מחדל
    .venv/bin/python poc/book_ontopo.py "הדסון" "20:00" # שם + שעה
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

    print(f"→ מחפש את '{restaurant}' ב-Ontopo...", flush=True)
    found = await resolve_ontopo_url(restaurant)
    print(f"→ resolve: status={found['status']} url={found['url']}", flush=True)
    if not found["url"]:
        print("  לא נמצא / כמה סניפים:", [c["title"] for c in found["candidates"][:3]])
        return

    print(f"→ מנסה: {restaurant}, {time}, 2 סועדים\n", flush=True)
    res = await book_table(
        restaurant=restaurant,
        page_url=found["url"],
        date="",
        time=time,
        party_size=2,
        name="אלון",
        dry_run=True,
        notify=notify,
    )
    print("\n— תוצאה —")
    print("success:", res.success)
    print("summary:", res.summary)
    print("details:", res.details)


if __name__ == "__main__":
    asyncio.run(main())
