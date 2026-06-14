"""
WhatsApp via Twilio (שלב 1).

שולח הודעות חזרה למשתמש דרך Twilio. ב-Sandbox אין צורך באישור Meta —
מתחילים לפתח מיד. בפרודקשן מחליפים את TWILIO_WHATSAPP_FROM ל-sender אמיתי.
"""

import httpx

from app.config import settings

TWILIO_API = "https://api.twilio.com/2010-04-01"


async def send_text(to: str, body: str) -> dict:
    """
    שליחת הודעת WhatsApp דרך Twilio. `to` בפורמט 'whatsapp:+9725...'.
    בתוך חלון 24 השעות אפשר טקסט חופשי; מחוץ לחלון צריך template מאושר.
    """
    url = f"{TWILIO_API}/Accounts/{settings.twilio_account_sid}/Messages.json"
    data = {"From": settings.twilio_whatsapp_from, "To": to, "Body": body}
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(url, data=data, auth=auth)
        resp.raise_for_status()
        return resp.json()
