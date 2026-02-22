"""Groq LLM card generation."""
import json
import logging
import re
from urllib.parse import urlparse

from groq import Groq

from config import GROQ_API_KEY, LLM_MODEL, MIN_CARDS, MAX_CARDS

logger = logging.getLogger(__name__)

_groq = Groq(api_key=GROQ_API_KEY)

_SYSTEM_PROMPT = f"""\
You are an expert at creating Anki flashcards following the SuperMemo Twenty Rules of Formulating Knowledge.
Given a transcript, generate {MIN_CARDS}–{MAX_CARDS} high-quality flashcards.

CARD TYPES — use whichever fits best, aim for roughly 50% each:

1. Basic cards — for concepts, explanations, causes, and reasoning:
   {{"type": "basic", "front": "Why did X happen?", "back": "X happened because Y. For example, Z."}}

2. Cloze deletion cards — for facts, definitions, names, dates, quantities:
   {{"type": "cloze", "text": "The Roman army used {{{{c1::pilum}}}} as their primary throwing weapon."}}
   - Use {{{{c1::answer}}}} syntax — one cloze per card (c1 only)
   - The full sentence must be self-contained and meaningful without extra context

RULES (follow strictly):

Minimum information principle (Rule 4):
- Each card tests exactly ONE atomic fact or concept
- Never combine multiple facts into one card
- Simple cards are always better than complex ones

Avoid sets and enumerations (Rules 9, 10):
- Never create a card like "What are the 5 causes of X?" with a list answer
- Instead, make one card per item: "What was the PRIMARY cause of X?" / "What role did Y play in causing X?"

Combat interference (Rule 11):
- When two concepts are similar, make the question specific enough to distinguish them
- Add context cues to prevent confusion between related ideas

Optimize wording (Rule 12):
- Remove all filler words — every word must earn its place
- Front: a precise, specific question (no yes/no questions)
- Back: the shortest possible complete answer, 1–3 sentences max

Use examples (Rule 14):
- Anchor abstract concepts with a concrete example in the answer
- Prefer specific, vivid examples over generic ones

Redundancy is fine (Rule 17):
- The same concept can appear on multiple cards from different angles
- E.g. one card asking for the cause, another for the effect, another for the example

Prioritize (Rule 20):
- Focus on the most important, surprising, or actionable insights
- Skip trivial details: co-host names, timestamps, sponsors, filler anecdotes

Plain text only — no markdown, no bullet points in answers.

Respond ONLY with a JSON array. No explanation, no markdown fences.
"""


def _sanitize_tag(url: str) -> str:
    parsed = urlparse(url)
    tag = f"{parsed.netloc}{parsed.path}".replace("/", "_").strip("_")
    # Anki tags cannot contain spaces
    return re.sub(r"[^\w\-.]", "_", tag)[:100]


def _extract_json(text: str) -> list[dict]:
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting array from within the text
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try extracting individual JSON objects
    objects = re.findall(r'\{[^{}]+\}', text, re.DOTALL)
    if objects:
        cards = []
        for obj in objects:
            try:
                cards.append(json.loads(obj))
            except json.JSONDecodeError:
                continue
        if cards:
            return cards

    raise ValueError("Could not extract JSON from LLM response")


# Max chars per LLM chunk (~9k tokens for transcript, leaving room for prompt + response)
_CHUNK_CHARS = 30_000


def _call_llm(
    transcript_chunk: str,
    url: str,
    chunk_index: int,
    total_chunks: int,
    min_cards: int = MIN_CARDS,
    max_cards: int = MAX_CARDS,
) -> list[dict]:
    """Send one transcript chunk to the LLM and return raw parsed cards."""
    chunk_note = ""
    if total_chunks > 1:
        chunk_note = f" (part {chunk_index + 1} of {total_chunks})"

    system = _SYSTEM_PROMPT.replace(
        f"{MIN_CARDS}–{MAX_CARDS} high-quality flashcards",
        f"{min_cards}–{max_cards} high-quality flashcards",
    )
    response = _groq.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Source URL: {url}{chunk_note}\n\nTranscript:\n{transcript_chunk}"},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    raw = response.choices[0].message.content or ""
    logger.debug("LLM chunk %d raw response: %d chars", chunk_index + 1, len(raw))
    return _extract_json(raw)


def _validate_cards(raw_cards: list[dict], tags: list[str]) -> list[dict]:
    """Validate and normalize raw LLM card output."""
    valid = []
    for card in raw_cards:
        if not isinstance(card, dict):
            continue
        card_type = str(card.get("type", "basic")).strip().lower()
        if card_type == "cloze":
            text = str(card.get("text", "")).strip()
            if not text or "{{c1::" not in text:
                continue
            valid.append({"type": "cloze", "text": text, "tags": tags})
        else:
            front = str(card.get("front", "")).strip()
            back = str(card.get("back", "")).strip()
            if not front or not back:
                continue
            valid.append({"type": "basic", "front": front, "back": back, "tags": tags})
    return valid


def generate_cards(transcript: str, url: str, title: str = "") -> list[dict]:
    """Generate Anki cards from transcript, chunking if needed to fit Groq TPM limits."""
    tag = _sanitize_tag(url)
    tags = ["auto-generated", tag]

    # Split transcript into chunks
    chunks = [transcript[i:i + _CHUNK_CHARS] for i in range(0, len(transcript), _CHUNK_CHARS)]
    total_chunks = len(chunks)

    # Distribute the total card budget evenly across chunks
    cards_per_chunk = max(3, MIN_CARDS // total_chunks)
    max_per_chunk = max(5, MAX_CARDS // total_chunks)
    logger.info(
        "Generating cards via %s for url=%s (%d chunk(s), %d–%d cards/chunk, %d–%d total)",
        LLM_MODEL, url, total_chunks, cards_per_chunk, max_per_chunk, MIN_CARDS, MAX_CARDS,
    )

    all_cards = []
    for i, chunk in enumerate(chunks):
        try:
            raw = _call_llm(chunk, url, i, total_chunks, cards_per_chunk, max_per_chunk)
            valid = _validate_cards(raw, tags)
            logger.info("Chunk %d/%d: %d valid cards", i + 1, total_chunks, len(valid))
            all_cards.extend(valid)
        except Exception:
            logger.exception("Card generation failed for chunk %d/%d; skipping", i + 1, total_chunks)

    # Append source link to each card
    link_label = title if title else "Source"
    source_html = f'<br><br><a href="{url}">[{link_label}]</a>'
    for card in all_cards:
        if card["type"] == "cloze":
            card["source_html"] = source_html
        else:
            card["back"] += source_html

    logger.info("Generated %d total valid cards across %d chunk(s)", len(all_cards), total_chunks)
    return all_cards
