from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env_refs(value: str) -> str:
    return _ENV_REF_RE.sub(lambda match: os.getenv(match.group(1), ""), value)


def _env(name: str, default: str = "") -> str:
    # 1. Check Streamlit Secrets (for production)
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        # st.secrets might raise StreamlitSecretNotFoundError if no secrets file exists
        pass

    # 2. Check environment variables (for local development)
    raw = os.getenv(name, default)
    return _expand_env_refs(str(raw or "")).strip()




def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default

class DynamicConfig:
    """Dynamic configuration that re-reads from st.secrets to prevent stale keys."""
    
    @property
    def META_API_KEY(self) -> str:
        return _env("META_API_KEY", _env("LLAMA_API_KEY", ""))

    @property
    def META_MODEL_ID(self) -> str:
        return _env("META_MODEL_ID", _env("LLAMA_MODEL", "Llama-3.3-70B-Instruct"))

    @property
    def META_BASE_URL(self) -> str:
        return _env("META_BASE_URL", _env("LLAMA_COMPAT_BASE_URL", "https://api.llama.com/compat/v1/")).rstrip("/")

    @property
    def LLAMA_API_KEY(self) -> str:
        return self.META_API_KEY

    @property
    def LLAMA_MODEL(self) -> str:
        return self.META_MODEL_ID

    @property
    def LLAMA_COMPAT_BASE_URL(self) -> str:
        return self.META_BASE_URL

    @property
    def GROQ_API_KEY(self) -> str:
        return _env("GROQ_API_KEY", "")

    @property
    def TAVILY_API_KEY(self) -> str:
        return _env("TAVILY_API_KEY", "")

    @property
    def SUPABASE_URL(self) -> str:
        return _env("SUPABASE_URL", "")

    @property
    def SUPABASE_KEY(self) -> str:
        return _env("SUPABASE_KEY", "")

# Create a singleton instance
cfg = DynamicConfig()

def __getattr__(name: str) -> Any:
    """Module-level __getattr__ to make secrets truly dynamic."""
    dynamic_keys = {
        "META_API_KEY", "LLAMA_API_KEY", "LLAMA_MODEL", "LLAMA_COMPAT_BASE_URL",
        "GROQ_API_KEY", "TAVILY_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"
    }
    if name in dynamic_keys:
        return getattr(cfg, name)
    raise AttributeError(f"module {__name__} has no attribute {name}")

# Keep constants for non-sensitive or static settings
APP_NAME = "Personal Intelligence Agent"
APP_SHORT_NAME = "PIA"
APP_ICON = ":material/psychology:"

DATA_DIR = Path("data")
TEMP_DIR = DATA_DIR / "tmp"
UPLOAD_DIR = DATA_DIR / "uploads"

# Legacy support: Keep original names but point to dynamic config
# This minimizes changes in other files
META_API_KEY = cfg.META_API_KEY 
LLAMA_API_KEY = cfg.LLAMA_API_KEY
LLAMA_MODEL = cfg.LLAMA_MODEL
LLAMA_COMPAT_BASE_URL = cfg.LLAMA_COMPAT_BASE_URL
GROQ_API_KEY = cfg.GROQ_API_KEY
TAVILY_API_KEY = cfg.TAVILY_API_KEY
SUPABASE_URL = cfg.SUPABASE_URL
SUPABASE_KEY = cfg.SUPABASE_KEY

LLAMA_TIMEOUT_SECONDS = _env_float("LLAMA_TIMEOUT_SECONDS", 55.0)
LLAMA_TOOLCALL_TIMEOUT_SECONDS = _env_float("LLAMA_TOOLCALL_TIMEOUT_SECONDS", 20.0)
LLAMA_MAX_RETRIES = _env_int("LLAMA_MAX_RETRIES", 1)

