python3 -m pip install -r requirements.txt
Copy-Item .env.example .env
# Open .env and put your own key after OPENAI_API_KEY=
python3 -m pip install -r requirements.txt
Copy-Item .env.example .env
# Open .env and put your own key after OPENAI_API_KEY=
python3 ui/server.py
```

Open `http://127.0.0.1:8000`, select a supported audio/video file, provide its key, chords, genre, and vocal style, then click **Analyze this take**. The browser sends the file to the local server. It converts video with FFmpeg when necessary, uses OpenAI transcription, and asks the Responses API for structured coaching feedback. `drift.py` separately provides the measurable pitch events.

Open `http://127.0.0.1:8000`, select a supported audio/video file, provide its key, chords, genre, and vocal style, then click **Analyze this take**. The browser sends the file to the local server. It converts video with FFmpeg when necessary, uses OpenAI transcription, and asks the Responses API for structured coaching feedback. `drift.py` separately provides the measurable pitch events.

Each developer supplies their own `OPENAI_API_KEY` in `.env`. The server reads it only from that local file; `.env` is ignored by Git and must never be committed. `.env.example` is the safe template that remains in the repository.

The expected melody remains the hardcoded `REFERENCE_SEQUENCE` in `../drift.py`; edit that before a real session. Install FFmpeg and place it on `PATH` to accept anything other than WAV. Larger files are compressed locally for transcription; temporary source and derived files are deleted after the request.
The expected melody remains the hardcoded `REFERENCE_SEQUENCE` in `../drift.py`; edit that before a real session. Install FFmpeg and place it on `PATH` to accept anything other than WAV. Larger files are compressed locally for transcription; temporary source and derived files are deleted after the request.
