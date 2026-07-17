"""ליבת הקול החופשי: _say מחולל טרי מהמודל, הוולידטור פוסל דטרמיניסטית,
וכל כשל (פלט מפר / timeout / חריגה) נופל שקוף למאגר הקיים. _presay מחולל
מראש לטיימר ולא שולח כלום כשההמתנה בוטלה."""

import asyncio
import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402


def _model(monkeypatch, reply: str, delay: float = 0.0, error: Exception | None = None):
    """מוק לקריאת המודל — הנקודה היחידה שהטסטים מחליפים."""
    calls = []

    async def fake(intent, ctx):
        calls.append((intent, ctx))
        if delay:
            await asyncio.sleep(delay)
        if error:
            raise error
        return reply

    monkeypatch.setattr(pipeline, "_say_model", fake)
    return calls


# ── פלט תקין עובר ──


async def test_valid_output_passes(monkeypatch):
    _model(monkeypatch, "עוד רגע ואני איתך, האתר חופר 🔄")
    assert await pipeline._say("heartbeat") == "עוד רגע ואני איתך, האתר חופר 🔄"


async def test_negated_honesty_is_allowed(monkeypatch):
    """'לא סגרתי' היא כנות, לא הכרזת ביצוע — ה-lookbehind לא פוסל אותה."""
    reply = "נתקע לי משהו באמצע ועוד לא סגרתי — ננסה שוב?"
    _model(monkeypatch, reply)
    assert await pipeline._say("failure_stuck", fallback=("נתקע, ננסה שוב?",)) == reply


# ── הוולידטור מפיל → fallback מהמאגר ──


async def test_foreign_emoji_falls_back(monkeypatch):
    _model(monkeypatch, "אני על זה 😊")
    assert await pipeline._say("heartbeat") in pipeline.HEARTBEAT_MSGS


async def test_done_claim_in_heartbeat_falls_back(monkeypatch):
    _model(monkeypatch, "סגרתי לך הכל 🤙")
    assert await pipeline._say("heartbeat") in pipeline.HEARTBEAT_MSGS


async def test_instant_promise_falls_back(monkeypatch):
    _model(monkeypatch, "שנייה ואני חוזר אליך")
    assert await pipeline._say("heartbeat") in pipeline.HEARTBEAT_MSGS


async def test_too_long_falls_back(monkeypatch):
    _model(monkeypatch, "בלה " * 100)
    assert await pipeline._say("heartbeat") in pipeline.HEARTBEAT_MSGS


async def test_missing_anchor_falls_back(monkeypatch):
    """nudge_question בלי המילה 'תשובה' — העוגן שהטסטים נועלים — נפסל."""
    _model(monkeypatch, "עוד פה, מחכה לך 🤙")
    assert await pipeline._say("nudge_question") in pipeline.NUDGE_MSGS["question"]


async def test_missing_ctx_link_falls_back(monkeypatch):
    """קיר-כרטיס בלי הלינק עצמו בהודעה — חסר העוגן הקריטי → מאגר."""
    ctx = {"link": "https://geverai.duckdns.org/b/abc"}
    safe = ("ההזמנה מחכה לך כאן: https://geverai.duckdns.org/b/abc",)
    _model(monkeypatch, "סידרתי הכל, נשאר רק התשלום 🤝")
    assert (await pipeline._say("card_wall", ctx, fallback=safe)) == safe[0]


async def test_ctx_link_present_passes(monkeypatch):
    reply = "נשאר רק התשלום — כאן: https://geverai.duckdns.org/b/abc"
    _model(monkeypatch, reply)
    ctx = {"link": "https://geverai.duckdns.org/b/abc"}
    assert (await pipeline._say("card_wall", ctx, fallback=("x",))) == reply


# ── כשל טכני → fallback ──


async def test_timeout_falls_back(monkeypatch):
    _model(monkeypatch, "עוד רגע איתך 🔄", delay=0.5)
    monkeypatch.setattr(pipeline, "SAY_TIMEOUT_S", 0.02)
    assert await pipeline._say("heartbeat") in pipeline.HEARTBEAT_MSGS


async def test_model_error_falls_back(monkeypatch):
    _model(monkeypatch, "", error=RuntimeError("quota"))
    assert await pipeline._say("heartbeat") in pipeline.HEARTBEAT_MSGS


async def test_no_fallback_anywhere_raises(monkeypatch):
    """כוונה בלי מאגר במפה ובלי fallback מהאתר — שגיאת תכנות, מתפוצץ לפני המודל."""
    calls = _model(monkeypatch, "היי")
    with pytest.raises(ValueError):
        await pipeline._say("ack_start")
    assert calls == []  # נעצרנו לפני קריאת מודל


# ── pre-generate ──


