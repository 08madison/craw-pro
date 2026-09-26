import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")
# low | medium | high | xhigh | max; empty = model default
CLAUDE_EFFORT = os.environ.get("LLM_EFFORT", "")
# "default" enables server-side refusal fallbacks; "off" disables them
CLAUDE_FALLBACKS = os.environ.get("LLM_FALLBACKS", "default")

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
