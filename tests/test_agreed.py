"""גילוי הסכמות: צ'קבוקסים שה-agent סימן בשם הלקוח מדווחים בתמצית בהודעת הסיום
("אישרתי בשמך: ...") — שום תקנון לא נחתם בשקט (בקשת אלון, טסט 15.7)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation.bu_runner import _parse_result  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def test_parse_agreed_line():
    final = (
        "מילאתי הכל.\n"
        "AGREED: תקנון ומדיניות ביטול | האזור בחוץ הוא אזור עישון\n"
        "SUMMARY_REACHED 20:00"
    )
    r = _parse_result(final, commit=False)
    assert r["agreed"] == ["תקנון ומדיניות ביטול", "האזור בחוץ הוא אזור עישון"]
    assert r["success"] is True


def test_parse_no_agreed_is_empty():
    r = _parse_result("הכל טוב\nSUMMARY_REACHED 20:00", commit=False)
    assert r["agreed"] == []


def test_success_message_discloses_agreements(monkeypatch):
    """הודעת ה"יש! הגעתי למסך האישור" נושאת את תמצית ההסכמות שסומנו."""
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._resolved.clear()
    pipeline._preresolve.clear()
    pipeline._await_answer.clear()
    pipeline._last_out.clear()
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED 20:00",
            details={"summary_reached": True, "time": "20:00", "agreed": ["תקנון ומדיניות ביטול"]},
        )

    async def fake_get_profile(phone):
        return None

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    asyncio.run(
        pipeline.run_booking("p1", {"restaurant": "הדסון", "time": "20:00", "party_size": 2})
    )
    final_msg = sent[-1]
    assert "בשמך" in final_msg and "תקנון ומדיניות ביטול" in final_msg
