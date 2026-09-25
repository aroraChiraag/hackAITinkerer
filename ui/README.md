# ShruTea web companion

The web companion runs the repository's real drift.py detector, the same pitch analysis shrutea.lua uses in REAPER, and renders the resulting timeline markers, a coaching verdict, a practice plan, arrangement ideas, a transcript, and raw JSON.

## Run it

From the repository root, after the setup in ../README.md:

~~~bash
.venv\Scripts\python ui\server.py
~~~

Open http://127.0.0.1:8000. Click **Try the included REAPER take** for an immediate result, or select a take and click **Analyze this take**. The key, genre, chords, and vocal style fields feed the coaching for both buttons.

- WAV works without additional tools. MP3, M4A, and video inputs need FFmpeg on PATH.
- The UI measures the first eight seconds of a take.
- With OPENAI_API_KEY in ../.env, the server transcribes a temporary eight-second excerpt and asks OpenAI for structured coaching grounded in the transcript, your musical context, and the measured drift. If that call fails, the status line shows the error and the page falls back to local coaching.
- Without a key, pitch analysis is still real; the transcript and coaching plan are clearly labelled samples.
- Uploads and temporary files are deleted after each request. Restart the server after editing .env.
