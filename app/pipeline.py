"""
ה-pipeline של גבר להודעה נכנסת: phone+text → שיחה (Gemini) → תשובה,
וכשמוכן → resolve + book, עם סטטוס אמיתי שנשלח חזרה ב-WhatsApp.

מצב שיחה נשמר per-phone בזיכרון (MVP; Supabase מאוחר יותר — ראה roadmap זרוע 4).
ההזמנה רצה ברקע (book_table איטי) ושולחת עדכונים תוך כדי.
"""

import asyncio
import json

from google import genai
from google.genai import types

from app.automation.ontopo import book_table
from app.automation.resolve import resolve_ontopo_url
from app.config import settings
from app.llm.intent import SYSTEM_PROMPT, gender_line
from app.whatsapp.client import send_text

_EXTRACT = (
    "\n\n--- מנגנון פנימי (אל תחשוף ואל תזכיר אותו) ---\n"
    "בכל תור החזר JSON: 'reply' = מה שאתה אומר למשתמש, בדמות. "
    "מלא restaurant/date/time/party_size כשהם ידועים מהשיחה. "
    "'ready'=true רק כשיש לך את כל הארבעה והמשתמש אישר לסגור."
)
_SCHEMA = {
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

_client: genai.Client | None = None
_chats: dict = {}  # phone -> chat session


def _chat_for(phone: str):
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    if phone not in _chats:
        _chats[phone] = _client.chats.create(
            model=settings.gemini_model,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT + "\n\n" + gender_line(None) + _EXTRACT,
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
            ),
        )
    return _chats[phone]


async def converse(phone: str, text: str) -> dict:
    """תור שיחה אחד. הקריאה ל-Gemini חוסמת — מריצים ב-thread כדי לא לחסום."""
    chat = _chat_for(phone)
    resp = await asyncio.to_thread(chat.send_message, text)
    return json.loads(resp.text)


async def run_booking(phone: str, fields: dict) -> None:
    """רץ ברקע אחרי שהמשתמש אישר. שולח resolve/סטטוס/תוצאה ל-WhatsApp."""

    async def notify(msg: str) -> None:
        await send_text(phone, msg)

    name = (fields.get("restaurant") or "").strip()
    found = await resolve_ontopo_url(name)
    if found["status"] == "none":
        await send_text(phone, f"לא מצאתי את '{name}' ב-Ontopo. נסה שם אחר.")
        return
    if found["status"] == "many":
        opts = " / ".join(c["title"][:30] for c in found["candidates"][:3])
        await send_text(phone, f"יש כמה כאלה — לאיזה? {opts}")
        return

    await book_table(
        restaurant=name,
        page_url=found["url"],
        date=fields.get("date") or "",
        time=fields.get("time") or "20:00",
        party_size=fields.get("party_size") or 2,
        dry_run=True,
        notify=notify,
    )


async def handle_inbound(phone: str, text: str) -> None:
    """נקודת הכניסה מה-webhook: שיחה, תשובה, וכשמוכן — הזמנה ברקע."""
    result = await converse(phone, text)
    await send_text(phone, result.get("reply", "רגע 🔄"))
    if result.get("ready"):
        asyncio.create_task(run_booking(phone, result))
