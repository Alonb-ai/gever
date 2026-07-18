"""שער הגישה (ACCESS_GATE) — הכנה למספר האמיתי: גבר עונה רק למאושרים ב-DB.

כבוי (ברירת מחדל) = אפס שינוי התנהגות. דלוק: זר מקבל תשובת-שער אחת בלבד ואז
שתיקה, אפס קריאות מודל ואפס כתיבה לזיכרון; קוד הזמנה תקף מאשר וממשיך טבעי
לאונבורדינג; קוד שגוי נופל לכלל השתיקה; מאושר עובר רגיל."""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import memory  # noqa: E402


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._await_answer.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._last_out.clear()
    pipeline._gate_last_reply.clear()
    memory._approved_cache.clear()


def _wire(monkeypatch, converse_result=None, *, profile=None, gate=False, codes=""):
    """חיווט handle_inbound: מונה קריאות מודל, לוכד הודעות/כתיבות DB, שער נשלט."""
    sent: list[str] = []
    converse_calls: list[str] = []
    upserts: list[dict] = []
    typing: list = []

    async def fake_converse(phone, text):
        converse_calls.append(text)
        pipeline._last_seen[phone] = time.time()
        return dict(converse_result or {"reply": "אהלן", "ready": False})

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_typing(message_id):
        typing.append(message_id)

    async def fake_noop(phone):
        pass

    async def fake_get_profile(phone):
        return profile

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append({"name": name, "email": email, "prefs": prefs})

    monkeypatch.setattr(settings, "access_gate", gate)
    monkeypatch.setattr(settings, "invite_codes", codes)
    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    return sent, converse_calls, upserts, typing


def test_gate_off_is_zero_change(monkeypatch):
    """הדגל כבוי (ברירת המחדל) = הזרימה של היום בדיוק: converse רץ ותשובה נשלחת.
    המשתמש מסומן מוכר — מגע ראשון מדלג על converse בכוונה (fix/onboarding-double)."""
    _reset()
    sent, calls, _, _ = _wire(monkeypatch, gate=False)
    pipeline._last_seen["g_off"] = 10**12
    asyncio.run(pipeline.handle_inbound("g_off", "היי"))
    assert calls == ["היי"]
    assert "אהלן" in sent  # תשובת השיחה יצאה; אין הודעת שער
    assert not any("קוד" in m for m in sent)


def test_stranger_gets_one_gate_reply_then_silence(monkeypatch):
    """זר: תשובת-שער אחת (עם 'קוד'), ההודעה השנייה מושתקת לגמרי."""
    _reset()
    sent, calls, _, _ = _wire(monkeypatch, gate=True)

    async def go():
        await pipeline.handle_inbound("stranger1", "היי מה קורה")
        await pipeline.handle_inbound("stranger1", "הלו??")

    asyncio.run(go())
    assert len(sent) == 1 and "קוד" in sent[0]
    assert calls == []  # אפס קריאות מודל לזרים — הגנת עלות


def test_stranger_leaves_no_trace(monkeypatch):
    """הודעות זרים לא נכנסות ל-_turns ולא נכתבות ל-DB, ואין להן typing."""
    _reset()
    sent, _, upserts, typing = _wire(monkeypatch, gate=True)
    asyncio.run(pipeline.handle_inbound("stranger2", "היי"))
    assert "stranger2" not in pipeline._turns
    assert upserts == []
    assert typing == []


def test_gate_reply_again_after_gap(monkeypatch):
    """אחרי חלון השתיקה מותר תזכורת-שער אחת נוספת."""
    _reset()
    sent, _, _, _ = _wire(monkeypatch, gate=True)
    asyncio.run(pipeline.handle_inbound("stranger3", "היי"))
    pipeline._gate_last_reply["stranger3"] = time.time() - pipeline.GATE_REPLY_GAP_S - 1
    asyncio.run(pipeline.handle_inbound("stranger3", "יש מישהו?"))
    assert len(sent) == 2 and all("קוד" in m for m in sent)


def test_valid_code_approves_and_onboards(monkeypatch):
    """קוד תקף: approve נכתב ל-DB, ברוך-הבא נשלח, והזרימה ממשיכה טבעי —
    האונבורדינג של מגע ראשון נדלק על אותה הודעה, וההודעה הבאה עוברת רגיל."""
    _reset()
    sent, calls, upserts, _ = _wire(monkeypatch, gate=True, codes="GVR1, GVR2")

    async def go():
        await pipeline.handle_inbound("newbie", " GVR1 ")
        await pipeline.handle_inbound("newbie", "תזמין לי שולחן")

    asyncio.run(go())
    assert upserts and upserts[0]["prefs"] == {"approved": True}
    assert "קוד" in sent[0]  # ברוך-הבא על הקוד
    assert any("גבר" in m and "מייל" in m for m in sent)  # האונבורדינג נדלק
    # הודעת הקוד היא מגע ראשון — ההיכרות היא התשובה היחידה (בלי converse,
    # fix/onboarding-double); ההודעה הבאה של המאושר עוברת רגיל.
    assert calls == ["תזמין לי שולחן"]


def test_wrong_code_falls_to_silence(monkeypatch):
    """קוד שגוי אחרי תשובת-השער לא מאשר ולא נענה — כלל השתיקה."""
    _reset()
    sent, calls, upserts, _ = _wire(monkeypatch, gate=True, codes="GVR1")

    async def go():
        await pipeline.handle_inbound("stranger4", "היי")
        await pipeline.handle_inbound("stranger4", "GVR9")

    asyncio.run(go())
    assert len(sent) == 1  # רק תשובת-השער הראשונה
    assert calls == [] and upserts == []


def test_approved_user_passes(monkeypatch):
    """משתמש עם prefs.approved עובר את השער לזרימה הרגילה."""
    _reset()
    prof = {"name": "אלון", "email": "a@b.co", "prefs": {"approved": True}}
    sent, calls, _, _ = _wire(monkeypatch, gate=True, profile=prof)
    asyncio.run(pipeline.handle_inbound("vip1", "היי"))
    assert calls == ["היי"]
    assert "אהלן" in sent


def test_is_approved_caches_and_approve_invalidates(monkeypatch):
    """cache: קריאה שנייה לא מכה DB; approve נתפס מיד; TTL שפג → קריאה מחדש."""
    _reset()
    reads: list[str] = []
    prof: dict = {"prefs": {}}

    async def fake_get_profile(phone):
        reads.append(phone)
        return prof

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        prof["prefs"] = prefs

    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)

    async def go():
        assert not await memory.is_approved("c1")
        assert not await memory.is_approved("c1")  # מה-cache
        assert len(reads) == 1
        await memory.approve("c1")
        assert await memory.is_approved("c1")  # invalidate ב-approve — נתפס מיד בלי DB
        memory._approved_cache["c1"] = (False, time.time() - memory._APPROVED_TTL_S - 1)
        assert await memory.is_approved("c1")  # TTL פג → קורא DB ורואה את האישור

    asyncio.run(go())


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
