# ShruTea

ShruTea is a vocal-pitch agent embedded in REAPER. It compares a rendered vocal take to a fixed reference melody, identifies notes that drift by more than 20 cents, places named markers directly on the project timeline, and gives the producer a concise next action.

It is designed for a monophonic vocal demo clip, not chord detection or full-song transcription.

## How it works

1. Render a vocal take to WAV from REAPER.
2. Run shrutea.lua and select that WAV.
3. The ReaScript runs drift.py as a Python subprocess.
4. drift.py uses librosa pYIN to estimate pitch and compares each reference-note window to its intended frequency.
5. Notes beyond the 20-cent threshold become project markers. ShruTea then prints a labeled coaching verdict in REAPER's console.

## Requirements

- REAPER with ReaScript/Lua support
- Python 3.11 or newer
- Python packages declared in requirements.txt

Install dependencies:

~~~bash
python3 -m pip install -r requirements.txt
~~~

## Configure the reference melody

Edit REFERENCE_SEQUENCE in drift.py before analyzing a take. Each tuple contains:

    (start_time_in_seconds, expected_note_name, expected_frequency_hz)

The supplied demo uses A4 from the start:

    REFERENCE_SEQUENCE = ((0.0, "A4", 440.0),)

For a multi-note demo, add entries in chronological order. A note stays active until the following entry:

    REFERENCE_SEQUENCE = (
        (0.0, "A4", 440.0),
        (1.5, "B4", 493.88),
        (3.0, "A4", 440.0),
    )

## Install in REAPER

1. Copy shrutea.lua, drift.py, llm_coach.py, and commentary.py into REAPER's Scripts folder, or leave them in this repository and load the Lua file here.
2. In REAPER, open **Actions > Show Action List**.
3. Choose **New Action > Load ReaScript** and select shrutea.lua.
4. Render or bounce the vocal take to WAV.
5. Find shrutea.lua in the Action List and click **Run**.
6. Select the rendered WAV in REAPER's file picker.
7. Inspect the named markers on the project timeline and the REAPER console.

If REAPER cannot find Python, set SHRUTEA_PYTHON to the absolute interpreter path reported by:

~~~bash
which python3
~~~

## Embedded coaching agent

After adding drift markers, shrutea.lua runs llm_coach.py and prints a labeled **ShruTea says:** verdict in REAPER's console. The coach receives the intended reference melody and measured drift JSON, then prefers OPENAI_API_KEY, ANTHROPIC_API_KEY, or OPENROUTER_API_KEY, in that order.

If no key is configured, ShruTea uses a local, evidence-based fallback verdict so marker analysis remains available offline.

## Run the web companion

The browser companion is a functional view of the same REAPER workflow: it calls the real local drift.py, shows marker timing and reference context, then renders a coaching verdict, practice plan, transcript, and raw JSON. Its **Try the included REAPER take** button exercises the full result workspace without a manual upload.

~~~bash
python3 -m pip install -r requirements.txt
cp .env.example .env  # optional: add OPENAI_API_KEY for transcription and structured coaching
python3 ui/server.py
~~~

Open http://127.0.0.1:8000. WAV works with no further setup; MP3, M4A, and video inputs require FFmpeg. The UI analyzes only the first eight seconds, and drift.py caps all analyses at twenty seconds so a long render cannot stall a live demo.

With OPENAI_API_KEY, ShruTea sends a temporary eight-second WAV excerpt to OpenAI for transcription and asks the Responses API for structured coaching. If the key or network is unavailable, the local pitch result and all UI cards still render using a deterministic evidence-based fallback.

## Tests

Run the pitch threshold tests:

~~~bash
python3 test_drift.py
~~~

They generate a 440 Hz A4 tone, which must produce an empty JSON list, and a 427 Hz tone, which must produce the A4 to G#4 drift event at roughly 50 cents.

To verify the Lua-to-Python-to-REAPER flow without opening REAPER:

~~~bash
lua test_shrutea.lua
~~~

The mock test generates a temporary flat tone, loads mock_reaper.lua, runs the real shrutea.lua, and asserts that the Python subprocess, JSON parser, marker call, and coaching console output all succeed.
