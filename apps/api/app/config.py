from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-change-me-dev-only-secret"


class Settings(BaseSettings):
    # Defaults match docker-compose.yml so tests and dev work out of the box.
    database_url: str = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/comm_center"
    # Signs access and refresh tokens. The default is for development only: set a long random
    # value (for example `openssl rand -hex 32`) anywhere else.
    jwt_secret: str = DEV_JWT_SECRET
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 60 * 60
    # Region used to read phone numbers typed without a country code.
    default_phone_region: str = "PH"

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
