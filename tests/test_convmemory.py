"""בדיקות לזיכרון-שיחה (convmemory): השיחה נבנית מ-history שמור, שורדת restart
דרך Supabase, מתכווצת ל-CHAT_TURNS, ועובדת בתהליך גם בלי מפתחות.

מ-mock-ים את ה-Gemini client (chats.create רושם את ה-history שקיבל) ואת שכבת
הזיכרון (dict פשוט שמשחק את תפקיד Supabase)."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402


class _FakeChat:
    def __init__(self, history):
        self.history = history

    def send_message(self, msg):
        r = type("R", (), {})()
        r.text = json.dumps({"reply": "סבבה", "ready": False})
        return r


class _FakeChats:
    def __init__(self):
        self.last_history = None

    def create(self, *, model, config, history):
        self.last_history = history  # מה ש-_chat_for בנה מהתורות השמורות
        return _FakeChat(history)


class _FakeClient:
    def __init__(self):
        self.chats = _FakeChats()


def _setup(monkeypatch, *, supabase_on: bool):
    """מאפס מצב מודול, מחבר client מזויף ושכבת-זיכרון מזויפת. מחזיר את ה-store."""
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._reset_next.clear()
    pipeline._booking.clear()

    fake = _FakeClient()
    monkeypatch.setattr(pipeline, "_client", fake)

    store: dict = {}  # phone -> {"prefs": {...}} — משחק את Supabase

    async def fake_get_profile(phone):
        return store.get(phone) if supabase_on else None

    async def fake_recent_bookings(phone, limit=3):
        return []

    async def fake_upsert_profile(phone, name=None, email=None, prefs=None):
        if not supabase_on:
            return
        row = store.setdefault(phone, {})
        if prefs is not None:
            row["prefs"] = prefs

    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "recent_bookings", fake_recent_bookings)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert_profile)
    return fake, store


def test_survives_restart_via_supabase(monkeypatch):
    """קריטריון הקבלה של הבאג: אחרי restart (זיכרון-בתהליך נמחק) — השיחה משוחזרת
    מ-Supabase, ולכן ה-history שנבנה כולל את התורות הקודמים."""
    fake, store = _setup(monkeypatch, supabase_on=True)
    phone = "+972500000001"

    asyncio.run(pipeline.converse(phone, "שלום"))  # תור 1: מגע ראשון, history ריק
    assert fake.chats.last_history == []
    asyncio.run(pipeline.converse(phone, "מה קורה"))  # תור 2: רואה 2 תורות
    assert len(fake.chats.last_history) == 2
    assert len(pipeline._turns[phone]) == 4  # 2 חילופים = 4 תורות

    pipeline._turns.clear()  # === restart ===: הזיכרון-בתהליך נמחק
    asyncio.run(pipeline.converse(phone, "עוד הודעה"))  # תור 3: שחזור מ-Supabase
    assert len(fake.chats.last_history) == 4  # זכר את 4 התורות מה-DB, לא התחיל מאפס


def test_caps_at_chat_turns(monkeypatch):
    """ההיסטוריה מתכווצת לזנב CHAT_TURNS — לא גדלה בלי גבול."""
    _setup(monkeypatch, supabase_on=True)
    phone = "+972500000002"
    for i in range(pipeline.CHAT_TURNS):  # הרבה חילופים
        asyncio.run(pipeline.converse(phone, f"הודעה {i}"))
    assert len(pipeline._turns[phone]) == pipeline.CHAT_TURNS


def test_in_process_memory_without_keys(monkeypatch):
    """בלי Supabase — הזיכרון-בתהליך עדיין עובד (אין רגרסיה במסלול ה-dev)."""
    fake, _ = _setup(monkeypatch, supabase_on=False)
    phone = "+972500000003"
    asyncio.run(pipeline.converse(phone, "שלום"))
    asyncio.run(pipeline.converse(phone, "עוד"))
    assert len(fake.chats.last_history) == 2  # תור 2 ראה את תור 1 מהזיכרון-בתהליך


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
