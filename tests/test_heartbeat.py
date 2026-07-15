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


def test_heartbeat_sends_two_different_messages(monkeypatch):
    """שקט ארוך → שתי פעימות, ותמיד *שונות* זו מזו (משוב אלון 15.7: אותה הודעה
    פעמיים ברצף מרגישה בוט)."""
    sent, sleeps = _run_heartbeat(monkeypatch, last_out_age=200)
    assert len(sent) == 2  # ה-fake לא מאפס את השעון — שתי הפעימות נשלחו, ולא יותר
    assert sent[0] != sent[1]
    assert sleeps == [pipeline.HEARTBEAT_S] * 2


def test_heartbeat_quiet_when_recently_spoke(monkeypatch):
    """הודעה יצאה הרגע (ack/רשימה) → אין פעימה, לא מספימים."""
    sent, _ = _run_heartbeat(monkeypatch, last_out_age=5)
    assert sent == []


def test_heartbeat_repertoire_passes_character_rules():
    """כל הרפרטואר עומד בחוקי הדמות (אימוג'י מהפלטה, בלי חשיפה), ורחב מספיק."""
    assert len(pipeline.HEARTBEAT_MSGS) >= 5
    assert all(not character_leaks(m) for m in pipeline.HEARTBEAT_MSGS)
    assert len(set(pipeline.HEARTBEAT_MSGS)) == len(pipeline.HEARTBEAT_MSGS)
