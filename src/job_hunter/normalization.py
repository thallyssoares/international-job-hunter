from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .models import Job

TAG_RE = re.compile(r"<[^>]+>")
AMOUNT_RE = re.compile(r"(?<![\w])(?:\$\s*)?(\d[\d,]*(?:\.\d+)?)\s*([kK])?")


def plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def valid_application_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def _period_to_monthly(amount: float, period: str) -> float | None:
    factors = {
        "monthly": 1.0,
        "month": 1.0,
        "per month": 1.0,
        "annual": 1 / 12,
        "annually": 1 / 12,
        "yearly": 1 / 12,
        "per year": 1 / 12,
        "hourly": 2080 / 12,
        "per hour": 2080 / 12,
        "weekly": 52 / 12,
        "per week": 52 / 12,
        "fortnightly": 26 / 12,
        "biweekly": 26 / 12,
    }
    factor = factors.get(period.lower())
    return round(amount * factor, 2) if factor is not None else None


def salary_data(source: str, raw: dict[str, Any]) -> tuple[str | None, str | None, float | None, float | None, str]:
    """Return original, currency, monthly USD bounds, and a review status."""
    if source == "himalayas":
        low, high = raw.get("minSalary"), raw.get("maxSalary")
        if low is None and high is None:
            return None, raw.get("currency"), None, None, "undisclosed"
        currency = str(raw.get("currency") or "").upper() or None
        period = str(raw.get("salaryPeriod") or "annual")
        original = f"{currency or 'Currency unknown'} {low if low is not None else '?'}–{high if high is not None else '?'} / {period}"
        if currency != "USD":
            return original, currency, None, None, "review"
        min_month = _period_to_monthly(float(low), period) if low is not None else None
        max_month = _period_to_monthly(float(high), period) if high is not None else None
        if min_month is None and max_month is None:
            return original, currency, None, None, "review"
        return original, currency, min_month, max_month, "normalized"

    value = raw.get("salary")
    if not isinstance(value, str) or not value.strip() or "undisclosed" in value.lower() or "not provided" in value.lower():
        return None, None, None, None, "undisclosed"
    text = value.strip()
    # A bare "$" is ambiguous (CAD, AUD, etc.). Normalize only when USD is explicit.
    currency = "USD" if re.search(r"\bUSD\b|\bUS\$", text, re.I) else None
    if currency != "USD":
        return text, currency, None, None, "review"
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        number = float(match.group(1).replace(",", ""))
        if match.group(2):
            number *= 1000
        amounts.append(number)
    if not amounts:
        return text, currency, None, None, "review"
    period_match = re.search(r"\b(month(?:ly)?|year(?:ly)?|annual(?:ly)?|hour(?:ly)?|week(?:ly)?|fortnightly|biweekly)\b", text, re.I)
    if not period_match:
        return text, currency, None, None, "review"
    period = period_match.group(1).lower()
    if period.startswith("month"):
        period = "monthly"
    elif period.startswith("year") or period.startswith("annual"):
        period = "annual"
    elif period.startswith("hour"):
        period = "hourly"
    elif period.startswith("week"):
        period = "weekly"
    lo = _period_to_monthly(min(amounts), period)
    hi = _period_to_monthly(max(amounts), period)
    if lo is None or hi is None:
        return text, currency, None, None, "review"
    return text, currency, lo, hi, "normalized"


def _location_names(source: str, raw: dict[str, Any]) -> tuple[list[str], bool]:
    if source == "himalayas":
        restrictions = raw.get("locationRestrictions")
        if not isinstance(restrictions, list):
            return [], False
        names = [str(x.get("name", "")) for x in restrictions if isinstance(x, dict)]
        if not names and len(restrictions) == 0:
            return [], True
        return names, False
    value = raw.get("candidate_required_location")
    if not isinstance(value, str) or not value.strip():
        return [], False
    return [part.strip() for part in re.split(r"[,;|]", value) if part.strip()], False


