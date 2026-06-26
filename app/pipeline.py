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
from app.automation.browser_book import BU_TIMEOUT_S, book_table_bu
from app.automation.resolve import resolve_ontopo_url
from app.config import settings
from app.db import memory
from app.llm.intent import KNOWN_HINT, ONBOARDING_BLOCK, SYSTEM_PROMPT, gender_line
from app.whatsapp.client import send_text, send_typing

_EXTRACT = (
    "\n\n--- מנגנון פנימי (אל תחשוף ואל תזכיר אותו) ---\n"
    "בכל תור החזר JSON: 'reply' = מה שאתה אומר למשתמש, בדמות. "
    "מלא restaurant/date/time/party_size כשהם ידועים מהשיחה. "
    "אם המשתמש מסר את שמו או המייל שלו, מלא name/email (אל תמציא — רק אם נאמרו). "
    "אם מסר עובדה קבועה על עצמו ששווה לזכור — מצב זוגי, עיר מגורים, מסעדה מועדפת, "
    "מגבלות אוכל, או אזורים שהוא אוהב — מלא תחת 'profile' (רק מה שנאמר במפורש, אל "
    "תנחש ואל תכתוב מצב רגעי או פרט חד-פעמי של ההזמנה). אם אין — השאר 'profile' ריק. "
    "'ready'=true רק כשיש לך את כל הארבעה והמשתמש אישר לסגור (התחלת הזמנה). "
    "'confirm'=true רק כשכבר הגעתם למסך האישור (יש הזמנה ממתינה) והמשתמש מאשר "
    "במפורש לסגור אותה סופית — לא להתחלה של הזמנה חדשה. "
    "שדה 'task_type': 'restaurant' אם זו הזמנת מסעדה, אחרת 'other'. "
    "ברירת מחדל restaurant אם לא ברור עדיין."
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "ready": {"type": "boolean"},
        "confirm": {"type": "boolean"},
        "task_type": {"type": "string", "enum": ["restaurant", "other"]},
        "restaurant": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": "string"},
        "party_size": {"type": "integer"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "profile": {
            "type": "object",
            "properties": {
                "relationship": {"type": "string"},
                "city": {"type": "string"},
                "fav_restaurant": {"type": "string"},
                "dietary": {"type": "string"},
                "areas": {"type": "string"},
            },
        },
    },
    "required": ["reply", "ready"],
}

log = logging.getLogger("gever")

_client: genai.Client | None = None
# phone -> רשימת תורות [{"role","text"}]. זיכרון השיחה: נשמר בתהליך *וגם* מותמד ל-Supabase
# (prefs._chat), כדי שהשיחה תשרוד restart/redeploy. בלי מפתחות Supabase = בתהליך בלבד, כמו פעם.
_turns: dict = {}
_last_seen: dict = {}  # phone -> time.time() של התור האחרון (פתיחת "דף חדש" אחרי שקט)
_reset_next: set = set()  # phones שיקבלו שיחה טרייה בתור הבא (אחרי שהזמנה נסגרה)
_pending: set = (
    set()
)  # ponytail: hold strong refs — create_task() tasks get GC'd mid-flight otherwise
# אמת-קרקע על תוצאת ההזמנה האמיתית, phone -> {"state": ..., "info": ...}.
# state: "working" | "done" | "failed" | "none" | "ambiguous" | "pending". מוזרק ל-converse
# כדי שמודל השיחה לא ימציא הצלחה/כישלון. נכתב רק ב-run_booking/run_commit (המקור לאמת).
_booking: dict = {}
# הזמנה שהגיעה למסך האישור ומחכה ל"מאשר" — פרמטרי ה-playbook לשחזור בסגירה האמיתית.
# (res.details לא נשמר אחרי run_booking, לכן שומרים כאן את מה ש-book_table צריך.)
_pending_commit: dict = {}

# פער שאחריו פותחים "דף חדש": שיחה טרייה במקום לגרור את ההיסטוריה הישנה.
SESSION_GAP_S = 3 * 60 * 60  # ~3 שעות

