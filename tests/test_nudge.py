"""נדנוד עדין: גבר שאל/מחכה (שאלה/אישור/כרטיס) והלקוח נעלם ~5 דק' — תזכורת
אחת בדמות. הודעה נכנסת מבטלת; אין לולאה; אין נדנוד בלי מצב המתנה."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import character_leaks  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def _fresh(monkeypatch, delay: float = 0.01):
    """איפוס state + fake ל-_send_and_record; מחזיר את רשימת הנשלחות."""
    pipeline._nudge.clear()
    pipeline._booking.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._preresolve.clear()
    pipeline._pending_commit.clear()
    pipeline._await_answer.clear()
    pipeline._last_out.clear()
    sent = []

    async def fake_send(phone, text):
        sent.append(text)

    monkeypatch.setattr(pipeline, "_send_and_record", fake_send)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", delay)
    return sent


def test_nudge_fires_once_after_silence(monkeypatch):
    """עבר הזמן בלי מענה → תזכורת אחת בדיוק, גם אחרי המתנה ארוכה (לא לולאה)."""
    sent = _fresh(monkeypatch)

    async def main():
        pipeline._arm_nudge("p1", "confirm")
        await asyncio.sleep(0.1)  # פי 10 מה-delay — ירייה שנייה הייתה נתפסת כאן

    asyncio.run(main())
    assert len(sent) == 1
    assert "סגור" in sent[0] or "סוגר" in sent[0]  # עוגן הקשר האישור
    assert "p1" not in pipeline._nudge  # הטיימר נוקה אחרי הירייה


def test_inbound_message_cancels_nudge(monkeypatch):
    """הודעה נכנסת מהלקוח (handle_inbound) מבטלת את הטיימר — שום תזכורת."""
    sent = _fresh(monkeypatch, delay=0.05)

    async def fake_typing(message_id):
        pass

    async def fake_inner(phone, text, message_id=None):
        pass

    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_handle_inbound_inner", fake_inner)

    async def main():
        pipeline._arm_nudge("p1", "question")
        await pipeline.handle_inbound("p1", "מאשר")
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert sent == []
    assert "p1" not in pipeline._nudge


def test_rearm_replaces_timer_single_fire(monkeypatch):
    """arming כפול (שאלה ואז מצב חדש) → הטיימר הישן מוחלף, יורה רק אחד."""
    sent = _fresh(monkeypatch)

    async def main():
        pipeline._arm_nudge("p1", "question")
        pipeline._arm_nudge("p1", "confirm")
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert len(sent) == 1


def _run_booking(monkeypatch, result: ActionResult) -> bool:
    """מריץ run_booking עם תוצאת דפדפן מזויפת ומחזיר האם נדנוד נדרך (בתוך הלולאה,
    לפני ש-asyncio.run מנקה tasks תלויים)."""

    async def fake_book(**kwargs):
        return result

    async def fake_get_profile(phone):
        return None

    async def fake_persist(phone):
        pass

    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_persist)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "https://x", "platform": "ontopo"}

    async def main():
        await pipeline.run_booking("p1", {"restaurant": "הדסון", "date": "מחר", "time": "20:00"})
        return "p1" in pipeline._nudge

    return asyncio.run(main())


def test_nudge_armed_on_missing_question(monkeypatch):
    """שאלת MISSING נשלחה → טיימר נדנוד נדרך."""
    _fresh(monkeypatch, delay=60)
    armed = _run_booking(
        monkeypatch,
        ActionResult(success=False, summary="MISSING:email", details={"missing": "email"}),
    )
    assert armed


def test_nudge_armed_on_pending_confirm(monkeypatch):
    """ "לסגור?" נשלח (מצב pending) → טיימר נדנוד נדרך."""
    _fresh(monkeypatch, delay=60)
    armed = _run_booking(monkeypatch, ActionResult(success=True, summary="ok", details={}))
    assert armed
    assert pipeline._booking["p1"]["state"] == "pending"


def test_nudge_armed_on_card_wall(monkeypatch):
    """לינק קיר-כרטיס נשלח → טיימר נדנוד נדרך."""
    _fresh(monkeypatch, delay=60)
    armed = _run_booking(
        monkeypatch,
        ActionResult(success=True, summary="card", details={"card_required": True}),
    )
    assert armed
    assert pipeline._booking["p1"]["state"] == "card"


def test_no_nudge_without_wait_state(monkeypatch):
    """כישלון (אין שאלה ללקוח, אין מה לאשר) → שום טיימר לא נדרך."""
    _fresh(monkeypatch, delay=60)
    armed = _run_booking(
        monkeypatch,
        ActionResult(success=False, summary="fail", details={"failed": "no_availability"}),
    )
    assert not armed


def test_nudge_repertoire_passes_character_rules():
    """כל הניסוחים בדמות: עוברים character_leaks, שונים זה מזה, ונושאים את עוגן
    ההקשר שלהם (תשובה / סגירה / לינק) בכל וריאנט."""
    anchors = {
        "question": lambda m: "תשובה" in m,
        "confirm": lambda m: "סגור" in m or "סוגר" in m,
        "card": lambda m: "לינק" in m,
    }
    assert set(pipeline.NUDGE_MSGS) == set(anchors)
    for kind, msgs in pipeline.NUDGE_MSGS.items():
        assert len(msgs) >= 2
        assert len(set(msgs)) == len(msgs)
        assert all(not character_leaks(m) for m in msgs)
        assert all(anchors[kind](m) for m in msgs)