async def test_presay_cancelled_timer_sends_nothing(monkeypatch):
    """הטיימר בוטל (הלקוח ענה) → החילול מבוטל ושום דבר לא נשלח."""
    _model(monkeypatch, "עוד רגע איתך 🔄", delay=0.2)
    sent = []
    task = pipeline._presay("heartbeat")

    async def timer():
        sent.append(await task)

    t = asyncio.create_task(timer())
    await asyncio.sleep(0.01)
    t.cancel()
    task.cancel()
    await asyncio.sleep(0.05)
    assert sent == []
    assert task.cancelled()


async def test_presay_sends_when_timer_fires(monkeypatch):
    """הטיימר פקע → ההודעה שחוללה מראש נמסרת מיד."""
    _model(monkeypatch, "עדיין פה, האתר זז לאט 🔄")
    task = pipeline._presay("heartbeat")
    await asyncio.sleep(0.01)  # "הטיימר"
    assert await task == "עדיין פה, האתר זז לאט 🔄"


# ── המיקרו-פרומפט וה-INTENTS עצמם ──


def test_say_prompt_carries_core_gender_goal_and_ctx():
    system, user = pipeline._say_prompt("ask_missing", {"field": "שם משפחה", "gender": "female"})
    assert pipeline.INTENTS["ask_missing"]["goal"] in user
    assert "שם משפחה" in user  # ההקשר וגם עוגן must_ctx נכנסו לפרומפט
    assert "לשון נקבה" in system  # gender_line הוזרקה ל-system
    assert system.startswith(pipeline.VOICE_CORE)  # ליבת הדמות, לא ה-SYSTEM_PROMPT המלא


def test_intents_wellformed_and_pools_pass_their_own_rules():
    """המפה תקינה: goal מלא, regex-ים מתקמפלים, וכל מאגר fallback סטטי עובר את
    חוקי הכוונה של עצמו — המאגרים הם רשת הביטחון, אסור שהוולידטור יפסול אותם."""
    for intent, card in pipeline.INTENTS.items():
        assert card["goal"].strip(), intent
        for pat in (*card.get("forbid", ()), *card.get("must", ())):
            re.compile(pat)
        pool = card.get("fallback")
        if pool is None:
            continue
        assert len(pool) >= 2, intent
        for variant in pool:
            assert pipeline._say_violations(intent, {}, variant) == [], (intent, variant)


def test_intents_cover_all_static_pools():
    """כל מאגר סטטי ב-pipeline ממופה לכוונה — שלא יישאר מאגר יתום מחוץ למפה."""
    mapped = [c["fallback"] for c in pipeline.INTENTS.values() if c.get("fallback") is not None]
    for pool in (
        pipeline.HEARTBEAT_MSGS,
        *pipeline.NUDGE_MSGS.values(),
        pipeline.CARD_RELEASE_MSGS,
        *pipeline.SENSITIVE_MSGS.values(),
        pipeline.RESUME_ACK_MSGS,
    ):
        assert any(pool is m for m in mapped)


# ── ההסבה: כל כוונה מחווטת לאתר הקריאה שלה ──


def test_every_intent_wired_to_its_call_site():
    """כל כוונה במפה מחווטת לאתר קריאה חי (שם הכוונה מופיע גם מחוץ להגדרתה —
    ב-_say/_presay או במיפוי kind→intent של _arm_nudge). שלוש הכוונות העשירות
    (pending_confirm / card_wall / booked_confirmed) נשארו קשיחות בכוונה —
    הרכבת f-string רב-חלקים — והטסט נועל את הרשימה הזאת, כך שכוונה חדשה לא
    תישאר יתומה בשקט וכוונה 'קשיחה' לא תוסב בלי לעדכן את ההחלטה כאן."""
    src = inspect.getsource(pipeline)
    left_hard = {"pending_confirm", "card_wall", "booked_confirmed"}
    for intent in pipeline.INTENTS:
        occurrences = src.count(f'"{intent}"')
        if intent in left_hard:
            assert occurrences == 1, f"{intent}: אמור להישאר קשיח (רק ההגדרה במפה)"
        else:
            assert occurrences >= 2, f"{intent}: אין אתר קריאה — הכוונה יתומה"


async def test_nudge_timer_delivers_pregenerated_model_text(monkeypatch):
    """ההסבה חיה מקצה לקצה: טיימר הנדנוד שולח את הטקסט שחולל מראש מהמודל
    (pre-generate בזמן ההמתנה) — לא מהמאגר; והמאגר נשאר רשת ביטחון בלבד."""
    _model(monkeypatch, "עוד פה, מחכה רק לתשובה שלך ואז ממשיך 🤙")
    sent = []

    async def fake_send(phone, text):
        sent.append(text)

    monkeypatch.setattr(pipeline, "_send_and_record", fake_send)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 0.02)
    pipeline._nudge.clear()
    pipeline._arm_nudge("pSAY", "question", ctx={"field": "מייל"})
    await asyncio.sleep(0.1)
    assert sent == ["עוד פה, מחכה רק לתשובה שלך ואז ממשיך 🤙"]
    assert sent[0] not in pipeline.NUDGE_MSGS["question"]  # באמת מהמודל, לא מהמאגר
