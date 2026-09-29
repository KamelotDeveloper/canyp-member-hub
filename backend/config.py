"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Cargar backend/.env (ruta absoluta al módulo: funciona desde cualquier CWD,
    # incluidos run.py, desktop_run.py y pytest). Nunca commiteable (ver .gitignore).
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    # Supabase (suscripciones/licencias). SUPABASE_SERVICE_KEY y MP_ACCESS_TOKEN
    # son credenciales de PRIVILEGIO DEL OPERADOR: nunca se empaquetan en el
    # sidecar ni se escriben en disco del cliente. La clasificación y el fallo
    # explícito ante su ausencia viven en backend/operator_credentials.py.
    # En dev se leen de backend/.env (ignorado por git y excluido del .spec).
    SUPABASE_URL: str = "https://nrysusllouuytjlwdyvn.supabase.co"
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # MercadoPago (Checkout Pro). MP_ACCESS_TOKEN es de producción, es
    # credencial de privilegio del operador y vive fuera del bundle.
    # CANYP_PORT lo inyecta Rust (sidecar) al elegir un puerto libre; 8000 es
    # solo el fallback de dev (uvicorn manual).
    CANYP_PORT: int = 8000
    MP_ACCESS_TOKEN: str = ""
    MP_NOTIFICATION_URL: str = "https://suscripcion-api.vercel.app/api/webhook"

    @property
    def mp_base_url(self) -> str:
        return f"http://127.0.0.1:{self.CANYP_PORT}"

    @property
    def mp_success_url(self) -> str:
        return f"{self.mp_base_url}/api/suscripcion/exito"

    @property
    def mp_failure_url(self) -> str:
        return f"{self.mp_base_url}/api/suscripcion/fallo"

    @property
    def mp_pending_url(self) -> str:
        return f"{self.mp_base_url}/api/suscripcion/pendiente"

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
