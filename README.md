# ShruTea

ShruTea is an AI-assisted vocal coach embedded in REAPER. It measures every sung note in a vocal take, drops a named marker on the REAPER timeline wherever pitch drifts more than 20 cents (orange for flat, blue for sharp), and turns that evidence into concrete coaching. A browser companion shows the same analysis with editable extracted lyrics, a practice plan, and genre-aware arrangement ideas.

It is designed for a monophonic vocal line, not chord detection or full-song transcription.

## Who it's for

Producers, composers, rap artists, singers, and sound engineers. With ShruTea at their disposal, every session starts from real evidence about the vocal instead of guesswork, and we can guarantee certified bangers.

## Where ShruTea can go

- **Streaming platforms:** Spotify could offer ShruTea as a coaching service to its signed artists, helping them sharpen their vocals before release.
- **DAW plugin:** as a plugin for Audacity or Ableton Live, ShruTea shows exactly which notes drift and by how much, so artists can apply Melodyne or Auto-Tune in an informed way instead of flattening the whole performance.
- **Music labels:** labels such as Warner Music or Def Jam could offer ShruTea as a vocal trainer to their artists, a game changer for developing talent at scale.

These are opportunities we see for ShruTea, not existing partnerships. All product and company names are trademarks of their respective owners.

## How it works

1. drift.py uses librosa's pYIN to track pitch, refined with YIN for cent-level precision.
2. In **auto mode** (default) it splits the take into sung notes and measures each one against its nearest semitone, so any melody works without setup. In **reference mode** it compares windows of a fixed REFERENCE_SEQUENCE instead.
3. Notes beyond 20 cents become JSON events: time, note, cents off, and whether the note was flat or sharp.
4. shrutea.lua turns those events into REAPER markers, then llm_coach.py prints a **ShruTea says:** verdict in the REAPER console.
5. ui/server.py runs the same detector for the web companion, extracts lyrics with a local Whisper model, and with an OpenAI or Anthropic key adds structured AI coaching.

The first 20 seconds of a take are analyzed (8 seconds in the web UI) so a live demo never stalls.

## Setup

Requires Python 3.11+ (3.13 works). Create a virtual environment in the repository folder; shrutea.lua finds `.venv` automatically.

Windows:

~~~bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
~~~

macOS / Linux:

~~~bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
~~~

Optional: copy `.env.example` to `.env` and add an API key. The first key set is used, in this order: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`. Without a key, everything still runs with local coaching.

## Use it in REAPER

1. In REAPER, open **Actions > Show Action List > New Action > Load ReaScript** and select `shrutea.lua` from this folder. Keep the script in this folder so it can find drift.py, llm_coach.py, `.venv`, and `.env`.
2. Select the vocal item on the timeline and run the ShruTea action. Markers land on the item's own position.
3. With no item selected, ShruTea opens a file picker for a rendered WAV and places markers relative to the project start.
4. Read the verdict in the ReaScript console. Re-running replaces earlier ShruTea markers (your own markers are untouched), and the whole change is one undo step.

Environment overrides: `SHRUTEA_PYTHON` (interpreter path), `SHRUTEA_MODE` (`auto` or `reference`), `SHRUTEA_DRIFT_SCRIPT`, `SHRUTEA_COACH_SCRIPT`.

## Run the web companion

~~~bash
.venv\Scripts\python ui\server.py
~~~

(`.venv/bin/python ui/server.py` on macOS / Linux.) Open http://127.0.0.1:8000 and click **Try the included REAPER take**, or upload a take and click **Analyze this take**. WAV works out of the box; MP3, M4A, and video need FFmpeg on PATH.

- **Extracted Lyrics:** a local Whisper model (`faster-whisper`, `small` by default; downloaded once on first start) transcribes the first 60 seconds, so audio never leaves your machine. With `ANTHROPIC_API_KEY`, non-English lyrics are transliterated to Roman script (for example Hinglish); set `SHRUTEA_LYRICS_SCRIPT=original` to keep the original script. The lyrics box is editable: fix any misheard words and click **Update coaching with these lyrics**. Tune with `SHRUTEA_WHISPER_MODEL` (`base` is faster) and `SHRUTEA_LYRICS_SECONDS`.
- **With `OPENAI_API_KEY`:** the Responses API returns structured coaching (melody, vibrato, rhyme, practice steps, arrangement ideas) grounded in the lyrics, the musical context you enter, and the measured drift. If the call fails, the page says why and shows local coaching.
- **With `ANTHROPIC_API_KEY`:** Claude (`claude-opus-5` by default, set `SHRUTEA_CLAUDE_MODEL` to change) writes the same structured coaching card. If Claude's safety filter declines a request, the API automatically re-runs it on a fallback model.
- **With only `OPENROUTER_API_KEY`:** a one-line live verdict on top of local coaching.
- **With no key:** real pitch markers plus a clearly labelled sample coaching plan.

## Reference mode

To compare against an intended melody instead of the nearest semitone, edit REFERENCE_SEQUENCE in drift.py and run with `--mode reference` (or set `SHRUTEA_MODE=reference` for REAPER). Each entry is `(start_time_in_seconds, note_name, frequency_hz)` and stays active until the next one:

    REFERENCE_SEQUENCE = (
        (0.0, "A4", 440.0),
        (1.5, "B4", 493.88),
        (3.0, "A4", 440.0),
    )

## Tests

~~~bash
.venv\Scripts\python test_drift.py
~~~

Generates tones and checks both modes: in-tune notes are ignored, 427 Hz reads as A4 → G#4 about 52 cents flat, 432 Hz as A4 about 32 cents flat, and a sharp second note is found at the right time.

To run the real shrutea.lua against a mock REAPER (markers, item offsets, re-run cleanup, and coaching output) with any Lua 5.3+ interpreter:

~~~bash
lua test_shrutea.lua
~~~

No Lua installed? `.venv\Scripts\python -m pip install lupa`, then:

~~~bash
.venv\Scripts\python -c "import lupa; lupa.LuaRuntime().execute('dofile([[test_shrutea.lua]])')"
~~~

## Acknowledgements

A big thank you to CREWASIS and Hackathon 1.0 for making ShruTea possible.
