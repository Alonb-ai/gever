"""בידוד הטסטים מהעולם האמיתי: מאפסים את מפתחות Supabase/Browserbase לכל טסט.

נצפה חי (תחקיר 15.7): pytest שרץ מתיקייה עם .env אמיתי (worktree של ספייק) כתב
משתמשי פיקסצ'רה ('p1', 'c9') לטבלת users של הפרודקשן. הטסטים חייבים להיות
דטרמיניסטיים ואפס-רשת בכל סביבת הרצה — לא רק כשבמקרה אין .env.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _no_real_backends(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_key", "")
    monkeypatch.setattr(settings, "browserbase_api_key", "")
