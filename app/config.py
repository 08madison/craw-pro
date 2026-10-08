import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from a local .env file; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(Path(os.environ.get("ENV_FILE", ".env")))


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --- LLM provider ---
# "openai": any OpenAI-compatible API (DeepSeek, Qwen/DashScope, Moonshot/Kimi, Zhipu GLM,
#           OpenAI, OpenRouter, SiliconFlow, Ollama ...) -> LLM_API_KEY + LLM_BASE_URL + LLM_MODEL
# "anthropic": Claude -> ANTHROPIC_API_KEY
# empty: auto-detect from which key is set; no key at all = basic mode (no AI)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "").strip().lower() or (
    "openai" if LLM_API_KEY else "anthropic" if ANTHROPIC_API_KEY else ""
)
LLM_MODEL = os.environ.get("LLM_MODEL", "") or ("claude-opus-5" if LLM_PROVIDER == "anthropic" else "")
# Claude only: low | medium | high | xhigh | max; empty = model default
LLM_EFFORT = os.environ.get("LLM_EFFORT", "")
# Claude only: "default" enables server-side refusal fallbacks; "off" disables them
LLM_FALLBACKS = os.environ.get("LLM_FALLBACKS", "default")
# Max output tokens per call (DeepSeek and some others cap at 8192)
LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 8192)
# OpenAI-compatible only: send response_format=json_object (disable for providers that reject it)
LLM_JSON_MODE = os.environ.get("LLM_JSON_MODE", "1") != "0"

# Optional password protecting the web UI / API (strongly recommended on a public host)
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
MAX_PAGES_LIMIT = _int("MAX_PAGES_LIMIT", 50)
MAX_DEPTH_LIMIT = _int("MAX_DEPTH_LIMIT", 3)
CRAWL_CONCURRENCY = _int("CRAWL_CONCURRENCY", 2)
REQUEST_DELAY_MS = _int("REQUEST_DELAY_MS", 500)
MAX_PAGE_CHARS = _int("MAX_PAGE_CHARS", 120_000)
MAX_CONCURRENT_JOBS = _int("MAX_CONCURRENT_JOBS", 3)
ALLOW_PRIVATE_NETWORKS = os.environ.get("ALLOW_PRIVATE_NETWORKS", "") == "1"

USER_AGENT = os.environ.get(
    "CRAWLER_USER_AGENT",
    "Mozilla/5.0 (compatible; CrawPro/1.0; +https://github.com/08madison/craw-pro)",
)


def browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return os.environ.get("ENABLE_BROWSER", "1") != "0"
