"""האצות הלופ: סגירה-באותו-סשן (keep_on_summary + resume ב-commit) ו-pre-resolve
ברקע בזמן שהלקוח משלים פרטים. נולד מריצת ה-10-דקות של אלון (14.7)."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import browser_book  # noqa: E402
from app.config import settings  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._last_out.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()
    pipeline._preresolve.clear()


def _bb_run(monkeypatch, tmp_path, result: dict, keep_on_summary: bool):
    """מריץ book_table_bu על browserbase מדומה; מחזיר (details, released)."""
    settings.bu_record_dir = str(tmp_path)
    settings.bu_browser = "browserbase"
    released = []

    async def fake_run(job):
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump(result, f)

    async def fake_create():
        return "s-sum", "wss://cdp"

    async def fake_release(sid):
        released.append(sid)

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(browser_book, "_bb_create_session", fake_create)
    monkeypatch.setattr(browser_book, "release_session", fake_release)
    try:
        res = asyncio.run(
            browser_book.book_table_bu(
                restaurant="הדסון",
                page_url="http://x",
                date="26",
                time="20:00",
                party_size=2,
                keep_on_summary=keep_on_summary,
            )
        )
    finally:
        settings.bu_browser = "local"
    return res.details, released


def test_keep_on_summary_keeps_session(monkeypatch, tmp_path):
    """summary_reached עם keep_on_summary → הסשן חי ו-session_id חוזר (סגירה בקליק)."""
    result = {"success": True, "summary_reached": True, "message": "SUMMARY_REACHED 20:00"}
    details, released = _bb_run(monkeypatch, tmp_path, result, keep_on_summary=True)
    assert details["session_id"] == "s-sum"
    assert released == []


def test_summary_releases_session_by_default(monkeypatch, tmp_path):
    """בלי keep_on_summary (DRY_RUN של היום) — הסשן משוחרר כמו תמיד, אין דליפת דקות."""
    result = {"success": True, "summary_reached": True, "message": "SUMMARY_REACHED 20:00"}
    details, released = _bb_run(monkeypatch, tmp_path, result, keep_on_summary=False)
    assert details["session_id"] is None
    assert released == ["s-sum"]


def test_commit_resumes_live_session(monkeypatch):
    """job עם session_id → הסגירה נורית כ-resume על אותו סשן, לא ניווט מאפס."""
    _reset()
    book_calls = []

    async def fake_send_text(phone, msg):
        pass

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        return ActionResult(success=True, summary="BOOKED", details={"confirmation": "C1"})

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    pipeline._pending_commit["p1"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
        "session_id": "s-sum",
    }
    asyncio.run(pipeline.run_commit("p1"))
    assert book_calls[0]["resume"]["session_id"] == "s-sum"
    assert "הדסון" in book_calls[0]["resume"]["recap"]


async def _inbound_and_drain(phone: str, text: str):
    await pipeline.handle_inbound(phone, text)
    for _ in range(3):  # נותנים ל-tasks שנורו ברקע להסתיים
        await asyncio.sleep(0)
        if pipeline._pending:
            await asyncio.gather(*list(pipeline._pending), return_exceptions=True)


def _wire_inbound(monkeypatch, reply: dict):
    async def fake_converse(phone, text):
        return reply

    async def fake_send_text(phone, msg):
        pass

    async def fake_typing(message_id):
        pass

    async def fake_pace(seconds):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_pace", fake_pace)


def test_ready_releases_stale_commit_session(monkeypatch):
    """בקשה חדשה (ready) נוטשת gate ישן — הסשן החי שלו משוחרר, לא מדליף."""
    _reset()
    released = []

    async def fake_release(sid):
        released.append(sid)

    async def fake_run_booking(phone, fields):
        pass

    _wire_inbound(monkeypatch, {"reply": "סוגר", "ready": True, "restaurant": "רוסטיקו"})
    monkeypatch.setattr(pipeline, "release_session", fake_release)
    monkeypatch.setattr(pipeline, "run_booking", fake_run_booking)
    pipeline._last_seen["p1"] = 10**12  # לא מגע ראשון — האונבורדינג לא חלק מהטסט
    pipeline._pending_commit["p1"] = {"restaurant": "הדסון", "session_id": "s-old", "name": "א"}
    asyncio.run(_inbound_and_drain("p1", "תזמין רוסטיקו מחר ב-20:00 לשניים"))
    assert released == ["s-old"]
    assert "p1" not in pipeline._pending_commit


def test_preresolve_fires_on_partial_and_run_booking_consumes(monkeypatch):
    """ready=false עם שם מסעדה → resolve נורה ברקע; run_booking קוטף בלי חיפוש שני."""
    _reset()
    resolve_calls = []
    book_calls = []

    async def fake_resolve(name):
        resolve_calls.append(name)
        return {"status": "one", "url": "http://ontopo/x", "platform": "ontopo", "fallback": None}

    _wire_inbound(monkeypatch, {"reply": "לאיזו שעה?", "ready": False, "restaurant": "הדסון"})
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    pipeline._last_seen["p1"] = 10**12  # לא מגע ראשון — האונבורדינג לא חלק מהטסט
    asyncio.run(_inbound_and_drain("p1", "תסגור לי שולחן בהדסון"))
    assert resolve_calls == ["הדסון"]  # נורה כבר מהשיחה
    assert pipeline._preresolve["p1"]["name"] == "הדסון"

    async def fake_send_text(phone, msg):
        pass

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        return ActionResult(
            success=False, summary="FAILED:no_availability", details={"failed": "no_availability"}
        )

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline.memory, "get_profile", fake_get_profile)
    asyncio.run(pipeline.run_booking("p1", {"restaurant": "הדסון", "date": "מחר", "time": "20:00"}))
    assert resolve_calls == ["הדסון"]  # לא היה resolve שני — נקטפה התוצאה המוכנה
    assert book_calls[0]["page_url"] == "http://ontopo/x"
    assert "p1" not in pipeline._preresolve


def test_preresolve_mismatch_cancelled_and_fresh_resolve(monkeypatch):
    """הלקוח החליף מסעדה בין השיחה לריצה — ה-pre-resolve הישן מבוטל ורץ חיפוש טרי."""
    _reset()
    resolve_calls = []

    async def fake_resolve(name):
        resolve_calls.append(name)
        return {"status": "one", "url": f"http://x/{name}", "platform": "ontopo", "fallback": None}

    async def fake_send_text(phone, msg):
        pass

    async def fake_book(**kwargs):
        return ActionResult(
            success=False, summary="FAILED:no_availability", details={"failed": "no_availability"}
        )

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline.memory, "get_profile", fake_get_profile)

    async def _drive():
        task = asyncio.create_task(fake_resolve("הדסון"))
        pipeline._preresolve["p1"] = {"name": "הדסון", "task": task}
        await asyncio.sleep(0)
        await pipeline.run_booking("p1", {"restaurant": "רוסטיקו", "date": "מחר", "time": "20:00"})

    asyncio.run(_drive())
    assert resolve_calls[-1] == "רוסטיקו"  # חיפוש טרי למסעדה החדשה
    assert "p1" not in pipeline._preresolve
