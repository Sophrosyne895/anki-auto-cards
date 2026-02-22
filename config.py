import os
from pathlib import Path

# Directories
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Server
PORT = int(os.environ.get("ANKI_PIPELINE_PORT", 8766))
AUTH_TOKEN = os.environ.get("ANKI_PIPELINE_TOKEN", "")

# Groq
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
WHISPER_MODEL = "whisper-large-v3"
LLM_MODEL = "llama-3.3-70b-versatile"

# AnkiConnect
ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_CONNECT_VERSION = 6
DECK_NAME = os.environ.get("ANKI_DECK_NAME", "Podcast & Video Notes")
NOTE_TYPE = "Basic"

# Card generation
MIN_CARDS = 10
MAX_CARDS = 30

# Queue
PENDING_CARDS_FILE = DATA_DIR / "pending_cards.json"
QUEUE_RETRY_INTERVAL = 60  # seconds

# Audio chunking
MAX_AUDIO_MB = 20
CHUNK_DURATION_SEC = 600  # 10 minutes per chunk

# Logging
LOG_FILE = LOGS_DIR / "app.log"
