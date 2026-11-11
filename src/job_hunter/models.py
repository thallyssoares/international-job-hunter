from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Job:
    job_id: str
    source: str
    company: str
    title: str
    location: str
    eligibility: str
    eligibility_reason: str
    employment_type: str | None
    salary_original: str | None
    salary_currency: str | None
    salary_min_monthly_usd: float | None
    salary_max_monthly_usd: float | None
    salary_status: str
    publication_date: str | None
    description: str
    application_url: str
    match_score: int = 0
    match_explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Job":
        return cls(**value)
