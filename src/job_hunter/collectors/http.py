from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests

LOG = logging.getLogger(__name__)


class JsonClient:
    def __init__(self, timeout: int = 25, max_retries: int = 2, session: Any = None):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Collector endpoint must use HTTPS")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429 and attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After", "1")
                    try:
                        delay = min(max(float(retry_after), 0), 30)
                    except ValueError:
                        delay = 1
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object from job API")
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(2**attempt, 4))
        raise RuntimeError(f"Request to {parsed.netloc} failed after retries: {last_error}") from last_error
