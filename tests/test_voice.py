"""הודעות קוליות נכנסות: webhook אודיו → הורדה → תמלול → handle_inbound (אותו
מסלול כמו טקסט); כשל תמלול → כנות בדמות; הקלטה ארוכה → בקשת קיצור; זר בשער
הגישה לא שורף תמלול."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import main, pipeline  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm.transcribe import MAX_VOICE_BYTES  # noqa: E402


def _fresh(monkeypatch):
    """מוקים לכל שרשרת הקול; מחזיר (sent, inbound, transcribed) לרישום קריאות."""
    sent, inbound, transcribed = [], [], []

    async def fake_send(phone, text):
        sent.append(text)

    async def fake_inbound(phone, text, message_id=None):
        inbound.append((phone, text, message_id))

    async def fake_typing(message_id):
        pass

    monkeypatch.setattr(pipeline, "_send_and_record", fake_send)
    monkeypatch.setattr(pipeline, "handle_inbound", fake_inbound)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    return sent, inbound, transcribed


def test_voice_transcribed_flows_into_handle_inbound(monkeypatch):
    """המסלול המאושר: הורדה → תמלול → הטקסט נכנס ל-handle_inbound כאילו הוקלד."""
    sent, inbound, _ = _fresh(monkeypatch)

    async def fake_download(media_id):
        assert media_id == "m1"
        return b"\x00" * 1000, "audio/ogg; codecs=opus"

    async def fake_transcribe(audio, mime):
        assert mime == "audio/ogg; codecs=opus"
        return "שולחן לשניים בהדסון מחר ב20:00"

    monkeypatch.setattr(pipeline, "download_media", fake_download)
    monkeypatch.setattr(pipeline, "transcribe_voice", fake_transcribe)

    asyncio.run(pipeline.handle_voice("972", "m1", "wamid.V1"))
    assert inbound == [("972", "שולחן לשניים בהדסון מחר ב20:00", "wamid.V1")]
    assert sent == []  # אין הודעת ביניים — התשובה תגיע מהמסלול הרגיל


def test_transcription_failure_is_honest(monkeypatch):
    """תמלול נפל (רשת/מודל) → הודעת כנות מהמאגר, בלי להמשיך למסלול הטקסט."""
    sent, inbound, _ = _fresh(monkeypatch)

    async def fake_download(media_id):
        return b"\x00" * 1000, "audio/ogg"

    async def fake_transcribe(audio, mime):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(pipeline, "download_media", fake_download)
    monkeypatch.setattr(pipeline, "transcribe_voice", fake_transcribe)

    asyncio.run(pipeline.handle_voice("972", "m1"))
    assert inbound == []
    assert sent and sent[0] in pipeline.VOICE_FAILED_MSGS


def test_empty_transcript_is_honest(monkeypatch):
    """אין דיבור ברור (תמלול ריק) → אותה כנות כמו כשל."""
    sent, inbound, _ = _fresh(monkeypatch)

    async def fake_download(media_id):
        return b"\x00" * 1000, "audio/ogg"

    async def fake_transcribe(audio, mime):
        return ""

    monkeypatch.setattr(pipeline, "download_media", fake_download)
    monkeypatch.setattr(pipeline, "transcribe_voice", fake_transcribe)

    asyncio.run(pipeline.handle_voice("972", "m1"))
    assert inbound == []
    assert sent and sent[0] in pipeline.VOICE_FAILED_MSGS


def test_long_audio_asks_to_shorten_without_transcribing(monkeypatch):
    """מעל MAX_VOICE_BYTES → בקשת קיצור עדינה, ובלי לשרוף תמלול (הגנת עלות)."""
    sent, inbound, transcribed = _fresh(monkeypatch)

    async def fake_download(media_id):
        return b"\x00" * (MAX_VOICE_BYTES + 1), "audio/ogg"

    async def fake_transcribe(audio, mime):
        transcribed.append(1)
        return "לא אמור לקרות"

    monkeypatch.setattr(pipeline, "download_media", fake_download)
    monkeypatch.setattr(pipeline, "transcribe_voice", fake_transcribe)

    asyncio.run(pipeline.handle_voice("972", "m1"))
    assert transcribed == [] and inbound == []
    assert sent and sent[0] in pipeline.VOICE_TOO_LONG_MSGS


def test_download_failure_is_honest(monkeypatch):
    """גם כשל בהורדת המדיה עצמה נופל לאותה הודעת כנות."""
    sent, inbound, _ = _fresh(monkeypatch)

    async def fake_download(media_id):
        raise RuntimeError("media url expired")

    monkeypatch.setattr(pipeline, "download_media", fake_download)

    asyncio.run(pipeline.handle_voice("972", "m1"))
    assert inbound == []
    assert sent and sent[0] in pipeline.VOICE_FAILED_MSGS


def test_stranger_voice_hits_gate_without_transcription(monkeypatch):
    """שער גישה דלוק וזר שולח קולית → תשובת-שער בלבד, בלי הורדה ובלי תמלול."""
    sent, inbound, _ = _fresh(monkeypatch)
    gate_replies, downloads = [], []

    async def fake_send_text(phone, text):
        gate_replies.append(text)

    async def fake_download(media_id):
        downloads.append(media_id)
        return b"", "audio/ogg"

    monkeypatch.setattr(settings, "access_gate", True)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "download_media", fake_download)
    pipeline._gate_last_reply.clear()

    asyncio.run(pipeline.handle_voice("stranger", "m1"))
    assert downloads == [] and inbound == [] and sent == []
    assert gate_replies and "קוד" in gate_replies[0]


def test_webhook_audio_routes_to_handle_voice(monkeypatch):
    """webhook עם type=audio → handle_voice עם ה-media_id; בלי id — מדלגים בשקט."""
    main._seen_msg_ids.clear()
    calls = []

    async def fake_voice(phone, media_id, message_id=None):
        calls.append((phone, media_id, message_id))

    monkeypatch.setattr(main, "handle_voice", fake_voice)
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "audio",
                                    "id": "wamid.A1",
                                    "from": "972",
                                    "audio": {
                                        "id": "media9",
                                        "mime_type": "audio/ogg; codecs=opus",
                                        "voice": True,
                                    },
                                },
                                {"type": "audio", "id": "wamid.A2", "from": "972", "audio": {}},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    asyncio.run(main._process_webhook(payload))
    assert calls == [("972", "media9", "wamid.A1")]
