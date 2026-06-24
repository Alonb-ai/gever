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


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
