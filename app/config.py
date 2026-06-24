"""הגדרות מרכזיות — נטענות מ-.env דרך pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Browserbase — תשתית דפדפן (stealth/captcha/proxy) למצב bu_browser=browserbase
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""
    model_api_key: str = ""
    model_name: str = "google/gemini-3-flash-preview"  # ה-driver של ה-agent (browser-use)

    # browser-use — שכבת הניווט האוטונומית, רצה ב-venv נפרד כ-subprocess
    # (browser-use מצמיד google-genai==1.65, מתנגש עם ה-app על 2.8 → בידוד).
    bu_venv_path: str = ".venv-bu/bin/python"
    bu_browser: str = "local"  # local (Chrome מקומי, חינם) | browserbase (stealth/captcha)
    bu_headless: bool = True
    bu_chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    bu_record_dir: str = "bu_recordings"  # וידאו+GIF+הנמקת-agent לכל ריצה

    # Gemini (שיחה)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

    # WhatsApp via Meta Cloud API
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "gever_verify_2026"  # אנחנו בוחרים; חייב להתאים לדאשבורד של Meta
    whatsapp_api_version: str = "v21.0"
    whatsapp_app_secret: str = ""  # אימות חתימת webhook (X-Hub-Signature-256). ריק → דילוג (dev)

    # Supabase — זיכרון בין שיחות (זרוע 4). ריק → memory layer הוא no-op מלא.
    supabase_url: str = ""
    supabase_service_key: str = ""
    encryption_key: str = ""  # Fernet — הצפנת name/email at-rest

    # שגיאות: True (dev/MVP) → הודעת כשל ב-WhatsApp כוללת פירוט השגיאה + session.
    # False (פרודקשן) → הודעה בדמות בלבד, בלי לדלוף טכני ללקוח אמיתי.
    debug_errors: bool = True

    # הזמנה אמיתית כבויה כברירת מחדל: "מאשר" מגיע למסך האישור ועוצר (לא סוגר בפועל).
    # ponytail: דגל יחיד; הופכים ל-False ב-.env/Coolify רק להזמנה אמיתית, עם פיקוח.
    dry_run: bool = True

    # ponytail: שדות Lemon Squeezy (זרוע 6) עדיין מוסרים — אף מסלול לא קורא להם.


settings = Settings()
