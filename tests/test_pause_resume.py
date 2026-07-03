"""pause-resume: עצירה על שאלה ללקוח → סשן Browserbase נשאר חי → התשובה ממשיכה
מאותו מסך. מקרי הקצה: סשן מת (fallback טרי), החלפת מסעדה (שחרור), שחרור על כל
תוצאה סופית וגם על timeout/חריגה (keepAlive מחויב באידל — דליפת סשן = כסף)."""

import asyncio
import json as _json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import browser_book, bu_runner  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


# ─── שכבת browser_book: מחזור חיי הסשן ───────────────────────────────────────


def _bb_harness(monkeypatch, *, runner_result: dict, live_url: str | None = None):
    """מדמה Browserbase: create/check/release נרשמים, ה-runner כותב תוצאה קבועה."""
    calls = {"created": 0, "released": [], "job": None}

    async def fake_create():
        calls["created"] += 1
        return f"sess-new-{calls['created']}", "wss://new"

    async def fake_live(session_id):
        return live_url

    async def fake_release(session_id):
        calls["released"].append(session_id)

    async def fake_run(job):
        calls["job"] = job
        with open(job["result_path"], "w", encoding="utf-8") as f:
            _json.dump(runner_result, f)

    monkeypatch.setattr(browser_book, "_bb_create_session", fake_create)
    monkeypatch.setattr(browser_book, "_bb_live_connect_url", fake_live)
    monkeypatch.setattr(browser_book, "release_session", fake_release)
    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(browser_book.settings, "bu_browser", "browserbase")
    monkeypatch.setattr(browser_book.settings, "bu_record_dir", "")
    return calls


def _book(**kw):
    args = dict(restaurant="גרקו", page_url="http://x", date="6.7", time="16:00", party_size=2)
    args.update(kw)
    return asyncio.run(browser_book.book_table_bu(**args))


def test_missing_keeps_session_alive_and_returns_id(monkeypatch):
    calls = _bb_harness(
        monkeypatch, runner_result={"success": False, "missing": "seating_area", "message": "m"}
    )
    res = _book()
    assert res.details["session_id"] == "sess-new-1"  # ה-pipeline ישמור אותו
    assert calls["released"] == []  # הסשן מחכה לתשובת הלקוח


def test_terminal_result_releases_session(monkeypatch):
    calls = _bb_harness(monkeypatch, runner_result={"success": True, "message": "SUMMARY_REACHED"})
    res = _book()
    assert calls["released"] == ["sess-new-1"]  # אין סיבה לשלם על אידל
    assert res.details["session_id"] is None


def test_resume_with_live_session_reconnects_same_screen(monkeypatch):
    calls = _bb_harness(
        monkeypatch,
        runner_result={"success": True, "message": "SUMMARY_REACHED"},
        live_url="wss://live-old",
    )
    _book(resume={"session_id": "sess-old", "recap": "בחרתי תאריך ועצרתי על ישיבה"})
    assert calls["created"] == 0  # אין סשן חדש
    assert calls["job"]["cdp_url"] == "wss://live-old"
    assert calls["job"]["resume"]["recap"].startswith("בחרתי")
    assert calls["released"] == ["sess-old"]  # הסתיים → שוחרר


def test_resume_with_dead_session_falls_back_to_fresh_run(monkeypatch):
    calls = _bb_harness(
        monkeypatch,
        runner_result={"success": True, "message": "SUMMARY_REACHED"},
        live_url=None,  # הסשן פג
    )
    _book(resume={"session_id": "sess-dead", "recap": "..."})
    assert calls["created"] == 1  # ריצה טרייה
    assert "resume" not in calls["job"]  # ה-task הרגיל, לא המשך-מסך


def test_timeout_releases_session(monkeypatch):
    calls = _bb_harness(monkeypatch, runner_result={})

    async def boom(job):
        raise asyncio.TimeoutError

    monkeypatch.setattr(browser_book, "_run_subprocess", boom)
    res = _book()
    assert res.success is False
    assert calls["released"] == ["sess-new-1"]  # גם תקיעה לא מדליפה סשן


