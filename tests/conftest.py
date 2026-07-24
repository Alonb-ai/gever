"""בידוד הטסטים מהעולם האמיתי: מאפסים את מפתחות Supabase/Browserbase לכל טסט.

נצפה חי (תחקיר 15.7): pytest שרץ מתיקייה עם .env אמיתי (worktree של ספייק) כתב
משתמשי פיקסצ'רה ('p1', 'c9') לטבלת users של הפרודקשן. הטסטים חייבים להיות
דטרמיניסטיים ואפס-רשת בכל סביבת הרצה — לא רק כשבמקרה אין .env.
"""

import pytest

from app import pipeline
from app.automation import shows_catalog
from app.config import settings


@pytest.fixture(autouse=True)
def _no_real_backends(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_key", "")
    monkeypatch.setattr(settings, "browserbase_api_key", "")
    # בלי Brave אמיתי: חיפוש-הטלפון של הודעת הכשל (phone_hint) לא יוצא לרשת בטסטים
    monkeypatch.setattr(settings, "brave_api_key", "")
    # קטלוג ההופעות לא יוצא לרשת: אפס מקורות + cache נקי פר-טסט (fetch_upcoming → [])
    monkeypatch.setattr(shows_catalog, "_SOURCES", ())
    monkeypatch.setattr(shows_catalog, "_cache", {"ts": 0.0, "items": []})


@pytest.fixture(autouse=True)
def _fresh_conversation_state():
    """מצב per-phone שנצבר לאורך שיחה (רשימת הנפסלים, מנעול ההמלצות) מתאפס בין
    טסטים — ריצת run_booking כושלת בקובץ אחד לא תסנן המלצות בקובץ אחר."""
    pipeline._rejected.clear()
    pipeline._rec_inflight.clear()
    yield


@pytest.fixture(autouse=True)
def _say_offline(monkeypatch):
    """הקול החופשי לא מחולל בטסטים: _say_model נכשל מיד וכל _say נופל דטרמיניסטית
    (ובאפס לטנציה/רשת) למאגר ה-fallback — כך כל הטסטים הקיימים נועלים את מסלול
    המאגרים, רשת הביטחון שלעולם לא נמחקת. טסטים שבודקים את מסלול המודל עצמו
    (test_say) דורסים את המוק הזה מקומית."""

    async def _fail(intent, ctx):
        raise RuntimeError("say offline in tests")

    monkeypatch.setattr(pipeline, "_say_model", _fail)
