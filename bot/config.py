from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str
    REDIS_URL: str
    OPENROUTER_API_KEY: str
    S3_ENDPOINT_URL: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET_NAME: str
    YOOKASSA_ACCOUNT_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra='ignore')

settings = Settings()
