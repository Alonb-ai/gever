"""זיכרון בין שיחות — async API מעל Supabase REST (PostgREST) דרך httpx.

עיצוב מאושר:
- name + email מוצפנים at-rest עם Fernet(ENCRYPTION_KEY) — מצפינים בכתיבה, מפענחים בקריאה.
- GATING: בלי supabase_url או supabase_service_key הכל no-op — get_profile/recent_bookings
  מחזירים None/[] ו-upsert/log לא עושים כלום. הפייפליין מתנהג בדיוק כמו היום בלי מפתחות.
- אף פונקציה לא זורקת על קונפיג חסר או כשל רשת — תופסים, מתעדים, ומחזירים ברירת-מחדל בטוחה.
"""

import logging

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

log = logging.getLogger("gever")

_TIMEOUT = 10.0


def _enabled() -> bool:
    """הזיכרון פעיל רק כששתי הקונפיגורציות קיימות."""
    return bool(settings.supabase_url and settings.supabase_service_key)


def _rest_url(path: str) -> str:
    return f"{settings.supabase_url.rstrip('/')}/rest/v1/{path}"


def _headers(extra: dict | None = None) -> dict:
    key = settings.supabase_service_key
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _fernet() -> Fernet | None:
    """Fernet מ-ENCRYPTION_KEY, או None אם המפתח חסר/לא תקין (אז לא מצפינים)."""
    if not settings.encryption_key:
        return None
    try:
        return Fernet(settings.encryption_key.encode())
    except (ValueError, TypeError) as exc:
        log.warning("memory: invalid ENCRYPTION_KEY, storing PII as-is: %s", exc)
        return None


def _encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    f = _fernet()
    if f is None:
        return value
    return f.encrypt(value.encode()).decode()


def _decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    f = _fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        # ערך לא-מוצפן (legacy) או מפתח שונה — מחזירים כמו שהוא במקום להפיל.
        return value


async def _request(
    method: str,
    path: str,
    *,
    op: str,
    phone: str,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response | None:
    """בקשת PostgREST אחת: client+headers+raise_for_status, תופס ומחזיר None בכשל.

    מרכז את ה-boilerplate החוזר (יצירת client, מפתחות שירות, try/except-warning).
    מי שקורא אחראי על ה-_enabled() short-circuit ועל עיצוב ברירת-המחדל המגודרת.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(
                method,
                _rest_url(path),
                headers=_headers(headers),
                params=params,
                json=json,
            )
            resp.raise_for_status()
            return resp
    except Exception as exc:  # noqa: BLE001 — לעולם לא מפילים את הפייפליין על קריאת זיכרון
        log.warning("memory.%s failed for %s: %s", op, phone, exc)
        return None


async def get_profile(phone: str) -> dict | None:
    """פרופיל המשתמש לפי phone, עם name/email מפוענחים. None אם אין/כבוי/כשל."""
    if not _enabled():
        return None
    resp = await _request(
        "GET",
        "users",
        op="get_profile",
        phone=phone,
        params={"phone": f"eq.{phone}", "select": "*", "limit": "1"},
    )
    if resp is None:
        return None
    rows = resp.json()
    if not rows:
        return None
    row = rows[0]
    row["name"] = _decrypt(row.get("name"))
    row["email"] = _decrypt(row.get("email"))
    return row


async def upsert_profile(
    phone: str,
    name: str | None = None,
    email: str | None = None,
    prefs: dict | None = None,
) -> None:
    """יוצר/מעדכן פרופיל. שדות None לא נדרסים. name/email נשמרים מוצפנים."""
    if not _enabled():
        return
    payload: dict = {"phone": phone, "updated_at": "now()"}
    if name is not None:
        payload["name"] = _encrypt(name)
    if email is not None:
        payload["email"] = _encrypt(email)
    if prefs is not None:
        payload["prefs"] = prefs
    await _request(
        "POST",
        "users",
        op="upsert_profile",
        phone=phone,
        headers={"Prefer": "resolution=merge-duplicates"},
        params={"on_conflict": "phone"},
        json=payload,
    )


async def set_inflight(phone: str, restaurant: str) -> None:
    """מסמן שהזמנה רצה עכשיו — שורד restart כדי שיתומים (redeploy באמצע ריצה) יזוהו
    בעליית השרת. read-merge כי upsert דורס את prefs כיחידה. race מול תור שיחה מקביל
    אפשרי תיאורטית — זניח למשתמשי הבטא, השדה מתנקה בכל מקרה בסוף הריצה הבאה."""
    if not _enabled():
        return
    prof = await get_profile(phone)
    prefs = (prof or {}).get("prefs") or {}
    prefs["_inflight"] = {"restaurant": restaurant}
    await upsert_profile(phone, prefs=prefs)


async def clear_inflight(phone: str) -> None:
    """מסיר את סימון הריצה (הריצה הסתיימה — בכל תוצאה)."""
    if not _enabled():
        return
    prof = await get_profile(phone)
    prefs = (prof or {}).get("prefs") or {}
    if prefs.pop("_inflight", None) is not None:
        await upsert_profile(phone, prefs=prefs)


async def list_inflight() -> list[dict]:
    """[{phone, restaurant}] של הזמנות שהיו באוויר — נקרא בעליית השרת לאיתור יתומים."""
    if not _enabled():
        return []
    resp = await _request(
        "GET",
        "users",
        op="list_inflight",
        phone="*",
        params={"select": "phone,prefs", "prefs->_inflight": "not.is.null"},
    )
    if resp is None:
        return []
    out = []
    for row in resp.json():
        inf = (row.get("prefs") or {}).get("_inflight") or {}
        out.append({"phone": row.get("phone"), "restaurant": inf.get("restaurant") or ""})
    return out


async def log_booking(
    phone: str,
    restaurant: str,
    date: str,
    time: str,
    party_size: int,
    status: str,
) -> None:
    """רושם הזמנה בהיסטוריה. no-op כשהזיכרון כבוי; לא מפיל על כשל."""
    if not _enabled():
        return
    payload = {
        "phone": phone,
        "restaurant": restaurant,
        "date": date,
        "time": time,
        "party_size": party_size,
        "status": status,
    }
    await _request(
        "POST",
        "bookings",
        op="log_booking",
        phone=phone,
        json=payload,
    )


async def recent_bookings(phone: str, limit: int = 3) -> list:
    """ההזמנות האחרונות (חדש→ישן) לצורך recap קל. [] אם אין/כבוי/כשל."""
    if not _enabled():
        return []
    resp = await _request(
        "GET",
        "bookings",
        op="recent_bookings",
        phone=phone,
        params={
            "phone": f"eq.{phone}",
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        },
    )
    if resp is None:
        return []
    return resp.json()
