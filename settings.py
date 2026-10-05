"""Centralised, environment-driven configuration.

Every value here can be overridden with an environment variable so the same
code runs locally against the Inngest dev server and in production against
Inngest Cloud or a self-hosted Inngest server.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- Inngest ---------------------------------------------------------------
# When true we target the local/self-hosted dev server (no auth required).
# Set INNGEST_DEV=false and provide keys to target Inngest Cloud.
INNGEST_DEV = _env_flag("INNGEST_DEV", default=True)
INNGEST_APP_ID = os.getenv("INNGEST_APP_ID", "rag_app")
INNGEST_API_BASE_URL = os.getenv(
    "INNGEST_API_BASE_URL", "http://127.0.0.1:8288"
).rstrip("/")
INNGEST_EVENT_API_BASE_URL = os.getenv(
    "INNGEST_EVENT_API_BASE_URL", INNGEST_API_BASE_URL
).rstrip("/")
INNGEST_EVENT_KEY = os.getenv("INNGEST_EVENT_KEY")
INNGEST_SIGNING_KEY = os.getenv("INNGEST_SIGNING_KEY")
INNGEST_ENV = os.getenv("INNGEST_ENV")

# --- OpenAI ----------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")
RAG_LLM_MODEL = os.getenv("RAG_LLM_MODEL", "gpt-4o-mini")

# --- Qdrant ----------------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")
QDRANT_DIM = int(os.getenv("QDRANT_DIM", "3072"))

# --- Uploads ---------------------------------------------------------------
# Must be the SAME path on the machine running Streamlit and the machine
# running the Inngest worker, because the ingest event carries a file path.
# See README for the shared-volume setup.
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "uploads")).resolve()


def missing_config() -> list[str]:
    """Return a list of configuration problems that will break the app."""
    problems: list[str] = []

    if not OPENAI_API_KEY:
        problems.append("OPENAI_API_KEY is not set")

    if not INNGEST_DEV:
        if not INNGEST_EVENT_KEY:
            problems.append("INNGEST_EVENT_KEY is required when not in dev mode")
        if not INNGEST_SIGNING_KEY:
            problems.append(
                "INNGEST_SIGNING_KEY is required when not in dev mode "
                "(it verifies incoming requests and authorises the REST API)"
            )

    return problems