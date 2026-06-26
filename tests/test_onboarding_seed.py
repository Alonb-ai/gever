"""בדיקת ה-seed שנבנה לפי היכרות עם המשתמש: פרופיל ריק (חדש) מקבל בלוק ONBOARDING;
פרופיל עם מייל (מוכר) מקבל את _profile_block + רמז ההיכרות, בלי בלוק ה-onboarding.
בודק את _seed_from ישירות, בלי Gemini חי."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.intent import KNOWN_HINT, ONBOARDING_BLOCK  # noqa: E402
from app.pipeline import _seed_from  # noqa: E402


def test_new_user_gets_onboarding_block():
    seed = _seed_from(None, [])
    assert ONBOARDING_BLOCK in seed
    assert KNOWN_HINT not in seed


def test_known_user_gets_profile_and_recall_not_onboarding():
    profile = {"name": "אלון", "email": "alon@example.com"}
    seed = _seed_from(profile, [])
    assert ONBOARDING_BLOCK not in seed
    assert KNOWN_HINT in seed
    assert "alon@example.com" in seed  # _profile_block הוזרק
