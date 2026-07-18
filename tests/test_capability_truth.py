"""אמת-יכולות (נצפה חי 18.7): גבר הציע ללקוח "אנסה לצלצל אליהם מחר" — יכולת
שאין לו (הוא סוגר דרך אתרים בלבד) — וכשנשאל הסגיר "פחות עובד לי מהמערכת".
התיקון: הדמות יודעת מה היא לא עושה (SYSTEM_PROMPT + VOICE_CORE), המשמר תופס
"מערכת" בהקשר עצמי, והודעת הכשל טלפון-בלבד נושאת את מספר המקום כשנמצא."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.llm.intent import SYSTEM_PROMPT, character_leaks  # noqa: E402


# --- אמת-יכולות בפרומפטים: גבר לא מתקשר, בשני הקולות (המלא והמיקרו) ---


def test_capability_truth_in_system_prompt():
    assert "לא מתקשר למקומות" in SYSTEM_PROMPT
    assert "נותנים ללקוח את המספר" in SYSTEM_PROMPT


def test_capability_truth_in_voice_core():
    assert "לא מתקשר" in pipeline.VOICE_CORE
    assert "הלקוח מתקשר בעצמו" in pipeline.VOICE_CORE


# --- המשמר: "מערכת" בהקשר עצמי נתפסת, מערכת של צד שלישי לא ---


def test_leak_catches_self_referential_system():
    assert character_leaks("פתאום קלטתי שטלפונים פחות עובד לי מהמערכת")
    assert character_leaks("המערכת שלי לא עושה טלפונים")
    assert character_leaks("זה לא עבר במערכת שלנו")


def test_leak_ignores_third_party_system():
    assert not character_leaks("מערכת ההזמנות של המסעדה לא מקבלת אונליין")
    assert not character_leaks("המערכת שלהם לא מקבלת הזמנות")
    assert not character_leaks("קיבלתי אישור מהמערכת של אונטופו")


# --- הודעת הכשל טלפון-בלבד: מספר המקום עובר ללקוח כשנמצא, ולא מומצא כשאין ---


def test_no_online_failure_carries_place_phone(monkeypatch):
    async def fake_hint(name, raw):
        assert name == "הדסון"
        return "03-5222922"

    monkeypatch.setattr(pipeline, "_resolve_phone_hint", fake_hint)
    hit = asyncio.run(pipeline._failure_reply("no_online_booking", "הדסון"))
    assert hit is not None
    assert hit[0] == "המקום לא מקבל הזמנות אונליין"
    assert "03-5222922" in hit[1]


def test_no_online_failure_without_phone_stays_clean(monkeypatch):
    async def fake_hint(name, raw):
        return None

    monkeypatch.setattr(pipeline, "_resolve_phone_hint", fake_hint)
    hit = asyncio.run(pipeline._failure_reply("no_online_booking", "הדסון"))
    assert hit is not None
    assert "הדסון" in hit[1]
    assert "המספר שלהם" not in hit[1]


def test_other_failures_skip_phone_lookup(monkeypatch):
    """שליפת הטלפון רצה רק על no_online_booking במסעדות — לא על שאר הכשלים."""
    calls = []

    async def fake_hint(name, raw):
        calls.append(name)
        return "03-5222922"

    monkeypatch.setattr(pipeline, "_resolve_phone_hint", fake_hint)
    asyncio.run(pipeline._failure_reply("no_availability", "הדסון"))
    asyncio.run(pipeline._failure_reply("no_online_booking", "סרט", task_type="events"))
    assert calls == []
