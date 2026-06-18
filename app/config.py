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
    whatsapp_app_secret: str = ""  # אימות חתימת webhook (X-Hub-Signature-256). ריק → דילוג (dev)

    # Supabase — זיכרון בין שיחות (זרוע 4). ריק → memory layer הוא no-op מלא.
    supabase_url: str = ""
    supabase_service_key: str = ""
    encryption_key: str = ""  # Fernet — הצפנת name/email at-rest

    # ponytail: שדות Lemon Squeezy (זרוע 6) עדיין מוסרים — אף מסלול לא קורא להם.


settings = Settings()
