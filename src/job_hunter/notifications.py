from __future__ import annotations

import logging
from typing import Any

import requests

from .models import Job

LOG = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, session: Any = None, timeout: int = 20):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.session = session or requests.Session()
        self.timeout = timeout

    @staticmethod
    def format_message(job: Job) -> str:
        salary = job.salary_original or "Not disclosed"
        monthly = ""
        if job.salary_min_monthly_usd is not None:
            monthly = f" (about USD {job.salary_min_monthly_usd:,.0f}/month minimum)"
        source_url = "https://himalayas.app" if job.source == "himalayas" else job.application_url
        return (
            f"{job.title} — {job.company}\n"
            f"Location: {job.location or 'Not specified'}\n"
            f"Brazil eligibility: {job.eligibility} — {job.eligibility_reason}\n"
            f"Salary: {salary}{monthly}{' [review]' if job.salary_status == 'review' else ''}\n"
            f"Match: {job.match_score}/100\n"
            f"Why: {job.match_explanation}\n"
            f"Apply: {job.application_url}\n"
            f"Source: {job.source.title()} ({source_url})"
        )

    def send(self, job: Job) -> bool:
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = self.session.post(
                endpoint,
                json={"chat_id": self.chat_id, "text": self.format_message(job), "disable_web_page_preview": True},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                LOG.error("Telegram rejected a notification (job %s)", job.job_id)
                return False
            return True
        except (requests.RequestException, ValueError) as exc:
            # Do not log the request URL: it contains the bot token.
            LOG.error("Telegram delivery failed for job %s (%s)", job.job_id, type(exc).__name__)
            return False
