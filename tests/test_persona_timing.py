"""ממצא live-test 7.7: הבטחת עדכון-מיידי שקרית ("מעדכן אותך בשנייה") כשריצה לא
התחילה או כשהיא לוקחת דקות. נועלים את העוגנים: הפרסונה וה-_EXTRACT קושרים הבטחת
זמן לאמת, וההודעות המכניות בתחילת ריצה מתאמות ציפיות של דקות — בלי "שנייה"."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import SYSTEM_PROMPT  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

_SECOND_WORDS = ("שנייה", "שניה")


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._reset_next.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()


def test_system_prompt_couples_time_promises_to_truth():
    """חוק הברזל על סטטוס מכסה גם זמן: יצאת = כמה דקות, לא יצאת = בלי הבטחת עדכון."""
    assert "כמה דקות" in SYSTEM_PROMPT
    assert "אל תגיד שאתה על זה ואל תבטיח עדכון" in SYSTEM_PROMPT


def test_extract_couples_time_promises_to_flag():
    """חוזה המנגנון: בלי דגל אין הבטחת זמן, ועם דגל — הביצוע לוקח כמה דקות."""
    assert "לוקח כמה דקות" in pipeline._EXTRACT
    assert "אין 'שנייה'" in pipeline._EXTRACT


def _capture_first_vary(monkeypatch):
    """מחליף את _vary בלכידה: שומר את כל הווריאנטים של כל קריאה, מחזיר את הראשון."""
    calls = []

    def fake_vary(*variants):
        calls.append(variants)
        return variants[0]

    monkeypatch.setattr(pipeline, "_vary", fake_vary)
    return calls


def test_run_booking_start_notice_sets_minutes_not_seconds(monkeypatch):
    """הודעת "אני על זה" בתחילת ריצה: כל וריאנט מתאם דקות ואף אחד לא מבטיח שנייה."""
    _reset()
    vary_calls = _capture_first_vary(monkeypatch)

    async def fake_send_text(phone, msg):
        pass

    async def fake_resolve(name):
        return {"status": "one", "url": "http://hudson", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="הגעתי למסך האישור (DRY_RUN).",
            details={"time": "20:00", "restaurant": "הדסון", "date": "מחר"},
        )

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {
        "task_type": "restaurant",
        "restaurant": "הדסון",
        "date": "מחר",
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("pt1", fields))

    assert vary_calls, "הודעת ההתנעה לא נשלחה"
    for variant in vary_calls[0]:  # הקריאה הראשונה ב-run_booking = הודעת ההתנעה
        assert "דקות" in variant, f"וריאנט בלי תיאום ציפיות: {variant}"
        assert not any(w in variant for w in _SECOND_WORDS), f"הבטחת שנייה: {variant}"


def test_run_commit_start_notice_has_no_second_promise(monkeypatch):
    """הודעת ההתנעה של הסגירה הסופית: אף וריאנט לא מבטיח 'שנייה'."""
    _reset()
    vary_calls = _capture_first_vary(monkeypatch)
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="ההזמנה בוצעה.",
            details={"confirmation": "OK1", "restaurant": "הדסון", "date": "מחר", "time": "20:00"},
        )

    async def fake_log(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    pipeline._pending_commit["pt2"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("pt2"))

    assert vary_calls, "הודעת ההתנעה לא נשלחה"
    for variant in vary_calls[0]:
        assert not any(w in variant for w in _SECOND_WORDS), f"הבטחת שנייה: {variant}"
