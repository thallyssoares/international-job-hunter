from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .collectors.himalayas import HimalayasCollector
from .collectors.remotive import RemotiveCollector
from .filters import deduplicate, job_passes
from .normalization import normalize_job
from .notifications import TelegramNotifier
from .ranking import rank_jobs
from .state import JobState

LOG = logging.getLogger("job_hunter")
ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | Path = ROOT / "config.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML object")
    return config


def run_pipeline(
    config: dict[str, Any],
    collectors: list[Any],
    notifier: TelegramNotifier | None,
    state: JobState,
    dry_run: bool = False,
) -> dict[str, int]:
    gathered = []
    successful_sources = 0
    failed_sources = 0
    for collector in collectors:
        try:
            source_jobs = collector.collect()
            successful_sources += 1
            LOG.info("Collected %d raw jobs from %s", len(source_jobs), collector.source)
            gathered.extend((collector.source, raw) for raw in source_jobs)
        except Exception as exc:  # Keep one independent source from stopping the other.
            failed_sources += 1
            LOG.error("Collector %s failed (%s): %s", collector.source, type(exc).__name__, exc)
    if successful_sources == 0:
        raise RuntimeError("All job sources failed; no pipeline results can be trusted")

    normalized = []
    invalid = 0
    for source, raw in gathered:
        try:
            job = normalize_job(source, raw, config)
        except Exception as exc:
            LOG.warning("Skipping malformed %s job (%s)", source, type(exc).__name__)
            invalid += 1
            continue
        if job is None:
            invalid += 1
            continue
        passes, reason = job_passes(job, config)
        if passes:
            normalized.append(job)
        else:
            LOG.debug("Filtered %s: %s", job.job_id, reason)

    unique = deduplicate(normalized)
    ranked = rank_jobs(unique, config)
    new_jobs = [job for job in ranked if not state.has(job.job_id)]
    limit = int(config.get("pipeline", {}).get("max_notifications", 10))
    selected = new_jobs[:limit]
    LOG.info(
        "Pipeline summary: collected=%d valid_candidates=%d deduplicated=%d new=%d selected=%d invalid=%d source_failures=%d",
        len(gathered), len(normalized), len(unique), len(new_jobs), len(selected), invalid, failed_sources,
    )
    for job in selected:
        LOG.info("Candidate score=%d title=%s company=%s eligibility=%s", job.match_score, job.title, job.company, job.eligibility)

    if dry_run or notifier is None:
        LOG.info("Telegram delivery disabled; state left unchanged")
        return {"selected": len(selected), "sent": 0, "notification_failures": 0, "source_failures": failed_sources}

    sent = 0
    notification_failures = 0
    for job in selected:
        if notifier.send(job):
            state.mark_sent(job.job_id)
            sent += 1
            LOG.info("Telegram delivery succeeded for %s", job.job_id)
        else:
            notification_failures += 1
    return {"selected": len(selected), "sent": sent, "notification_failures": notification_failures, "source_failures": failed_sources}


def main() -> int:
    parser = argparse.ArgumentParser(description="Find international remote roles and notify through Telegram")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Collect and rank without sending or changing state")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")

    config = load_config(args.config)
    pipeline = config.get("pipeline", {})
    state_path = Path(pipeline.get("state_path", "data/state.json"))
    if not state_path.is_absolute():
        state_path = ROOT / state_path
    state = JobState(state_path)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    notifier = None
    if not args.dry_run and token and chat_id:
        notifier = TelegramNotifier(token, chat_id, timeout=int(pipeline.get("request_timeout_seconds", 25)))
    elif not args.dry_run:
        LOG.warning("Telegram secrets are not both configured; running in non-notifying mode")

    collectors = [
        HimalayasCollector(
            max_pages=int(pipeline.get("max_himalayas_pages", 3)),
            queries=pipeline.get("himalayas_search_queries"),
            country=str(config.get("geography", {}).get("country_code", "BR")),
        ),
        RemotiveCollector(),
    ]
    try:
        result = run_pipeline(config, collectors, notifier, state, dry_run=args.dry_run)
    except Exception as exc:
        LOG.exception("Pipeline failed: %s", exc)
        return 1
    if result["notification_failures"]:
        LOG.error("%d Telegram messages failed; successful deliveries were persisted", result["notification_failures"])
        return 1
    LOG.info("Run complete: %d selected, %d delivered", result["selected"], result["sent"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
