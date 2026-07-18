"""סטיקרים יוצאים: בניית בקשות ל-Graph API (שליחה/העלאה/הורדת מדיה), cache של
media_id עם רענון עצלן, וסטיקר החגיגה — נורה רק אחרי סגירה אמיתית ולכל היותר
פעם ביום ללקוח."""

import asyncio
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402
from app.whatsapp import client  # noqa: E402


class _Resp:
    def __init__(self, data=None, content=b""):
        self._data = data or {}
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeHttp:
    """מחליף את httpx.AsyncClient — רושם קריאות ומחזיר תשובות Graph API קבועות."""

    posts: list = []
    gets: list = []

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FakeHttp.posts.append((url, kw))
        if url.endswith("/media"):
            return _Resp({"id": "MEDIA_ID_1"})
        return _Resp({"messages": [{"id": "wamid.OUT"}]})

    async def get(self, url, **kw):
        _FakeHttp.gets.append((url, kw))
        if "graph.facebook.com" in url:
            return _Resp({"url": "https://lookaside.example/blob", "mime_type": "audio/ogg"})
        return _Resp(content=b"OGGDATA")


def _fake_http(monkeypatch):
    _FakeHttp.posts, _FakeHttp.gets = [], []
    monkeypatch.setattr(client, "httpx", SimpleNamespace(AsyncClient=_FakeHttp))
    client._media_cache.clear()


def test_send_sticker_builds_correct_payload(monkeypatch):
    _fake_http(monkeypatch)
    asyncio.run(client.send_sticker("972", "MID7"))
    url, kw = _FakeHttp.posts[-1]
    assert url.endswith("/messages")
    assert kw["json"] == {
        "messaging_product": "whatsapp",
        "to": "972",
        "type": "sticker",
        "sticker": {"id": "MID7"},
    }


def test_send_sticker_file_uploads_once_and_caches(monkeypatch, tmp_path):
    """שתי שליחות מאותו קובץ → העלאה אחת (cache) ושתי הודעות סטיקר."""
    _fake_http(monkeypatch)
    p = tmp_path / "s.webp"
    p.write_bytes(b"WEBPDATA")

    asyncio.run(client.send_sticker_file("972", str(p)))
    asyncio.run(client.send_sticker_file("972", str(p)))

    uploads = [c for c in _FakeHttp.posts if c[0].endswith("/media")]
    sends = [c for c in _FakeHttp.posts if c[0].endswith("/messages")]
    assert len(uploads) == 1 and len(sends) == 2
    assert uploads[0][1]["data"] == {"messaging_product": "whatsapp", "type": "image/webp"}
    assert sends[0][1]["json"]["sticker"] == {"id": "MEDIA_ID_1"}


def test_stale_media_id_reuploaded(monkeypatch, tmp_path):
    """media_id של Meta פג אחרי 30 יום — cache ישן מה-TTL מרענן בהעלאה חדשה."""
    _fake_http(monkeypatch)
    p = tmp_path / "s.webp"
    p.write_bytes(b"WEBPDATA")
    client._media_cache[str(p)] = ("OLD_ID", time.time() - client.MEDIA_TTL_S - 1)

    asyncio.run(client.send_sticker_file("972", str(p)))
    uploads = [c for c in _FakeHttp.posts if c[0].endswith("/media")]
    assert len(uploads) == 1  # הועלה מחדש
    assert client._media_cache[str(p)][0] == "MEDIA_ID_1"


def test_download_media_two_hops_with_bearer(monkeypatch):
    """הורדת מדיה: GET /{media-id} → url זמני → הורדה, שתיהן עם Bearer."""
    _fake_http(monkeypatch)
    data, mime = asyncio.run(client.download_media("m55"))
    assert data == b"OGGDATA" and mime == "audio/ogg"
    assert "m55" in _FakeHttp.gets[0][0]
    for _url, kw in _FakeHttp.gets:
        assert kw["headers"]["Authorization"].startswith("Bearer ")


def _celebrate_fresh(monkeypatch):
    pipeline._last_sticker.clear()
    stickers = []

    async def fake_sticker(phone, path):
        stickers.append((phone, path))

    monkeypatch.setattr(pipeline, "send_sticker_file", fake_sticker)
    return stickers


def test_celebrate_at_most_once_a_day(monkeypatch):
    """סטיקר חגיגה — אחד ביום לכל לקוח; לקוח אחר לא נחסם."""
    stickers = _celebrate_fresh(monkeypatch)
    asyncio.run(pipeline._maybe_celebrate("p1"))
    asyncio.run(pipeline._maybe_celebrate("p1"))
    asyncio.run(pipeline._maybe_celebrate("p2"))
    assert [s[0] for s in stickers] == ["p1", "p2"]
    # אתמול נשלח → היום מותר שוב
    pipeline._last_sticker["p1"] = time.time() - pipeline.STICKER_GAP_S - 1
    asyncio.run(pipeline._maybe_celebrate("p1"))
    assert [s[0] for s in stickers] == ["p1", "p2", "p1"]


def test_celebrate_failure_is_swallowed(monkeypatch):
    """כשל בשליחת הסטיקר לא מפוצץ את זרימת האישור."""
    pipeline._last_sticker.clear()

    async def boom(phone, path):
        raise RuntimeError("meta down")

    monkeypatch.setattr(pipeline, "send_sticker_file", boom)
    asyncio.run(pipeline._maybe_celebrate("p1"))  # לא זורק


def test_celebration_assets_exist():
    """קבצי הסטיקרים של החגיגה קיימים בריפו ובגודל חוקי לסטיקר סטטי (≤100KB)."""
    for name in pipeline.CELEBRATION_STICKERS:
        p = pipeline.STICKER_DIR / name
        assert p.is_file(), f"חסר {p}"
        assert p.stat().st_size <= 100 * 1024


def test_run_commit_success_fires_sticker_once(monkeypatch):
    """הסגירה האמיתית שולחת סטיקר חגיגה — פעם אחת, ורק על הצלחה."""
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._last_out.clear()
    pipeline._last_sticker.clear()
    sent, stickers = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_sticker(phone, path):
        stickers.append(path)

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="ok",
            details={"confirmation": "C1", "restaurant": "הדסון", "time": "20:00"},
        )

    async def fake_log(*a, **kw):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_sticker_file", fake_sticker)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    job = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    pipeline._pending_commit["p1"] = dict(job)
    asyncio.run(pipeline.run_commit("p1"))
    assert len(stickers) == 1
    assert stickers[0].endswith(tuple(pipeline.CELEBRATION_STICKERS))

    # סגירה שנייה באותו יום — בלי סטיקר נוסף (אין ספאם)
    pipeline._pending_commit["p1"] = dict(job)
    asyncio.run(pipeline.run_commit("p1"))
    assert len(stickers) == 1


def test_run_commit_failure_sends_no_sticker(monkeypatch):
    """כישלון סגירה = אין מה לחגוג — שום סטיקר."""
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._last_out.clear()
    pipeline._last_sticker.clear()
    stickers = []

    async def fake_send_text(phone, msg):
        pass

    async def fake_sticker(phone, path):
        stickers.append(path)

    async def fake_book(**kwargs):
        return ActionResult(success=False, summary="נכשל", details={"failed": "no_slot"})

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_sticker_file", fake_sticker)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)

    pipeline._pending_commit["p9"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("p9"))
    assert stickers == []
