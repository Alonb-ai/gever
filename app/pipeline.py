"""
ה-pipeline של גבר להודעה נכנסת: phone+text → שיחה (Gemini) → תשובה,
וכשמוכן → resolve + book, עם סטטוס אמיתי שנשלח חזרה ב-WhatsApp.

מצב שיחה נשמר per-phone בזיכרון (MVP; Supabase מאוחר יותר — ראה roadmap זרוע 4).
ההזמנה רצה ברקע (book_table איטי) ושולחת עדכונים תוך כדי.
"""

import asyncio
import json
import logging
import time

from google import genai
from google.genai import types

from app.automation import engine
from app.automation.ontopo import book_table
from app.automation.resolve import resolve_ontopo_url
from app.config import settings
from app.db import memory
from app.llm.intent import SYSTEM_PROMPT, gender_line
from app.whatsapp.client import send_text, send_typing

_EXTRACT = (
    "\n\n--- מנגנון פנימי (אל תחשוף ואל תזכיר אותו) ---\n"
    "בכל תור החזר JSON: 'reply' = מה שאתה אומר למשתמש, בדמות. "
    "מלא restaurant/date/time/party_size כשהם ידועים מהשיחה. "
    "אם המשתמש מסר את שמו או המייל שלו, מלא name/email (אל תמציא — רק אם נאמרו). "
    "'ready'=true רק כשיש לך את כל הארבעה והמשתמש אישר לסגור. "
    "שדה 'task_type': 'restaurant' אם זו הזמנת מסעדה, אחרת 'other'. "
    "ברירת מחדל restaurant אם לא ברור עדיין."
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "ready": {"type": "boolean"},
        "task_type": {"type": "string", "enum": ["restaurant", "other"]},
        "restaurant": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": "string"},
        "party_size": {"type": "integer"},
        "name": {"type": "string"},
        "email": {"type": "string"},
    },
    "required": ["reply", "ready"],
}

log = logging.getLogger("gever")

_client: genai.Client | None = None
_chats: dict = {}  # phone -> chat session
_last_seen: dict = {}  # phone -> time.time() של התור האחרון (פתיחת "דף חדש" אחרי שקט)
_reset_next: set = set()  # phones שיקבלו שיחה טרייה בתור הבא (אחרי שהזמנה נסגרה)
_pending: set = (
    set()
)  # ponytail: hold strong refs — create_task() tasks get GC'd mid-flight otherwise
# אמת-קרקע על תוצאת ההזמנה האמיתית, phone -> {"state": ..., "info": ...}.
# state: "working" | "done" | "failed" | "none" | "ambiguous". מוזרק ל-converse כדי
# שמודל השיחה לא ימציא הצלחה/כישלון. נכתב רק ב-run_booking (המקור היחיד לאמת).
_booking: dict = {}

# פער שאחריו פותחים "דף חדש": שיחה טרייה במקום לגרור את ההיסטוריה הישנה.
SESSION_GAP_S = 3 * 60 * 60  # ~3 שעות


