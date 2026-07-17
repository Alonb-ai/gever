"""בדיקת אימות חתימת webhook (X-Hub-Signature-256) — נתיב אבטחה."""

import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import main  # noqa: E402
from app.config import settings  # noqa: E402

BODY = b'{"entry":[]}'


def _sig(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_no_secret_skips():
    settings.whatsapp_app_secret = ""
    assert main._valid_signature(BODY, None) is True


def test_correct_signature():
    settings.whatsapp_app_secret = "s3cr3t"
    assert main._valid_signature(BODY, _sig(b"s3cr3t", BODY)) is True


def test_wrong_or_missing_signature():
    settings.whatsapp_app_secret = "s3cr3t"
    assert main._valid_signature(BODY, "sha256=deadbeef") is False
    assert main._valid_signature(BODY, None) is False


if __name__ == "__main__":
    test_no_secret_skips()
    test_correct_signature()
    test_wrong_or_missing_signature()
    settings.whatsapp_app_secret = ""
    print("ok")


def test_duplicate_message_id_handled_once():
    """Meta retry/כפילות: אותו msg id פעמיים → עיבוד אחד (נצפה חי 15.7: תשובת
    סיום כפולה כי ה-200 חיכה לכל העיבוד ומטא שלחה שוב)."""
    import asyncio

    from app import pipeline

    main._seen_msg_ids.clear()
    calls = []

    async def fake_inbound(phone, text, msg_id=None):
        calls.append(text)

    orig = main.handle_inbound
    main.handle_inbound = fake_inbound
    try:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "type": "text",
                                        "id": "wamid.X1",
                                        "from": "972",
                                        "text": {"body": "היי"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        asyncio.run(main._process_webhook(payload))
        asyncio.run(main._process_webhook(payload))  # ה-retry של מטא
    finally:
        main.handle_inbound = orig
    assert calls == ["היי"]
    assert pipeline is not None


def test_stale_replayed_message_skipped():
    """שידור חוזר אחרי deploy: ה-dedupe בזיכרון מת עם הקונטיינר ומטא משדרת
    הודעות ישנות — הודעה עם timestamp בן שעה נזרקת, טרייה מטופלת, וחסרת
    timestamp מטופלת (עדיף לטפל מלהשתיק). נצפה חי 17.7 ("עוד פעם קלארו אחי?")."""
    import asyncio
    import time as _t

    main._seen_msg_ids.clear()
    calls = []

    async def fake_inbound(phone, text, msg_id=None):
        calls.append(text)

    def msg(i, body, ts):
        m = {"type": "text", "id": i, "from": "972", "text": {"body": body}}
        if ts is not None:
            m["timestamp"] = str(int(ts))
        return m

    orig = main.handle_inbound
    main.handle_inbound = fake_inbound
    try:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    msg("wamid.S1", "ישנה", _t.time() - 3600),
                                    msg("wamid.S2", "טרייה", _t.time() - 5),
                                    msg("wamid.S3", "בלי-זמן", None),
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        asyncio.run(main._process_webhook(payload))
    finally:
        main.handle_inbound = orig
    assert calls == ["טרייה", "בלי-זמן"]
