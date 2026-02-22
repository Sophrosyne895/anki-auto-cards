# Anki Auto-Card Pipeline

Automatically generates Anki flashcards from YouTube and podcast URLs shared from your iPhone.

## How It Works

1. Share a YouTube or Overcast URL from your iPhone via iOS Shortcut
2. Mac server receives it and returns `202 Accepted` instantly
3. Background worker fetches the transcript (YouTube API or Groq Whisper)
4. Groq LLM generates 10–30 flashcards
5. Cards are pushed to Anki via AnkiConnect
6. If Anki is closed, cards queue to disk and flush automatically when Anki opens

## One-Time Setup

### 1. Install dependencies

```bash
cd /Users/evocalize/code/anki
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Ensure `ffmpeg` and `yt-dlp` are available (for podcast audio):
```bash
brew install ffmpeg yt-dlp
```

### 2. Install AnkiConnect

In Anki: **Tools → Add-ons → Get Add-ons** → enter code `2055492159` → restart Anki.

### 3. Configure the launchd plist

Edit `com.evocalize.anki-pipeline.plist` and fill in:
- `GROQ_API_KEY` — from [console.groq.com](https://console.groq.com)
- `ANKI_PIPELINE_TOKEN` — any secret string (e.g. output of `openssl rand -hex 16`)

### 4. Install and start the service

```bash
cp com.evocalize.anki-pipeline.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.evocalize.anki-pipeline.plist
```

To restart after editing the plist:
```bash
launchctl unload ~/Library/LaunchAgents/com.evocalize.anki-pipeline.plist
launchctl load ~/Library/LaunchAgents/com.evocalize.anki-pipeline.plist
```

### 5. Install Tailscale

Install [Tailscale](https://tailscale.com) on your Mac and iPhone. Note your Mac's Tailscale IP (`100.x.x.x`).

### 6. Create iOS Shortcut

1. Open **Shortcuts** app → **+** new shortcut
2. Add action: **Receive** input from **Share Sheet** (URLs)
3. Add action: **Get URLs from Input**
4. Add action: **Get Contents of URL**
   - URL: `http://<mac-tailscale-ip>:8766/submit`
   - Method: `POST`
   - Headers: `X-Token` = your secret token; `Content-Type` = `application/json`
   - Body: `{"url": "<URL from step 3>"}`
5. Add action: **Show Notification** with the `message` field from the response
6. Name it "Send to Anki" and add to Share Sheet

## Verification

```bash
# Health check
curl http://localhost:8766/health

# Submit a YouTube video
curl -X POST http://localhost:8766/submit \
  -H "X-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtu.be/dQw4w9WgXcQ"}'

# Watch logs
tail -f logs/app.log
```

## File Structure

```
anki/
├── main.py              # FastAPI app + HTTP endpoints
├── worker.py            # Background thread: job processing + retry
├── transcribe.py        # YouTube transcript API + yt-dlp/Whisper
├── cards.py             # Groq LLM card generation + JSON parsing
├── anki_connect.py      # AnkiConnect HTTP client
├── queue_store.py       # Atomic file-based card queue
├── config.py            # All constants and env var config
├── requirements.txt
├── com.evocalize.anki-pipeline.plist  # launchd service
├── logs/                # Rotating log files (auto-created)
└── data/                # pending_cards.json (auto-created)
```

## Troubleshooting

| Issue | Fix |
|---|---|
| `curl: Connection refused` | Check `launchctl list \| grep anki` and `logs/launchd.log` |
| Cards not appearing in Anki | Anki must be open with AnkiConnect installed; check `GET /health` |
| YouTube transcript unavailable | Falls back to Whisper automatically |
| Groq API errors | Check `logs/app.log`; verify `GROQ_API_KEY` in plist |
| iOS Shortcut not connecting | Confirm Tailscale is running on both devices |
