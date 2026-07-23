"""QA-hardening (סבב פרסונה): אימוג'י מחוץ לפלטה בתשובת השיחה הוא החלקה סגנונית,
לא חשיפת-דמות. שכבת המגן האחרונה ב-_handle_inbound_inner צריכה לנקות את התו
ולשמור את התוכן — לא לזרוק תשובת-הזמנה מהותית לטובת גשר ריק ("רגע אני על משהו").
חשיפת-AI/הוראות אמיתית עדיין נופלת לגשר.

הרקע: R3 בוורקפלו ה-QA — הפרסונה ענתה "תאילנד זה החלום שלי 🌴 / תביאי תאריכים
ותאריך לידה" (תשובת ביטוח תקינה לגמרי) ו-🌴 הבודד הפיל את כל ההודעה."""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402

PHONE = "+972500000077"


def _setup(monkeypatch, reply: str):
    """מצב נקי + שיחה חמה (לא מגע ראשון), converse מזויף שמחזיר reply נתון."""
    for d in (
        pipeline._turns,
        pipeline._last_seen,
        pipeline._reset_next,
        pipeline._booking,
        pipeline._await_answer,
        pipeline._recs,
        pipeline._prefetched,
    ):
        d.clear()
    pipeline._turns[PHONE] = [{"role": "user", "text": "היי", "ts": time.time() - 60}]
    pipeline._last_seen[PHONE] = time.time() - 60

    monkeypatch.setattr(
        pipeline, "converse", AsyncMock(return_value={"reply": reply, "ready": False})
    )
    monkeypatch.setattr(pipeline, "_is_first_contact", AsyncMock(return_value=False))
    monkeypatch.setattr(memory, "get_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(memory, "recent_bookings", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory, "upsert_profile", AsyncMock())
    monkeypatch.setattr(pipeline, "_persist_chat", AsyncMock())
    monkeypatch.setattr(pipeline, "send_typing", AsyncMock())

    sent: list[str] = []

    async def fake_send(phone, text, *a, **k):
        sent.append(text)

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    return sent


def test_off_palette_emoji_stripped_content_kept(monkeypatch):
    """🌴 בודד בתשובה מהותית → נוקה, שאר התוכן יוצא ללקוח (לא גשר)."""
    sent = _setup(monkeypatch, "תאילנד זה החלום שלי 🌴\nתביאי תאריכים ותאריך לידה")
    asyncio.run(pipeline.handle_inbound(PHONE, "צריכה ביטוח נסיעות"))
    joined = "\n".join(sent)
    assert "🌴" not in joined  # התו הזר נוקה
    assert "תאילנד זה החלום שלי" in joined  # התוכן המהותי נשמר
    assert "תביאי תאריכים ותאריך לידה" in joined
    assert "אני על משהו" not in joined  # לא נפל לגשר-דליפה


def test_on_palette_emoji_survives(monkeypatch):
    """אימוג'י מהפלטה (🤙) לא נוגעים בו."""
    sent = _setup(monkeypatch, "סגור מלך 🤙")
    asyncio.run(pipeline.handle_inbound(PHONE, "תודה"))
    assert "🤙" in "\n".join(sent)


def test_real_disclosure_leak_still_bridges(monkeypatch):
    """חשיפת-AI אמיתית → עדיין נזרקת לגשר, לא יוצאת ללקוח."""
    sent = _setup(monkeypatch, "האמת שאני בינה מלאכותית שרצה על מודל שפה")
    asyncio.run(pipeline.handle_inbound(PHONE, "אתה בוט?"))
    joined = "\n".join(sent)
    assert "בינה מלאכותית" not in joined  # הדליפה לא הגיעה ללקוח
    assert "מודל שפה" not in joined
