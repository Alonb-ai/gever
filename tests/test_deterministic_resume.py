"""resume דטרמיניסטי: תשובה שתואמת אופציה ששלחנו (MISSING+OPTIONS) נורית ישר,
בלי לסמוך על ה-extract. תשובה חופשית ממשיכה בנתיב הרגיל (converse)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()
    pipeline._preresolve.clear()
    pipeline._await_answer.clear()
    pipeline._last_out.clear()
    pipeline._turns.clear()


def test_missing_stop_stores_answer_context(monkeypatch):
    """עצירת MISSING עם אופציות שומרת את ההקשר לירייה דטרמיניסטית."""
    _reset()

    async def fake_send_list(phone, body, labels):
        pass

    async def fake_send_text(phone, msg):
        pass

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING:seating_area",
            details={"missing": "seating_area", "options": ["בפנים", "מרפסת מעשנים"]},
        )

    async def fake_get_profile(phone):
        return None

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    fields = {"restaurant": "הדסון", "date": "מחר", "time": "20:00", "party_size": 2}
    asyncio.run(pipeline.run_booking("p1", fields))

    pend = pipeline._await_answer["p1"]
    assert pend["field"] == "seating_area"
    assert pend["options"] == ["בפנים", "מרפסת מעשנים"]
    assert pend["fields"]["time"] == "20:00"


def _wire_inbound(monkeypatch):
    booked = []

    async def fake_converse(phone, text):
        raise AssertionError("converse לא אמור להיקרא בהתאמה דטרמיניסטית")

    async def fake_run_booking(phone, fields):
        booked.append(fields)

    async def fake_send_text(phone, msg):
        pass

    async def fake_typing(message_id):
        pass

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "run_booking", fake_run_booking)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    return booked


async def _drain():
    for _ in range(3):
        await asyncio.sleep(0)
        if pipeline._pending:
            await asyncio.gather(*list(pipeline._pending), return_exceptions=True)


def test_matching_time_answer_fires_directly(monkeypatch):
    """טאפ על שעה חלופית → ירייה ישירה: השעה נכנסת לשדה, converse לא באמצע."""
    _reset()
    booked = _wire_inbound(monkeypatch)
    pipeline._booking["p1"] = {"state": "missing", "info": "שעה"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הדסון", "date": "מחר", "time": "20:00", "party_size": 2},
        "field": "time",
        "options": ["19:30", "21:15"],
    }

    async def go():
        await pipeline.handle_inbound("p1", "19:30")
        await _drain()

    asyncio.run(go())
    assert booked[0]["time"] == "19:30"
    assert "p1" not in pipeline._await_answer
    # ההיסטוריה משקפת את החילוף: תור המשתמש ואחריו ה-ack שנרשם דרך _send_and_record
    user_turn = pipeline._turns["p1"][-2]
    assert user_turn["role"] == "user" and user_turn["text"] == "19:30" and user_turn["ts"] > 0
    assert pipeline._turns["p1"][-1]["role"] == "model"


def test_matching_choice_answer_goes_to_notes(monkeypatch):
    """בחירת אזור ישיבה → נכנסת ל-notes עם שם השדה, שהרץ ידע מה נבחר."""
    _reset()
    booked = _wire_inbound(monkeypatch)
    pipeline._booking["p1"] = {"state": "missing", "info": "ישיבה"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הדסון", "time": "20:00", "notes": "יום הולדת"},
        "field": "seating_area",
        "options": ["בפנים", "מרפסת מעשנים"],
    }

    async def go():
        await pipeline.handle_inbound("p1", "מרפסת מעשנים")
        await _drain()

    asyncio.run(go())
    assert "seating_area: מרפסת מעשנים" in booked[0]["notes"]
    assert "יום הולדת" in booked[0]["notes"]


def test_free_text_answer_falls_through_to_converse(monkeypatch):
    """תשובה שלא תואמת אף אופציה ("אולי בעצם מחר?") ממשיכה בנתיב הרגיל."""
    _reset()
    called = []

    async def fake_converse(phone, text):
        called.append(text)
        return {"reply": "בסדר", "ready": False}

    async def fake_send_text(phone, msg):
        pass

    async def fake_typing(message_id):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    pipeline._booking["p1"] = {"state": "missing", "info": "שעה"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הדסון", "time": "20:00"},
        "field": "time",
        "options": ["19:30"],
    }
    asyncio.run(pipeline.handle_inbound("p1", "אולי בעצם נדחה למחר"))
    assert called  # הגיע ל-converse
    assert "p1" in pipeline._await_answer  # ההקשר נשאר — אולי עוד יבחר מהרשימה
