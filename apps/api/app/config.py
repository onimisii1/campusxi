from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/campusxi"
    # Supabase Auth. Tokens are verified against the project's JWKS; set
    # supabase_jwt_secret only for projects still on the legacy HS256 secret (and tests).
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    jwt_audience: str = "authenticated"
    # Match-result bets are sports betting: off until a sports-betting licence is held.
    result_bets_enabled: bool = False
    # Browser origins allowed to call the API (comma-separated in the environment).
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5180"]


settings = Settings()
