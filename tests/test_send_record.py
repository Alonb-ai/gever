"""_send_and_record / _maybe_ack: הודעות מכניות נרשמות לזיכרון השיחה (בתהליך + התמדה),
רשימות נרשמות כטקסט, ו-ack כפול שניות אחרי תשובת הפרסונה לא נשלח."""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402


def _reset():
    pipeline._turns.clear()
    pipeline._last_out.clear()


def _wire(monkeypatch, sent, upserts):
    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, labels):
        sent.append((body, tuple(labels)))

    async def fake_get_profile(phone):
        return {"prefs": {"kept": 1}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)


def test_send_and_record_saves_turn_and_persists(monkeypatch):
    """ההודעה נשלחת, נרשמת כתור model בזיכרון-בתהליך, ומותמדת ל-prefs._chat
    בלי לדרוס prefs קיימים — "תשלח שוב את הלינק" עובד גם אחרי restart."""
    _reset()
    sent, upserts = [], []
    _wire(monkeypatch, sent, upserts)

    asyncio.run(pipeline._send_and_record("p1", "הנה הלינק: https://x"))

    assert sent == ["הנה הלינק: https://x"]
    last = pipeline._turns["p1"][-1]
    assert last["role"] == "model" and last["text"] == "הנה הלינק: https://x"
    assert last["ts"] > 0  # ts פר-תור — לתחקירים (לקח 15.7)
    assert upserts[0]["kept"] == 1  # prefs קיימים שרדו את המיזוג
    assert upserts[0]["_chat"]["turns"][-1]["text"] == "הנה הלינק: https://x"
    assert upserts[0]["_chat"]["ts"] > 0


def test_send_list_and_record_records_labels(monkeypatch):
    """רשימת בחירה נרשמת כתור טקסט אחד עם כל האופציות — גבר זוכר מה הציע."""
    _reset()
    sent, upserts = [], []
    _wire(monkeypatch, sent, upserts)

    asyncio.run(pipeline._send_list_and_record("p1", "איזה מהם?", ["סניף א", "סניף ב"]))

    assert sent == [("איזה מהם?", ("סניף א", "סניף ב"))]
    recorded = pipeline._turns["p1"][-1]["text"]
    assert "איזה מהם?" in recorded and "סניף א" in recorded and "סניף ב" in recorded


def test_record_out_caps_turns():
    """הרישום שומר על תקרת CHAT_TURNS — הודעות מכניות לא מנפחות את ההיסטוריה."""
    _reset()
    for i in range(pipeline.CHAT_TURNS + 5):
        pipeline._record_out("p1", f"m{i}")
    assert len(pipeline._turns["p1"]) == pipeline.CHAT_TURNS
    assert pipeline._turns["p1"][-1]["text"] == f"m{pipeline.CHAT_TURNS + 4}"


def test_maybe_ack_skips_recent_sends_stale(monkeypatch):
    """ack מכני מדולג כשהפרסונה ענתה הרגע (כפילות בוט), ונשלח כשעבר זמן.
    בדילוג גם המודל לא נקרא — לא שורפים חילול על הודעה שלא תישלח."""
    _reset()
    sent, upserts = [], []
    _wire(monkeypatch, sent, upserts)
    say_calls = []

    async def spy_model(intent, ctx):
        say_calls.append(intent)
        raise RuntimeError("offline")  # נופל למאגר — כמו בכל הטסטים

    monkeypatch.setattr(pipeline, "_say_model", spy_model)

    pipeline._last_out["p1"] = time.time()  # תשובת הפרסונה יצאה ממש עכשיו
    asyncio.run(pipeline._maybe_ack("p1", "ack_start", fallback=("רגע אני על זה 🔄",)))
    assert sent == []
    assert say_calls == []  # מדולג לפני החילול

    pipeline._last_out["p1"] = time.time() - pipeline.ACK_GAP_S - 1
    asyncio.run(pipeline._maybe_ack("p1", "ack_start", fallback=("רגע אני על זה 🔄",)))
    assert sent == ["רגע אני על זה 🔄"]  # מסלול ה-fallback של האתר
    assert say_calls == ["ack_start"]
