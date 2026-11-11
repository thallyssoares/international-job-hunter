# International Job Hunter

Daily, profile-based discovery of international remote data and applied AI jobs, with optional private Telegram alerts. It uses public APIs, a deterministic scoring model, and a small JSON file in this repository for notification history. It needs no server, database, Docker, paid service, or LLM API.

## What it does

The GitHub Actions workflow runs at 09:00 `America/Fortaleza` (12:00 UTC) and can also be started manually. It looks for AI Engineer, AI Solutions Architect, GenAI/LLM Engineer, Data Engineer, and related roles. It ranks enterprise GenAI, agentic systems, RAG, relevant technologies, seniority, and confirmed eligibility in Brazil/LATAM/worldwide.

The desired salary floor is USD 3,000 per month. Ranges overlapping the floor (e.g. USD 2,500–6,000/month) are kept; only ranges known to be entirely below it are rejected. USD currency and pay period must be unambiguous to normalize. Undisclosed salaries remain eligible. Ambiguous or non-USD salaries are retained and flagged for review. A generic “Remote” location is marked uncertain; explicit locations excluding Brazil/LATAM are filtered out. Seniority years are never used as a hard rejection.

## How the pipeline works

`src/job_hunter/collectors/` contains independent source adapters. Each source is collected separately, so one outage does not block the other. The pipeline normalizes and validates fields and HTTPS application URLs, classifies geography and salary, filters, deduplicates across sources, ranks with an explainable score, and sends at most 10 new jobs in score order. Notification IDs are recorded in `data/state.json` only after Telegram confirms a message was delivered. Failed messages remain eligible for a later run.

If either Telegram secret is missing, the workflow still collects, validates, ranks, and logs candidate summaries without sending messages or marking them notified. `--dry-run` also disables delivery and state changes.

## Job sources

- [Himalayas Remote Jobs API](https://himalayas.app/docs/remote-jobs-api): public JSON feed at `https://himalayas.app/jobs/api`, using country-filtered, keyword-based searches (`/jobs/api/search`). The collector uses `applicationLink` for applying and includes Himalayas source attribution in notifications, as required by the API terms.
- [Remotive public API](https://github.com/remotive-com/remote-jobs-api): `https://remotive.com/api/remote-jobs`; its documented response includes a `jobs[]` array with `id`, `title`, `company_name`, `job_type`, `candidate_required_location`, `salary`, `description`, and `url`. The API recommends no more than four requests per day and requires a link to Remotive; this workflow requests it once per daily run and links the listing.

Both sources publish delayed/cached listings, and availability can change. The pipeline does not scrape LinkedIn or bypass access controls. To add another source, implement a collector in `src/job_hunter/collectors/` that returns source-native dictionaries, then add it in `src/job_hunter/main.py` and map its fields in `normalization.py`.

## Edit your search criteria

Edit [`config.yaml`](config.yaml) from the GitHub web interface on Android. It contains target titles, technology terms, accepted employment types, geography rules, salary floor, pagination, and alert limits. For example, add a phrase under `profile.title_terms` or adjust `salary.minimum_monthly_usd`. Generic remote roles are kept as `uncertain` for review, while explicit incompatible regions are excluded.

## Set up Telegram

1. In Telegram, open **@BotFather**, send `/newbot`, follow the prompts, and copy the bot token. Keep it private.
2. Open the new bot's chat and press **Start** (or send `/start`) so Telegram permits the bot to message you.
3. In your Android browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` (replace the placeholder with your token). Find `message` → `chat` → `id` in the JSON. For a private chat, this is your `TELEGRAM_CHAT_ID`. If the response has no updates, send `/start` to the bot again and reload the page. Do not share screenshots or the URL containing the token.
4. Open this repository on GitHub. Go to **Settings → Secrets and variables → Actions → New repository secret**. Add these two secrets exactly:
   - `TELEGRAM_BOT_TOKEN`: the token from BotFather.
   - `TELEGRAM_CHAT_ID`: the chat ID from `getUpdates`.

The secrets are read only by the workflow. They are not stored in project files or printed in logs.

## Run it from an Android browser

1. Open the repository on GitHub and tap **Actions**.
2. Select **International Job Hunter** in the workflow list.
3. Tap **Run workflow**, choose the `main` branch, then tap the green **Run workflow** button.
4. Open the run that appears to follow its progress. The first manual run is useful to confirm that both secrets are set and that a real Telegram message arrives.

GitHub Actions also runs every day at 09:00 Fortaleza time. GitHub may delay scheduled runs during busy periods. If secrets are not set, the run is a validation-only run with no Telegram messages.

## Check logs and troubleshoot

Open **Actions → International Job Hunter → a run → hunt** to inspect source counts, filter/ranking summaries, and delivery results. Logs never include the bot token.

- **No candidates:** the role, location, and salary criteria may be too narrow; edit `config.yaml`. Listings without salary are included.
- **Remote eligibility uncertain:** the API did not clearly confirm Brazil. The job is retained with that status so you can inspect its listing.
- **Source request failed:** the source is retried with bounded backoff. A healthy source can still complete the run. If both fail, the workflow fails clearly.
- **HTTP 429:** the collector honors a short `Retry-After`; the next daily run will retry if the provider remains rate limited.
- **Telegram message failed:** check both repository secrets, confirm you pressed **Start** in the bot chat, and check `TELEGRAM_CHAT_ID`. Successful messages from a partial run are persisted; failed ones will be retried next time.
- **Workflow cannot push state:** confirm Actions are enabled and the repository's Actions setting allows the workflow `GITHUB_TOKEN` to write contents. The workflow needs `contents: write` to persist `data/state.json`.
- **Invalid state file:** restore a valid JSON file shaped like `{ "notified": {} }` at `data/state.json` from the GitHub file editor.

## Development and tests

The workflow installs Python 3.12 dependencies and runs the mocked automated test suite before collecting jobs. Tests do not call real job APIs or Telegram. No live Telegram delivery is claimed until a workflow run with your secrets succeeds.

From a Python environment, run:

```sh
python -m pip install -r requirements.txt
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m job_hunter.main --dry-run
```

The API shapes were checked against the official [Himalayas API reference](https://himalayas.app/docs/remote-jobs-api), its [data dictionary](https://himalayas.app/docs/data-dictionary), and [Remotive API documentation](https://github.com/remotive-com/remote-jobs-api). The runtime used for this implementation had no usable outbound proxy, so live API requests were not validated from this environment; mocked response-shape tests and GitHub Actions logs cover runtime behavior once the workflow runs.

## Notes on the corrected version

The Himalayas collector now uses targeted country-filtered search rather than just the first pages of the broad feed. Bare `$` salaries on Remotive are treated as currency-uncertain unless USD is explicit. API responses are validated in tests with simulated data; the real endpoints still need a successful GitHub Actions run.