def _spawn(coro) -> None:
    """כמו create_task, אבל שומר reference (אחרת ה-task נעלם בשקט ב-GC)."""
    task = asyncio.create_task(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def _profile_block(profile: dict | None) -> str:
    """בלוק PROFILE להזרקה ל-seed כשיש פרופיל — שם + העדפות. ריק אם אין פרופיל."""
    if not profile:
        return ""
    lines = ["\n\n--- פרופיל המשתמש (אתה כבר מכיר אותו, אל תבקש שוב שם/מייל) ---"]
    if profile.get("name"):
        lines.append(f"שם: {profile['name']}")
    prefs = profile.get("prefs") or {}
    if prefs.get("party_size"):
        lines.append(f"כמות סועדים ברירת מחדל: {prefs['party_size']}")
    if prefs.get("dietary"):
        lines.append(f"מגבלות אוכל: {prefs['dietary']}")
    if prefs.get("areas"):
        lines.append(f"אזורים מועדפים: {prefs['areas']}")
    return "\n".join(lines)


def _recap_block(bookings: list) -> str:
    """recap קצר מההזמנות האחרונות. ריק אם אין — לא גוררים תמלול מלא, רק תזכורת."""
    if not bookings:
        return ""
    lines = ["\n\n--- הזמנות אחרונות (רקע, אל תזכיר אלא אם רלוונטי) ---"]
    for b in bookings:
        parts = [b.get("restaurant") or "?"]
        if b.get("date"):
            parts.append(b["date"])
        if b.get("party_size"):
            parts.append(f"{b['party_size']} סועדים")
        lines.append("· " + " — ".join(str(p) for p in parts))
    return "\n".join(lines)


async def _seed_instruction(phone: str) -> str:
    """ה-system_instruction לשיחה טרייה: בסיס + פרופיל + recap (אם יש זיכרון).
    בלי מפתחות get_profile/recent_bookings מחזירים None/[] → בדיוק כמו היום."""
    base = SYSTEM_PROMPT + "\n\n" + gender_line(None)
    profile = await memory.get_profile(phone)
    bookings = await memory.recent_bookings(phone)
    return base + _profile_block(profile) + _recap_block(bookings) + _EXTRACT


async def _chat_for(phone: str):
    """מחזיר את השיחה של phone, ופותח "דף חדש" כשצריך: מגע ראשון, פער >~3 שעות,
    או אחרי שהזמנה נסגרה (_reset_next). שיחה טרייה נזרעת עם הפרופיל וה-recap."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)

    now = time.time()
    last = _last_seen.get(phone)
    stale = last is not None and (now - last) > SESSION_GAP_S
    fresh = phone not in _chats or stale or phone in _reset_next
    if fresh:
        _reset_next.discard(phone)
        _chats[phone] = _client.chats.create(
            model=settings.gemini_model,
            config=types.GenerateContentConfig(
                system_instruction=await _seed_instruction(phone),
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
            ),
        )
    _last_seen[phone] = now
    return _chats[phone]


def _truth_note(phone: str) -> str:
    """הזרקת אמת-קרקע נסתרת לפי מצב ההזמנה האמיתי, כדי שהמודל לא ימציא תוצאה.
    מחזיר prefix קצר להוסיף לפני הודעת המשתמש, או "" אם אין מצב רלוונטי."""
    b = _booking.get(phone)
    if not b:
        return ""
    state, info = b["state"], b.get("info", "")
    if state == "working":
        return (
            "[אמת-למערכת בלבד, אל תצטט: ההזמנה עדיין בתהליך, אין אישור. "
            "אל תכריז שסגרת — תגיד שאתה על זה ותעדכן כשסגור.]\n\n"
        )
    if state == "failed":
        return (
            f"[אמת-למערכת בלבד: ההזמנה נכשלה ({info}). "
            "אל תמציא הצלחה — תהיה כן ותציע לנסות שוב.]\n\n"
        )
    if state == "done":
        return f"[אמת-למערכת בלבד: ההזמנה אושרה ({info}).]\n\n"
    if state == "none":
        return f"[אמת-למערכת בלבד: לא מצאתי מסעדה בשם '{info}'. אל תמציא שסגרת — בקש שם אחר.]\n\n"
    if state == "ambiguous":
        return (
            f"[אמת-למערכת בלבד: יש כמה מסעדות תואמות ({info}), עוד לא בחרנו. "
            "אל תמציא שסגרת — בקש להבהיר לאיזו.]\n\n"
        )
    return ""


async def converse(phone: str, text: str) -> dict:
    """תור שיחה אחד. הקריאה ל-Gemini חוסמת — מריצים ב-thread כדי לא לחסום."""
    chat = await _chat_for(phone)
    msg = _truth_note(phone) + text
    resp = await asyncio.to_thread(chat.send_message, msg)
    return json.loads(resp.text)


BOOKING_TIMEOUT_S = 240  # ponytail: תקרה קשיחה — צעד Stagehand תקוע נכשל בקול, לא בדממה אינסופית


async def run_booking(phone: str, fields: dict) -> None:
    """רץ ברקע אחרי שהמשתמש אישר. שולח resolve/סטטוס/תוצאה ל-WhatsApp.

    עטוף ב-try + timeout: תקיעה או חריגה הופכות להודעת כישלון בדמות, לא לדממה.
    """

    async def notify(msg: str) -> None:
        await send_text(phone, msg)

    name = (fields.get("restaurant") or "").strip()
    task_type = fields.get("task_type") or "restaurant"
    if task_type != "restaurant":
        _booking[phone] = {"state": "failed", "info": "לא נתמך עדיין"}
        await send_text(phone, "זה לא משהו שאני סוגר אוטומטית עדיין, אבל אני פה.")
        return
    if not name:
        # הגנה: המודל ירה ready=True בלי שם מסעדה (קצה) — לא יורים הזמנה ריקה
        _booking.pop(phone, None)
        await send_text(phone, "רגע לאיזו מסעדה אנחנו סוגרים")
        return
    _booking[phone] = {"state": "working", "info": ""}
    try:
        found = await resolve_ontopo_url(name)
        if found["status"] == "none":
            _booking[phone] = {"state": "none", "info": name}
            await send_text(phone, f"לא מצאתי את '{name}' ב-Ontopo. נסה שם אחר.")
            return
        if found["status"] == "many":
            opts = " / ".join(c["title"][:30] for c in found["candidates"][:3])
            _booking[phone] = {"state": "ambiguous", "info": opts}
            await send_text(phone, f"יש כמה כאלה — לאיזה? {opts}")
            return

        res = await asyncio.wait_for(
            book_table(
                restaurant=name,
                page_url=found["url"],
                date=fields.get("date") or "",
                time=fields.get("time") or "20:00",
                party_size=fields.get("party_size") or 2,
                dry_run=True,
                notify=notify,
            ),
            timeout=BOOKING_TIMEOUT_S,
        )
        if res.success:
            _booking[phone] = {"state": "done", "info": res.summary}
            # זיכרון בין שיחות: שומר שם/מייל (אם נמסרו) ורושם את ההזמנה. no-op בלי מפתחות.
            await memory.upsert_profile(
                phone,
                name=(fields.get("name") or None),
                email=(fields.get("email") or None),
            )
            await memory.log_booking(
                phone,
                restaurant=name,
                date=fields.get("date") or "",
                time=fields.get("time") or "20:00",
                party_size=fields.get("party_size") or 2,
                status="confirmed",
            )
            # ponytail: לא מאפסים את השיחה כאן — איפוס אחרי שער ה-DRY_RUN איבד הקשר
            # וגרם להזמנה ריקה כש"מאשר" נכנס לשיחה טרייה. נחזיר per-completion אמיתי
            # כשתיבנה זרימת confirm→commit (זרוע C).
        else:
            _booking[phone] = {"state": "failed", "info": res.summary}
            d = res.details or {}
            await send_text(
                phone,
                res.summary + engine.error_detail(d.get("error"), session_id=d.get("session_id")),
            )
    except asyncio.TimeoutError:
        log.warning("booking timed out (%ss) for %s", BOOKING_TIMEOUT_S, phone)
        _booking[phone] = {"state": "failed", "info": "נתקע (timeout)"}
        await send_text(
            phone,
            "אחי זה נתקע לי, לקח יותר מדי. ננסה שוב?"
            + engine.error_detail(f"timeout אחרי {BOOKING_TIMEOUT_S}s"),
        )
    except Exception as e:
        log.exception("booking failed for %s", phone)
        _booking[phone] = {"state": "failed", "info": "חריגה באמצע"}
        await send_text(phone, "נתקעתי באמצע, לא הצלחתי לסגור. ננסה שוב?" + engine.error_detail(e))


async def handle_inbound(phone: str, text: str, message_id: str | None = None) -> None:
    """נקודת הכניסה מה-webhook: שיחה, תשובה, וכשמוכן — הזמנה ברקע."""
    await send_typing(message_id)  # 'מקליד…' בזמן שגבר חושב; התשובה תנקה אותו
    result = await converse(phone, text)
    await send_text(phone, result.get("reply", "רגע 🔄"))
    if result.get("ready"):
        _spawn(run_booking(phone, result))
