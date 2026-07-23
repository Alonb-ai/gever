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


def test_max_steps_restaurant_cut_multiscreen_keep_40():
    """חיתוך שריפת-כישלון (דוח הזירוז 17.7): מסעדה מצליחה ב-≤15 צעדים — 25 מספיק,
    וכישלון לא שורף 8+ דקות על 40; ורטיקלים מרובי-מסכים נשארים על 40."""
    assert browser_book._max_steps("restaurant") == 25
    assert browser_book._max_steps("cinema") == 40
    assert browser_book._max_steps("show") == 40
    # ביטוח: טופס רב-דפים עתיר שדות — תקרה גבוהה משל כולם (התנהגות ענף הביטוח)
    assert browser_book._max_steps("insurance") == 80


def test_job_carries_max_steps_by_task_type(monkeypatch, tmp_path):
    """ה-job שנשלח ל-runner נושא את התקרה הנכונה לפי הוורטיקל בפועל."""
    settings.bu_record_dir = str(tmp_path)
    settings.bu_browser = "local"
    jobs = []

    async def fake_run(job):
        jobs.append(job)
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump({"success": True, "message": "SUMMARY_REACHED"}, f)

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    asyncio.run(
        browser_book.book_table_bu(
            restaurant="הדסון", page_url="http://x", date="26", time="20:00", party_size=2
        )
    )
    asyncio.run(
        browser_book.book_table_bu(
            restaurant="",
            page_url="http://x",
            date="26",
            time="20:00",
            party_size=2,
            task_type="cinema",
            movie="האודיסאה",
            city="ראשון לציון",
        )
    )
    assert jobs[0]["task_type"] == "restaurant" and jobs[0]["max_steps"] == 25
    assert jobs[1]["task_type"] == "cinema" and jobs[1]["max_steps"] == 40


def test_timeout_ceiling_cinema_gets_the_long_one():
    """קולנוע ארוך ממסעדה (מפת מושבים + סוגי כרטיסים + טופס) — ריצה חיה נהרגה
    ב-600s קליק אחד לפני קיר-התשלום. מסעדות נשארות על התקרה הקצרה."""
    assert browser_book._timeout_s({"task_type": "cinema"}) == browser_book.BU_CINEMA_TIMEOUT_S
    assert browser_book._timeout_s({"task_type": "restaurant"}) == browser_book.BU_TIMEOUT_S
    assert browser_book._timeout_s({}) == browser_book.BU_TIMEOUT_S
    assert browser_book.BU_CINEMA_TIMEOUT_S > browser_book.BU_TIMEOUT_S
    # ביטוח: הארוכה מכולן (טופס רב-דפים) — התקרה של ענף הביטוח נשמרת במיזוג
    assert (
        browser_book._timeout_s({"task_type": "insurance"}) == browser_book.BU_INSURANCE_TIMEOUT_S
    )
    assert browser_book.BU_INSURANCE_TIMEOUT_S > browser_book.BU_CINEMA_TIMEOUT_S


def test_create_session_pins_region(monkeypatch):
    # זירוז 22.7: הסשן נפתח באזור מ-settings (פרנקפורט הקרוב ל-IL) ולא בברירת
    # המחדל us-west-2 של Browserbase שנכשל לטעון את הוט.
    captured: dict = {}

    async def cap_bb(method, path, body=None):
        captured["body"] = body
        return {"id": "sid", "connectUrl": "wss://x"}

    monkeypatch.setattr(browser_book, "_bb", cap_bb)
    asyncio.run(browser_book._bb_create_session())
    assert captured["body"]["region"] == browser_book.settings.browserbase_region
    assert captured["body"]["region"]  # לא ריק — נשלח בפועל
    # זירוז 22.7: חסימת פרסומות ברמת-הסשן — מרזה את ה-DOM הכבד של דפי הרשתות.
    assert captured["body"]["browserSettings"]["blockAds"] is True


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


