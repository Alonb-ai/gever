"""בדיקות ל-app.db.memory: GATING כבוי (no-op בלי Supabase) + Fernet round-trip."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import memory  # noqa: E402


def test_get_profile_disabled_returns_none():
    # בלי Supabase config — get_profile הוא no-op ומחזיר None בלי לזרוק.
    settings.supabase_url = ""
    settings.supabase_service_key = ""
    assert asyncio.run(memory.get_profile("+972500000000")) is None


def test_recent_bookings_disabled_returns_empty():
    # בלי Supabase config — recent_bookings מחזיר [] בלי לזרוק.
    settings.supabase_url = ""
    settings.supabase_service_key = ""
    assert asyncio.run(memory.recent_bookings("+972500000000")) == []


def test_fernet_roundtrip():
    # encrypt -> decrypt חוזר לערך המקורי עם מפתח שנוצר inline.
    settings.encryption_key = Fernet.generate_key().decode()
    plaintext = "אלון bazak@example.com"
    token = memory._encrypt(plaintext)
    assert token != plaintext
    assert memory._decrypt(token) == plaintext
