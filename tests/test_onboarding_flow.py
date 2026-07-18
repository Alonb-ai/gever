"""אונבורדינג מרוכז בשיחה ראשונה (בקשת אלון #6 + פידבק חי 18.7): מגע ראשון
אי-פעם → הודעת ההיכרות (גבר + שם + מייל) היא התשובה היחידה בתור — בלי converse
שעונה ברכה גנרית מעליה. ההודעה הראשונה נרשמת להיסטוריה, כך שבקשת הזמנה מיידית
לא אובדת — ה-converse של תור התשובה רואה אותה וממשיך. משתמש עם פרופיל/היסטוריה
לא מקבל היכרות; מסלולי MISSING:name/email הקיימים נשארים רשת ביטחון."""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._await_answer.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._last_out.clear()
    pipeline._prefetched.clear()


async def _drain():
    for _ in range(3):
        await asyncio.sleep(0)
        if pipeline._pending:
            await asyncio.gather(*list(pipeline._pending), return_exceptions=True)


def _wire(monkeypatch, converse_result, *, profile=None):
    """חיווט handle_inbound: converse מזויף, לכידת הודעות וריצות, פרופיל נשלט."""
    sent: list[str] = []
    booked: list[dict] = []
    upserts: list[dict] = []
    conv: list[str] = []  # אילו הודעות בכלל הגיעו ל-converse (תור היכרות = אפס)

    async def fake_converse(phone, text):
        conv.append(text)
        pipeline._last_seen[phone] = time.time()  # כמו _chat_for האמיתי
        return dict(converse_result)

    async def fake_run_booking(phone, fields):
        booked.append(fields)

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_typing(message_id):
        pass

    async def fake_noop(phone):
        pass

    async def fake_get_profile(phone):
        return profile

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append({"name": name, "email": email})

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "run_booking", fake_run_booking)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    return sent, booked, upserts, conv


def test_first_contact_sends_intro(monkeypatch):
    """מגע ראשון עם 'היי': הודעת ההיכרות (גבר + שם + מייל) היא התשובה היחידה —
    אפס קריאות converse (הברכה הכפולה מהפידבק החי 18.7), וההודעה נכנסת להיסטוריה."""
    _reset()
    sent, _, _, conv = _wire(monkeypatch, {"reply": "אהלן", "ready": False})
    asyncio.run(pipeline.handle_inbound("new1", "היי"))
    assert len(sent) == 1  # ההיכרות לבדה — בלי "אהלן" גנרי מעליה
    assert "גבר" in sent[0] and "שם" in sent[0] and "מייל" in sent[0]
    assert conv == []  # converse לא רץ על הודעת המגע הראשון
    first = pipeline._turns["new1"][0]  # ההודעה הראשונה בהיסטוריה — ה-converse הבא רואה אותה
    assert first["role"] == "user" and first["text"] == "היי"


def test_intro_only_once(monkeypatch):
    """ההיכרות היא חד-פעמית — הודעה שנייה באותה שיחה כן עוברת ל-converse כרגיל."""
    _reset()
    sent, _, _, conv = _wire(monkeypatch, {"reply": "אהלן", "ready": False})

    async def go():
        await pipeline.handle_inbound("new2", "היי")
        await pipeline.handle_inbound("new2", "מה קורה")

    asyncio.run(go())
    assert sum("מייל" in m for m in sent) == 1
    assert conv == ["מה קורה"]  # רק ההודעה השנייה הגיעה לשיחה הרגילה
    assert sent[-1] == "אהלן"


def test_known_profile_skips_intro(monkeypatch):
    """משתמש עם פרופיל (שם/מייל) לא מקבל אונבורדינג — רק תשובת השיחה."""
    _reset()
    prof = {"name": "אלון", "email": "alon@example.com", "prefs": {}}
    sent, _, _, _ = _wire(monkeypatch, {"reply": "אהלן", "ready": False}, profile=prof)
    asyncio.run(pipeline.handle_inbound("known1", "היי"))
    assert sent == ["אהלן"]


def test_persisted_chat_skips_intro(monkeypatch):
    """היסטוריית שיחה מותמדת (אחרי restart) = לא שיחה ראשונה, גם בלי שם/מייל."""
    _reset()
    prof = {"prefs": {"_chat": {"turns": [{"role": "user", "text": "היי"}], "ts": time.time()}}}
    sent, _, _, _ = _wire(monkeypatch, {"reply": "אהלן", "ready": False}, profile=prof)
    asyncio.run(pipeline.handle_inbound("known2", "עוד הודעה"))
    assert sent == ["אהלן"]


