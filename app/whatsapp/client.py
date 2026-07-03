"""
WhatsApp via Meta Cloud API.

שולח הודעות חזרה למשתמש דרך graph.facebook.com. בתוך חלון 24 השעות אפשר
טקסט חופשי; מחוץ לחלון צריך template מאושר. ה-MVP עובד בתוך החלון.
"""

import logging

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


def _list_rows(options: list[str]) -> list[dict]:
    """אופציות → שורות interactive list. מגבלות Meta: עד 10 שורות, כותרת ≤24 תווים,
    description ≤72 — שם ארוך נחתך בכותרת והמלא עובר ל-description."""
    rows = []
    for i, opt in enumerate(options[:10]):
        row = {"id": str(i), "title": opt[:24]}
        if len(opt) > 24:
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
