from pydantic_settings import BaseSettings


class Settings(BaseSettings):
# Proxy
    PROXY_SET: int = 0
    PROXY_TYPE: str = "http"
    PROXY_HOST: str = "5.129.236.15"
    PROXY_PORT: str = "3128"
    PROXY_USERNAME: str = "myuser"
    PROXY_PASSWORD: str

    # Telegram API credentials
    API_ID: int
    API_HASH: str
    STRING_SESSION: str

    # Database settings
    # Для Bothost.ru используйте /app/data/messages.db
    DATABASE_PATH: str = "postgresql://user:12345@db:5432/dixy"
    CHAT_ENTITIES: str = ""

    SCHEDULER_ON: int = 0
    SCHEDULER_PERIOD_MINUTES: int = 1
    DAYS_BACK: int = 1

    # Logging settings
    LOG_LEVEL: str = 'INFO'
    # Для Bothost.ru используйте /app/data/userbot.log
    LOG_FILE: str = "userbot.log"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
