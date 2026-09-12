# Functional ShruTea local UI

The web companion runs the repository's real local drift.py detector, the same pitch-analysis path used by shrutea.lua in REAPER. It renders returned timeline markers, reference notes, an agent verdict, a practice plan, a transcript, and raw JSON.

## Run it

From the repository root:

~~~bash
python3 -m pip install -r requirements.txt
cp .env.example .env  # optional: add OPENAI_API_KEY
python3 ui/server.py
~~~

Open http://127.0.0.1:8000. Click **Try the included REAPER take** for an immediate real result, or select a take and click **Analyze this take**.

- WAV works without additional tools. MP3, M4A, and video inputs need FFmpeg on PATH.
- The UI measures the first eight seconds; drift.py also has a hard twenty-second cap to prevent long takes from blocking a demo.
- With OPENAI_API_KEY, ShruTea generates a temporary short WAV excerpt for OpenAI transcription and a structured coaching response grounded in the transcript, supplied musical context, and local drift events.
- Without a key, or if the AI request fails, pitch analysis still completes locally and every UI card receives an evidence-based fallback. The source upload and temporary derived files are deleted by the server after the request.

The intended melody remains REFERENCE_SEQUENCE in ../drift.py; edit it before a real session.
