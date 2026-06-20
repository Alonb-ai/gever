"""בדיקות להרחבת הפרופיל: עובדות מ-'profile' נשמרות ל-prefs, ממוזגות בלי לדרוס
עובדות קודמות (ולא את _chat), ו-_profile_block מזריק אותן חזרה לזרע."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402


class _FakeChat:
    def __init__(self, replies):
        self._replies = replies  # תור של dict-ים שיוחזרו כ-JSON, אחד לכל send_message

    def send_message(self, msg):
        r = type("R", (), {})()
        r.text = json.dumps(self._replies.pop(0))
        return r


class _FakeChats:
    def __init__(self, replies):
        self._replies = replies

    def create(self, *, model, config, history):
        return _FakeChat(self._replies)


class _FakeClient:
    def __init__(self, replies):
        self.chats = _FakeChats(replies)


def _setup(monkeypatch, replies):
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._reset_next.clear()
    pipeline._booking.clear()
    monkeypatch.setattr(pipeline, "_client", _FakeClient(replies))

    store: dict = {}

    async def fake_get_profile(phone):
        return store.get(phone)

    async def fake_recent_bookings(phone, limit=3):
        return []

    async def fake_upsert_profile(phone, name=None, email=None, prefs=None):
        row = store.setdefault(phone, {})
        if name is not None:
            row["name"] = name
        if email is not None:
            row["email"] = email
        if prefs is not None:
            row["prefs"] = prefs

    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "recent_bookings", fake_recent_bookings)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert_profile)
    return store


def test_profile_facts_saved_and_merged(monkeypatch):
    """תור 1 מוסר עיר+זוגיות, תור 2 מוסר מסעדה מועדפת — שניהם נשמרים, וה-_chat נשמר."""
    store = _setup(
        monkeypatch,
        [
            {
                "reply": "סבבה",
                "ready": False,
                "profile": {"city": "תל אביב", "relationship": "בזוגיות"},
            },
            {"reply": "אחלה", "ready": False, "profile": {"fav_restaurant": "טייזו"}},
        ],
    )
    phone = "+972500000010"
    asyncio.run(pipeline.converse(phone, "אני גר בתל אביב בזוגיות"))
    asyncio.run(pipeline.converse(phone, "המסעדה האהובה עליי טייזו"))

    prefs = store[phone]["prefs"]
    assert prefs["city"] == "תל אביב"
    assert prefs["relationship"] == "בזוגיות"  # מתור 1 לא נדרס
    assert prefs["fav_restaurant"] == "טייזו"  # נוסף בתור 2
    assert "_chat" in prefs and len(prefs["_chat"]["turns"]) == 4  # זיכרון השיחה שרד


def test_empty_profile_facts_dropped(monkeypatch):
    """ערכים ריקים/None לא נכתבים — אי אפשר לאפס עובדה בטעות."""
    store = _setup(
        monkeypatch,
        [{"reply": "מה קורה", "ready": False, "profile": {"city": "", "relationship": "רווק"}}],
    )
    phone = "+972500000011"
    asyncio.run(pipeline.converse(phone, "מה נשמע"))
    prefs = store[phone]["prefs"]
    assert "city" not in prefs  # ריק — לא נשמר
    assert prefs["relationship"] == "רווק"


def test_profile_block_injects_facts():
    """_profile_block מזריק את העובדות החדשות (מייל/זוגיות/עיר/מסעדה) לזרע."""
    block = pipeline._profile_block(
        {
            "name": "אלון",
            "email": "a@b.com",
            "prefs": {"relationship": "בזוגיות", "city": "תל אביב", "fav_restaurant": "טייזו"},
        }
    )
    for needle in ["אלון", "a@b.com", "בזוגיות", "תל אביב", "טייזו"]:
        assert needle in block


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
