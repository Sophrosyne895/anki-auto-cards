"""Background worker: job queue processing and persistent card retry."""
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import anki_connect
import cards as card_gen
import job_status
import notify
import queue_store
import summary as summary_gen
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
    job_status.create(job_id, url)
    _job_queue.put(job)
    logger.info("Job submitted: id=%s url=%s", job_id, url)


def _process_job(job: Job) -> None:
    logger.info("[%s] Starting processing: %s", job.job_id, job.url)
    job_status.update(job.job_id, "transcribing")

    label = job.url

    try:
        transcript, title = transcribe.get_transcript(job.url, job.job_id)
        if title:
            label = title
    except Exception:
        logger.exception("[%s] Transcription failed; dropping job", job.job_id)
        job_status.update(job.job_id, "failed", "transcription error")
        notify.send("Anki Pipeline Failed", f"Transcription failed for {job.url}")
        return

    notify.send("Anki Pipeline", f"Transcription done for {label} — generating summary & cards")

    # Generate summary and save to Obsidian (non-blocking for card pipeline)
    job_status.update(job.job_id, "summarizing", label)
    try:
        md = summary_gen.generate_summary(transcript, job.url, title)
        summary_path = summary_gen.save_summary(md, job.url, title)
        logger.info("[%s] Summary saved: %s", job.job_id, summary_path)
        notify.send("Summary Saved", f"{label} → Obsidian")
    except Exception:
        logger.exception("[%s] Summary generation failed; continuing with cards", job.job_id)
        notify.send("Anki Pipeline", f"Summary failed for {label}, continuing with cards")

    job_status.update(job.job_id, "generating cards", label)
    try:
        generated_cards = card_gen.generate_cards(transcript, job.url, title)
    except Exception:
        logger.exception("[%s] Card generation failed; dropping job", job.job_id)
        job_status.update(job.job_id, "failed", "card generation error")
        notify.send("Anki Pipeline Failed", f"Card generation failed for {label}")
        return

    if not generated_cards:
        logger.warning("[%s] No cards generated", job.job_id)
        job_status.update(job.job_id, "done", "no cards generated")
        notify.send("Anki Pipeline", f"No cards generated for {label}")
        return

    job_status.update(job.job_id, "pushing to anki", f"{len(generated_cards)} cards")
    if anki_connect.is_anki_running():
        try:
            result = anki_connect.add_notes_bulk(generated_cards)
            logger.info("[%s] Cards pushed to Anki: %s", job.job_id, result)
            job_status.update(job.job_id, "done", f"{result['added']} cards added")
            notify.send("Anki Cards Added", f"{result['added']} cards from {label}")
        except Exception:
            logger.exception("[%s] AnkiConnect push failed; queuing cards", job.job_id)
            job_status.update(job.job_id, "done", f"{len(generated_cards)} cards queued (Anki error)")
            queue_store.enqueue_cards(generated_cards)
    else:
        logger.info("[%s] Anki not running; queuing %d cards", job.job_id, len(generated_cards))
        job_status.update(job.job_id, "done", f"{len(generated_cards)} cards queued (Anki offline)")
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
