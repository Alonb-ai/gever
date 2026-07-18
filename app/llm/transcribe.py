"""
תמלול הודעות קוליות — Gemini.

הודעה קולית של וואטסאפ היא ogg/opus קטן (דקות בודדות = מאות KB) — הרבה מתחת
לתקרת ה-20MB של בקשת inline, אז הבייטים נשלחים ישירות בלי Files API.
"""

import asyncio
import logging

from google import genai
from google.genai import types

from app.config import settings

log = logging.getLogger("gever")

# הגנת עלות: ~2-3 דקות של opus קולי. ארוך מזה — מבקשים לקצר, לא מתמללים.
MAX_VOICE_BYTES = 700_000

_PROMPT = (
    "תמלל את ההקלטה הזאת מילה במילה, בשפה שבה היא נאמרה (בדרך כלל עברית). "
    "החזר את הטקסט בלבד — בלי הערות, בלי תרגום ובלי תיאורי רקע. "
    "אם אין בה דיבור ברור החזר טקסט ריק."
)

_client: genai.Client | None = None


async def transcribe_voice(audio: bytes, mime_type: str) -> str:
    """טקסט התמלול, "" כשאין דיבור ברור. חריגות (רשת/מודל) עולות למתקשר."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    # וואטסאפ שולח "audio/ogg; codecs=opus" — ל-Gemini מוסרים mime בסיסי
    mime = (mime_type or "audio/ogg").split(";")[0].strip()
    resp = await asyncio.to_thread(
        _client.models.generate_content,
        model=settings.gemini_model,
        contents=[types.Part.from_bytes(data=audio, mime_type=mime), _PROMPT],
        config=types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return (resp.text or "").strip()
