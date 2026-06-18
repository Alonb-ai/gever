"""
playbook הזמנת מסעדה ב-Ontopo (זרוע הביצוע).

ה"ידיים" של גבר: orchestrator דטרמיניסטי שמריץ את Ontopo דרך Stagehand לפי
תרשים הזרימה. ניווט *ישיר* לדף המסעדה (deep-link) — החיפוש בדף הבית לא מנווט.
כולל אימות שזו המסעדה הנכונה, בדיקת זמינות אמיתית, ושער אישור לפני צעד
בלתי-הפיך. הסטטוס נפלט מצמתים אמיתיים: 🔄 כשמתחילים, ✅ רק כשבאמת הצליח.

הערה: resolve של שם מסעדה -> page_url (deep-link) הוא צעד נפרד (TODO) —
חיפוש/דירקטוריון. כאן מקבלים page_url מוכן.
"""

import os
from typing import Awaitable, Callable

from stagehand import AsyncStagehand

from app.models.schemas import ActionResult

StatusFn = Callable[[str], Awaitable[None]]


async def _noop(_: str) -> None:
    pass


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch == " ")


# מילות-מפתח שמסמנות דיל/רשימה/שובר ולא את דף ההזמנה האמיתי של המסעדה
_LISTING_WORDS = (
    "ארוחת",
    "טעימות",
    "דיל",
    "מבצע",
    "כרטיס",
    "שובר",
    "חבילת",
    "זוגית",
    "גיפט",
)


def _is_listing(title: str) -> bool:
    """True אם הכותרת היא דיל/שובר/חבילה ולא דף הזמנה אמיתי של מסעדה."""
    return any(w in title for w in _LISTING_WORDS)


# מילות-רעש שאינן מבחינות בין סניפים (שם האתר וכו') — מותר שיופיעו בכותרת "נקייה".
_NOISE_WORDS = {"ontopo"}


def _is_clean_name(req: str, title: str) -> bool:
    """
    True אם הכותרת היא השם המבוקש ללא מילים מבחינות — כלומר דף ההזמנה הראשי
    ("<שם> - Ontopo"), להבדיל מסניף אמיתי ("הדסון לילינבלום") שמוסיף מילה.
    req ו-title שניהם מנורמלים (_norm).
    """
    req_words = set(req.split())
    extra = [w for w in title.split() if w not in req_words]
    return all(w in _NOISE_WORDS for w in extra)


def _match_restaurant(requested: str, candidates: list[str]) -> tuple[str, str | None, list[str]]:
    """דיסאמביגואציה (לשימוש ב-resolver של שם->URL). status: one|many|none."""
    req = _norm(requested)
    req_words = [w for w in req.split() if len(w) >= 2]
    good = []
    for c in candidates:
        nc = _norm(c)
        if req and (req in nc or nc in req or (req_words and all(w in nc for w in req_words))):
            good.append(c)
    if len(good) == 1:
        return "one", good[0], good
    if len(good) > 1:
        # מעדיפים את דף ההזמנה האמיתי: כותרת שהיא בדיוק השם המבוקש, או השם +
        # רעש בלבד (כמו "Ontopo"). וריאציות עם מילים מבחינות (סניפים אמיתיים
        # כמו "הדסון לילינבלום") אינן "נקיות" וישארו לשאלת הבהרה.
        clean = [c for c in good if _is_clean_name(req, _norm(c))]
        if len(clean) == 1:
            return "one", clean[0], clean
        return "many", None, good
    return "none", None, good


async def _extract(session, instruction: str, schema: dict) -> dict:
    res = await session.extract(instruction=instruction, schema=schema)
    data = res.model_dump()
    return (data.get("data") or {}).get("result") or {}


