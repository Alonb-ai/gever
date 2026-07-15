"""בדיקה ל-book_table_bu: ממירה את ה-JSON שה-runner כותב ל-ActionResult, בלי דפדפן חי
(מ-mock-ים את ה-subprocess שכותב תוצאה מוכנה לקובץ)."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation import browser_book  # noqa: E402
from app.config import settings  # noqa: E402


def test_book_table_bu_parses_runner_result(monkeypatch, tmp_path):
    settings.bu_record_dir = str(tmp_path)
    settings.bu_browser = "local"

    async def fake_run(job):
        # מחקה את ה-runner: כותב JSON תוצאה ל-job["result_path"]
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump(
                {
                    "success": True,
                    "stage": "הגעתי לשלב פרטי אשראי",
                    "card_required": True,
                    "message": "הכל מוכן אח שלי, נשאר רק כרטיס",
                },
                f,
                ensure_ascii=False,
            )

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="הדסון",
            page_url="http://x",
            date="26",
            time="21:30",
            party_size=2,
            name="אלון",
        )
    )
    assert res.success is True
    assert "מוכן" in res.summary
    assert res.details["card_required"] is True
    assert res.details["restaurant"] == "הדסון"


def test_book_table_bu_timeout_is_honest(monkeypatch, tmp_path):
    settings.bu_record_dir = str(tmp_path)
    settings.bu_browser = "local"

    async def fake_timeout(job):
        raise asyncio.TimeoutError

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_timeout)
    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="הדסון", page_url="http://x", date="26", time="21:30", party_size=2
        )
    )
    assert res.success is False
    assert res.details["stage"] == "timeout"


def test_release_session_retries_transient_failure(monkeypatch):
    # ריצת ביטוח חיה 1 (15.7): נפילת רשת רגעית הפילה גם את השחרור היחיד והסשן
    # נשאר RUNNING ומחויב. עכשיו: ניסיון שנכשל → retry שמצליח.
    calls: list[str] = []

    async def flaky_bb(method, path, body=None):
        calls.append(path)
        if len(calls) == 1:
            raise RuntimeError("network blip")
        return {}

    async def no_sleep(_secs):
        return None

    monkeypatch.setattr(browser_book, "_bb", flaky_bb)
    monkeypatch.setattr(browser_book.asyncio, "sleep", no_sleep)
    asyncio.run(browser_book.release_session("sid-1"))
    assert len(calls) == 2


def test_release_session_gives_up_quietly_after_three(monkeypatch):
    calls: list[str] = []

    async def dead_bb(method, path, body=None):
        calls.append(path)
        raise RuntimeError("network down")

    async def no_sleep(_secs):
        return None

    monkeypatch.setattr(browser_book, "_bb", dead_bb)
    monkeypatch.setattr(browser_book.asyncio, "sleep", no_sleep)
    asyncio.run(browser_book.release_session("sid-2"))  # best-effort — לא זורק
    assert len(calls) == 3


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
