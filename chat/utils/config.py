import os
from pathlib import Path
from functools import lru_cache

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field, field_validator

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

if HAS_PYDANTIC:

    class Settings(BaseSettings):

        elastic_url: str = Field(
            default="http://elasticsearch:9200", alias="ELASTIC_URL"
        )
        elastic_url_local: str = Field(
            default="http://localhost:9200", alias="ELASTIC_URL_LOCAL"
        )
        index_name: str = Field(default="chess-rag", alias="INDEX_NAME")
        elastic_port: int = Field(default=9200, alias="ELASTIC_PORT")

        postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
        postgres_db: str = Field(default="chess_assistant", alias="POSTGRES_DB")
        postgres_user: str = Field(default="chess_assistant", alias="POSTGRES_USER")
        postgres_password: str = Field(
            default="chess_assistant", alias="POSTGRES_PASSWORD"
        )
        postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

        openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
        openai_model: str = Field(default="gpt-3.5-turbo", alias="OPENAI_MODEL")
        openai_eval_model: str = Field(
            default="gpt-3.5-turbo", alias="OPENAI_EVAL_MODEL"
        )
        openai_timeout: float = Field(default=20.0, alias="OPENAI_TIMEOUT")
        openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")

        stockfish_path: str = Field(default="stockfish", alias="STOCKFISH_PATH")
        engine_depth: int = Field(default=15, alias="ENGINE_DEPTH")
        engine_threads: int = Field(default=1, alias="ENGINE_THREADS")
        engine_hash_mb: int = Field(default=64, alias="ENGINE_HASH_MB")
        engine_timeout: float = Field(default=0.15, alias="ENGINE_TIMEOUT")

        pgn_path: str = Field(
            default=str(
                Path(__file__).resolve().parents[2] / "data" / "lichess_db.pgn"
            ),
            alias="PGN_PATH",
        )
        max_index_docs: int = Field(default=2000, alias="MAX_INDEX_DOCS")
        bulk_chunk_size: int = Field(default=500, alias="BULK_CHUNK_SIZE")

        redis_url: str = Field(default="", alias="REDIS_URL")
        cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")
        cache_max_entries: int = Field(default=200, alias="CACHE_MAX_ENTRIES")

        streamlit_port: int = Field(default=8501, alias="STREAMLIT_PORT")
        app_env: str = Field(default="development", alias="APP_ENV")
        log_level: str = Field(default="INFO", alias="LOG_LEVEL")

        rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")

        model_config = {
            "env_file": str(Path(__file__).resolve().parents[2] / ".env"),
            "env_file_encoding": "utf-8",
            "extra": "ignore",
            "populate_by_name": True,
        }

        @field_validator("openai_model", "openai_eval_model", mode="before")
        @classmethod
        def strip_model(cls, v):
            return v.strip() if isinstance(v, str) else v

        @field_validator("postgres_password", mode="after")
        @classmethod
        def validate_password(cls, v, info):

            app_env = (
                info.data.get("app_env", "development") if info.data else "development"
            )
            if app_env and app_env.lower() == "production" and v == "chess_assistant":
                raise ValueError(
                    "postgres_password must be changed from default 'chess_assistant' in production"
                )
            return v

        @property
        def is_production(self) -> bool:
            return self.app_env.lower() == "production"

    @lru_cache(maxsize=1)
    def get_settings() -> "Settings":
        return Settings()

else:

    class Settings:
        def __init__(self):
            self.elastic_url = os.getenv("ELASTIC_URL", "http://elasticsearch:9200")
            self.elastic_url_local = os.getenv(
                "ELASTIC_URL_LOCAL", "http://localhost:9200"
            )
            self.index_name = os.getenv("INDEX_NAME", "chess-rag")
            self.elastic_port = int(os.getenv("ELASTIC_PORT", "9200"))
            self.postgres_host = os.getenv("POSTGRES_HOST", "localhost")
            self.postgres_db = os.getenv("POSTGRES_DB", "chess_assistant")
            self.postgres_user = os.getenv("POSTGRES_USER", "chess_assistant")
            self.postgres_password = os.getenv("POSTGRES_PASSWORD", "chess_assistant")
            self.postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
            self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
            self.openai_model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
            self.openai_eval_model = os.getenv("OPENAI_EVAL_MODEL", "gpt-3.5-turbo")
            self.openai_timeout = float(os.getenv("OPENAI_TIMEOUT", "20"))
            self.openai_base_url = (
                os.getenv("OPENAI_BASE_URL")
                or os.getenv("OPENAI_API_BASE")
                or os.getenv("LLM_GATEWAY_URL")
                or os.getenv("LLM_BASE_URL")
                or ""
            )
            self.stockfish_path = os.getenv("STOCKFISH_PATH", "stockfish")
            self.engine_depth = int(os.getenv("ENGINE_DEPTH", "15"))
            self.engine_threads = int(os.getenv("ENGINE_THREADS", "1"))
            self.engine_hash_mb = int(os.getenv("ENGINE_HASH_MB", "64"))
            self.engine_timeout = float(os.getenv("ENGINE_TIMEOUT", "0.15"))
            self.pgn_path = os.getenv(
                "PGN_PATH",
                str(Path(__file__).resolve().parents[2] / "data" / "lichess_db.pgn"),
            )
            self.max_index_docs = int(os.getenv("MAX_INDEX_DOCS", "2000"))
            self.bulk_chunk_size = int(os.getenv("BULK_CHUNK_SIZE", "500"))
            self.redis_url = os.getenv("REDIS_URL", "")
            self.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
            self.cache_max_entries = int(os.getenv("CACHE_MAX_ENTRIES", "200"))
            self.streamlit_port = int(os.getenv("STREAMLIT_PORT", "8501"))
            self.app_env = os.getenv("APP_ENV", "development")
            self.log_level = os.getenv("LOG_LEVEL", "INFO")
            self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
            self.is_production = self.app_env.lower() == "production"

            if self.is_production and self.postgres_password == "chess_assistant":
                import warnings

                warnings.warn(
                    "postgres_password is default 'chess_assistant' in production – change it!"
                )

        def model_dump(self):
            return self.__dict__

    _cached: "Settings | None" = None

    def get_settings() -> "Settings":
        global _cached
        if _cached is None:
            _cached = Settings()
        return _cached


settings = get_settings()
