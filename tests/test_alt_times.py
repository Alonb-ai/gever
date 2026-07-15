"""השעה המבוקשת תפוסה → הצעת חלופות אמיתיות מהדף ("לסגור ב-19:30?") במקום
"לא מצאתי" — MISSING:time + OPTIONS, באותו מנגנון של אזור הישיבה (בקשת אלון 15.7)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import bu_runner  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def test_task_offers_times_instead_of_failing():
    """ה-task מנחה: שעות פנויות אחרות באותו יום → MISSING:time + OPTIONS, לא כישלון."""
    task = bu_runner._build_task(
        {"url": "http://x", "date": "מחר", "time": "20:00", "party_size": 2, "dry_run": True}
    )
    assert "MISSING:time" in task
    assert "FAILED:no_availability" in task  # נשאר רק למקרה שאין אף שעה באותו יום


def _run_missing_time(monkeypatch, options):
    pipeline._booking.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._preresolve.clear()
    pipeline._last_out.clear()
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(("text", msg))

    async def fake_send_list(phone, body, labels):
        sent.append(("list", body, tuple(labels)))

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING:time",
            details={"missing": "time", "options": options, "session_id": "s-t", "stage": "x"},
        )

    async def fake_get_profile(phone):
        return None

    async def fake_persist(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_persist)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    asyncio.run(pipeline.run_booking("p1", {"restaurant": "הדסון", "date": "מחר", "time": "20:00"}))
    return sent


def test_two_free_times_become_tap_list(monkeypatch):
    """שתי חלופות → רשימת טאפ; הכותרת נושאת את השעה שנפלה ואת הצעת הסגירה."""
    sent = _run_missing_time(monkeypatch, ["19:30", "21:15"])
    kind, body, labels = sent[-1]
    assert kind == "list" and labels == ("19:30", "21:15")
    # הצעת הסגירה מנוסחת ב-_vary ("לסגור"/"ואני סוגר") — בודקים את השורש, לא נוסח אחד
    assert "20:00" in body and ("סגור" in body or "סוגר" in body)
    # הסשן חי וממתין — הבחירה תמשיך מאותו מסך
    assert pipeline._resume["p1"]["session_id"] == "s-t"
    assert pipeline._booking["p1"]["state"] == "missing"


def test_single_free_time_offers_to_close(monkeypatch):
    """חלופה אחת → שאלת סגירה ישירה: 'ה-20:00 תפוס, אבל 19:30 פנוי — לסגור?'."""
    sent = _run_missing_time(monkeypatch, ["19:30"])
    kind, msg = sent[-1]
    assert kind == "text"
    assert "20:00" in msg and "19:30" in msg and "סגור" in msg