def test_first_conversation_booking_not_lost(monkeypatch):
    """בקשת הזמנה מיידית בשיחה ראשונה: ההיכרות נשלחת לבדה (היא שמבקשת שם+מייל),
    הבקשה לא אובדת — נרשמת להיסטוריה, וה-converse של תור התשובה (שרואה אותה)
    יורה את הריצה עם כל הפרטים."""
    _reset()
    ready = {
        "reply": "על זה",
        "ready": True,
        "restaurant": "טאיזו",
        "date": "18.7",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון בזק",
        "email": "alon@example.com",
    }
    sent, booked, _, conv = _wire(monkeypatch, ready)

    async def go():
        await pipeline.handle_inbound("new3", "תזמין לי את טאיזו מחר ב-20:00 לשניים")
        await _drain()

    asyncio.run(go())
    assert booked == [] and conv == []  # תור ההיכרות: בלי converse ובלי ריצה
    assert len(sent) == 1 and "מייל" in sent[0]  # ההיכרות היא שביקשה את הפרטים
    # הבקשה המקורית בהיסטוריה — ה-converse של התור הבא רואה מה ביקשו
    assert any(t["role"] == "user" and "טאיזו" in t["text"] for t in pipeline._turns["new3"])

    async def answer():
        await pipeline.handle_inbound("new3", "אלון בזק alon@example.com")
        await _drain()

    asyncio.run(answer())
    assert conv == ["אלון בזק alon@example.com"]  # תור התשובה כן עובר ב-converse
    assert booked and booked[0]["name"] == "אלון בזק"
    assert booked[0]["email"] == "alon@example.com"
    assert booked[0]["restaurant"] == "טאיזו"  # הבקשה המקורית נשמרה, לא נדרשה שוב
    assert "new3" not in pipeline._await_answer


def test_contact_answer_in_two_natural_steps(monkeypatch):
    """תשובה חלקית (רק שם) → ממשיכים לחכות רק למייל, והענף הקיים משלים ומריץ."""
    _reset()
    sent, booked, upserts, _ = _wire(monkeypatch, {"reply": "רגע", "ready": False})
    pipeline._last_seen["new4"] = time.time()  # לא מגע ראשון — בודקים רק את ההשלמה
    pipeline._booking["new4"] = {"state": "missing", "info": "contact"}
    pipeline._await_answer["new4"] = {
        "fields": {"restaurant": "טאיזו", "time": "20:00", "party_size": 2},
        "field": "contact",
        "options": [],
    }

    async def go():
        await pipeline.handle_inbound("new4", "אלון בזק")
        await _drain()

    asyncio.run(go())
    assert booked == []  # עוד אין מייל — לא רצים
    assert pipeline._await_answer["new4"]["field"] == "email"
    assert pipeline._await_answer["new4"]["fields"]["name"] == "אלון בזק"
    assert any("מייל" in m for m in sent)

    async def finish():
        await pipeline.handle_inbound("new4", "alon@example.com")
        await _drain()

    asyncio.run(finish())
    assert booked and booked[0]["name"] == "אלון בזק"
    assert booked[0]["email"] == "alon@example.com"


def test_profile_user_ready_runs_without_gate(monkeypatch):
    """משתמש עם פרופיל מלא: ready יוצא ישר לריצה — בלי שאלות זהות בדרך."""
    _reset()
    prof = {"name": "אלון בזק", "email": "alon@example.com", "prefs": {}}
    ready = {"reply": "על זה", "ready": True, "restaurant": "טאיזו", "time": "20:00"}
    sent, booked, _, _ = _wire(monkeypatch, ready, profile=prof)

    async def go():
        await pipeline.handle_inbound("known3", "תזמין טאיזו ל-20:00")
        await _drain()

    asyncio.run(go())
    assert booked  # רץ מיד
    assert "known3" not in pipeline._await_answer


def test_gate_asks_when_not_first_contact(monkeypatch):
    """לא שיחה ראשונה אבל חסר מייל: השער שואל לפני הריצה (במקום עצירת MISSING
    באמצע הטופס), וההקשר נשמר להשחלה."""
    _reset()
    ready = {"reply": "על זה", "ready": True, "restaurant": "טאיזו", "name": "אלון בזק"}
    sent, booked, _, _ = _wire(monkeypatch, ready)
    pipeline._last_seen["old1"] = time.time()

    async def go():
        await pipeline.handle_inbound("old1", "תזמין טאיזו")
        await _drain()

    asyncio.run(go())
    assert booked == []
    assert pipeline._await_answer["old1"]["field"] == "email"
    assert pipeline._await_answer["old1"]["fields"]["name"] == "אלון בזק"
    assert any("מייל" in m for m in sent)


def test_unsure_ready_skips_contact_gate(monkeypatch):
    """ready עם task_type=unsure לא נעצר על זהות — קודם מבררים מסעדה או סרט."""
    _reset()
    ready = {"reply": "רגע", "ready": True, "task_type": "unsure", "restaurant": "האודיסאה"}
    sent, booked, _, _ = _wire(monkeypatch, ready)
    pipeline._last_seen["new5"] = time.time()

    async def go():
        await pipeline.handle_inbound("new5", "תזמין את האודיסאה")
        await _drain()

    asyncio.run(go())
    assert booked  # run_booking קיבל את זה — ענף ה-unsure שלו הוא ששואל
    assert "new5" not in pipeline._await_answer


def test_contact_pair_parsing():
    """הפירוק הדטרמיניסטי: שם+מייל בהודעה אחת, כל אחד לבד, ורעש → כלום."""
    assert pipeline._contact_pair("אלון בזק alon@example.com") == {
        "email": "alon@example.com",
        "name": "אלון בזק",
    }
    assert pipeline._contact_pair("אלון בזק, alon@example.com") == {
        "email": "alon@example.com",
        "name": "אלון בזק",
    }
    assert pipeline._contact_pair("דנה לוי") == {"name": "דנה לוי"}
    assert pipeline._contact_pair("alon@example.com") == {"email": "alon@example.com"}
    assert pipeline._contact_pair("למה אתה צריך את זה בכלל?") == {}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
