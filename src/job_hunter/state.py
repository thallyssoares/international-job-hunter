from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class JobState:
    def __init__(self, path: str | Path, max_ids: int = 5000):
        self.path = Path(path)
        self.max_ids = max_ids
        self.notified = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            values = data.get("notified", {})
            if isinstance(values, list):
                return {str(value): "" for value in values}
            if not isinstance(values, dict):
                raise ValueError("'notified' must be an object or list")
            return {str(key): str(value) for key, value in values.items()}
        except (OSError, json.JSONDecodeError, AttributeError, ValueError) as exc:
            raise RuntimeError(f"Could not read notification state file {self.path}: {exc}") from exc

    def has(self, job_id: str) -> bool:
        return job_id in self.notified

    def mark_sent(self, job_id: str) -> None:
        self.notified[job_id] = datetime.now(timezone.utc).isoformat()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        limited = dict(list(self.notified.items())[-self.max_ids :])
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps({"notified": limited}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp_path, self.path)
        self.notified = limited
