"""שחרור מוקדם של סשן קיר-כרטיס נטוש: הלקוח קיבל לינק, גם הנדנוד לא הועיל —
אחרי CARD_RELEASE_DELAY_S נוספות משחררים את הסשן (לא שורפים 30 דק' אידל),
מנקים את מצב ה-card ומודיעים בכנות. הודעה נכנסת מבטלת; אין שחרור כפול;
אין שחרור כשאין סשן; חזרת הלקוח אחרי שחרור = ריצה טרייה בלי קריסה."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import character_leaks  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def _fresh(monkeypatch, delay: float = 0.01, release_delay: float = 0.01):
    """איפוס state + fakes; מחזיר (sent, released) — ההודעות והסשנים ששוחררו."""
    pipeline._nudge.clear()
    pipeline._booking.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._preresolve.clear()
    pipeline._pending_commit.clear()
    pipeline._await_answer.clear()
    pipeline._last_out.clear()
    sent, released = [], []

    async def fake_send(phone, text):
        sent.append(text)

    async def fake_release(session_id):
        released.append(session_id)

    async def fake_save_flow(phone):
        pass

    monkeypatch.setattr(pipeline, "_send_and_record", fake_send)
    monkeypatch.setattr(pipeline, "release_session", fake_release)
    monkeypatch.setattr(pipeline, "_save_flow", fake_save_flow)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", delay)
    monkeypatch.setattr(pipeline, "CARD_RELEASE_DELAY_S", release_delay)
    return sent, released


def test_release_after_unanswered_card_nudge(monkeypatch):
    """נדנוד card נורה ואין מענה → שחרור הסשן, ניקוי מצב card, והודעה כנה אחת."""
    sent, released = _fresh(monkeypatch)

    async def main():
        pipeline._booking["p1"] = {"state": "card", "info": "https://link"}
        pipeline._arm_nudge("p1", "card", session_id="sess-1")
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert released == ["sess-1"]
    assert "p1" not in pipeline._booking  # מצב card נוקה — חזרה = ריצה טרייה
    assert len(sent) == 2  # נדנוד + הודעת שחרור, ולא יותר
    assert "שחרר" in sent[1] and "מחדש" in sent[1]  # עוגני הכנות וההבטחה לפתוח שוב


def test_inbound_message_cancels_release(monkeypatch):
    """הלקוח ענה אחרי הנדנוד אבל לפני השחרור → הכל מבוטל, הסשן נשאר חי."""
    sent, released = _fresh(monkeypatch, release_delay=0.05)

    async def fake_typing(message_id):
        pass

    async def fake_inner(phone, text, message_id=None):
        pass

    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_handle_inbound_inner", fake_inner)

    async def main():
        pipeline._booking["p1"] = {"state": "card", "info": "https://link"}
        pipeline._arm_nudge("p1", "card", session_id="sess-1")
        await asyncio.sleep(0.03)  # הנדנוד כבר נורה, השחרור עוד לא
        await pipeline.handle_inbound("p1", "פותח עכשיו")
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert released == []
    assert pipeline._booking["p1"]["state"] == "card"  # המצב לא נוקה
    assert len(sent) == 1  # רק הנדנוד — בלי הודעת שחרור


def test_no_double_release(monkeypatch):
    """ה-task יורה פעם אחת — גם המתנה ארוכה פי כמה לא משחררת שוב."""
    sent, released = _fresh(monkeypatch)

    async def main():
        pipeline._booking["p1"] = {"state": "card", "info": "https://link"}
        pipeline._arm_nudge("p1", "card", session_id="sess-1")
        await asyncio.sleep(0.2)  # פי 10 משני ההשהיות יחד

    asyncio.run(main())
    assert released == ["sess-1"]
    assert "p1" not in pipeline._nudge  # הטיימר נוקה בסוף


def test_no_release_without_session(monkeypatch):
    """קיר-כרטיס בלי סשן חי (לינק דף רגיל) → נדנוד בלבד, שום שחרור ושום ניקוי."""
    sent, released = _fresh(monkeypatch)

    async def main():
        pipeline._booking["p1"] = {"state": "card", "info": "https://page"}
        pipeline._arm_nudge("p1", "card")
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert released == []
    assert pipeline._booking["p1"]["state"] == "card"
    assert len(sent) == 1  # רק הנדנוד


def test_fresh_run_after_release_no_crash(monkeypatch):
    """הלקוח חוזר אחרי שהסשן שוחרר → run_booking רץ טרי ומגיע ל-pending בלי קריסה."""
    sent, released = _fresh(monkeypatch)

    async def fake_book(**kwargs):
        return ActionResult(success=True, summary="ok", details={})

    async def fake_get_profile(phone):
        return None

    async def fake_persist(phone):
        pass

    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_persist)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "https://x", "platform": "ontopo"}

    async def main():
        pipeline._booking["p1"] = {"state": "card", "info": "https://link"}
        pipeline._arm_nudge("p1", "card", session_id="sess-1")
        await asyncio.sleep(0.1)  # השחרור קרה, מצב ה-card נוקה
        await pipeline.run_booking("p1", {"restaurant": "הדסון", "date": "מחר", "time": "20:00"})

    asyncio.run(main())
    assert released == ["sess-1"]
    assert pipeline._booking["p1"]["state"] == "pending"  # ריצה טרייה הגיעה עד הסוף


def test_release_repertoire_passes_character_rules():
    """כל ניסוחי השחרור בדמות: character_leaks נקי, שונים זה מזה, ונושאים את
    העוגנים — שורש "שחרר" (כנות) ו"מחדש" (ההבטחה לפתוח שוב)."""
    msgs = pipeline.CARD_RELEASE_MSGS
    assert len(msgs) >= 2
    assert len(set(msgs)) == len(msgs)
    assert all(not character_leaks(m) for m in msgs)
    assert all("שחרר" in m and "מחדש" in m for m in msgs)
