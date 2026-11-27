"""Job store: persisted JSON, in-flight de-duplication and a result cache keyed by seed hash."""

import hashlib
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

ACTIVE = ("pending", "running")


def seed_key(seed_material: str) -> str:
    return hashlib.sha256(seed_material.strip().encode("utf-8")).hexdigest()


class JobStore:
    def __init__(self, state_dir: str, cache_ttl_s: int) -> None:
        self.path = os.path.join(state_dir, "jobs.json")
        self.cache_ttl_s = cache_ttl_s
        self._lock = threading.RLock()
        os.makedirs(state_dir, exist_ok=True)
        self._jobs: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._jobs = json.load(f)
            except (OSError, ValueError):
                self._jobs = {}
        # Jobs that were in flight when the adapter stopped can't be resumed.
        for job in self._jobs.values():
            if job.get("status") in ACTIVE:
                job["status"] = "failed"
                job["error"] = "adapter restarted while job was running"
        self._save()

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._jobs, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def find_reusable(self, key: str) -> Optional[Dict[str, Any]]:
        """An in-flight job for this seed, or a completed one still inside the cache TTL."""
        now = time.time()
        with self._lock:
            best = None
            for job in self._jobs.values():
                if job.get("seed_key") != key:
                    continue
                if job["status"] in ACTIVE:
                    return dict(job)
                if job["status"] == "completed" and now - job.get("finished_at", 0) <= self.cache_ttl_s:
                    if best is None or job["finished_at"] > best["finished_at"]:
                        best = job
            return dict(best) if best else None

    def runs_started_since(self, since: float) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.get("created_at", 0) >= since and not j.get("cached"))

    def create(self, key: str) -> Dict[str, Any]:
        job = {
            "id": "mfa_" + uuid.uuid4().hex[:16],
            "seed_key": key,
            "status": "pending",
            "progress": 0,
            "stage": "queued",
            "created_at": time.time(),
        }
        with self._lock:
            self._jobs[job["id"]] = job
            self._save()
        return dict(job)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)
                self._save()
