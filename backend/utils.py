"""
Oracle-X Shared Utilities
Logging, shared state, and helper functions used across routers.
"""
from typing import Optional
from models.schemas import NewsItem


# ═══════════════════════════════════════════════════════════════════════════════
# TERMINAL COLORS & LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
class Colors:
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    END = '\033[0m'

def log_header(message: str):
    print(f"\n{Colors.PURPLE}{'═'*60}{Colors.END}", flush=True)
    print(f"{Colors.PURPLE}{Colors.BOLD}  🔮 {message}{Colors.END}", flush=True)
    print(f"{Colors.PURPLE}{'═'*60}{Colors.END}", flush=True)

def log_step(emoji: str, message: str, color: str = Colors.CYAN):
    print(f"{color}  {emoji}  {message}{Colors.END}", flush=True)

def log_success(message: str):
    print(f"{Colors.GREEN}  ✓  {message}{Colors.END}", flush=True)

def log_warning(message: str):
    print(f"{Colors.YELLOW}  ⚠  {message}{Colors.END}", flush=True)

def log_error(message: str):
    print(f"{Colors.RED}  ✗  {message}{Colors.END}", flush=True)

def log_info(message: str):
    print(f"{Colors.GRAY}      {message}{Colors.END}", flush=True)

def log_result(label: str, value: str, color: str = Colors.WHITE):
    print(f"{Colors.GRAY}      {label}: {color}{value}{Colors.END}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION FLAGS (sourced from central config; re-exported for convenience)
# ═══════════════════════════════════════════════════════════════════════════════
from config import settings

# Use real API data instead of mock fixtures.
USE_REAL_API = settings.USE_REAL_API
# Master switch for the AI features, whichever provider is configured.
USE_AI = settings.USE_AI


# ═══════════════════════════════════════════════════════════════════════════════
# NEWS CACHE (shared between news and analysis endpoints)
# ═══════════════════════════════════════════════════════════════════════════════
_news_cache: dict = {}


def get_news_cache() -> dict:
    """Get the news cache dict."""
    return _news_cache


def update_news_cache(items):
    """Update the news cache with fetched items."""
    global _news_cache
    _news_cache = {item.id: item for item in items}


def get_news_from_cache(news_id: str) -> Optional[NewsItem]:
    """Get news item from cache."""
    if news_id in _news_cache:
        return _news_cache[news_id]
    return None
