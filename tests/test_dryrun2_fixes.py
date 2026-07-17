"""בדיקות לתיקוני dry-run #2:
- #1: _chat_for פותח שיחה טרייה אחרי restart (זיכרון-בתהליך + _last_seen ריקים)
  כשיש _chat ישן/closed מותמד — גם בלי 'ts', וגם כשיש 'ts' ישן >3h.
- #3: _truth_note של "working" נוקב בשם המסעדה שבתהליך.
- #4: ONBOARDING_BLOCK מזכיר מייל.

מ-mock-ים את ה-Gemini client ואת שכבת הזיכרון (כמו test_convmemory)."""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import ONBOARDING_BLOCK  # noqa: E402


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
        self.last_history = history
        return _FakeChat(history)


class _FakeClient:
    def __init__(self):
        self.chats = _FakeChats()


def _setup(monkeypatch):
    """מאפס מצב מודול, מחבר client + שכבת-זיכרון מזויפים. מחזיר (fake, store)."""
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._reset_next.clear()
    pipeline._booking.clear()
    pipeline._pending_commit.clear()

    fake = _FakeClient()
    monkeypatch.setattr(pipeline, "_client", fake)

    store: dict = {}

    async def fake_get_profile(phone):
        return store.get(phone)

    async def fake_recent_bookings(phone, limit=3):
        return []

    async def fake_upsert_profile(phone, name=None, email=None, prefs=None):
        row = store.setdefault(phone, {})
        if prefs is not None:
            row["prefs"] = prefs

    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "recent_bookings", fake_recent_bookings)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert_profile)
    return fake, store


# ── #1 — fresh page after restart ──────────────────────────────────────────


def test_restart_restores_chat_when_ts_fresh(monkeypatch):
    """התהפך ב-fix/chat-memory (רגרסיית פרוד 17.7): ts טרי (<3h) אחרי restart —
    ההיסטוריה משוחזרת גם בלי סשן הזמנה חי. היוריסטיקת no_live_session הישנה
    מחקה את זיכרון השיחה של כל המשתמשים בכל deploy; flow חי ממילא משוחזר
    ב-_restore_flow, אז שחזור התורות כבר לא מטעה. ts ישן עדיין פותח דף חדש
    (test_restart_with_old_ts_is_stale_even_with_live_session)."""
    fake, store = _setup(monkeypatch)
    phone = "+972500000010"
    store[phone] = {
        "prefs": {"_chat": {"turns": [{"role": "user", "text": "רוסטיקו"}], "ts": time.time()}}
    }
    asyncio.run(pipeline.converse(phone, "שלום"))
    assert len(fake.chats.last_history) == 1  # התור הישן שוחזר — deploy לא מוחק שיחה


def test_restart_opens_fresh_with_legacy_chat_no_ts(monkeypatch):
    """backward-compat: _chat ישן בלי 'ts' (הסכמה הישנה {turns}). אחרי restart, בלי
    סשן חי — נפתח נקי בלי לקרוס על ts חסר."""
    fake, store = _setup(monkeypatch)
    phone = "+972500000011"
    store[phone] = {"prefs": {"_chat": {"turns": [{"role": "user", "text": "רוסטיקו"}]}}}
    asyncio.run(pipeline.converse(phone, "שלום"))
    assert fake.chats.last_history == []


def test_restart_with_old_ts_is_stale_even_with_live_session(monkeypatch):
    """הבאג השני (gap אמיתי >3h אחרי restart): ts ישן ב-_chat → stale גם אם יש סשן
    חי בזיכרון. מאשר שמסלול ה-ts עובד עצמאית מבדיקת הסשן-החי."""
    fake, store = _setup(monkeypatch)
    phone = "+972500000012"
    old_ts = time.time() - (pipeline.SESSION_GAP_S + 60)
    store[phone] = {
        "prefs": {"_chat": {"turns": [{"role": "user", "text": "רוסטיקו"}], "ts": old_ts}}
    }
    pipeline._booking[phone] = {"state": "working", "info": "רוסטיקו"}  # סשן חי
    asyncio.run(pipeline.converse(phone, "שלום"))
    assert fake.chats.last_history == []  # ה-ts הישן הכריע staleness


def test_in_process_pending_to_confirm_keeps_history(monkeypatch):
    """לא רגרסיה: בתוך אותו תהליך, סשן הזמנה חי (_pending_commit) שומר על ההמשכיות —
    התור השני רואה את ההיסטוריה, לא נפתח נקי."""
    fake, _ = _setup(monkeypatch)
    phone = "+972500000013"
    asyncio.run(pipeline.converse(phone, "שלום"))  # תור 1, _last_seen נכתב
    assert fake.chats.last_history == []
    asyncio.run(pipeline.converse(phone, "עוד"))  # תור 2, מסלול חם — רואה היסטוריה
    assert len(fake.chats.last_history) == 2


# ── #3 — truth_note names the in-flight restaurant ──────────────────────────


def test_truth_note_working_names_restaurant(monkeypatch):
    _setup(monkeypatch)
    phone = "+972500000020"
    pipeline._booking[phone] = {"state": "working", "info": "ביצ'יקלטה"}
    note = pipeline._truth_note(phone)
    assert "ביצ'יקלטה" in note
    assert "הזמנה אחרת" in note or "אחרת" in note  # אומר שאי-אפשר להתחיל אחרת


def test_truth_note_working_empty_info_degrades(monkeypatch):
    """fallback: info ריק (אין שם) → הערה הגנרית הישנה, בלי לקרוס."""
    _setup(monkeypatch)
    phone = "+972500000021"
    pipeline._booking[phone] = {"state": "working", "info": ""}
    note = pipeline._truth_note(phone)
    assert "בתהליך" in note


# ── #4 — onboarding mentions email ──────────────────────────────────────────


def test_onboarding_block_mentions_email():
    assert "מייל" in ONBOARDING_BLOCK


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
