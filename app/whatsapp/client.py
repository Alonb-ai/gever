"""
WhatsApp via Meta Cloud API.

שולח הודעות חזרה למשתמש דרך graph.facebook.com. בתוך חלון 24 השעות אפשר
טקסט חופשי; מחוץ לחלון צריך template מאושר. ה-MVP עובד בתוך החלון.
"""

import httpx

from app.config import settings


async def send_text(to: str, body: str) -> dict:
    """שליחת טקסט חופשי. `to` = wa_id במספרים בלבד (לדוגמה '972542773331')."""
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/messages"
    )
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
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
