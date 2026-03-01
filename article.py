"""Article text extraction for web pages (blog posts, news, documentation, etc.)."""
import logging

import trafilatura
from trafilatura.settings import use_config

logger = logging.getLogger(__name__)

# Increase trafilatura's download timeout and disable its own sleep to let us control timing
_traf_config = use_config()
_traf_config.set("DEFAULT", "DOWNLOAD_TIMEOUT", "20")


def get_article_text(url: str) -> tuple[str, str]:
    """Fetch a web article and extract its main text and title.

    Returns (text, title). Raises RuntimeError if extraction fails or yields
    too little content (likely not a readable article).
    """
    logger.info("Fetching article: %s", url)
    downloaded = trafilatura.fetch_url(url, config=_traf_config)
    if not downloaded:
        raise RuntimeError(f"Failed to download URL: {url}")

    result = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        output_format="json",
        with_metadata=True,
        config=_traf_config,
    )
    if not result:
        raise RuntimeError(f"trafilatura could not extract content from: {url}")

    import json
    data = json.loads(result)
    text = data.get("text") or ""
    title = data.get("title") or ""

    if len(text) < 300:
        raise RuntimeError(
            f"Extracted text too short ({len(text)} chars) — probably not a readable article: {url}"
        )

    logger.info("Article extracted: %d chars, title=%r", len(text), title)
    return text, title
