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

    # WhatsApp via Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # אבטחה ותשלומים (Lemon Squeezy)
    encryption_key: str = ""
    lemonsqueezy_api_key: str = ""
    lemonsqueezy_store_id: str = ""
    lemonsqueezy_webhook_secret: str = ""


settings = Settings()
