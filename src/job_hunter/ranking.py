from __future__ import annotations

from .models import Job


def score_job(job: Job, config: dict) -> tuple[int, str]:
    title = job.title.casefold()
    text = f"{job.title} {job.description}".casefold()
    points: list[tuple[int, str]] = []

    if "architect" in title:
        points.append((30, "AI/solutions architecture role"))
    elif any(term in title for term in ("genai", "generative ai", "llm", "ai engineer", "artificial intelligence engineer")):
        points.append((30, "AI or GenAI engineering role"))
    elif "data engineer" in title:
        points.append((25, "Data Engineering role"))
    elif "machine learning engineer" in title:
        points.append((25, "Applied ML engineering role"))
    else:
        points.append((20, "Relevant engineering title"))

    if any(term in text for term in ("enterprise genai", "enterprise generative ai", "production genai", "production ai")):
        points.append((15, "enterprise or production GenAI"))
    if any(term in text for term in ("multi-agent", "multi agent", "agentic", "ai agents", "llm agents")):
        points.append((12, "AI agents or agentic systems"))
    if any(term in text for term in (" rag ", "retrieval augmented", "retrieval-augmented", "vector search")):
        points.append((10, "RAG or retrieval systems"))

    technologies = [str(value) for value in config.get("profile", {}).get("technologies", [])]
    matched = [tech for tech in technologies if tech.casefold() in text]
    if matched:
        points.append((min(16, 2 * len(matched)), "stack: " + ", ".join(matched[:5])))

    if any(level in title for level in ("mid", "senior", "staff", "lead", "principal", "architect")):
        points.append((8, "target seniority"))
    if job.eligibility == "confirmed_brazil":
        points.append((15, "Brazil eligibility confirmed"))
    elif job.eligibility == "confirmed_latam":
        points.append((12, "LATAM eligibility confirmed"))
    elif job.eligibility == "confirmed_worldwide":
        points.append((9, "worldwide eligibility confirmed"))
    else:
        points.append((0, "Brazil eligibility needs review"))
    if job.salary_status == "undisclosed":
        points.append((2, "salary undisclosed; retained for review"))
    elif job.salary_status == "review":
        points.append((1, "salary details need review"))
    elif job.salary_min_monthly_usd is not None and job.salary_min_monthly_usd >= float(config.get("salary", {}).get("minimum_monthly_usd", 3000)):
        points.append((5, "salary meets desired floor"))

    total = min(100, sum(points_value for points_value, _ in points))
    explanation = "; ".join(reason for _, reason in points if reason)
    job.match_score = total
    job.match_explanation = explanation
    return total, explanation


def rank_jobs(jobs: list[Job], config: dict) -> list[Job]:
    for job in jobs:
        score_job(job, config)
    return sorted(jobs, key=lambda job: (-job.match_score, job.title.casefold(), job.company.casefold(), job.job_id))
