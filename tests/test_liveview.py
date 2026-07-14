"""Live View בקיר-כרטיס: הסשן נשאר חי, live_view_url נשלף מ-Browserbase, וה-pipeline
מעדיף אותו על לינק הדף (Ontopo הוא SPA — לינק רגיל מאבד את כל מה שכבר מולא)."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import browser_book  # noqa: E402
from app.config import settings  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def test_live_view_url_fetches_fullscreen(monkeypatch):
    async def fake_bb(method, path, body=None):
        assert method == "GET" and path == "/sessions/s1/debug"
        return {"debuggerFullscreenUrl": "https://bb.live/s1"}

    monkeypatch.setattr(browser_book, "_bb", fake_bb)
    assert asyncio.run(browser_book.live_view_url("s1")) == "https://bb.live/s1"


def test_live_view_url_safe_on_failure(monkeypatch):
    """כשל API או היעדר סשן → None בשקט (הקורא נופל ללינק דף), לא חריגה ללקוח."""

    async def boom(method, path, body=None):
        raise RuntimeError("api down")

    monkeypatch.setattr(browser_book, "_bb", boom)
    assert asyncio.run(browser_book.live_view_url("s1")) is None
    assert asyncio.run(browser_book.live_view_url(None)) is None


def test_card_wall_keeps_session_alive(monkeypatch, tmp_path):
    """card_required על Browserbase: הסשן לא משוחרר ו-session_id חוזר ב-details —
    בלעדיו אין Live View והלקוח מקבל SPA מאופסת."""
    settings.bu_record_dir = str(tmp_path)
    settings.bu_browser = "browserbase"
    released = []

    async def fake_run(job):
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump({"success": True, "card_required": True, "message": "x"}, f)

    async def fake_create():
        return "s-card", "wss://cdp"

    async def fake_release(sid):
        released.append(sid)

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(browser_book, "_bb_create_session", fake_create)
    monkeypatch.setattr(browser_book, "release_session", fake_release)
    try:
        res = asyncio.run(
            browser_book.book_table_bu(
                restaurant="הדסון", page_url="http://x", date="26", time="21:00", party_size=2
            )
        )
    finally:
        settings.bu_browser = "local"
    assert res.details["session_id"] == "s-card"
    assert released == []


def _commit_card_case(monkeypatch, live_url):
    """מריץ run_commit מול קיר-כרטיס עם session_id חי; מחזיר את ההודעות שנשלחו."""
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._last_out.clear()
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="CARD_REQUIRED",
            details={"card_required": True, "session_id": "s-live"},
        )

    async def fake_live(session_id):
        assert session_id == "s-live"
        return live_url

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "live_view_url", fake_live)
    pipeline._pending_commit["p1"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("p1"))
    return sent


def test_pipeline_card_prefers_live_view(monkeypatch):
    sent = _commit_card_case(monkeypatch, "https://bb.live/s-live")
    assert any("https://bb.live/s-live" in m for m in sent)
    assert pipeline._booking["p1"]["state"] == "card"


def test_pipeline_card_falls_back_to_page_link(monkeypatch):
    """אין Live View (סשן מת/כשל) → חוזרים ללינק הדף — הלקוח לא נשאר בלי כלום."""
    sent = _commit_card_case(monkeypatch, None)
    assert any("http://x" in m for m in sent)
