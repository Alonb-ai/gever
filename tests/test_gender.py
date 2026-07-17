"""המסלול הנשי מקצה לקצה: המין נלמד בשיחה (extract → profile.gender) → נשמר
ב-prefs → נטען לזרע של התור הבא (gender_line בלשון נקבה), וההודעות המכניות
ב-pipeline נקיות מפנייה גברית ("אחי"/"בראדר") — הן נשלחות לכל משתמש/ת."""

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import gender_line  # noqa: E402


class _FakeChat:
    def __init__(self, replies):
        self._replies = replies

    def send_message(self, msg):
        r = type("R", (), {})()
        r.text = json.dumps(self._replies.pop(0))
        return r


class _FakeChats:
    def __init__(self, replies):
        self._replies = replies
        self.last_config = None

    def create(self, *, model, config, history):
        self.last_config = config  # הזרע (system_instruction) שנבנה לתור הזה
        return _FakeChat(self._replies)


class _FakeClient:
    def __init__(self, replies):
        self.chats = _FakeChats(replies)


def _setup(monkeypatch, replies):
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._reset_next.clear()
    pipeline._booking.clear()
    fake = _FakeClient(replies)
    monkeypatch.setattr(pipeline, "_client", fake)

    store: dict = {}  # phone -> row — משחק את Supabase

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
    return fake, store


def test_gender_learned_saved_and_seeded(monkeypatch):
    """השרשרת המלאה: ה-extract מחזיר profile.gender=female → נשמר ב-prefs →
    הזרע של התור הבא נבנה עם שורת הפנייה בלשון נקבה."""
    fake, store = _setup(
        monkeypatch,
        [
            {"reply": "סבבה", "ready": False, "profile": {"gender": "female"}},
            {"reply": "אחלה", "ready": False},
        ],
    )
    phone = "+972500000020"
    asyncio.run(pipeline.converse(phone, "היי אני מחפשת מקום למחר בערב"))
    assert store[phone]["prefs"]["gender"] == "female"  # נשמר ל-Supabase (prefs)

    asyncio.run(pipeline.converse(phone, "משהו רומנטי"))
    seed = fake.chats.last_config.system_instruction  # נטען לזרע של התור הבא
    assert gender_line("female") in seed


def test_gender_line_female_is_rich():
    """הפנייה הנשית עשירה כמו הגברית: לשון נקבה עקבית + כינויי חיבה מותאמים,
    בלי הכינויים המתנשאים (מוזכרים רק כקו אדום)."""
    line = gender_line("female")
    assert "נקבה" in line
    for needle in ("אחותי", "מלכה", "קפטנית"):
        assert needle in line
    assert "לא ידוע" in gender_line(None)  # בלי מידע — ניטרלי, לא מטים


def test_gender_line_male_rotates_wide_repertoire():
    """בקשת אלון 17.7 ('לא רואה מספיק אלוף, דוד, חיים שלי — בעיקר אחי'): הפנייה
    הגברית נושאת רפרטואר רחב + הוראת רוטציה מפורשת, לא רק 'אחי'."""
    line = gender_line("male")
    assert "זכר" in line
    for needle in ("אלוף", "דוד", "חיים שלי", "נשמה", "כפרה"):
        assert needle in line
    assert "ברירת המחדל" in line  # 'אחי' הוא לא ברירת המחדל — הוראת הרוטציה


def test_mechanical_messages_not_male_addressed():
    """ההודעות המכניות (pipeline + התנצלות היתומים ב-main) נשלחות לכל משתמש/ת —
    אסור שיהיה בהן 'אחי'/'אחשלי'/'בראדר' (נמצא: 'שנייה אחי', 'אחי זה נתקע לי',
    'אחשלי נפלתי'). סריקת מקור — נעילה נגד רגרסיה."""
    from app import main

    for mod in (pipeline, main):
        with open(mod.__file__, encoding="utf-8") as f:
            src = f.read()
        assert not re.search(r"אחי\b|אחשלי|בראדר", src), mod.__file__


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
