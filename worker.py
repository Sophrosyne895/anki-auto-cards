"""Background worker: job queue processing and persistent card retry."""
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import anki_connect
import cards as card_gen
import queue_store
import transcribe
from config import QUEUE_RETRY_INTERVAL

logger = logging.getLogger(__name__)

_job_queue: queue.Queue = queue.Queue()


@dataclass
class Job:
    url: str
    job_id: str
    attempt: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def submit_job(url: str, job_id: str) -> None:
    job = Job(url=url, job_id=job_id)
    _job_queue.put(job)
    logger.info("Job submitted: id=%s url=%s", job_id, url)


def _process_job(job: Job) -> None:
    logger.info("[%s] Starting processing: %s", job.job_id, job.url)

    try:
        transcript, title = transcribe.get_transcript(job.url)
    except Exception:
        logger.exception("[%s] Transcription failed; dropping job", job.job_id)
        return

    try:
        generated_cards = card_gen.generate_cards(transcript, job.url, title)
    except Exception:
        logger.exception("[%s] Card generation failed; dropping job", job.job_id)
        return

    if not generated_cards:
        logger.warning("[%s] No cards generated", job.job_id)
        return

    if anki_connect.is_anki_running():
        try:
            result = anki_connect.add_notes_bulk(generated_cards)
            logger.info("[%s] Cards pushed to Anki: %s", job.job_id, result)
        except Exception:
            logger.exception("[%s] AnkiConnect push failed; queuing cards", job.job_id)
            queue_store.enqueue_cards(generated_cards)
    else:
        logger.info("[%s] Anki not running; queuing %d cards", job.job_id, len(generated_cards))
        queue_store.enqueue_cards(generated_cards)


def _flush_pending_cards() -> None:
    depth = queue_store.peek_depth()
    if depth == 0:
        return
    if not anki_connect.is_anki_running():
        return

    logger.info("Flushing %d pending cards to Anki", depth)
    pending = queue_store.dequeue_all()
    if not pending:
        return

    try:
        result = anki_connect.add_notes_bulk(pending)
        logger.info("Flush complete: %s", result)
    except Exception:
        logger.exception("Flush failed; re-queuing cards")
        queue_store.enqueue_cards(pending)


def _worker_loop() -> None:
    last_flush = 0.0
    while True:
        # Try to get a job with a timeout so we can also run periodic flush
        try:
            job = _job_queue.get(timeout=QUEUE_RETRY_INTERVAL)
            _process_job(job)
            _job_queue.task_done()
        except queue.Empty:
            pass

        now = time.monotonic()
        if now - last_flush >= QUEUE_RETRY_INTERVAL:
            _flush_pending_cards()
            last_flush = now


def start_worker() -> None:
    t = threading.Thread(target=_worker_loop, daemon=True, name="anki-worker")
    t.start()
    logger.info("Background worker started")
