"""בדיקות ל-router switch ב-run_booking: task_type='other' → stub כן, בלי resolve/book.
task_type='restaurant'/חסר → המסלול הקיים (resolve נקרא)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    """לוכד הודעות שנשלחות, וקובע resolve/book לדגלים שמוודאים שלא נקראו."""
    sent: list[str] = []
    called = {"resolve": False, "book": False}

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        called["resolve"] = True
        return {"status": "none", "url": "", "candidates": []}

    async def fake_book(**kwargs):
        called["book"] = True
        raise AssertionError("book_table לא אמור להיקרא במסלול 'other'")

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_ontopo_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table", fake_book)
    pipeline._booking.clear()
    return sent, called


@pytest.mark.asyncio
async def test_other_sends_stub_no_resolve(_patch_io):
    sent, called = _patch_io
    await pipeline.run_booking("p1", {"task_type": "other"})
    assert called["resolve"] is False
    assert called["book"] is False
    assert sent and "עדיין" in sent[0]
    assert pipeline._booking["p1"]["state"] == "failed"


@pytest.mark.asyncio
async def test_restaurant_takes_today_path(_patch_io):
    sent, called = _patch_io
    await pipeline.run_booking("p2", {"task_type": "restaurant", "restaurant": "טאיזו"})
    assert called["resolve"] is True  # נכנס למסלול הקיים


@pytest.mark.asyncio
async def test_absent_task_type_defaults_to_restaurant(_patch_io):
    sent, called = _patch_io
    await pipeline.run_booking("p3", {"restaurant": "טאיזו"})
    assert called["resolve"] is True
