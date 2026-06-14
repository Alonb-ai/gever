"""
גבר מלא — שיחה + ביצוע אמיתי (הפה + הידיים), מקומי לבדיקה עצמית.

אתה מדבר עם גבר; כשיש לו מסעדה+תאריך+שעה+כמות ואתה מאשר — הוא *באמת* מריץ
את Ontopo דרך Browserbase (DRY_RUN: עד מסך האישור, בלי לבצע הזמנה ממשית),
ומזרים סטטוס אמיתי. כל הרצה מופיעה ב-Browserbase → Sessions עם וידאו.

הרצה:
    .venv/bin/python poc/gever.py          # ניטרלי
    .venv/bin/python poc/gever.py male      # פנייה בזכר

הערה: עד שיהיה resolver (שם→URL), רק מסעדות מהמפה למטה מחוברות.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.automation.ontopo import book_table
from app.automation.resolve import resolve_ontopo_url
from app.llm.intent import SYSTEM_PROMPT, gender_line

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

EXTRACT_INSTR = (
    "\n\n--- מנגנון פנימי (אל תחשוף ואל תזכיר אותו למשתמש) ---\n"
    "בכל תור החזר JSON: 'reply' = מה שאתה אומר למשתמש, בדמות. "
    "מלא restaurant/date/time/party_size כשהם ידועים מהשיחה. "
    "'ready'=true רק כשיש לך את כל הארבעה והמשתמש אישר לסגור."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "ready": {"type": "boolean"},
        "restaurant": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": "string"},
        "party_size": {"type": "integer"},
    },
    "required": ["reply", "ready"],
}


async def notify(msg: str) -> None:
    print(f"   [ביצוע] {msg}", flush=True)


async def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("חסר GEMINI_API_KEY ב-.env")
    gender = sys.argv[1].strip().lower() if len(sys.argv) > 1 else None

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT + "\n\n" + gender_line(gender) + EXTRACT_INSTR,
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )

    print("— גבר: שיחה + ביצוע אמיתי (DRY_RUN). Ctrl-C ליציאה —\n")
    while True:
        try:
            msg = input("אתה:  ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n🤙")
            return
        if not msg:
            continue

        data = json.loads(chat.send_message(msg).text)
        print(f"גבר:  {data['reply']}\n")

        if not data.get("ready"):
            continue

        name = (data.get("restaurant") or "").strip()
        print(f"   [ביצוע] מחפש את '{name}' ב-Ontopo...", flush=True)
        found = await resolve_ontopo_url(name)
        if found["status"] == "none":
            print(f"   [ביצוע] לא מצאתי את '{name}' ב-Ontopo. נסה שם אחר.\n")
            continue
        if found["status"] == "many":
            opts = " / ".join(c["title"][:30] for c in found["candidates"][:3])
            print(f"   [ביצוע] כמה סניפים — לאיזה? {opts}\n")
            continue

        res = await book_table(
            restaurant=name,
            page_url=found["url"],
            date=data.get("date") or "",
            time=data.get("time") or "20:00",
            party_size=data.get("party_size") or 2,
            name="אלון",
            dry_run=True,
            notify=notify,
        )
        print(f"\n   [תוצאה] {res.summary}")
        print(f"   [פרטים] {res.details.get('screen')}\n")


if __name__ == "__main__":
    asyncio.run(main())
