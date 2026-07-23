"""התאוששות יתומים: redeploy באמצע הזמנה הרג אותה בדממה (נצפה חי 3 פעמים).
עכשיו: סימון inflight שורד restart (Supabase prefs), ובעליית השרת גבר מתנצל
ומבקש לשלוח שוב — במקום לקוח שמחכה לנצח."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main_mod  # noqa: E402
from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def test_set_inflight_merges_into_existing_prefs(monkeypatch):
    """set_inflight לא דורס prefs קיימים (הם נדרסים כיחידה ב-upsert)."""
    captured = {}

    async def fake_get_profile(phone):
        return {"prefs": {"dietary": "צמחוני", "_chat": {"turns": []}}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        captured["prefs"] = prefs

    monkeypatch.setattr(memory, "_enabled", lambda: True)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)

    asyncio.run(memory.set_inflight("p1", "גרקו"))
    assert captured["prefs"]["_inflight"] == {"restaurant": "גרקו"}
    assert captured["prefs"]["dietary"] == "צמחוני"  # לא נדרס

    asyncio.run(memory.clear_inflight("p1"))  # get_profile הפייק בלי _inflight → אין upsert נוסף


def test_clear_inflight_removes_marker(monkeypatch):
    captured = {}

    async def fake_get_profile(phone):
        return {"prefs": {"_inflight": {"restaurant": "גרקו"}, "city": "תל אביב"}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        captured["prefs"] = prefs

    monkeypatch.setattr(memory, "_enabled", lambda: True)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)

    asyncio.run(memory.clear_inflight("p1"))
    assert "_inflight" not in captured["prefs"]
    assert captured["prefs"]["city"] == "תל אביב"


def test_run_booking_marks_and_clears_inflight(monkeypatch):
    """הריצה מסמנת inflight בהתחלה ומנקה בסוף — גם בהצלחה וגם בכישלון."""
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._resume.clear()
    events = []

    async def fake_set(phone, restaurant):
        events.append(("set", restaurant))

    async def fake_clear(phone):
        events.append(("clear",))

    async def fake_send_text(phone, msg):
        pass

    async def fake_resolve(name):
        return {"status": "one", "url": "http://x", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(success=True, summary="SUMMARY_REACHED", details={})

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(memory, "set_inflight", fake_set)
    monkeypatch.setattr(memory, "clear_inflight", fake_clear)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)

    fields = {"task_type": "restaurant", "restaurant": "גרקו", "time": "16:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("pI", fields))
    assert events == [("set", "גרקו"), ("clear",)]


def test_startup_apologizes_to_orphans(monkeypatch):
    """עליית שרת עם הזמנה שנקטעה → הודעת התנצלות + ניקוי הסימון."""
    from fastapi.testclient import TestClient

    sent, cleared = [], []

    async def fake_list():
        return [{"phone": "972500000000", "restaurant": "גרקו"}]

    async def fake_clear(phone):
        cleared.append(phone)

    async def fake_send(phone, msg):
        sent.append((phone, msg))

    monkeypatch.setattr(main_mod.memory, "list_inflight", fake_list)
    monkeypatch.setattr(main_mod.memory, "clear_inflight", fake_clear)
    monkeypatch.setattr(main_mod, "send_text", fake_send)
    monkeypatch.setattr(main_mod.settings, "bu_browser", "local")  # מדלג על sweep

    with TestClient(main_mod.app):  # מריץ את ה-lifespan
        pass

    assert cleared == ["972500000000"]
    assert len(sent) == 1 and "נפלתי באמצע" in sent[0][1] and "גרקו" in sent[0][1]
