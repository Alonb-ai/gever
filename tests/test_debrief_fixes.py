"""תיקוני תחקיר 15.7: מיפוי broken_page/login_required, retry אוטומטי על דף שבור,
וסיכום הזמנה לפני הזנת אשראי."""

import asyncio
import os
import sys

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
    pipeline._await_answer.clear()
    pipeline._last_out.clear()


def test_failure_reply_covers_all_agent_reasons():
    """כל אוצר המילים של FAILED ב-bu_runner ממופה — אף סיבה כנה לא נופלת לגנרית."""
    for reason in (
        "no_availability",
        "closed",
        "no_online_booking",
        "login_required",
        "broken_page",
    ):
        hit = pipeline._failure_reply(reason, "הדסון")
        assert hit is not None, reason
        assert "הדסון" in hit[1]


def _wire(monkeypatch, sent, results):
    calls = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        calls.append(kwargs)
        return results[min(len(calls) - 1, len(results) - 1)]

    async def fake_get_profile(phone):
        return None

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    return calls


def test_broken_page_retries_once_then_succeeds(monkeypatch):
    """דף שבור חולף → ניסיון חוזר אוטומטי אחד (בטסט החי זה עלה 10 דקות המתנה)."""
    _reset()
    sent = []
    broken = ActionResult(
        success=False, summary="FAILED:broken_page", details={"failed": "broken_page"}
    )
    good = ActionResult(
        success=True,
        summary="SUMMARY_REACHED 20:00",
        details={"summary_reached": True, "time": "20:00"},
    )
    calls = _wire(monkeypatch, sent, [broken, good])

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    asyncio.run(
        pipeline.run_booking("p1", {"restaurant": "הדסון", "time": "20:00", "party_size": 2})
    )
    assert len(calls) == 2  # ניסיון + retry אחד
    assert pipeline._booking["p1"]["state"] == "pending"  # ה-retry הציל את הריצה
    assert any("נסיון" in m or "ניסיון" in m or "מנסה שוב" in m for m in sent)


def test_broken_page_twice_gets_specific_message(monkeypatch):
    """גם ה-retry נכשל → הודעת broken_page ספציפית, לא 'משהו לא זרם' הגנרית."""
    _reset()
    sent = []
    broken = ActionResult(
        success=False, summary="FAILED:broken_page", details={"failed": "broken_page"}
    )
    calls = _wire(monkeypatch, sent, [broken, broken])
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    asyncio.run(
        pipeline.run_booking("p1", {"restaurant": "הדסון", "time": "20:00", "party_size": 2})
    )
    assert len(calls) == 2
    assert pipeline._booking["p1"]["state"] == "failed"
    assert "הדסון" in sent[-1] and "לא זרם" not in sent[-1]


def test_card_message_recaps_booking(monkeypatch):
    """קיר-כרטיס: ההודעה מסכמת מה נסגר (תאריך/שעה/סועדים) לפני שהלקוח מזין אשראי."""
    _reset()
    sent = []
    card = ActionResult(
        success=True,
        summary="CARD_REQUIRED",
        details={"card_required": True, "time": "19:15", "summary_reached": True},
    )
    _wire(monkeypatch, sent, [card])

    async def fake_live(session_id):
        return None

    monkeypatch.setattr(pipeline, "live_view_url", fake_live)
    pipeline._resolved["p1"] = {"name": "אסה", "url": "http://x", "platform": "ontopo"}
    asyncio.run(
        pipeline.run_booking(
            "p1", {"restaurant": "אסה", "date": "23.7", "time": "19:00", "party_size": 3}
        )
    )
    final = sent[-1]
    assert "19:15" in final and "23.7" in final and "3" in final  # השעה שנבחרה בפועל


ASA_SPLIT_REPORT = """הגעתי למסך פרטי האשראי של ההזמנה ל-ASA Izakaya. כל הפרטים הוזנו.

AGREED: תקנון ומדיניות ביטול | האזור שנבחר הוא אזור עישון.

נבחר: 3 סועדים בתאריך 23.07 בשעה 19:00 באזור בחוץ Asa - אזור עישון.
URL: https://s1.ontopo.com/he/checkout/feBZRKpnrWU

SUMMARY_REACHED 19:00
CARD_REQUIRED"""


def test_split_final_lines_still_parse():
    """הרגרסיה של טסט 15.7 (פעמיים!): ה-agent פיצל את שורת הסיום לשתי שורות —
    ריצה שהגיעה למסך האשראי דווחה ככישלון. בלוק-הסיום קורא עד 3 שורות אחרונות."""
    from app.automation.bu_runner import _parse_result

    r = _parse_result(ASA_SPLIT_REPORT, commit=False)
    assert r["success"] is True
    assert r["summary_reached"] is True and r["card_required"] is True
    assert r["time"] == "19:00"
    assert r["agreed"] and "תקנון" in r["agreed"][0]
    assert r["page_now"].startswith("https://s1.ontopo.com")


def test_unrecognized_failure_releases_leaked_session(monkeypatch):
    """כישלון לא-מזוהה שהשאיר סשן חי → הסשן משוחרר, לא מדליף 30 דק' keepAlive."""
    _reset()
    sent, released = [], []
    bad = ActionResult(success=False, summary="גיבריש בלי מרקר", details={"session_id": "s-leak"})
    _wire(monkeypatch, sent, [bad])

    async def fake_release(sid):
        released.append(sid)

    monkeypatch.setattr(pipeline, "release_session", fake_release)
    pipeline._resolved["p1"] = {"name": "אסה", "url": "http://x", "platform": "ontopo"}

    async def _go():
        await pipeline.run_booking("p1", {"restaurant": "אסה", "time": "19:00"})
        import asyncio as _a

        for _ in range(3):
            await _a.sleep(0)
            if pipeline._pending:
                await _a.gather(*list(pipeline._pending), return_exceptions=True)

    asyncio.run(_go())
    assert released == ["s-leak"]
