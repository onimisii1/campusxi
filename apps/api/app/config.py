from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/campusxi"
    # Supabase Auth. Tokens are verified against the project's JWKS; set
    # supabase_jwt_secret only for projects still on the legacy HS256 secret (and tests).
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    jwt_audience: str = "authenticated"
    # Paid contests and stakes need the fantasy licence, school approval and payments (Phase 5).
    paid_play_enabled: bool = False
    # Match-result bets are sports betting: off until a sports-betting licence is held.
    result_bets_enabled: bool = False
    # Every match gets one free contest automatically when fixtures are imported.
    default_free_contest_capacity: int = 1000
    # Browser origins allowed to call the API (comma-separated in the environment).
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5180"]


settings = Settings()
