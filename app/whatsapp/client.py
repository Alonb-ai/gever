"""
WhatsApp via Meta Cloud API.

שולח הודעות חזרה למשתמש דרך graph.facebook.com. בתוך חלון 24 השעות אפשר
טקסט חופשי; מחוץ לחלון צריך template מאושר. ה-MVP עובד בתוך החלון.
"""

import logging
import time
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger("gever")


def _messages_url() -> str:
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/messages"
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


async def send_typing(message_id: str | None) -> None:
    """מחוון 'מקליד…' בוואטסאפ (Cloud API, Public Beta). נשלח כחלק מסימון ההודעה
    הנכנסת כנקראה; נמשך עד ~25 שניות או עד שנשלחת תשובה (שמנקה אותו). דורש את
    message_id של ההודעה הנכנסת. best-effort — כשל מתועד ולא שובר את הזרימה."""
    if not message_id:
        return
    url = _messages_url()
    headers = _headers()
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — מחוון הקלדה הוא קישוט, לא קריטי
        log.warning("send_typing failed: %s", exc)


# כותרת שורה מוגבלת ל-24 תווים — קיצור מוכר עדיף על מילה חתוכה באמצע.
_ABBREV = [("תל אביב-יפו", "ת״א"), ("תל אביב יפו", "ת״א"), ("תל אביב", "ת״א"), ("ירושלים", "י-ם")]


def _fit_title(text: str, limit: int = 24) -> str:
    """התאמת כותרת למגבלה בלי לחתוך מילה באמצע: קודם ראשי תיבות מוכרים (ת״א),
    ואם עדיין ארוך — משמיטים מילים שלמות מהסוף. השם המלא ממילא ב-description."""
    if len(text) <= limit:
        return text
    for full, ab in _ABBREV:
        if full in text:
            text = text.replace(full, ab)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.strip() or text[:limit]


def _list_rows(options: list[str]) -> list[dict]:
    """אופציות → שורות interactive list. מגבלות Meta: עד 10 שורות, כותרת ≤24 תווים,
    description ≤72. סניפים של אותה רשת חולקים רישא ("התאילנדית …") — חיתוך ב-24
    היה מעלים את המיקום, המבדיל האמיתי בין השורות. לכן הכותרת היא החלק המבדיל
    (הזנב אחרי הרישא המשותפת = המיקום) והשם המלא עובר ל-description."""
    opts = options[:10]
    strip = 0
    if len(opts) > 1:
        for words in zip(*(o.split() for o in opts)):
            if len(set(words)) != 1:
                break
            strip += 1
    rows = []
    for i, opt in enumerate(opts):
        tail = " ".join(opt.split()[strip:])
        title = _fit_title(tail or opt)
        row = {"id": str(i), "title": title}
        if title != opt:
            row["description"] = opt[:72]
        rows.append(row)
    return rows


async def send_list(to: str, body: str, options: list[str], button: str = "בחירה") -> dict:
    """הודעת בחירה-מרשימה (WhatsApp interactive list) — במקום להקריא אופציות בטקסט.
    התשובה חוזרת ב-webhook כ-list_reply ומוזרמת לשיחה כטקסט רגיל."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {"button": button[:20], "sections": [{"rows": _list_rows(options)}]},
        },
    }
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(_messages_url(), json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def download_media(media_id: str) -> tuple[bytes, str]:
    """הורדת מדיה נכנסת (הודעה קולית וכו'): GET /{media-id} מחזיר url זמני
    (פג תוך 5 דקות) + mime_type, וההורדה עצמה דורשת את אותו Bearer.
    מחזיר (bytes, mime_type)."""
    meta_url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{media_id}"
    headers = _headers()
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(meta_url, headers=headers)
        resp.raise_for_status()
        info = resp.json()
        resp = await http.get(info["url"], headers=headers)
        resp.raise_for_status()
        return resp.content, info.get("mime_type") or ""


# מדיה שהעלינו (סטיקרים) נשמרת אצל Meta ל-30 יום — cache של media_id עם רענון
# עצלן לפני התפוגה, שלא נעלה את אותו webp בכל שליחה.
MEDIA_TTL_S = 25 * 24 * 60 * 60
_media_cache: dict = {}  # path -> (media_id, ts)


async def upload_media(path: str, mime_type: str = "image/webp") -> str:
    """העלאת קובץ מדיה ל-Meta (POST /{phone-number-id}/media) — מחזיר media_id."""
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/media"
    )
    p = Path(path)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            url,
            headers=_headers(),
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (p.name, p.read_bytes(), mime_type)},
        )
        resp.raise_for_status()
        return resp.json()["id"]


async def send_sticker(to: str, media_id: str) -> dict:
    """שליחת סטיקר לפי media_id שהועלה (webp סטטי ≤100KB / מונפש ≤500KB)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "sticker",
        "sticker": {"id": media_id},
    }
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(_messages_url(), json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def send_sticker_file(to: str, path: str) -> dict:
    """סטיקר מקובץ מקומי: העלאה חד-פעמית עם cache של media_id (רענון עצלן לפני
    תפוגת ה-30 יום של Meta)."""
    cached = _media_cache.get(path)
    if cached and time.time() - cached[1] < MEDIA_TTL_S:
        media_id = cached[0]
    else:
        media_id = await upload_media(path)
        _media_cache[path] = (media_id, time.time())
    return await send_sticker(to, media_id)


async def send_text(to: str, body: str) -> dict:
    """שליחת טקסט חופשי. `to` = wa_id במספרים בלבד (לדוגמה '972542773331')."""
    url = _messages_url()
    headers = _headers()
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
