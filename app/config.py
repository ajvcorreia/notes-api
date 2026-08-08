from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    joplin_base_url: str = "http://joplin:22300"
    joplin_email: str
    joplin_password: str

    # Clients call this API with `X-API-Key: <api_key>`.
    api_key: str

    # SQLite file backing the /stats usage dashboard. Mount a volume over its
    # parent directory to keep usage history across container restarts.
    stats_db_path: str = "data/stats.db"


settings = Settings()
