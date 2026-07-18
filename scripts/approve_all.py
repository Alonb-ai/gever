"""אישור חד-פעמי של כל המשתמשים הקיימים ב-DB (prefs.approved=true).

להרצה פעם אחת *לפני* הדלקת ACCESS_GATE — שאף משתמש קיים לא יינעל בחוץ:
    .venv/bin/python scripts/approve_all.py
דורש SUPABASE_URL + SUPABASE_SERVICE_KEY ב-.env (או בסביבה). בטוח להרצה חוזרת.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import memory  # noqa: E402


async def main() -> None:
    resp = await memory._request(
        "GET", "users", op="approve_all", phone="*", params={"select": "phone"}
    )
    if resp is None:
        raise SystemExit("אין חיבור ל-Supabase — בדוק SUPABASE_URL/SUPABASE_SERVICE_KEY ב-.env")
    phones = [row["phone"] for row in resp.json() if row.get("phone")]
    for phone in phones:
        await memory.approve(phone)
        print(f"approved: {phone}")
    print(f'סה"כ אושרו {len(phones)} משתמשים')


if __name__ == "__main__":
    asyncio.run(main())
