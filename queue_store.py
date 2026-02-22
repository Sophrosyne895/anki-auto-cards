"""Atomic file-based persistent card queue."""
import json
import logging
import os
from typing import Any

from config import PENDING_CARDS_FILE

logger = logging.getLogger(__name__)


def _load() -> list[dict[str, Any]]:
    if not PENDING_CARDS_FILE.exists():
        return []
    try:
        return json.loads(PENDING_CARDS_FILE.read_text())
    except Exception:
        logger.exception("Failed to read pending cards file; starting fresh")
        return []


def _save(cards: list[dict[str, Any]]) -> None:
    tmp = PENDING_CARDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cards, indent=2))
    os.replace(tmp, PENDING_CARDS_FILE)


def enqueue_cards(cards: list[dict[str, Any]]) -> None:
    existing = _load()
    existing.extend(cards)
    _save(existing)
    logger.info("Enqueued %d cards to persistent queue (total: %d)", len(cards), len(existing))


def dequeue_all() -> list[dict[str, Any]]:
    cards = _load()
    if cards:
        _save([])
    return cards


def peek_depth() -> int:
    return len(_load())
