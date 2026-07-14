"""בדיקות pipeline לוורטיקל הקולנוע: routing ל-resolve_cinema_url, העברת
task_type/movie/city ל-book_table_bu, הודעת קיר-כרטיס עם סיכום מלא (סרט/שעה/מושבים),
דילוג alt_time, _human לשדות קולנוע, _failure_reply קולנוע, ושחזור ב-run_commit."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

_FIELDS = {
    "task_type": "cinema",
    "movie": "האודיסאה",
    "city": "ראשון לציון",
    "date": "15.7",
    "time": "20:00",
    "party_size": 2,
    "name": "אלון",
}


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._reset_next.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()


def _wire(monkeypatch, *, book, resolve=None, sent=None, lists=None):
    """חיווט הפייקים המשותף: resolve קולנוע (ברירת מחדל one→planet), book, ושליחות."""
    sent = sent if sent is not None else []
    lists = lists if lists is not None else []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, options, button="בחירה"):
        lists.append((body, options))

    async def default_resolve(name):
        return {
            "status": "one",
            "url": "https://www.planetcinema.co.il/films/the-odyssey/7460s2r",
            "platform": "planet",
            "candidates": [],
            "fallback": None,
        }

    async def fail_restaurant_resolve(name):
        raise AssertionError("resolve_reservation_url לא אמור להיקרא בקולנוע")

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "resolve_cinema_url", resolve or default_resolve)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fail_restaurant_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    return sent, lists


def test_cinema_routes_to_cinema_resolver_and_passes_vertical_fields(monkeypatch):
    """task_type='cinema' → resolve_cinema_url (לא המסעדות), ו-book_table_bu מקבל
    task_type/movie/city; name המשותף = שם הסרט."""
    _reset()
    captured = {}

    async def fake_book(**kwargs):
        captured.update(kwargs)
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED 21:30 | שורה 7 CARD_REQUIRED",
            details={"card_required": True, "time": "21:30", "seats": "שורה 7"},
        )

    _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("c1", dict(_FIELDS)))

    assert captured["task_type"] == "cinema"
    assert captured["movie"] == "האודיסאה" and captured["city"] == "ראשון לציון"
    assert captured["restaurant"] == "האודיסאה"  # name המשותף לכל מנגנוני הקיצור
    assert captured["dry_run"] is True
    assert captured["page_url"].startswith("https://www.planetcinema.co.il/films/")


def test_cinema_card_wall_message_carries_full_summary_and_link(monkeypatch):
    """העצירה המוצלחת הסטנדרטית של האבטיפוס: קיר-כרטיס → הודעה עם סרט, שעת ההקרנה,
    המושבים, 'נשאר רק התשלום' ולינק. state='card', בלי gate לאישור."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED 21:30 | שורה 7 מושבים 11,12 CARD_REQUIRED",
            details={
                "card_required": True,
                "time": "21:30",
                "seats": "שורה 7 מושבים 11,12",
            },
        )

    sent, _ = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("c2", dict(_FIELDS)))

    assert pipeline._booking["c2"]["state"] == "card"
    final = sent[-1]
    assert "האודיסאה" in final and "21:30" in final and "שורה 7 מושבים 11,12" in final
    assert "התשלום" in final
    assert "https://www.planetcinema.co.il/films/" in final  # לינק (fallback לדף)
    assert "c2" not in pipeline._pending_commit  # אין מה לאשר — הלקוח סוגר בעצמו