async def book_table(
    restaurant: str,
    page_url: str,
    date: str,
    time: str,
    party_size: int,
    name: str = "",
    phone: str = "",
    *,
    dry_run: bool = True,
    notify: StatusFn | None = None,
) -> ActionResult:
    """
    מזמין שולחן בדף מסעדה ב-Ontopo (page_url = deep-link). date ריק => תאריך
    ברירת המחדל של הווידג'ט. dry_run=True עוצר לפני האישור הסופי.
    """
    notify = notify or _noop
    client = AsyncStagehand(
        browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
        browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID") or None,
        model_api_key=os.getenv("MODEL_API_KEY"),
    )
    session = await client.sessions.start(
        model_name=os.getenv("MODEL_NAME", "google/gemini-2.5-pro"),
        system_prompt="אתה מבצע פעולות באתר Ontopo בעברית, בזהירות ובדייקנות. עקוב אחר ההוראות בדיוק.",
    )
    try:
        await notify("רגע 🔄")
        await session.navigate(url=page_url)

        # ── אימות: שזה דף ההזמנה של המסעדה הנכונה ──
        page = await _extract(
            session,
            "the restaurant name on this page and whether a reservation/booking widget is visible",
            {"type": "object", "properties": {
                "restaurant": {"type": "string"}, "has_booking_form": {"type": "boolean"},
            }},
        )
        on_page = page.get("restaurant") or ""
        if not page.get("has_booking_form"):
            return ActionResult(
                success=False,
                summary=f"לא הצלחתי לפתוח את דף ההזמנה של '{restaurant}'.",
                details={"stage": "page", "page": page},
            )
        if restaurant and _norm(restaurant) not in _norm(on_page) and _norm(on_page) not in _norm(restaurant):
            return ActionResult(
                success=False,
                summary=f"הדף לא תואם ל'{restaurant}' (נפתח '{on_page}').",
                details={"stage": "verify", "on_page": on_page},
            )

        # ── כמות, תאריך, ובדיקת זמינות אמיתית ──
        await session.act(input=f"בחר {party_size} סועדים")
        if date:
            await session.act(input=f"בחר את התאריך: {date}")
        avail = await _extract(
            session,
            "list all available booking time slots currently shown in the widget",
            {"type": "object", "properties": {"available_times": {"type": "array", "items": {"type": "string"}}}},
        )
        times = avail.get("available_times") or []
        if not times:
            return ActionResult(
                success=False,
                summary=f"אין מקום ב'{on_page or restaurant}' {date or ''}. לבדוק יום אחר?",
                details={"stage": "availability", "available_times": []},
            )

        chosen_time = time if time in times else times[0]
        near = chosen_time != time
        await session.act(input=f"בחר את השעה {chosen_time}")
        if name:
            await session.act(input=f"מלא את שם המזמין: {name}")
        if phone:
            await session.act(input=f"מלא טלפון: {phone}")

        screen = await _extract(
            session,
            "the booking summary shown before final confirmation (restaurant, date, time, party size)",
            {"type": "object", "properties": {
                "restaurant": {"type": "string"}, "date": {"type": "string"},
                "time": {"type": "string"}, "party_size": {"type": "string"},
            }},
        )
        details = {
            "restaurant": on_page or restaurant, "date": date or "היום",
            "time": chosen_time, "party_size": party_size, "near_time": near, "screen": screen,
        }

        # ── שער אישור לפני צעד בלתי-הפיך ──
        if dry_run:
            await notify(f"כמעט סגור — {details['restaurant']}, {details['date']} {chosen_time}, {party_size} סועדים. מאשר?")
            return ActionResult(
                success=True,
                summary="הגעתי למסך האישור (DRY_RUN — לא ביצעתי הזמנה אמיתית).",
                details=details,
            )

        await session.act(input="אשר את ההזמנה סופית")
        proof = await _extract(
            session,
            "the confirmation details or confirmation number shown after the booking succeeded",
            {"type": "object", "properties": {"confirmation": {"type": "string"}}},
        )
        details["confirmation"] = proof.get("confirmation")
        await notify(f"סגור ✅ {details['restaurant']}, {details['date']} {chosen_time}, {party_size} סועדים.")
        return ActionResult(success=True, summary="ההזמנה בוצעה.", details=details)

    except Exception as e:  # captcha / חסימה / שגיאת אתר → כישלון כן
        await notify("נתקלתי בבעיה, לא הצלחתי לסגור.")
        return ActionResult(
            success=False,
            summary="משהו נתקע באתר, לא סגרתי. ננסה שוב?",
            details={"stage": "error", "error": str(e)},
        )
    finally:
        await session.end()
