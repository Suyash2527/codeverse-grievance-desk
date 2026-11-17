"""Runtime configuration. Every value comes from the environment.

No secret is ever hardcoded here or anywhere else in the codebase; this module
only names the environment variables the system reads.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    confidence_threshold: float
    embedding_model: str
    embedding_dim: int
    chat_model: str
    stt_model: str
    openai_api_key: str | None
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    langfuse_host: str | None
    n8n_webhook_base: str | None
    # Sarvam speech, used by the simulated phone-call and WhatsApp voice
    # channels. Optional: without a key both channels fall back to text.
    sarvam_api_key: str | None = None
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str | None = None

    @property
    def category_master_csv(self) -> Path:
        return self.data_dir / "grievance_category_master.csv"

    @property
    def department_directory_csv(self) -> Path:
        return self.data_dir / "department_directory.csv"

    @property
    def grievance_history_csv(self) -> Path:
        return self.data_dir / "mock_grievance_history.csv"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR") or (_REPO_ROOT / "data"))
    return Settings(
        data_dir=data_dir,
        database_url=os.environ.get("DATABASE_URL", "sqlite+pysqlite:///./hackfusion.db"),
        # Policy input, not a constant: the Policy Agent compares decision
        # confidence against this before allowing an automated resolution.
        confidence_threshold=float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75")),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1536")),
        chat_model=os.environ.get("CHAT_MODEL", "gpt-4o-mini"),
        # whisper-1 and gpt-4o-transcribe are marked deprecated in the
        # current SDK (shutdown 2027-02-26); gpt-transcribe supersedes them.
        stt_model=os.environ.get("STT_MODEL", "gpt-transcribe"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        langfuse_host=os.environ.get("LANGFUSE_HOST"),
        n8n_webhook_base=os.environ.get("N8N_WEBHOOK_BASE"),
        sarvam_api_key=os.environ.get("SARVAM_API_KEY") or None,
        sarvam_stt_model=os.environ.get("SARVAM_STT_MODEL", "saaras:v4"),
        sarvam_tts_model=os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3"),
        # Unset means Sarvam's default voice for the model and language.
        sarvam_tts_speaker=os.environ.get("SARVAM_TTS_SPEAKER") or None,
    )


settings = load_settings()
