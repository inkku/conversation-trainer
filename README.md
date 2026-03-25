# Conversation Trainer

A conversational language coaching app powered by Claude. Practice speaking in any language and get real-time, level-adaptive feedback on grammar, vocabulary, fluency, and delivery.

## What it does

- **Four proficiency levels** — Beginner through Fluent, each with a different coaching focus
- **Topic and scenario selection** — structured practice formats per level (survival conversations, professional scenarios, debates, job interviews)
- **Whisper-based speech recognition** — local, offline, works in any language
- **Session summaries** — end-of-session feedback with vocabulary recap and progress notes
- **Session history** — browse past sessions and track improvement over time

## Running the app

### Production (needs API key + Whisper)
```bash
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY
python app.py
# → http://localhost:8000
```

### Design / UI work (no API key needed)
```bash
pip install fastapi uvicorn jinja2 python-multipart
python mock_server.py
# → http://localhost:8001
```

See [DESIGNER.md](DESIGNER.md) for a full setup guide.

## Project structure

```
app.py              — FastAPI backend (Claude + Whisper)
mock_server.py      — Lightweight mock server for UI work
templates/
  index.html        — Entire frontend (vanilla JS, no frameworks)
requirements.txt    — Python dependencies
.env                — API key (not committed)
```

## Tech stack

- **Backend** — Python, FastAPI, Uvicorn
- **AI** — Anthropic Claude opus-4-6 (structured tool use for guaranteed JSON)
- **Speech-to-text** — OpenAI Whisper (runs locally, no network call)
- **Frontend** — Vanilla JS, single HTML file, Web Speech API for TTS
