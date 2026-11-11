from __future__ import annotations

import logging
from typing import Any

from .base import Collector
from .http import JsonClient

LOG = logging.getLogger(__name__)
API_URL = "https://himalayas.app/jobs/api/search"
DEFAULT_QUERIES = (
    "AI Engineer", "GenAI Engineer", "LLM Engineer", "Data Engineer",
    "AI Architect", "Solutions Architect",
)


class HimalayasCollector(Collector):
    """Search Brazil-eligible jobs by keyword, instead of sampling the global feed."""

    source = "himalayas"

    def __init__(
        self,
        client: JsonClient | None = None,
        max_pages: int = 3,
        queries: list[str] | tuple[str, ...] | None = None,
        country: str = "BR",
    ):
        self.client = client or JsonClient()
        self.max_pages = max_pages
        self.queries = tuple(queries) if queries is not None else DEFAULT_QUERIES
        self.country = country

    def collect(self) -> list[dict[str, Any]]:
        collected: dict[str, dict[str, Any]] = {}
        succeeded = 0
        for query in self.queries:
            for page in range(1, self.max_pages + 1):
                params = {"q": query, "country": self.country, "sort": "recent", "page": page}
                try:
                    payload = self.client.get_json(API_URL, params)
                    page_jobs = payload.get("jobs")
                    if not isinstance(page_jobs, list):
                        raise ValueError("Himalayas response 'jobs' must be a list")
                except (RuntimeError, ValueError) as exc:
                    LOG.warning("Himalayas search %r page %d failed: %s", query, page, exc)
                    break
                succeeded += 1
                for job in page_jobs:
                    if isinstance(job, dict):
                        key = str(job.get("guid") or job.get("applicationLink") or job.get("id") or "")
                        if key:
                            collected[key] = job
                # Search API pages are 20 jobs long. Don't request empty tail pages.
                if len(page_jobs) < 20:
                    break
        if succeeded == 0:
            raise RuntimeError("All Himalayas search requests failed")
        LOG.info("Himalayas returned %d unique jobs from %d requests", len(collected), succeeded)
        return list(collected.values())