# כמה תורות לשמור בזיכרון השיחה (10 חילופים). שיחת הזמנה כמעט אף פעם לא ארוכה מזה.
CHAT_TURNS = 20


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
    if profile.get("email"):
        lines.append(f"מייל: {profile['email']}")
    prefs = profile.get("prefs") or {}
    if prefs.get("party_size"):
        lines.append(f"כמות סועדים ברירת מחדל: {prefs['party_size']}")
    if prefs.get("dietary"):
        lines.append(f"מגבלות אוכל: {prefs['dietary']}")
    if prefs.get("areas"):
        lines.append(f"אזורים מועדפים: {prefs['areas']}")
    if prefs.get("relationship"):
        lines.append(f"מצב זוגי: {prefs['relationship']}")
    if prefs.get("city"):
        lines.append(f"עיר מגורים: {prefs['city']}")
    if prefs.get("fav_restaurant"):
        lines.append(f"מסעדה מועדפת: {prefs['fav_restaurant']}")
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


def _seed_from(profile: dict | None, bookings: list) -> str:
    """ה-system_instruction לשיחה: בסיס + פרופיל + recap. הנתונים נטענים פעם אחת
    ב-_chat_for (משמשים גם לתורות השמורות) ומועברים לכאן — בלי טעינה כפולה.
    בלי מפתחות profile=None/bookings=[] → בדיוק כמו היום."""
    base = SYSTEM_PROMPT + "\n\n" + gender_line(None)
    # חדש (אין profile/email) → בלוק היכרות; מוכר (יש מייל) → הפרופיל + רמז לשזירה עדינה.
    if not (profile and profile.get("email")):
        intro = ONBOARDING_BLOCK
    else:
        intro = _profile_block(profile) + KNOWN_HINT
    return base + intro + _recap_block(bookings) + _EXTRACT


