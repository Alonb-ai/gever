"""בדיקות ל-confirm→commit (realbooking): run_commit סוגר באמת רק עם שם, run_booking
מאכלס את ה-gate, וניתוב handle_inbound מכבד את dry_run ('מאשר' לא סוגר כשהדגל דלוק)."""

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
    pipeline._reset_next.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()


def test_run_commit_books_for_real_and_logs(monkeypatch):
    """job עם שם → book_table(dry_run=False), state=done עם מספר אישור, log_booking, gate נופ."""
    _reset()
    sent, book_calls, log_calls = [], [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        return ActionResult(
            success=True,
            summary="ההזמנה בוצעה.",
            details={
                "confirmation": "ABC123",
                "restaurant": "הדסון",
                "date": "מחר",
                "time": "20:00",
            },
        )

    async def fake_log(phone, restaurant, date, time, party_size, status):
        log_calls.append({"status": status, "restaurant": restaurant, "party_size": party_size})

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    pipeline._pending_commit["p1"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("p1"))

    assert book_calls and book_calls[0]["dry_run"] is False
    assert book_calls[0]["phone"] == "p1" and book_calls[0]["name"] == "אלון"
    assert pipeline._booking["p1"]["state"] == "done"
    assert pipeline._booking["p1"]["info"] == "ABC123"
    assert log_calls and log_calls[0]["status"] == "confirmed"
    assert "p1" not in pipeline._pending_commit  # ה-gate נוקה
    assert "p1" in pipeline._reset_next  # דף חדש בהודעה הבאה


def test_run_commit_without_name_asks_no_book(monkeypatch):
    """job בלי שם → לא קוראים ל-book_table, שואלים על איזה שם, וה-gate נשאר לתשובה."""
    _reset()
    sent, book_calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        raise AssertionError("book_table לא אמור להיקרא בלי שם")

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table", fake_book)

    pipeline._pending_commit["p2"] = {"restaurant": "הדסון", "page_url": "http://x", "name": ""}
    asyncio.run(pipeline.run_commit("p2"))

    assert not book_calls
    assert sent and "שם" in sent[0]
    assert "p2" in pipeline._pending_commit  # נשאר ממתין לשם


def test_run_booking_populates_gate(monkeypatch):
    """שער dry-run מצליח → state=pending ו-_pending_commit מאוכלס בפרמטרי ההזמנה."""
    _reset()

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
    monkeypatch.setattr(pipeline, "resolve_ontopo_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table", fake_book)
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
    asyncio.run(pipeline.run_booking("p3", fields))

    assert pipeline._booking["p3"]["state"] == "pending"
    job = pipeline._pending_commit["p3"]
    assert job["restaurant"] == "הדסון" and job["page_url"] == "http://hudson"
    assert job["party_size"] == 4 and job["name"] == "אלון"


def _route(monkeypatch, *, dry_run, result, pending=False):
    """מריץ handle_inbound עם converse מזויף ו-_spawn שלוכד בלי להריץ. מחזיר רשימת השמות שנוטחו."""
    _reset()
    spawned = []

    async def fake_converse(phone, text):
        return result

    async def fake_send_text(phone, msg):
        pass

    async def fake_send_typing(mid):
        pass

    def fake_spawn(coro):
        spawned.append(coro.__qualname__)
        coro.close()  # לא מריצים את ההזמנה האמיתית בטסט

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    monkeypatch.setattr(pipeline, "_spawn", fake_spawn)
    monkeypatch.setattr(pipeline.settings, "dry_run", dry_run)
    if pending:
        pipeline._pending_commit["pX"] = {
            "restaurant": "הדסון",
            "page_url": "http://x",
            "name": "אלון",
        }
    asyncio.run(pipeline.handle_inbound("pX", "מאשר"))
    return spawned


def test_route_confirm_blocked_when_dry_run(monkeypatch):
    """dry_run=True: 'מאשר' (confirm) על הזמנה ממתינה לא מפעיל סגירה אמיתית."""
    spawned = _route(
        monkeypatch, dry_run=True, result={"reply": "מוכן", "confirm": True}, pending=True
    )
    assert spawned == []  # שום סגירה


def test_route_confirm_commits_when_live(monkeypatch):
    """dry_run=False: 'מאשר' על הזמנה ממתינה → run_commit."""
    spawned = _route(
        monkeypatch, dry_run=False, result={"reply": "סוגר", "confirm": True}, pending=True
    )
    assert spawned == ["run_commit"]


def test_route_ready_starts_booking_and_drops_gate(monkeypatch):
    """ready=True (הזמנה חדשה/שונה) → run_booking, וה-gate הישן ננטש."""
    spawned = _route(
        monkeypatch, dry_run=False, result={"reply": "יאללה", "ready": True}, pending=True
    )
    assert spawned == ["run_booking"]
    assert "pX" not in pipeline._pending_commit


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
