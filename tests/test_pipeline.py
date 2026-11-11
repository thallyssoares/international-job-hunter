from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import requests

from job_hunter.collectors.himalayas import HimalayasCollector
from job_hunter.collectors.http import JsonClient
from job_hunter.collectors.remotive import RemotiveCollector
from job_hunter.filters import deduplicate, job_passes, title_matches
from job_hunter.main import run_pipeline
from job_hunter.models import Job
from job_hunter.normalization import determine_eligibility, normalize_job, salary_data
from job_hunter.notifications import TelegramNotifier
from job_hunter.ranking import rank_jobs
from job_hunter.state import JobState


CONFIG = {
    "profile": {
        "title_terms": ["ai engineer", "ai solutions architect", "genai", "llm engineer", "data engineer", "ai architect"],
        "technologies": ["Python", "SQL", "LangGraph", "MCP", "RAG", "Snowflake"],
        "employment_terms": ["full-time", "contractor", "contract", "b2b", "freelance"],
    },
    "geography": {
        "country": "Brazil", "country_code": "BR",
        "latam_terms": ["LATAM", "Latin America", "South America", "Brazil", "Brasil"],
        "worldwide_terms": ["worldwide", "work from anywhere", "anywhere", "global"],
        "incompatible_terms": ["USA only", "United States only", "Canada only", "Europe only"],
    },
    "salary": {"minimum_monthly_usd": 3000},
    "pipeline": {"max_description_chars": 50000, "max_notifications": 10},
}


def himalayas_job(**overrides):
    job = {
        "guid": "https://himalayas.app/companies/acme/jobs/ai-engineer",
        "title": "Senior GenAI Engineer",
        "companyName": "Acme",
        "employmentType": "Full Time",
        "minSalary": 36000,
        "maxSalary": 60000,
        "salaryPeriod": "annual",
        "currency": "USD",
        "locationRestrictions": [{"alpha2": "BR", "name": "Brazil", "slug": "brazil"}],
        "description": "Build enterprise RAG and multi-agent workflows in Python with LangGraph.",
        "applicationLink": "https://himalayas.app/companies/acme/jobs/ai-engineer",
        "pubDate": 1760000000,
    }
    job.update(overrides)
    return job


def remotive_job(**overrides):
    job = {
        "id": 42,
        "title": "Data Engineer",
        "company_name": "Acme",
        "job_type": "full_time",
        "candidate_required_location": "Brazil",
        "salary": "USD 4,000 - 6,000 per month",
        "publication_date": "2026-11-01T12:00:00",
        "description": "Python, SQL, Snowflake and APIs.",
        "url": "https://remotive.com/remote-jobs/data/data-engineer-42",
    }
    job.update(overrides)
    return job


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, params))
        return self.payloads.pop(0)


class FailedSession:
    def get(self, *args, **kwargs):
        raise requests.Timeout("timeout")


class FailedTelegramSession:
    def post(self, *args, **kwargs):
        raise requests.Timeout("timeout")


class OkResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


