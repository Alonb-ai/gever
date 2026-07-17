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


def test_run_subprocess_passes_provider_keys_only_when_set(monkeypatch, tmp_path):
    """מפתחות ספקי-הנווט החלופיים (השוואת מודלים) עוברים ל-subprocess רק אם מולאו —
    pydantic-settings לא כותב ל-os.environ, אז בלי ההעברה המפורשת ה-runner עיוור להם."""
    captured = {}

    class _FakeProc:
        async def communicate(self, data=None):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return _FakeProc()

    monkeypatch.setattr(browser_book.asyncio, "create_subprocess_exec", fake_exec)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BROWSER_USE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "a-key")
    monkeypatch.setattr(settings, "browser_use_api_key", "bu-key")
    monkeypatch.setattr(settings, "openai_api_key", "")

    asyncio.run(browser_book._run_subprocess({"steps_path": str(tmp_path / "steps.log")}))

    env = captured["env"]
    assert env["GEMINI_API_KEY"] == "g-key" and env["GOOGLE_API_KEY"] == "g-key"
    assert env["ANTHROPIC_API_KEY"] == "a-key"
    assert env["BROWSER_USE_API_KEY"] == "bu-key"
    assert "OPENAI_API_KEY" not in env  # ריק ב-settings → לא מוזרק


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


def test_timeout_ceiling_cinema_gets_the_long_one():
    """קולנוע ארוך ממסעדה (מפת מושבים + סוגי כרטיסים + טופס) — ריצה חיה נהרגה
    ב-600s קליק אחד לפני קיר-התשלום. מסעדות נשארות על התקרה הקצרה."""
    assert browser_book._timeout_s({"task_type": "cinema"}) == browser_book.BU_CINEMA_TIMEOUT_S
    assert browser_book._timeout_s({"task_type": "restaurant"}) == browser_book.BU_TIMEOUT_S
    assert browser_book._timeout_s({}) == browser_book.BU_TIMEOUT_S
    assert browser_book.BU_CINEMA_TIMEOUT_S > browser_book.BU_TIMEOUT_S


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
