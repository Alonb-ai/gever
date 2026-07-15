"""heartbeat בזמן ריצה: אחרי ~75 שנ' שקט — סימן חיים, מקס' 2; שקט קצר — כלום."""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.llm.intent import character_leaks  # noqa: E402


def _run_heartbeat(monkeypatch, last_out_age: float):
    pipeline._last_out.clear()
    pipeline._last_out["p1"] = time.time() - last_out_age
    sent, sleeps = [], []

    async def fake_send(phone, text):
        sent.append(text)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(pipeline, "_send_and_record", fake_send)
    monkeypatch.setattr(pipeline.asyncio, "sleep", fake_sleep)
    asyncio.run(pipeline._heartbeat("p1"))
    return sent, sleeps


def test_heartbeat_sends_on_long_silence(monkeypatch):
    """שקט ארוך מ-75 שנ' → עדכון; הלולאה מוגבלת לשניים ונגמרת לבד."""
    sent, sleeps = _run_heartbeat(monkeypatch, last_out_age=200)
    assert len(sent) == 2  # ה-fake לא מאפס את השעון — שתי הפעימות נשלחו, ולא יותר
    assert sleeps == [pipeline.HEARTBEAT_S] * 2


def test_heartbeat_quiet_when_recently_spoke(monkeypatch):
    """הודעה יצאה הרגע (ack/רשימה) → אין פעימה, לא מספימים."""
    sent, _ = _run_heartbeat(monkeypatch, last_out_age=5)
    assert sent == []


def test_heartbeat_variants_pass_character_rules(monkeypatch):
    """כל וריאנט של הפעימה עומד בחוקי הדמות (אימוג'י מהפלטה, בלי חשיפה)."""
    captured = []

    def fake_vary(*variants):
        captured.extend(variants)
        return variants[0]

    monkeypatch.setattr(pipeline, "_vary", fake_vary)
    _run_heartbeat(monkeypatch, last_out_age=200)
    assert captured and all(not character_leaks(v) for v in captured)