class Tests(unittest.TestCase):
    def test_title_variations(self):
        for title in ("LLM Engineer", "Senior AI Solutions Architect", "Generative AI Engineer", "Lead Data Engineer"):
            with self.subTest(title=title):
                self.assertTrue(title_matches(title, CONFIG))
        self.assertFalse(title_matches("Marketing Manager", CONFIG))
        self.assertFalse(title_matches("Retail Software Engineer", CONFIG))

    def test_salary_normalization_for_structured_himalayas_and_monthly_remotive(self):
        _, _, low, high, status = salary_data("himalayas", himalalayas := {"minSalary": 36000, "maxSalary": 72000, "currency": "USD", "salaryPeriod": "annual"})
        self.assertEqual((low, high, status), (3000.0, 6000.0, "normalized"))
        _, _, low, high, status = salary_data("remotive", {"salary": "USD 4,000 - 6,000 per month"})
        self.assertEqual((low, high, status), (4000.0, 6000.0, "normalized"))

    def test_non_usd_and_unclear_salary_are_reviewed_not_converted(self):
        _, currency, low, high, status = salary_data("himalayas", {"minSalary": 50000, "currency": "EUR", "salaryPeriod": "annual"})
        self.assertEqual((currency, low, high, status), ("EUR", None, None, "review"))
        _, _, low, high, status = salary_data("remotive", {"salary": "$70,000 - $90,000"})
        self.assertEqual((low, high, status), (None, None, "review"))

    def test_eligibility_distinguishes_brazil_latam_worldwide_uncertain_and_incompatible(self):
        self.assertEqual(determine_eligibility("remotive", {"candidate_required_location": "Brazil"}, CONFIG)[0], "confirmed_brazil")
        self.assertEqual(determine_eligibility("remotive", {"candidate_required_location": "LATAM"}, CONFIG)[0], "confirmed_latam")
        self.assertEqual(determine_eligibility("remotive", {"candidate_required_location": "Worldwide"}, CONFIG)[0], "confirmed_worldwide")
        self.assertEqual(determine_eligibility("remotive", {"candidate_required_location": "Remote"}, CONFIG)[0], "uncertain")
        self.assertEqual(determine_eligibility("remotive", {"candidate_required_location": "USA Only"}, CONFIG)[0], "ineligible")
        self.assertEqual(determine_eligibility("himalayas", {"locationRestrictions": []}, CONFIG)[0], "confirmed_worldwide")

    def test_filter_keeps_undisclosed_and_uncertain_salary_but_excludes_clear_low_salary(self):
        low = normalize_job("himalayas", himalalayas := himalayas_job(minSalary=24000, maxSalary=30000), CONFIG)
        self.assertFalse(job_passes(low, CONFIG)[0])
        unknown = normalize_job("himalayas", himalayas_job(minSalary=None, maxSalary=None), CONFIG)
        self.assertTrue(job_passes(unknown, CONFIG)[0])
        uncertain = normalize_job("remotive", remotive_job(candidate_required_location="Remote", salary="USD 2,000 - 3,000"), CONFIG)
        self.assertIsNotNone(uncertain)
        self.assertEqual(uncertain.salary_status, "review")
        self.assertTrue(job_passes(uncertain, CONFIG)[0])

    def test_ranking_is_deterministic_and_explainable(self):
        job = normalize_job("himalayas", himalayas_job(), CONFIG)
        ranked = rank_jobs([job], CONFIG)
        self.assertGreaterEqual(ranked[0].match_score, 70)
        self.assertIn("AI or GenAI engineering role", ranked[0].match_explanation)
        self.assertIn("Brazil eligibility confirmed", ranked[0].match_explanation)

    def test_deduplicates_ids_urls_and_cross_source_company_title(self):
        a = normalize_job("himalayas", himalayas_job(), CONFIG)
        same_url = normalize_job("remotive", remotive_job(company_name="Different", title="Other", url=a.application_url), CONFIG)
        same_company_title = normalize_job("remotive", remotive_job(id=43, title=a.title), CONFIG)
        self.assertEqual(len(deduplicate([a, same_url, same_company_title])), 1)

    def test_empty_api_results(self):
        self.assertEqual(HimalayasCollector(FakeClient([{"jobs": []}]), queries=["AI Engineer"]).collect(), [])
        self.assertEqual(RemotiveCollector(FakeClient([{"jobs": [], "job-count": 0}])).collect(), [])

    def test_himalayas_searches_for_brazil_and_paginates_by_page(self):
        page1 = [{"guid": f"job-{i}"} for i in range(20)]
        client = FakeClient([{"jobs": page1}, {"jobs": [{"guid": "job-20"}]}])
        jobs = HimalayasCollector(client, max_pages=3, queries=["AI Engineer"]).collect()
        self.assertEqual(len(jobs), 21)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0][1], {"q": "AI Engineer", "country": "BR", "sort": "recent", "page": 1})
        self.assertEqual(client.calls[1][1]["page"], 2)

    def test_himalayas_search_keeps_results_when_a_later_query_fails(self):
        class SometimesFailClient:
            def get_json(self, url, params=None):
                if params["q"] == "LLM Engineer":
                    raise RuntimeError("upstream failure")
                return {"jobs": [{"guid": "job-1", "title": "AI Engineer"}]}
        jobs = HimalayasCollector(SometimesFailClient(), queries=["AI Engineer", "LLM Engineer"]).collect()
        self.assertEqual(len(jobs), 1)

    def test_salary_range_overlapping_minimum_is_kept(self):
        job = normalize_job("himalayas", himalayas_job(minSalary=30000, maxSalary=72000), CONFIG)
        self.assertTrue(job_passes(job, CONFIG)[0])
        self.assertEqual(job.salary_min_monthly_usd, 2500)
        self.assertEqual(job.salary_max_monthly_usd, 6000)

    def test_dollar_sign_without_currency_is_reviewed(self):
        self.assertEqual(salary_data("remotive", {"salary": "$5,000 per month"})[-1], "review")

    def test_failed_external_request_retries_are_bounded(self):
        with self.assertRaisesRegex(RuntimeError, "failed after retries"):
            JsonClient(max_retries=0, session=FailedSession()).get_json("https://example.com/jobs")

    def test_invalid_urls_and_malformed_rows_are_skipped(self):
        self.assertIsNone(normalize_job("himalayas", himalayas_job(applicationLink="http://insecure.example/job"), CONFIG))
        self.assertIsNone(normalize_job("remotive", {"id": 1, "title": "AI Engineer", "company_name": "x", "url": "javascript:alert(1)"}, CONFIG))

    def test_state_persistence_and_malformed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = JobState(path)
            state.mark_sent("himalayas:one")
            self.assertTrue(JobState(path).has("himalayas:one"))
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                JobState(path)

    def test_notification_failure_does_not_mark_job_sent(self):
        job = normalize_job("himalayas", himalayas_job(), CONFIG)
        class OneCollector:
            source = "himalayas"
            def collect(self):
                return [himalayas_job()]
        with tempfile.TemporaryDirectory() as directory:
            state = JobState(Path(directory) / "state.json")
            notifier = TelegramNotifier("secret", "chat", session=FailedTelegramSession())
            result = run_pipeline(CONFIG, [OneCollector()], notifier, state)
            self.assertEqual(result["notification_failures"], 1)
            self.assertFalse(state.has(job.job_id))

    def test_successful_notification_marks_state_only_after_delivery(self):
        class OneCollector:
            source = "himalayas"
            def collect(self):
                return [himalayas_job()]
        class OkSession:
            def post(self, *args, **kwargs):
                return OkResponse()
        with tempfile.TemporaryDirectory() as directory:
            state = JobState(Path(directory) / "state.json")
            notifier = TelegramNotifier("secret", "chat", session=OkSession())
            result = run_pipeline(CONFIG, [OneCollector()], notifier, state)
            self.assertEqual(result["sent"], 1)
            self.assertTrue(JobState(state.path).has("himalayas:https://himalayas.app/companies/acme/jobs/ai-engineer"))

    def test_one_failed_source_does_not_stop_the_other(self):
        class BadCollector:
            source = "bad"
            def collect(self):
                raise RuntimeError("offline")
        class EmptyCollector:
            source = "empty"
            def collect(self):
                return []
        with tempfile.TemporaryDirectory() as directory:
            result = run_pipeline(CONFIG, [BadCollector(), EmptyCollector()], None, JobState(Path(directory) / "state.json"))
            self.assertEqual(result["source_failures"], 1)


if __name__ == "__main__":
    unittest.main()
