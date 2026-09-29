"""Application configuration (env-driven via pydantic-settings).

Defaults are dev-friendly so the service boots with zero config. Paths are resolved
relative to the `ml/` directory so they work regardless of the CWD.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ml/ (this file is ml/app/config.py)
ML_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ML_DIR.parent


def _resolve(p: str | Path) -> Path:
    """Resolve a possibly-relative path against the ml/ dir."""
    p = Path(p)
    return p if p.is_absolute() else (ML_DIR / p).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ML_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./data/toothfairy.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_min: int = 720  # 12h

    # Inference results dir shared with the frontend (Next serves it statically).
    results_dir: Path = REPO_ROOT / "web" / "public" / "results"
    # Where uploaded raw photos are stored (served via /media).
    upload_dir: Path = ML_DIR / "data" / "uploads"
    # Precomputed demo datasets used as the MOCK_INFERENCE source (never overridden
    # to a temp dir — the shipped demos live here). results_dir is the destination.
    demo_results_dir: Path = REPO_ROOT / "web" / "public" / "results"

    # 1 = skip heavy models, copy a precomputed demo dataset (fast dev/E2E).
    mock_inference: bool = False
    # Per-stage delay (s) for the mock job so the progress UI is visible; 0 in tests.
    mock_step_delay: float = 0.2

    cors_origins: str = "http://localhost:3000,http://localhost:8081"
    # Shared secret the Go gateway presents on internal calls. Empty = check disabled
    # (dev only); set it in every non-local deployment.
    internal_api_key: str = ""

    # ── LLM / RAG advisory layer ───────────────────────────────────────────────
    # Both flags default OFF so pytest/E2E keep exercising the deterministic stub
    # and never touch the network. Set them (plus a key) in ml/.env to go live.
    openai_api_key: str = ""
    openai_base_url: str = ""       # optional: Azure/proxy/self-hosted gateway
    llm_enabled: bool = False
    rag_enabled: bool = False
    llm_model: str = "gpt-5.6-sol"       # diagnosis + recommendation agents
    llm_helper_model: str = "gpt-5.6-luna"  # chunk contextualizing + eval judge
    llm_effort: str = "high"             # none | low | medium | high
    llm_max_tokens: int = 12000  # reasoning tokens bill against this; set3 emitted ~7.4k
    llm_timeout_s: float = 180.0
    llm_max_retries: int = 3
    # Moderation gate on free-text patient input (omni-moderation). Off by default so
    # the offline demo never calls out.
    moderation_enabled: bool = False
    # Retrieval: hybrid fetches `rag_candidates`, the cross-encoder reranks to `rag_top_n`.
    rag_candidates: int = 16
    rag_top_n: int = 6

    @property
    def corpus_dir(self) -> Path:
        return ML_DIR / "app" / "llm" / "corpus"

    @property
    def rag_index_dir(self) -> Path:
        return self.corpus_dir / "index"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_path(self) -> Path | None:
        """Local file path for a sqlite:/// URL, else None."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return _resolve(self.database_url[len(prefix):])
        return None


settings = Settings()
