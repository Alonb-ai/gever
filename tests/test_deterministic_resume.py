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


def test_missing_name_answer_relaunches_before_db_write(monkeypatch):
    """ממצא בטא #2 (המרוץ מהערב): תשובת MISSING:name מושחלת ישירות ל-job של
    ה-relaunch — הריצה יוצאת עם השם גם כשכתיבת הפרופיל ל-DB עוד לא הסתיימה,
    והפרופיל נכתב במקביל כ-persistence משני בלבד."""
    _reset()
    order = []
    booked = []
    db_done = asyncio.Event()

    async def fake_converse(phone, text):
        raise AssertionError("converse לא אמור להיקרא בהשחלה דטרמיניסטית")

    async def slow_upsert(phone, name=None, email=None, prefs=None):
        order.append("db_start")
        await db_done.wait()  # משחזר את המרוץ: הכתיבה תקועה — הריצה לא מחכה לה
        order.append(("db_end", name))

    async def fake_run_booking(phone, fields):
        order.append(("relaunch", fields.get("name")))
        booked.append(fields)
        db_done.set()  # הכתיבה "מסתיימת" רק אחרי שה-relaunch כבר יצא

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
    monkeypatch.setattr(memory, "upsert_profile", slow_upsert)
    pipeline._booking["p1"] = {"state": "missing", "info": "name"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "גאיג'ין", "date": "מחר", "time": "20:00", "party_size": 2},
        "field": "name",
        "options": [],
    }

    async def go():
        # wait_for: רגרסיה שממתינה לכתיבת ה-DB לפני ה-relaunch תיכשל מהר, לא תיתקע
        await asyncio.wait_for(pipeline.handle_inbound("p1", "דנה לוי"), timeout=5)
        await _drain()

    asyncio.run(go())
    # השם הגיע לריצה ישירות מה-job, לפני שכתיבת ה-DB הסתיימה
    assert booked[0]["name"] == "דנה לוי"
    assert order.index(("relaunch", "דנה לוי")) < order.index(("db_end", "דנה לוי"))
    assert "p1" not in pipeline._await_answer
    assert pipeline._booking["p1"]["state"] == "working"


def test_missing_email_answer_threads_directly(monkeypatch):
    """אותו מרוץ קיים גם ל-MISSING:email — המייל נשלף מהתשובה ונכנס ישירות ל-job."""
    _reset()
    booked = _wire_inbound(monkeypatch)
    pipeline._booking["p1"] = {"state": "missing", "info": "email"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "גאיג'ין", "time": "20:00", "party_size": 2},
        "field": "email",
        "options": [],
    }

    async def go():
        await pipeline.handle_inbound("p1", "המייל שלי dana@example.com")
        await _drain()

    asyncio.run(go())
    assert booked[0]["email"] == "dana@example.com"
    assert "p1" not in pipeline._await_answer


def test_missing_name_question_falls_to_converse(monkeypatch):
    """תשובה שאינה שם (שאלה / טקסט עם ספרות) ממשיכה ל-converse וההקשר נשאר."""
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
    pipeline._last_seen["p1"] = 10**12  # לא מגע ראשון — האונבורדינג לא חלק מהטסט
    pipeline._booking["p1"] = {"state": "missing", "info": "name"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "גאיג'ין", "time": "20:00"},
        "field": "name",
        "options": [],
    }
    asyncio.run(pipeline.handle_inbound("p1", "רגע, למה אתה צריך את השם שלי?"))
    asyncio.run(pipeline.handle_inbound("p1", "0501234567"))
    assert len(called) == 2  # שתי התשובות הגיעו ל-converse
    assert "p1" in pipeline._await_answer  # ההקשר נשאר — התשובה האמיתית עוד תגיע


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
    pipeline._last_seen["p1"] = 10**12  # לא מגע ראשון — האונבורדינג לא חלק מהטסט
    pipeline._booking["p1"] = {"state": "missing", "info": "שעה"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הדסון", "time": "20:00"},
        "field": "time",
        "options": ["19:30"],
    }
    asyncio.run(pipeline.handle_inbound("p1", "אולי בעצם נדחה למחר"))
    assert called  # הגיע ל-converse
    assert "p1" in pipeline._await_answer  # ההקשר נשאר — אולי עוד יבחר מהרשימה
