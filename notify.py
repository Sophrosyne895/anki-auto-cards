"""Push notifications via ntfy.sh."""
import logging
import urllib.request
import urllib.error

from config import NTFY_TOPIC

logger = logging.getLogger(__name__)


def send(title: str, message: str) -> None:
    if not NTFY_TOPIC:
        return

    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    req = urllib.request.Request(url, data=message.encode("utf-8"), method="POST")
    req.add_header("Title", title)

    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        logger.exception("ntfy notification failed")
