from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Defaults match docker-compose.yml so tests and dev work out of the box.
    database_url: str = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/comm_center"

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
