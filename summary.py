"""Generate a one-page Markdown summary and save to Obsidian vault."""
import logging
import re
from datetime import date
from pathlib import Path

from groq import Groq

from config import GROQ_API_KEY, LLM_MODEL, OBSIDIAN_SUMMARY_DIR

logger = logging.getLogger(__name__)

_groq = Groq(api_key=GROQ_API_KEY)

_SYSTEM_PROMPT = """\
You are an expert summarizer. Given a transcript, produce a concise one-page \
summary in Markdown format.

Structure:
- A 2–3 sentence **TL;DR** at the top
- 3–6 sections with descriptive `##` headings covering the key topics
- Each section: 2–4 sentences of clear, information-dense prose
- End with a `## Key Takeaways` section containing 3–5 bullet points

Rules:
- Write at a college/graduate level — preserve nuance and technical detail
- No filler, no fluff, no "In this video the host discusses…"
- Use plain Markdown — no HTML, no images
- Keep total length under 800 words
"""

# Same chunk size as cards.py
_CHUNK_CHARS = 30_000


def _sanitize_filename(title: str) -> str:
    """Turn a title into a safe filename (no path separators or special chars)."""
    name = re.sub(r"[^\w\s\-]", "", title)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if name else "Untitled"


def generate_summary(transcript: str, url: str, title: str = "") -> str:
    """Call the LLM to produce a Markdown summary of the transcript."""
    # If transcript is very long, take the first and last chunks to stay within limits
    if len(transcript) > _CHUNK_CHARS * 2:
        transcript = transcript[:_CHUNK_CHARS] + "\n\n[...]\n\n" + transcript[-_CHUNK_CHARS:]

    label = title or url
    response = _groq.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Title: {label}\nSource: {url}\n\nTranscript:\n{transcript}",
            },
        ],
        temperature=0.3,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def save_summary(summary_md: str, url: str, title: str = "") -> Path:
    """Save Markdown summary to the Obsidian vault. Returns the file path."""
    OBSIDIAN_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(title or url)
    today = date.today().isoformat()

    # Build the full note with YAML frontmatter
    frontmatter = (
        "---\n"
        f"source: {url}\n"
        f"date: {today}\n"
        f"tags: [auto-summary]\n"
        "---\n\n"
    )
    heading = f"# {title}\n\n" if title else ""
    content = frontmatter + heading + summary_md + "\n"

    path = OBSIDIAN_SUMMARY_DIR / f"{filename}.md"

    # Avoid overwriting: append a number if the file already exists
    counter = 2
    while path.exists():
        path = OBSIDIAN_SUMMARY_DIR / f"{filename} {counter}.md"
        counter += 1

    path.write_text(content, encoding="utf-8")
    logger.info("Summary saved to %s", path)
    return path
