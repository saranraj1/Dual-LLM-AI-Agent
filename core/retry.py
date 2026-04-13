"""
core/retry.py — Exponential backoff with jitter for LLM API calls.

Handles:
- Groq 429 (rate limit) with Retry-After header respect
- Groq 503 (service unavailable)
- Network timeouts
- Configurable max retries and base delay
"""

import time
import random
import urllib.error
import logging
from functools import wraps
from typing import Callable, TypeVar, Any, Optional

log = logging.getLogger("agent.retry")

T = TypeVar("T")

# ── Config ────────────────────────────────────────────────────────────────────
MAX_RETRIES  = 4
BASE_DELAY   = 1.0    # seconds
MAX_DELAY    = 60.0   # cap exponential growth
JITTER_RANGE = 0.5    # ±500ms randomness to prevent thundering herd

# HTTP status codes that should trigger a retry
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _extract_retry_after(exc: urllib.error.HTTPError) -> Optional[float]:
    """Pull the Retry-After header value from a 429 response, if present."""
    try:
        val = exc.headers.get("Retry-After", "")
        if val:
            return float(val)
    except (ValueError, AttributeError):
        pass
    return None


def _should_retry(exc: Exception) -> bool:
    """Return True if this exception is retryable."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_STATUSES
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionResetError)):
        return True
    msg = str(exc).lower()
    return any(kw in msg for kw in [
        "timed out", "connection refused", "connection reset",
        "remote end closed", "rate limit", "too many requests",
    ])


def with_retry(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_delay:  float = BASE_DELAY,
    label:       str = "",
    **kwargs: Any,
) -> T:
    """
    Call func(*args, **kwargs) with exponential backoff on retryable errors.

    Args:
        func:        The callable to retry.
        *args:       Positional args forwarded to func.
        max_retries: Maximum number of retry attempts (default 4).
        base_delay:  Initial delay in seconds (default 1.0).
        label:       Human-readable label for log messages.
        **kwargs:    Keyword args forwarded to func.

    Returns:
        The return value of a successful func call.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Optional[Exception] = None
    name = label or getattr(func, "__name__", "call")

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)

        except Exception as exc:
            last_exc = exc

            if attempt >= max_retries:
                log.error("[retry] %s failed after %d attempts: %s", name, max_retries + 1, exc)
                raise

            if not _should_retry(exc):
                log.debug("[retry] %s — non-retryable error: %s", name, exc)
                raise

            # ── Determine delay ───────────────────────────────────────────────
            retry_after = None
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                retry_after = _extract_retry_after(exc)

            if retry_after is not None:
                delay = min(retry_after + random.uniform(0, JITTER_RANGE), MAX_DELAY)
                log.warning("[retry] %s — rate limited. Retry-After: %.1fs (attempt %d/%d)",
                            name, delay, attempt + 1, max_retries)
            else:
                # Exponential backoff: 1s, 2s, 4s, 8s … capped at MAX_DELAY
                exp_delay = min(base_delay * (2 ** attempt), MAX_DELAY)
                jitter    = random.uniform(-JITTER_RANGE, JITTER_RANGE)
                delay     = max(0.1, exp_delay + jitter)
                log.warning("[retry] %s — %s. Retrying in %.1fs (attempt %d/%d)",
                            name, type(exc).__name__, delay, attempt + 1, max_retries)

            time.sleep(delay)

    raise last_exc  # unreachable, but satisfies type checker


def retryable(max_retries: int = MAX_RETRIES, base_delay: float = BASE_DELAY):
    """
    Decorator that wraps a function with automatic retry logic.

    Usage:
        @retryable(max_retries=3)
        def call_api(prompt):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return with_retry(func, *args, max_retries=max_retries,
                              base_delay=base_delay, label=func.__name__, **kwargs)
        return wrapper
    return decorator