def test_sweep_releases_all_running_orphans(monkeypatch):
    """בעליית השרת אין ריצה חיה — כל סשן RUNNING בפרויקט משוחרר (redeploy באמצע ריצה)."""
    released = []

    async def fake_bb(method, path, body=None):
        assert method == "GET" and "status=RUNNING" in path
        return [{"id": "a1"}, {"id": "b2"}]

    async def fake_release(session_id):
        released.append(session_id)

    monkeypatch.setattr(browser_book, "_bb", fake_bb)
    monkeypatch.setattr(browser_book, "release_session", fake_release)
    n = asyncio.run(browser_book.sweep_orphan_sessions())
    assert n == 2 and released == ["a1", "b2"]


# ─── שכבת ה-task: ניסוח ההמשך ────────────────────────────────────────────────


def test_resume_task_continues_from_current_screen():
    job = {
        "url": "http://x",
        "party_size": 2,
        "date": "6.7",
        "time": "16:00",
        "name": "אלון",
        "dry_run": True,
        "resume": {"recap": "מילאתי תאריך וסועדים, עצרתי על אזור ישיבה"},
        "notes": "ישיבה בחוץ",
    }
    task = bu_runner._build_task(job)
    assert "המשך מהמסך הנוכחי" in task and "אל תנווט" in task
    assert "עצרתי על אזור ישיבה" in task  # ה-recap בפנים
    assert "התחל מהכתובת" not in task  # לא מנווטים מחדש
    assert "ישיבה בחוץ" in task  # התשובה של הלקוח הגיעה
    assert "SUMMARY_REACHED" in task  # חוזה ה-markers נשמר גם ב-resume


# ─── שכבת ה-pipeline: הזרימה המלאה ───────────────────────────────────────────


def _pipeline_harness(monkeypatch, book_results: list, released: list):
    sent, calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        calls.append("resolve")
        return {"status": "one", "url": "http://fresh", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        calls.append(("book", kwargs.get("resume"), kwargs["page_url"]))
        return book_results.pop(0)

    async def fake_release(session_id):
        released.append(session_id)

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "release_session", fake_release)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    return sent, calls


def test_missing_then_answer_resumes_same_session(monkeypatch):
    """הזרימה המלאה: עצירה על ישיבה → תשובת לקוח → הריצה השנייה ממשיכה מאותו סשן."""
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._resume.clear()
    released: list = []
    missing_res = ActionResult(
        success=False,
        summary="MISSING:seating_area",
        details={"missing": "seating_area", "session_id": "sess-77", "stage": "עצרתי על ישיבה"},
    )
    ok_res = ActionResult(success=True, summary="SUMMARY_REACHED", details={})
    sent, calls = _pipeline_harness(monkeypatch, [missing_res, ok_res], released)

    fields = {
        "task_type": "restaurant",
        "restaurant": "גרקו",
        "date": "6.7",
        "time": "16:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("pR", fields))
    assert pipeline._resume["pR"]["session_id"] == "sess-77"  # הסשן נשמר

    # הלקוח ענה → ready חדש עם notes; הריצה ממשיכה מאותו מסך בלי resolve מחדש
    fields2 = {**fields, "notes": "בחוץ"}
    asyncio.run(pipeline.run_booking("pR", fields2))

    resolves = [c for c in calls if c == "resolve"]
    books = [c for c in calls if isinstance(c, tuple)]
    assert len(resolves) == 1  # רק הריצה הראשונה עשתה resolve
    assert books[1][1]["session_id"] == "sess-77"  # resume הועבר
    assert books[1][2] == "http://fresh"  # אותו url מהסבב הראשון
    assert "pR" not in pipeline._resume  # נוצל — לא יתנגש בהזמנה הבאה


def test_answer_with_different_restaurant_releases_stale_session(monkeypatch):
    """הלקוח החליף מסעדה בזמן שסשן חיכה → הסשן הישן משוחרר וריצה טרייה עם resolve."""
    pipeline._booking.clear()
    pipeline._resume.clear()
    released: list = []
    ok_res = ActionResult(success=True, summary="SUMMARY_REACHED", details={})
    sent, calls = _pipeline_harness(monkeypatch, [ok_res], released)
    pipeline._resume["pS"] = {
        "restaurant": "גרקו",
        "url": "http://old",
        "platform": "tabit",
        "session_id": "sess-stale",
        "recap": "...",
    }

    fields = {
        "task_type": "restaurant",
        "restaurant": "טאיזו",
        "date": "6.7",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("pS", fields))

    assert released == ["sess-stale"]  # לא מדליפים את הסשן הישן
    assert "resolve" in calls  # מסעדה חדשה → resolve רגיל
    books = [c for c in calls if isinstance(c, tuple)]
    assert books[0][1] is None  # בלי resume


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