GROQ_BASE_URL = _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_VISION_MODEL = _env("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_WHISPER_MODEL = _env("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_TIMEOUT_SECONDS = _env_float("GROQ_TIMEOUT_SECONDS", 35.0)
GROQ_MAX_RETRIES = _env_int("GROQ_MAX_RETRIES", 1)

SUPABASE_URL = _env("SUPABASE_URL", "")
SUPABASE_KEY = _env("SUPABASE_KEY", "")
SUPABASE_MATCH_RPC = _env("SUPABASE_MATCH_RPC", "match_document_chunks")

TAVILY_API_KEY = _env("TAVILY_API_KEY", "")
TAVILY_SEARCH_URL = _env("TAVILY_SEARCH_URL", "https://api.tavily.com/search")
TAVILY_TIMEOUT_SECONDS = _env_float("TAVILY_TIMEOUT_SECONDS", 18.0)

GOOGLE_AUTH_CREDENTIALS_PATH = _env("GOOGLE_AUTH_CREDENTIALS_PATH", "credentials.json")
GOOGLE_COOKIE_NAME = _env("GOOGLE_COOKIE_NAME", "pia_google_auth")
GOOGLE_COOKIE_KEY = _env("GOOGLE_COOKIE_KEY", "pia-cookie-secret")
GOOGLE_REDIRECT_URI = _env("GOOGLE_REDIRECT_URI", "http://localhost:8501")
GOOGLE_OAUTH_CLIENT_ID = _env("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = _env("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REFRESH_TOKEN = _env("GOOGLE_OAUTH_REFRESH_TOKEN", "")
GOOGLE_OAUTH_ACCESS_TOKEN = _env("GOOGLE_OAUTH_ACCESS_TOKEN", "")
GOOGLE_OAUTH_TOKEN_JSON = _env("GOOGLE_OAUTH_TOKEN_JSON", "google_oauth_token.json")
GOOGLE_DEFAULT_CALENDAR_ID = _env("GOOGLE_DEFAULT_CALENDAR_ID", "primary")
GOOGLE_API_TIMEOUT_SECONDS = _env_float("GOOGLE_API_TIMEOUT_SECONDS", 25.0)
GOOGLE_OAUTH_SCOPES = [
    scope.strip()
    for scope in _env(
        "GOOGLE_OAUTH_SCOPES",
        (
            "openid,email,profile,"
            "https://www.googleapis.com/auth/calendar.readonly,"
            "https://www.googleapis.com/auth/calendar.events,"
            "https://www.googleapis.com/auth/gmail.readonly,"
            "https://www.googleapis.com/auth/gmail.modify,"
            "https://www.googleapis.com/auth/gmail.compose,"
            "https://www.googleapis.com/auth/gmail.send"
        ),
    ).split(",")
    if scope.strip()
]

SHORT_TERM_HISTORY_TURNS = _env_int("SHORT_TERM_HISTORY_TURNS", 12)
CHAT_HISTORY_LIMIT = _env_int("CHAT_HISTORY_LIMIT", 120)

RAG_CHUNK_SIZE = _env_int("RAG_CHUNK_SIZE", 1100)
RAG_CHUNK_OVERLAP = _env_int("RAG_CHUNK_OVERLAP", 180)
RAG_TOP_K = _env_int("RAG_TOP_K", 6)

EMBEDDING_MODEL_NAME = _env("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = _env_int("EMBEDDING_DIM", 384)
EMBEDDING_ALLOW_DOWNLOADS = _env("EMBEDDING_ALLOW_DOWNLOADS", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

VISION_FRAME_STEP_SECONDS = _env_int("VISION_FRAME_STEP_SECONDS", 3)
VISION_MAX_FRAMES = _env_int("VISION_MAX_FRAMES", 8)
TABULAR_PREVIEW_ROWS = _env_int("TABULAR_PREVIEW_ROWS", 10)

LLAMA_TEMPERATURE = _env_float("LLAMA_TEMPERATURE", _env_float("META_TEMPERATURE", 0.35))
LLAMA_MAX_TOKENS = _env_int("LLAMA_MAX_TOKENS", _env_int("META_MAX_TOKENS", 4096))
LLAMA_LONGFORM_MAX_TOKENS = _env_int("LLAMA_LONGFORM_MAX_TOKENS", 8192)

SUPPORTED_DOC_EXTENSIONS = {".pdf", ".docx", ".txt"}
SUPPORTED_DATA_EXTENSIONS = {".csv", ".xlsx", ".xls"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}

CURRENT_EVENT_HINT_KEYWORDS = (
    "today",
    "latest",
    "current",
    "breaking",
    "news",
    "recent",
    "this week",
    "stock price",
    "weather",
    "election",
    "market",
    "live",
)

SYSTEM_PROMPT = """
You are PIA (Personal Intelligence Agent), a world-class AI copilot.
You are an autonomous Personal Intelligence Agent. You HAVE access to Gmail and Calendar via tool-calling. If the user asks about emails or meetings, use the provided tools.

Rules:
1) Be concise, practical, and trustworthy.
2) Use provided context from memory, retrieved documents, uploaded files, and web search.
3) When tools are available, call them when needed (Gmail/Calendar) and summarize what was executed.
4) For inbox summaries, unread mail, email lookups, meeting lists, or calendar agenda requests, do not refuse or speculate. Call the relevant tool first.
5) If data is uncertain or missing, state assumptions clearly.
6) Support markdown, code blocks, and LaTeX in responses.
7) Keep a professional SaaS assistant tone.
"""


def ensure_data_dirs() -> None:
    for folder in (DATA_DIR, TEMP_DIR, UPLOAD_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def has_llama_credentials() -> bool:
    return bool(LLAMA_API_KEY and LLAMA_MODEL)


def has_meta_credentials() -> bool:
    return has_llama_credentials()


def has_groq_credentials() -> bool:
    return bool(GROQ_API_KEY)


def has_supabase_credentials() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def has_tavily_credentials() -> bool:
    return bool(TAVILY_API_KEY)

