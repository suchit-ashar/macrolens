"""Shared HTTP helper for fetchers that don't need source-specific handling."""
import time

import requests

USER_AGENT = "MacroLens/0.1 (educational macro dashboard)"


class FetchError(RuntimeError):
    pass


def get(url: str, params: dict | None = None, session=None, retries: int = 3, timeout: int = 60):
    """GET with retries and backoff. Returns the Response (status 200) or raises FetchError.

    4xx errors are not retried: a bad request will not fix itself.
    """
    session = session or requests.Session()
    last_err = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code == 200:
                return r
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            if 400 <= r.status_code < 500:
                break
        except requests.RequestException as e:
            last_err = str(e)
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise FetchError(f"GET {url} failed: {last_err}")