def determine_eligibility(source: str, raw: dict[str, Any], config: dict[str, Any]) -> tuple[str, str, str]:
    geography = config.get("geography", {})
    names, unrestricted = _location_names(source, raw)
    text = ", ".join(names)
    low = text.casefold()
    brazil = str(geography.get("country", "Brazil")).casefold()
    br_code = str(geography.get("country_code", "BR")).casefold()
    latam_terms = [str(x).casefold() for x in geography.get("latam_terms", [])]
    worldwide_terms = [str(x).casefold() for x in geography.get("worldwide_terms", [])]
    incompatible_terms = [str(x).casefold() for x in geography.get("incompatible_terms", [])]

    def contains(term: str) -> bool:
        return term in low

    if any(contains(term) for term in incompatible_terms):
        return "ineligible", "Explicit incompatible country or region restriction", text or ""
    if unrestricted:
        return "confirmed_worldwide", "Himalayas reports no country restriction (worldwide)", "Worldwide"
    restrictions = raw.get("locationRestrictions")
    if contains(brazil) or contains("brasil") or (isinstance(restrictions, list) and any(
        isinstance(item, dict) and str(item.get("alpha2", "")).casefold() == br_code for item in restrictions
    )):
        return "confirmed_brazil", "Brazil is explicitly included", text or "Brazil"
    if any(contains(term) for term in latam_terms):
        return "confirmed_latam", "Brazil/LATAM is explicitly included", text
    if any(contains(term) for term in worldwide_terms):
        return "confirmed_worldwide", "Listing explicitly says worldwide/anywhere", text or "Worldwide"
    generic_remote = {"remote", "remote work", "remote worldwide", "not specified", "unspecified", "flexible"}
    if names and all(name.casefold().strip() in generic_remote for name in names):
        return "uncertain", "Remote listing does not confirm Brazilian eligibility", text
    if names:
        return "ineligible", "Explicit location list does not include Brazil or LATAM", text
    return "uncertain", "Remote listing does not confirm Brazilian eligibility", "Remote; eligibility unclear"


def normalize_job(source: str, raw: dict[str, Any], config: dict[str, Any]) -> Job | None:
    if source == "himalayas":
        job_id = raw.get("guid") or raw.get("id")
        title = raw.get("title")
        company = raw.get("companyName")
        location_raw = raw.get("locationRestrictions")
        location = ", ".join(str(x.get("name", "")) for x in location_raw if isinstance(x, dict)) if isinstance(location_raw, list) else ""
        employment = raw.get("employmentType")
        published = raw.get("pubDate")
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, timezone.utc).isoformat()
        description = raw.get("description") or raw.get("excerpt") or ""
        url = raw.get("applicationLink")
    elif source == "remotive":
        job_id = raw.get("id")
        title = raw.get("title")
        company = raw.get("company_name")
        location = raw.get("candidate_required_location") or "Remote; eligibility unclear"
        employment = raw.get("job_type")
        published = raw.get("publication_date")
        description = raw.get("description") or ""
        url = raw.get("url")
    else:
        raise ValueError(f"Unsupported job source: {source}")
    if not job_id or not isinstance(title, str) or not title.strip() or not isinstance(company, str) or not company.strip() or not valid_application_url(url):
        return None
    if len(str(description)) > int(config.get("pipeline", {}).get("max_description_chars", 50000)):
        description = str(description)[: int(config.get("pipeline", {}).get("max_description_chars", 50000))]
    eligibility, reason, normalized_location = determine_eligibility(source, raw, config)
    salary_original, currency, salary_min, salary_max, salary_status = salary_data(source, raw)
    return Job(
        job_id=f"{source}:{job_id}", source=source, company=company.strip(), title=title.strip(),
        location=location or normalized_location, eligibility=eligibility, eligibility_reason=reason,
        employment_type=str(employment).strip() if employment else None, salary_original=salary_original,
        salary_currency=currency, salary_min_monthly_usd=salary_min, salary_max_monthly_usd=salary_max,
        salary_status=salary_status, publication_date=str(published) if published is not None else None,
        description=plain_text(description), application_url=url.strip(),
    )
