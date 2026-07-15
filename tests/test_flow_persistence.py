"""התמדת מצב ה-flow ל-prefs: redeploy באמצע שיחה לא הורג רשימה פתוחה / "מאשר"
ממתין / סניף שנבחר. שמירה בסוף כל ריצה, שחזור בטעינה הקרה הראשונה."""

import asyncio
import os
import sys
import time

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
    pipeline._last_out.clear()


def test_save_flow_persists_all_state(monkeypatch):
    """_save_flow כותב את חמשת מרכיבי המצב ל-prefs._flow בלי לדרוס prefs אחרים."""
    _reset()
    upserts = []

    async def fake_get_profile(phone):
        return {"prefs": {"kept": 1}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    pipeline._booking["p1"] = {"state": "pending", "info": "הדסון"}
    pipeline._pending_commit["p1"] = {"restaurant": "הדסון", "name": "אלון"}
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    pipeline._pending_pick["p1"] = {"סניף א": ("http://a", "ontopo")}

    asyncio.run(pipeline._save_flow("p1"))

    flow = upserts[0]["_flow"]
    assert upserts[0]["kept"] == 1
    assert flow["booking"]["state"] == "pending"
    assert flow["pending_commit"]["restaurant"] == "הדסון"
    assert flow["resolved"]["url"] == "http://x"
    assert flow["pending_pick"]["סניף א"] == ("http://a", "ontopo")
    assert flow["ts"] > 0


def _fresh_flow(**over):
    flow = {
        "booking": {"state": "pending", "info": "הדסון"},
        "pending_commit": {"restaurant": "הדסון", "name": "אלון"},
        "resume": {"restaurant": "הדסון", "session_id": "s1", "url": "http://x", "platform": ""},
        "resolved": {"name": "הדסון", "url": "http://x", "platform": "ontopo"},
        "pending_pick": {"סניף א": ["http://a", "ontopo"], "סניף ב": ["http://b", "tabit"]},
        "ts": time.time(),
    }
    flow.update(over)
    return flow


def test_restore_flow_after_restart():
    """שחזור מלא אחרי restart: כל המצב חוזר, ורשימות JSON הופכות חזרה ל-tuples."""
    _reset()
    pipeline._restore_flow("p1", _fresh_flow())
    assert pipeline._booking["p1"]["state"] == "pending"
    assert pipeline._pending_commit["p1"]["name"] == "אלון"
    assert pipeline._resume["p1"]["session_id"] == "s1"
    assert pipeline._resolved["p1"]["name"] == "הדסון"
    assert pipeline._pending_pick["p1"]["סניף ב"] == ("http://b", "tabit")


def test_restore_skips_stale_and_working():
    """מצב בן >3 שעות לא משוחזר (דף חדש ממילא); state='working' נזרק — הריצה מתה."""
    _reset()
    pipeline._restore_flow("p1", _fresh_flow(ts=time.time() - pipeline.SESSION_GAP_S - 60))
    assert "p1" not in pipeline._booking and "p1" not in pipeline._pending_commit

    pipeline._restore_flow("p1", _fresh_flow(booking={"state": "working", "info": "הדסון"}))
    assert "p1" not in pipeline._booking  # working נזרק
    assert pipeline._pending_commit["p1"]["name"] == "אלון"  # השאר כן שוחזר


def test_restore_never_overrides_live_memory():
    """מצב חם בזיכרון מנצח — שחזור לא דורס שיחה חיה."""
    _reset()
    pipeline._resolved["p1"] = {"name": "רוסטיקו", "url": "http://r", "platform": "tabit"}
    pipeline._restore_flow("p1", _fresh_flow())
    assert pipeline._resolved["p1"]["name"] == "רוסטיקו"
    assert "p1" not in pipeline._pending_commit


def test_restored_pick_fires_without_resolve(monkeypatch):
    """הסיפור המלא: רשימה נשלחה → redeploy → הלקוח מקיש על סניף — הריצה נורית ישר
    מהמצב המשוחזר, בלי resolve שני ובלי לשלוח את הרשימה שוב (הבאג ההיסטורי)."""
    _reset()
    resolve_calls, book_calls = [], []

    async def fake_resolve(name):
        resolve_calls.append(name)
        return {"status": "none"}

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        return ActionResult(
            success=False, summary="FAILED:no_availability", details={"failed": "no_availability"}
        )

    async def fake_send_text(phone, msg):
        pass

    async def fake_get_profile(phone):
        return None

    async def fake_persist(phone):
        pass

    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "_save_flow", fake_persist)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    pipeline._restore_flow("p1", _fresh_flow(booking=None, pending_commit=None, resume=None))
    asyncio.run(pipeline.run_booking("p1", {"restaurant": "סניף ב", "time": "20:00"}))

    assert resolve_calls == []  # לא היה חיפוש — הבחירה המשוחזרת שימשה ישירות
    assert book_calls[0]["page_url"] == "http://b"