def test_browser_crash_reports_and_releases_session(monkeypatch, tmp_path):
    """QA ביטוח 18.7 (#1): מות-דפדפן (browser_error) השאיר סשן Browserbase ‏RUNNING
    ומחויב, ו-details.session_id חזר null — אף שכבה לא יכלה לשחרר. עכשיו: browser_book
    משחרר בנתיב הכשל *וגם* מדווח את ה-session_id — ה-pipeline משחרר שוב כ-backstop."""
    monkeypatch.setattr(settings, "bu_record_dir", str(tmp_path))
    monkeypatch.setattr(settings, "bu_browser", "browserbase")
    released: list[str] = []

    async def fake_create():
        return "sid-crash", "wss://cdp"

    async def fake_release(sid):
        released.append(sid)

    async def fake_run(job):
        # מחקה runner שהדפדפן שלו מת באמצע: דיווח ריק → _parse_result נותן browser_error
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump({"success": False, "failed": "browser_error", "message": ""}, f)

    monkeypatch.setattr(browser_book, "_bb_create_session", fake_create)
    monkeypatch.setattr(browser_book, "release_session", fake_release)
    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="ביטוח נסיעות", page_url="http://x", date="26", time="", party_size=2
        )
    )
    assert res.success is False
    assert res.details["failed"] == "browser_error"
    assert released == ["sid-crash"]  # השחרור המקומי בנתיב הכשל
    assert res.details["session_id"] == "sid-crash"  # מדווח — לא null


def test_timeout_and_error_paths_report_session_id(monkeypatch, tmp_path):
    """גם timeout וגם חריגה (subprocess מת בלי קובץ תוצאה) מדווחים session_id
    ומשחררים — אף נתיב כשל לא מחזיר null על סשן שנוצר."""
    monkeypatch.setattr(settings, "bu_record_dir", str(tmp_path))
    monkeypatch.setattr(settings, "bu_browser", "browserbase")
    released: list[str] = []

    async def fake_create():
        return "sid-t", "wss://cdp"

    async def fake_release(sid):
        released.append(sid)

    monkeypatch.setattr(browser_book, "_bb_create_session", fake_create)
    monkeypatch.setattr(browser_book, "release_session", fake_release)

    async def fake_timeout(job):
        raise asyncio.TimeoutError

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_timeout)
    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="הדסון", page_url="http://x", date="26", time="20:00", party_size=2
        )
    )
    assert res.details["stage"] == "timeout" and res.details["session_id"] == "sid-t"

    async def fake_boom(job):
        raise RuntimeError("subprocess died")

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_boom)
    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="הדסון", page_url="http://x", date="26", time="20:00", party_size=2
        )
    )
    assert res.details["stage"] == "error" and res.details["session_id"] == "sid-t"
    assert released == ["sid-t", "sid-t"]


def test_timeout_ceiling_events_gets_the_long_one():
    """הופעות = מפת אולם + טפסים — אותה תקרה ארוכה כמו קולנוע (900s)."""
    assert browser_book._timeout_s({"task_type": "events"}) == 900
    assert browser_book._timeout_s({"task_type": "events"}) == browser_book.BU_CINEMA_TIMEOUT_S


def test_artist_and_venue_enter_the_job(monkeypatch, tmp_path):
    """artist/venue של הופעות נכנסים ל-job שנשלח ל-runner, כמו movie/city בקולנוע."""
    settings.bu_record_dir = str(tmp_path)
    captured = {}

    async def fake_run(job):
        captured.update(job)
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump({"success": True, "message": "ok"}, f)

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    asyncio.run(
        browser_book.book_table_bu(
            restaurant="קובי פרץ",
            page_url="http://x",
            date="11.08",
            time="",
            party_size=2,
            task_type="events",
            artist="קובי פרץ",
            venue="היכל מנורה",
        )
    )
    assert captured["task_type"] == "events"
    assert captured["artist"] == "קובי פרץ" and captured["venue"] == "היכל מנורה"
