"""Application configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Default is local SQLite relative to the CWD. The packaged sidecar
    # (backend/desktop_run.py) overrides DATABASE_URL at startup from the
    # persisted settings (remoto mode → Postgres URL) BEFORE the engine is
    # created, so this default only applies to bare `python run.py` / tests.
    DATABASE_URL: str = "sqlite:///canyp.db"
    # Dev origins (Vite) + Tauri desktop shell origins (v2):
    #   - Windows WebView2 serves the embedded UI from http://tauri.localhost
    #   - macOS/Linux use tauri://localhost
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:3000,"
        "http://localhost:8080,http://tauri.localhost,https://tauri.localhost,tauri://localhost"
    )
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
