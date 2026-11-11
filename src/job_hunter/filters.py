from __future__ import annotations

import re

from .models import Job


def title_matches(title: str, config: dict) -> bool:
    value = title.casefold()
    profile = config.get("profile", {})
    if any(str(term).casefold() in value for term in profile.get("title_terms", [])):
        return True
    # Keep common word-order variants and adjacent titles within the target families.
    has_engineer = "engineer" in value or "engineering" in value
    has_architect = "architect" in value
    # Use word boundaries so e.g. "retail engineer" is not mistaken for an AI role.
    has_ai = bool(re.search(r"\b(?:ai|artificial intelligence|genai|generative ai|llm|machine learning)\b", value))
    if has_ai and (has_engineer or has_architect):
        return True
    if "data" in value and has_engineer:
        return True
    return False


def employment_is_relevant(value: str | None, config: dict) -> bool:
    if not value:
        return True
    normalized = re.sub(r"[_\-/]+", " ", value.casefold())
    terms = [str(term).casefold() for term in config.get("profile", {}).get("employment_terms", [])]
    return any(re.sub(r"[_\-/]+", " ", term) in normalized for term in terms)


def job_passes(job: Job, config: dict) -> tuple[bool, str | None]:
    if job.eligibility == "ineligible":
        return False, "explicitly incompatible geography"
    if not title_matches(job.title, config):
        return False, "title outside target roles"
    if not employment_is_relevant(job.employment_type, config):
        return False, "employment type outside target types"
    minimum = float(config.get("salary", {}).get("minimum_monthly_usd", 3000))
    # Keep a range overlapping the requested minimum (e.g. USD 2,500-6,000).
    # Reject only if the advertised maximum is definitely below the target.
    disclosed_ceiling = job.salary_max_monthly_usd if job.salary_max_monthly_usd is not None else job.salary_min_monthly_usd
    if job.salary_status == "normalized" and disclosed_ceiling is not None and disclosed_ceiling < minimum:
        return False, f"normalized salary range entirely below USD {minimum:.0f}/month"
    return True, None


def deduplicate(jobs: list[Job]) -> list[Job]:
    result: list[Job] = []
    ids: set[str] = set()
    urls: set[str] = set()
    titles: set[tuple[str, str]] = set()
    for job in jobs:
        parsed = re.sub(r"[?#].*$", "", job.application_url.rstrip("/")).casefold()
        title_key = re.sub(r"[^a-z0-9]+", " ", job.title.casefold()).strip()
        company_key = re.sub(r"[^a-z0-9]+", " ", job.company.casefold()).strip()
        if job.job_id in ids or parsed in urls or (company_key and title_key and (company_key, title_key) in titles):
            continue
        ids.add(job.job_id)
        urls.add(parsed)
        titles.add((company_key, title_key))
        result.append(job)
    return result
