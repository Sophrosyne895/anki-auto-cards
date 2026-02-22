"""AnkiConnect HTTP client."""
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from config import ANKI_CONNECT_URL, ANKI_CONNECT_VERSION, DECK_NAME

logger = logging.getLogger(__name__)


def _request(action: str, **params: Any) -> Any:
    payload = json.dumps({
        "action": action,
        "version": ANKI_CONNECT_VERSION,
        "params": params,
    }).encode()
    req = urllib.request.Request(ANKI_CONNECT_URL, payload, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("error"):
        raise RuntimeError(f"AnkiConnect error: {data['error']}")
    return data.get("result")


def is_anki_running() -> bool:
    try:
        _request("version")
        return True
    except Exception:
        return False


def ensure_deck_exists(deck_name: str = DECK_NAME) -> None:
    decks = _request("deckNames")
    if deck_name not in decks:
        _request("createDeck", deck=deck_name)
        logger.info("Created deck: %s", deck_name)


def add_notes_bulk(cards: list[dict[str, Any]]) -> dict[str, int]:
    """Add a list of card dicts to Anki. Returns counts of added/skipped/failed."""
    ensure_deck_exists()

    notes = []
    for card in cards:
        tags = card.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if card.get("type") == "cloze":
            notes.append({
                "deckName": DECK_NAME,
                "modelName": "Cloze",
                "fields": {
                    "Text": card["text"],
                    "Back Extra": card.get("source_html", ""),
                },
                "options": {"allowDuplicate": False},
                "tags": tags,
            })
        else:
            notes.append({
                "deckName": DECK_NAME,
                "modelName": "Basic",
                "fields": {
                    "Front": card["front"],
                    "Back": card["back"],
                },
                "options": {"allowDuplicate": False},
                "tags": tags,
            })

    results = _request("addNotes", notes=notes)

    added = sum(1 for r in results if r is not None)
    skipped = sum(1 for r in results if r is None)
    logger.info("AnkiConnect: added=%d skipped=%d", added, skipped)
    return {"added": added, "skipped": skipped, "failed": 0}