def test_cinema_pending_skips_alt_time_and_asks_to_close(monkeypatch):
    """סיכום בלי קיר-כרטיס: סטיית שעה היא הנורמה בקולנוע (הקרנות בדידות) — אין
    מנגנון alt_time; ההודעה נוקבת בשעה שנתפסה + מושבים ושואלת 'לסגור?'."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED 21:30 | שורה 6 מושבים 9,10",
            details={"time": "21:30", "seats": "שורה 6 מושבים 9,10"},
        )

    sent, _ = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("c3", dict(_FIELDS)))  # התבקש 20:00, נתפס 21:30

    assert pipeline._booking["c3"]["state"] == "pending"
    assert "alt_time" not in pipeline._booking["c3"]  # אין התראת-חלופה נפרדת
    final = sent[-1]
    assert "21:30" in final and "שורה 6 מושבים 9,10" in final
    assert "סגור" in final and final.endswith("?")
    job = pipeline._pending_commit["c3"]
    assert job["task_type"] == "cinema" and job["movie"] == "האודיסאה"
    assert job["city"] == "ראשון לציון" and job["time"] == "21:30"


def test_cinema_missing_format_sends_real_options_list(monkeypatch):
    """MISSING:format עם OPTIONS מהדף → רשימת בחירה אמיתית שגוף ההודעה שלה נוקב
    ב'פורמט הקרנה'; הסשן החי נשמר ל-resume."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING:format",
            details={
                "missing": "format",
                "options": ["רגיל", "IMAX", "4DX"],
                "session_id": "sess-c",
                "stage": "עצרתי על פורמט",
            },
        )

    sent, lists = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("c4", dict(_FIELDS)))

    assert pipeline._booking["c4"]["state"] == "missing"
    assert pipeline._booking["c4"]["info"] == "format"
    assert len(lists) == 1
    body, options = lists[0]
    assert options == ["רגיל", "IMAX", "4DX"]
    assert "פורמט הקרנה" in body
    assert pipeline._resume["c4"]["session_id"] == "sess-c"  # pause-resume חי


