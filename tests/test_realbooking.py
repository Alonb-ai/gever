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
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
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
    assert any("סגור ✅" in m for m in sent)  # הלקוח קיבל אישור סגירה
    assert any("ABC123" in m for m in sent)  # כולל מספר האישור


def test_run_commit_card_wall_hands_link(monkeypatch):
    """קיר כרטיס בסגירה: success=False + card_required → לא log_booking, מוסרים לינק (זרוע C)."""
    _reset()
    sent, log_calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        return ActionResult(success=False, summary="CARD_REQUIRED", details={"card_required": True})

    async def fake_log(*a, **k):
        log_calls.append(1)

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    pipeline._pending_commit["pc"] = {
        "restaurant": "הדסון",
        "page_url": "http://ontopo/hudson",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("pc"))

    assert not log_calls  # לא נרשמה הזמנה
    assert pipeline._booking["pc"]["state"] == "card"
    assert sent and "כרטיס אשראי" in sent[-1]
    assert "http://ontopo/hudson" in sent[-1]  # זרוע C: הלינק נמסר
    assert not any("סגור ✅" in m for m in sent)  # לא מזייפים סגירה


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
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)

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


def test_handle_inbound_suppresses_character_leak(monkeypatch):
    """שכבת המגן האחרונה: reply שמסגיר AI לא יוצא לוואטסאפ — הודעת גישור בדמות במקומו."""
    _reset()
    sent = []

    async def fake_converse(phone, text):
        return {"reply": "כמודל שפה אני לא יכול להזמין שולחן", "ready": False}

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_typing(mid):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    asyncio.run(pipeline.handle_inbound("pL", "תזמין לי שולחן"))

    assert sent and "כמודל" not in sent[-1]  # הדליפה לא הגיעה ללקוח
    assert "רגע" in sent[-1]  # הודעת גישור בדמות


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


def test_route_double_fire_guard_blocks_second_booking(monkeypatch):
    """באג 4: הזמנה כבר רצה (state=working) — ready=true שני (למשל '?' של הלקוח) לא יורה שוב."""
    _reset()
    spawned = []

    async def fake_converse(phone, text):
        return {"reply": "על זה", "ready": True}

    async def fake_send_text(phone, msg):
        pass

    async def fake_send_typing(mid):
        pass

    def fake_spawn(coro):
        spawned.append(coro.__qualname__)
        coro.close()

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    monkeypatch.setattr(pipeline, "_spawn", fake_spawn)
    monkeypatch.setattr(pipeline.settings, "dry_run", False)

    pipeline._booking["pY"] = {"state": "working", "info": ""}
    asyncio.run(pipeline.handle_inbound("pY", "?"))
    assert spawned == []  # הזמנה כבר בתהליך — לא יורים שנייה


def test_run_booking_missing_field_asks_no_book(monkeypatch):
    """באג 3: recon מחזיר MISSING:email → גבר מבקש מהלקוח, state=missing, אין סגירה/log."""
    _reset()
    sent, log_calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {"status": "one", "url": "http://hudson", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="חסר מייל",
            details={"missing": "email"},
        )

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    async def fake_log(*a, **k):
        log_calls.append(1)

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    fields = {
        "task_type": "restaurant",
        "restaurant": "הדסון",
        "date": "מחר",
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("p4", fields))

    assert pipeline._booking["p4"]["state"] == "missing"
    assert pipeline._booking["p4"]["info"] == "email"
    assert "p4" not in pipeline._pending_commit  # לא נפתח gate — אין הזמנה ממתינה
    assert not log_calls  # לא נרשמה הזמנה
    assert sent and "מייל" in sent[-1]  # גבר ביקש את הפרט החסר


def test_run_booking_failure_does_not_leak_raw_agent_text(monkeypatch):
    """כישלון גנרי: res.summary הוא טקסט גולמי באנגלית של browser-use — אסור שיגיע ללקוח
    (קו-ברזל: לא חושפים אוטומציה) *ולא* ל-info (מוזרק ל-truth_note — אתר זדוני היה יכול
    להשחיל טקסט לבלוק האמת של המודל). נשמר רק ב-debug."""
    _reset()
    sent = []
    raw = "I was unable to complete the reservation. No active booking widget. CAPTCHA blocked."

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {"status": "one", "url": "http://x", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(success=False, summary=raw, details={})

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {"task_type": "restaurant", "restaurant": "גרקו", "time": "20:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("p5", fields))

    assert pipeline._booking["p5"]["state"] == "failed"
    assert pipeline._booking["p5"]["info"] == ""  # הגולמי לא נכנס ל-truth_note
    assert pipeline._booking["p5"]["debug"] == raw  # נשמר לדיבוג בלבד
    assert raw not in pipeline._truth_note("p5")  # בלוק האמת נקי מטקסט צד-שלישי
    assert sent  # נשלחה הודעה
    assert raw not in sent[-1]  # אבל לא הטקסט הגולמי
    assert "I was unable" not in sent[-1] and "CAPTCHA" not in sent[-1]
    assert "גרקו" in sent[-1]  # הודעת דמות בעברית שנוקבת בשם המסעדה


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
