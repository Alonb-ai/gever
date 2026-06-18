"""הגדרות מרכזיות — נטענות מ-.env דרך pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Browserbase + Stagehand
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""
    model_api_key: str = ""
    model_name: str = "anthropic/claude-sonnet-4-6"

    # Gemini (שיחה)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # WhatsApp via Meta Cloud API
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "gever_verify_2026"  # אנחנו בוחרים; חייב להתאים לדאשבורד של Meta
    whatsapp_api_version: str = "v21.0"

    # ponytail: שדות שלב-2 (Supabase/Lemon Squeezy/encryption) הוסרו — אף מסלול לא קורא להם.
    # להחזיר כשהזרוע מתחילה (זרוע 4 — Supabase, זרוע 6 — Lemon Squeezy). extra="ignore" → .env לא נשבר.


settings = Settings()
