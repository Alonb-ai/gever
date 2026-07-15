"""keepalive יומי ל-Supabase — פרויקט חינמי מושהה אחרי ~שבוע שקט (תקרית 14.7)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import main  # noqa: E402
from app.db import memory  # noqa: E402


def test_keepalive_queries_daily(monkeypatch):
    """הלולאה שולחת שאילתה, ישנה יום, ושולחת שוב — ומתה נקי על cancel."""
    calls, sleeps = [], []

    async def fake_recent(phone, limit=3):
        calls.append(phone)
        return []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:  # שני מחזורים מלאים מספיקים להוכחה
            raise asyncio.CancelledError

    monkeypatch.setattr(memory, "recent_bookings", fake_recent)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    try:
        asyncio.run(main._supabase_keepalive())
    except asyncio.CancelledError:
        pass
    assert calls == ["_keepalive", "_keepalive"]
    assert sleeps == [main.KEEPALIVE_INTERVAL_S] * 2
