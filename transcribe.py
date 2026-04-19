"""Transcript fetching: YouTube transcript API, article extraction, or yt-dlp + Groq Whisper."""
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from groq import Groq, RateLimitError
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

import article as article_mod
import job_status as _job_status
import notify as _notify
from config import GROQ_API_KEY, WHISPER_MODEL, MAX_AUDIO_MB, CHUNK_DURATION_SEC

logger = logging.getLogger(__name__)

_groq = Groq(api_key=GROQ_API_KEY)


def _is_youtube(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(h in host for h in ("youtube.com", "youtu.be", "www.youtube.com"))


def _extract_youtube_id(url: str) -> str:
    parsed = urlparse(url)
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/").split("?")[0]
    qs = parsed.query
    for part in qs.split("&"):
        if part.startswith("v="):
            return part[2:]
    raise ValueError(f"Cannot extract YouTube video ID from: {url}")


def _youtube_transcript(url: str) -> str:
    video_id = _extract_youtube_id(url)
    logger.info("Fetching YouTube transcript for video_id=%s", video_id)
    try:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id)
    except (TranscriptsDisabled, NoTranscriptFound):
        logger.warning("No transcript available for %s; falling back to Whisper", video_id)
        return _whisper_transcript(url)
    text = " ".join(entry.text for entry in transcript)
    logger.info("YouTube transcript fetched: %d chars", len(text))
    return text


FFMPEG = "/opt/homebrew/bin/ffmpeg"


def _split_audio(audio_path: Path, chunk_dir: Path) -> list[Path]:
    """Split audio into chunks using ffmpeg. Returns list of chunk paths."""
    cmd = [
        FFMPEG, "-y", "-i", str(audio_path),
        "-f", "segment",
        "-segment_time", str(CHUNK_DURATION_SEC),
        "-c", "copy",
        str(chunk_dir / "chunk_%03d.mp3"),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    return sorted(chunk_dir.glob("chunk_*.mp3"))


def _parse_retry_seconds(message: str) -> float:
    """Extract wait time from Groq rate limit message like 'try again in 4m35.5s'."""
    m = re.search(r"try again in\s+(?:(\d+)m)?(\d+(?:\.\d+)?)s", message)
    if m:
        minutes = float(m.group(1) or 0)
        seconds = float(m.group(2))
        return minutes * 60 + seconds
    return 60.0  # fallback


def _transcribe_audio_file(audio_path: Path, job_id: str = "", chunk_label: str = "") -> str:
    while True:
        try:
            with open(audio_path, "rb") as f:
                response = _groq.audio.transcriptions.create(
                    file=(audio_path.name, f),
                    model=WHISPER_MODEL,
                    response_format="text",
                )
            return response if isinstance(response, str) else response.text
        except RateLimitError as e:
            wait = _parse_retry_seconds(str(e)) + 5  # small buffer
            logger.warning("Whisper rate limit hit; waiting %.0fs before retry", wait)
            if job_id:
                detail = f"{chunk_label} — rate limited, retrying in {wait / 60:.0f}m"
                _job_status.update(job_id, "transcribing", detail)
                _notify.send("Anki Pipeline", f"Transcribing {detail}")
            time.sleep(wait)


def _whisper_transcript(url: str, job_id: str = "") -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        audio_path = tmp / "audio.mp3"

        logger.info("Downloading audio via yt-dlp: %s", url)
        if job_id:
            _job_status.update(job_id, "transcribing", "downloading audio")
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-x", "--audio-format", "mp3",
            "--audio-quality", "5",
            "--ffmpeg-location", "/opt/homebrew/bin",
            "-o", str(audio_path),
            url,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr.decode()}")

        # Handle yt-dlp adding extension
        candidates = list(tmp.glob("audio*"))
        if not candidates:
            raise RuntimeError("yt-dlp produced no output file")
        audio_path = candidates[0]

        size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        logger.info("Downloaded audio: %.1f MB", size_mb)

        if size_mb <= MAX_AUDIO_MB:
            if job_id:
                _job_status.update(job_id, "transcribing", "whisper 1/1")
            transcript = _transcribe_audio_file(audio_path, job_id, "chunk 1/1")
        else:
            logger.info("Audio >%dMB; splitting into chunks", MAX_AUDIO_MB)
            chunk_dir = tmp / "chunks"
            chunk_dir.mkdir()
            chunks = _split_audio(audio_path, chunk_dir)
            parts = []
            for i, chunk in enumerate(chunks):
                label = f"chunk {i + 1}/{len(chunks)}"
                logger.info("Transcribing chunk %d/%d", i + 1, len(chunks))
                if job_id:
                    _job_status.update(job_id, "transcribing", f"whisper {label}")
                parts.append(_transcribe_audio_file(chunk, job_id, label))
            transcript = " ".join(parts)

        logger.info("Whisper transcript: %d chars", len(transcript))
        return transcript


def get_title(url: str) -> str:
    """Fetch video/episode title via yt-dlp metadata (no download)."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--print", "title", "--no-download", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        logger.warning("Could not fetch title for %s", url)
    return ""


_AUDIO_VIDEO_EXTENSIONS = {
    ".mp3", ".mp4", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus",
    ".webm", ".mkv", ".avi", ".mov",
}

_AUDIO_VIDEO_DOMAINS = {
    "soundcloud.com", "www.soundcloud.com",
    "podcasts.apple.com",
    "open.spotify.com",
    "anchor.fm", "www.anchor.fm",
    "buzzsprout.com", "www.buzzsprout.com",
    "twitch.tv", "www.twitch.tv",
    "vimeo.com", "www.vimeo.com",
    "dailymotion.com", "www.dailymotion.com",
}


def _is_audio_video_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() in _AUDIO_VIDEO_DOMAINS:
        return True
    ext = Path(parsed.path).suffix.lower()
    return ext in _AUDIO_VIDEO_EXTENSIONS


def get_transcript(url: str, job_id: str = "") -> tuple[str, str]:
    """Route URL to appropriate transcript method. Returns (text, title)."""
    if _is_youtube(url):
        title = get_title(url)
        if job_id:
            _job_status.update(job_id, "transcribing", title or url)
        return _youtube_transcript(url), title

    if _is_audio_video_url(url):
        title = get_title(url)
        if job_id:
            _job_status.update(job_id, "transcribing", title or url)
        return _whisper_transcript(url, job_id), title

    # Try article extraction for web pages
    try:
        return article_mod.get_article_text(url)
    except Exception as e:
        logger.warning("Article extraction failed (%s); falling back to Whisper: %s", e, url)
        title = get_title(url)
        return _whisper_transcript(url, job_id), title
