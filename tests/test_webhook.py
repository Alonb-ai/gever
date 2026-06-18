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