def test_cinema_missing_language_asks_in_human_words(monkeypatch):
    """MISSING:language בלי options → שאלה טקסטואלית עם התרגום האנושי (מדובב/כתוביות)."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=False, summary="MISSING:language", details={"missing": "language"}
        )

    sent, lists = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("c5", dict(_FIELDS)))

    assert not lists
    assert "מדובב" in sent[-1] and "כתוביות" in sent[-1]


def test_failure_reply_cinema_wordings_and_restaurant_unchanged():
    """no_cinema_in_city (סיבה חדשה) ונוסח קולנוע ל-no_availability; ברירת המחדל
    של מסעדות לא זזה."""
    info, msg = pipeline._failure_reply(
        "no_cinema_in_city", "האודיסאה", task_type="cinema", city="חיפה"
    )
    assert "חיפה" in info and "חיפה" in msg and "רשת אחרת" in msg

    info, msg = pipeline._failure_reply(
        "no_availability", "האודיסאה", task_type="cinema", city="חיפה"
    )
    assert "הקרנה" in info and "הקרנה" in msg

    # מסעדות: אותו נוסח כמו קודם, ו-no_cinema_in_city לא קיימת שם
    info, msg = pipeline._failure_reply("no_availability", "גרקו")
    assert "אין מקום פנוי" in info
    assert pipeline._failure_reply("no_cinema_in_city", "גרקו") is None


def test_cinema_no_cinema_in_city_triggers_existing_fallback_loop(monkeypatch):
    """FAILED:no_cinema_in_city הוא FAILED רגיל — לולאת ה-attempts הקיימת מנסה את
    ה-fallback (רב-חן) בלי קוד חדש; כשגם הוא נכשל, ההודעה נוקבת בעיר."""
    _reset()
    calls = []

    async def fake_resolve(name):
        return {
            "status": "one",
            "url": "http://planet",
            "platform": "planet",
            "candidates": [],
            "fallback": {"url": "http://rav-hen", "platform": "rav-hen"},
        }

    async def fake_book(**kwargs):
        calls.append(kwargs["page_url"])
        return ActionResult(
            success=False,
            summary="FAILED:no_cinema_in_city",
            details={"failed": "no_cinema_in_city"},
        )

    sent, _ = _wire(monkeypatch, book=fake_book, resolve=fake_resolve)
    asyncio.run(pipeline.run_booking("c6", dict(_FIELDS)))

    assert calls == ["http://planet", "http://rav-hen"]  # שני ניסיונות, אפס קוד חדש
    assert pipeline._booking["c6"]["state"] == "failed"
    assert "ראשון לציון" in sent[-1]


def test_cinema_none_and_empty_movie_messages(monkeypatch):
    """resolve=none → 'לא מצאתי איפה קונים כרטיסים'; movie ריק → שאלה, בלי resolve."""
    _reset()
    resolves = []

    async def fake_resolve(name):
        resolves.append(name)
        return {"status": "none", "url": None, "platform": None, "candidates": []}

    async def fake_book(**kwargs):
        raise AssertionError("אין book כש-resolve=none")

    sent, _ = _wire(monkeypatch, book=fake_book, resolve=fake_resolve)
    asyncio.run(pipeline.run_booking("c7", dict(_FIELDS)))
    assert "כרטיסים" in sent[-1] and "האודיסאה" in sent[-1]
    assert pipeline._booking["c7"]["state"] == "none"

    asyncio.run(pipeline.run_booking("c8", {**_FIELDS, "movie": ""}))
    assert resolves == ["האודיסאה"]  # ה-resolve לא נקרא שוב על שם ריק
    assert "סרט" in sent[-1]
    assert "c8" not in pipeline._booking


def test_run_commit_restores_cinema_job(monkeypatch):
    """_pending_commit שומר task_type/movie/city ו-run_commit משחזר אותם לקריאה
    (סימטריה — באבטיפוס לא ירוץ בפועל, DRY_RUN תמיד)."""
    _reset()
    captured = {}

    async def fake_send_text(phone, msg):
        pass

    async def fake_book(**kwargs):
        captured.update(kwargs)
        return ActionResult(success=True, summary="BOOKED 777", details={"confirmation": "777"})

    async def fake_log(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    pipeline._pending_commit["c9"] = {
        "restaurant": "האודיסאה",
        "page_url": "http://planet",
        "platform": "planet",
        "date": "15.7",
        "time": "21:30",
        "party_size": 2,
        "name": "אלון",
        "task_type": "cinema",
        "movie": "האודיסאה",
        "city": "ראשון לציון",
    }
    asyncio.run(pipeline.run_commit("c9"))

    assert captured["task_type"] == "cinema"
    assert captured["movie"] == "האודיסאה" and captured["city"] == "ראשון לציון"
    assert captured["dry_run"] is False


def test_book_table_bu_job_carries_cinema_fields_and_seats_back(monkeypatch, tmp_path):
    """book_table_bu: task_type/movie/city נכנסים ל-job של ה-runner, ו-seats מהתוצאה
    חוזר ב-details (הצינור של הודעת קיר-הכרטיס)."""
    from app.automation import browser_book

    captured = {}

    async def fake_run(job):
        captured.update(job)
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump(
                {
                    "success": True,
                    "card_required": True,
                    "time": "21:30",
                    "seats": "שורה 7 מושבים 11,12",
                    "message": "SUMMARY_REACHED 21:30 | שורה 7 מושבים 11,12 CARD_REQUIRED",
                },
                f,
                ensure_ascii=False,
            )

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(browser_book.settings, "bu_record_dir", str(tmp_path))
    monkeypatch.setattr(browser_book.settings, "bu_browser", "local")
    monkeypatch.setattr(browser_book.settings, "bu_chrome_path", "")

    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="האודיסאה",
            page_url="https://www.planetcinema.co.il/films/the-odyssey/7460s2r",
            date="15.7",
            time="20:00",
            party_size=2,
            name="אלון",
            task_type="cinema",
            movie="האודיסאה",
            city="ראשון לציון",
        )
    )
    assert captured["task_type"] == "cinema"
    assert captured["movie"] == "האודיסאה" and captured["city"] == "ראשון לציון"
    assert res.details["seats"] == "שורה 7 מושבים 11,12"
    assert res.details["card_required"] is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