async def _chat_for(phone: str) -> tuple:
    """בונה את שיחת ה-Gemini לתור הזה מתוך history שמור, ומחזיר (chat, turns, prefs).
    פותח "דף חדש" (history ריק) במגע ראשון, פער >~3 שעות, או אחרי שהזמנה נסגרה.
    התורות נטענות מהזיכרון-בתהליך (_turns); אם ריק (למשל אחרי restart) — מ-Supabase."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)

    # ponytail: טעינה אחת per-turn לזרע *ולתורות השמורות*. ~read אחד/תור ל-Supabase —
    # זניח למשתמש יחיד; אם זה אי-פעם צוואר בקבוק, cache את הזרע per-session.
    profile = await memory.get_profile(phone)
    bookings = await memory.recent_bookings(phone)

    now = time.time()
    last = _last_seen.get(phone)
    stale = last is not None and (now - last) > SESSION_GAP_S
    fresh = stale or phone in _reset_next
    _reset_next.discard(phone)
    _last_seen[phone] = now

    prefs = (profile or {}).get("prefs") or {}
    if fresh:
        turns: list = []
    else:
        turns = _turns.get(phone)
        if turns is None:  # זיכרון-בתהליך ריק (restart/worker חדש) — שחזור מ-Supabase
            turns = (prefs.get("_chat") or {}).get("turns") or []

    chat = _client.chats.create(
        model=settings.gemini_model,
        config=types.GenerateContentConfig(
            system_instruction=_seed_from(profile, bookings),
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=_SCHEMA,
        ),
        history=[types.Content(role=t["role"], parts=[types.Part(text=t["text"])]) for t in turns],
    )
    return chat, turns, prefs


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
        return (
            f"[אמת-למערכת בלבד: ההזמנה כבר אושרה ({info}). אל תזמין שוב ואל תבקש "
            "פרטים מחדש — רק תאשר ללקוח בקצרה שזה סגור.]\n\n"
        )
    if state == "pending":
        # last-verify: info = שם המסעדה שנפתרה. נוקבים בו ומבקשים "לסגור?" כדי שהלקוח
        # יתפוס מסעדה שגויה (ביקש רוטשילד, נפתר רוסטיקו) לפני הסגירה.
        if settings.dry_run:
            return (
                f"[אמת-למערכת בלבד: הגעת עם הלקוח למסך האישור של '{info}' אבל זה מצב בדיקה "
                "ועדיין לא ביצעת הזמנה אמיתית. נקוב בשם המסעדה '" + info + "' במפורש ושאל "
                "'לסגור?' כדי שיאשר שזו המסעדה הנכונה. אל תגיד שסגרת או ששמור ואל תזמין "
                "שוב. אם הוא מאשר — תהיה כן, תגיד שהכל מוכן אבל עוד לא סגרת בפועל.]\n\n"
            )
        return (
            f"[אמת-למערכת בלבד: הגעת עם הלקוח למסך האישור של '{info}' — הכל מוכן וצריך רק "
            "את אישורו לסגירה סופית. נקוב בשם המסעדה '" + info + "' במפורש ושאל 'לסגור?' "
            "כדי שיאשר שזו המסעדה הנכונה. עדיין לא סגרת בפועל, אל תגיד שסגרת ואל תזמין "
            "שוב. אם הוא מאשר במפורש — זה הסימן לסגור; תאשר לו רק כשבאמת ייסגר.]\n\n"
        )
    if state == "card":
        return (
            "[אמת-למערכת בלבד: המקום דורש כרטיס אשראי מראש ואינך סוגר אותו אוטומטית. כבר "
            "שלחת ללקוח לינק לסגור בעצמו. אל תמציא שסגרת ואל תנסה שוב — הצע לעזור במקום אחר.]\n\n"
        )
    if state == "missing":
        return (
            f"[אמת-למערכת בלבד: הטופס דורש שדה חובה שחסר לי ('{info}'). אל תמציא אותו ואל "
            "תמציא שסגרת — בקש מהלקוח את הפרט הזה במפורש וחכה לתשובה.]\n\n"
        )
    if state == "none":
        return f"[אמת-למערכת בלבד: לא מצאתי מסעדה בשם '{info}'. אל תמציא שסגרת — בקש שם אחר.]\n\n"
    if state == "ambiguous":
        return (
            f"[אמת-למערכת בלבד: יש כמה מסעדות תואמות ({info}), עוד לא בחרנו. "
            "אל תמציא שסגרת — בקש להבהיר לאיזו.]\n\n"
        )
    return ""


async def converse(phone: str, text: str) -> dict:
    """תור שיחה אחד. הקריאה ל-Gemini חוסמת — מריצים ב-thread כדי לא לחסום.
    שומר את התור (טקסט המשתמש + ה-reply בדמות, בלי ה-truth_note) ל-_turns ול-Supabase,
    כדי שהשיחה תשרוד restart/redeploy ולא "תשכח" על מה דיברנו."""
    chat, turns, prefs = await _chat_for(phone)
    msg = _truth_note(phone) + text
    resp = await asyncio.to_thread(chat.send_message, msg)
    result = json.loads(resp.text)
    turns = [
        *turns,
        {"role": "user", "text": text},
        {"role": "model", "text": result.get("reply", "")},
    ][-CHAT_TURNS:]
    _turns[phone] = turns
    # ponytail: ממזגים את ה-prefs ב-Python (כבר בידינו מ-_chat_for) ל-upsert אחד —
    # עובדות פרופיל + _chat יחד. בלי race למשתמש יחיד; בלי read-merge ב-upsert_profile.
    facts = {k: v for k, v in (result.get("profile") or {}).items() if v not in (None, "", 0)}
    await memory.upsert_profile(
        phone,
        name=(result.get("name") or None),
        email=(result.get("email") or None),
        prefs={**prefs, **facts, "_chat": {"turns": turns}},
    )
    return result


def _il_phone(p: str) -> str:
    """מספר וואטסאפ (972XXXXXXXXX) → פורמט ישראלי מקומי (0XXXXXXXXX) שהטופס מצפה לו."""
    p = (p or "").lstrip("+")
    return "0" + p[3:] if p.startswith("972") else p


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

        # פרטי קשר: מהשיחה, ואם אין — מהפרופיל. הטלפון = הוואטסאפ בפורמט ישראלי (0...).
        prof = await memory.get_profile(phone)
        booker = (fields.get("name") or (prof or {}).get("name") or "").strip()
        email = (fields.get("email") or (prof or {}).get("email") or "").strip()
        await notify("רגע אני על זה 🔄")  # browser-use איטי ובלי streaming — מודיעים שאנחנו על זה
        res = await book_table_bu(
            restaurant=name,
            page_url=found["url"],
            date=fields.get("date") or "",
            time=fields.get("time") or "20:00",
            party_size=fields.get("party_size") or 2,
            name=booker,
            email=email,
            phone=_il_phone(phone),
            dry_run=True,
        )
        if res.success:
            # DRY_RUN: הגענו למסך האישור — זו *לא* הזמנה אמיתית. לכן לא "done", לא
            # log_booking, ולא לזייף "סגור" (חוק הברזל). שומרים רק פרופיל (שם/מייל)
            # לזיכרון. הסגירה האמיתית (confirm→commit) + שימוש בטלפון = זרוע C.
            # last-verify: ה-info נוקב בשם המסעדה שנפתרה (name), כדי שה-truth_note יורה
            # לפרסונה לאשר עם הלקוח את שם המקום — וכך לתפוס מסעדה שגויה לפני סגירה.
            _booking[phone] = {"state": "pending", "info": name}
            await memory.upsert_profile(
                phone,
                name=(fields.get("name") or None),
                email=(fields.get("email") or None),
            )
            # שומרים את פרמטרי ההזמנה לסגירה האמיתית (confirm→commit). booker כבר נפתר למעלה.
            d = res.details or {}
            _pending_commit[phone] = {
                "restaurant": name,  # name = שם המסעדה (ראה למעלה); page_url = ה-URL שנפתר
                "page_url": found["url"],
                "date": fields.get("date") or "",
                "time": d.get("time") or fields.get("time") or "20:00",  # השעה שאושרה בפועל
                "party_size": fields.get("party_size") or 2,
                "name": booker,
            }
        elif (res.details or {}).get("missing"):
            # באג 3: שדה חובה בטופס היה ריק (ה-runner לא המציא, עצר ודיווח MISSING).
            # מנגנון אחד כמו none/ambiguous: גבר מבקש מהלקוח את השדה וממתין — בלי
            # pre-validation בצד שלנו (הטופס מחליט מה חובה).
            field = res.details["missing"]
            _booking[phone] = {"state": "missing", "info": field}
            _human = {"email": "מייל", "name": "שם", "phone": "טלפון"}.get(field, field)
            await send_text(phone, f"רגע, חסר לי {_human} כדי לסגור — תשלח לי אותו?")
            return
        else:
            _booking[phone] = {"state": "failed", "info": res.summary}
            d = res.details or {}
            await send_text(
                phone,
                res.summary + engine.error_detail(d.get("error"), session_id=d.get("session_id")),
            )
    except asyncio.TimeoutError:
        log.warning("booking timed out (%ss) for %s", BU_TIMEOUT_S, phone)
        _booking[phone] = {"state": "failed", "info": "נתקע (timeout)"}
        await send_text(
            phone,
            "אחי זה נתקע לי, לקח יותר מדי. ננסה שוב?"
            + engine.error_detail(f"timeout אחרי {BU_TIMEOUT_S}s"),
        )
    except Exception as e:
        log.exception("booking failed for %s", phone)
        _booking[phone] = {"state": "failed", "info": "חריגה באמצע"}
        await send_text(phone, "נתקעתי באמצע, לא הצלחתי לסגור. ננסה שוב?" + engine.error_detail(e))


async def run_commit(phone: str) -> None:
    """הסגירה האמיתית אחרי 'מאשר': מריץ מחדש את ה-playbook עם dry_run=False, סוגר,
    רושם, ושולח 'סגור ✅' ללקוח. אם המקום דורש כרטיס אשראי — לא נסגר (PCI), מודיעים בכנות.
    עטוף ב-timeout/except כמו run_booking: תקיעה/חריגה → הודעת כישלון כנה."""

    async def notify(msg: str) -> None:
        await send_text(phone, msg)

    job = _pending_commit.get(phone)
    if not job:
        return
    if not job.get("name"):  # חוק ברזל: לא סוגרים בלי שם מזמין
        await send_text(phone, "רגע על איזה שם לסגור")
        return
    _booking[phone] = {"state": "working", "info": ""}
    try:
        await notify("רגע סוגר לך 🔄")  # browser-use איטי ובלי streaming
        res = await book_table_bu(
            restaurant=job["restaurant"],
            page_url=job["page_url"],
            date=job["date"],
            time=job["time"],
            party_size=job["party_size"],
            name=job["name"],
            phone=_il_phone(phone),
            dry_run=False,  # סגירה אמיתית (כיום ה-runner עדיין עוצר בכרטיס; commit מלא = עתידי)
        )
        if res.success:
            d = res.details or {}
            conf = d.get("confirmation") or ""
            _booking[phone] = {"state": "done", "info": conf}
            await memory.log_booking(
                phone,
                d.get("restaurant") or job["restaurant"],
                d.get("date") or job["date"],
                d.get("time") or job["time"],
                job["party_size"],
                status="confirmed",
            )
            _reset_next.add(phone)  # ההזמנה נסגרה — ההודעה הבאה פותחת דף חדש
            when = f"ל-{job['date']} " if job.get("date") else ""
            msg = (
                f"סגור ✅ {job['restaurant']} {when}בשעה {job['time']} "
                f"ל-{job['party_size']} סועדים.\nאישור יגיע אליך ב-SMS מהמסעדה 🤙"
            )
            if conf:
                msg += f"\nמספר אישור: {conf}"
            await send_text(phone, msg)
        elif (res.details or {}).get("card_required"):
            # זרוע C — קיר כרטיס: המקום דורש תשלום מראש, לא סוגרים אוטומטית (PCI).
            # מוסרים ללקוח את לינק המסעדה ב-Ontopo כדי שיסגור בעצמו.
            _booking[phone] = {"state": "card", "info": job["page_url"]}
            await send_text(
                phone,
                f"{job['restaurant']} דורש כרטיס אשראי מראש, ואת זה אני לא ממלא במקומך. "
                f"הנה הלינק לסגור בעצמך 👇\n{job['page_url']}",
            )
        else:
            _booking[phone] = {"state": "failed", "info": res.summary}
            d = res.details or {}
            await send_text(
                phone,
                res.summary + engine.error_detail(d.get("error"), session_id=d.get("session_id")),
            )
    except asyncio.TimeoutError:
        log.warning("commit timed out (%ss) for %s", BU_TIMEOUT_S, phone)
        _booking[phone] = {"state": "failed", "info": "נתקע (timeout)"}
        await send_text(
            phone,
            "אחי זה נתקע לי באישור, ננסה שוב?"
            + engine.error_detail(f"timeout אחרי {BU_TIMEOUT_S}s"),
        )
    except Exception as e:
        log.exception("commit failed for %s", phone)
        _booking[phone] = {"state": "failed", "info": "חריגה באישור"}
        await send_text(phone, "נתקעתי באישור, לא סגרתי. ננסה שוב?" + engine.error_detail(e))
    finally:
        _pending_commit.pop(phone, None)


async def handle_inbound(phone: str, text: str, message_id: str | None = None) -> None:
    """נקודת הכניסה מה-webhook: שיחה, תשובה, וכשמוכן — הזמנה/סגירה ברקע."""
    await send_typing(message_id)  # 'מקליד…' בזמן שגבר חושב; התשובה תנקה אותו
    result = await converse(phone, text)
    await send_text(phone, result.get("reply", "רגע 🔄"))
    # באג 4/5: guard ל-double-fire — אם כבר רצה הזמנה לטלפון הזה ("?" של הלקוח גרם
    # ל-ready=true שוב), לא יורים run_booking/run_commit שני שיתנגש בראשון (וגם לא
    # notify כפול — ה-guard מסיר את הכניסה-החוזרת).
    if _booking.get(phone, {}).get("state") == "working":
        return
    # קובעים state="working" *סינכרונית* לפני ה-spawn (לא בתוך ה-coroutine), כדי לסגור
    # חלון מירוץ: שתי הודעות מהירות לא יעברו שתיהן את ה-guard למעלה. ה-coroutine ידרוס.
    if phone in _pending_commit and result.get("confirm") and not settings.dry_run:
        _booking[phone] = {"state": "working", "info": ""}
        _spawn(run_commit(phone))  # 'מאשר' על הזמנה ממתינה → סגירה אמיתית
    elif result.get("ready"):
        _pending_commit.pop(phone, None)  # התחלת/שינוי הזמנה — נוטשים gate ישן
        _booking[phone] = {"state": "working", "info": ""}
        _spawn(run_booking(phone, result))
