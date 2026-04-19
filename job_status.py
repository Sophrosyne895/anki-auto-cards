"""In-memory job status tracker."""
import threading
import time
from dataclasses import dataclass, field

_lock = threading.Lock()
_jobs: dict[str, "JobStatus"] = {}

# Keep completed jobs around for a while so you can check them
_MAX_COMPLETED_AGE = 3600  # 1 hour


@dataclass
class JobStatus:
    job_id: str
    url: str
    stage: str = "queued"
    detail: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        elapsed = time.time() - self.started_at
        return {
            "job_id": self.job_id,
            "url": self.url,
            "stage": self.stage,
            "detail": self.detail,
            "elapsed": f"{elapsed:.0f}s",
        }


def create(job_id: str, url: str) -> None:
    with _lock:
        _jobs[job_id] = JobStatus(job_id=job_id, url=url)


def update(job_id: str, stage: str, detail: str = "") -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].stage = stage
            _jobs[job_id].detail = detail
            _jobs[job_id].updated_at = time.time()


def get_all() -> list[dict]:
    now = time.time()
    with _lock:
        # Prune old completed/failed jobs
        to_remove = [
            jid for jid, js in _jobs.items()
            if js.stage in ("done", "failed") and now - js.updated_at > _MAX_COMPLETED_AGE
        ]
        for jid in to_remove:
            del _jobs[jid]

        # Active first, then recent completed
        active = []
        completed = []
        for js in _jobs.values():
            if js.stage in ("done", "failed"):
                completed.append(js.to_dict())
            else:
                active.append(js.to_dict())
        return active + completed
