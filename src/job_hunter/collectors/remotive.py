from __future__ import annotations

import logging
from typing import Any

from .base import Collector
from .http import JsonClient

LOG = logging.getLogger(__name__)
API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveCollector(Collector):
    source = "remotive"

    def __init__(self, client: JsonClient | None = None):
        self.client = client or JsonClient()

    def collect(self) -> list[dict[str, Any]]:
        payload = self.client.get_json(API_URL)
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("Remotive response 'jobs' must be a list")
        result = [job for job in jobs if isinstance(job, dict)]
        LOG.info("Remotive returned %d jobs", len(result))
        return result
