# ShruTea

ShruTea is a vocal-pitch assistant that runs inside REAPER. It compares a rendered vocal take against a fixed reference melody, identifies notes that drift by more than 20 cents, and adds markers directly to the project timeline.

It is built for a monophonic vocal demo clip—not chord detection or full-song transcription.

## How it works

1. Render a vocal take to WAV from REAPER.
2. Run `shrutea.lua` from REAPER and select that WAV.
3. The ReaScript runs `drift.py` as a Python subprocess.
4. `drift.py` uses `librosa.pyin` to estimate vocal pitch, takes the median pitch for every hardcoded reference-note window, and calculates its cents distance from the reference note.
5. Drift above 20 cents is returned as JSON. The Lua script adds a REAPER marker with the note and cents-off value, then prints a summary in REAPER's console.

## Requirements

- REAPER with ReaScript/Lua support
- Python 3.11 or newer
- The Python packages in `requirements.txt`

Install the Python dependencies from this repository:

```bash
python3 -m pip install -r requirements.txt
```

`shrutea.lua` calls `python3`. If REAPER says that `python3` cannot be found, replace `python3` in the `command` line of `shrutea.lua` with the absolute path reported by:

```bash
which python3
```

## Configure the reference melody

Edit `REFERENCE_SEQUENCE` in `drift.py` before analyzing a take. Each tuple is:

```python
(start_time_in_seconds, expected_note_name, expected_frequency_hz)
```

The shipped demo uses A4 from the beginning of the clip:

```python
REFERENCE_SEQUENCE = ((0.0, "A4", 440.0),)
```

For a multi-note demo, add entries in chronological order. A note stays active until the following entry:

```python
REFERENCE_SEQUENCE = (
    (0.0, "A4", 440.0),
    (1.5, "B4", 493.88),
    (3.0, "A4", 440.0),
)
```

## Install in REAPER

1. Copy `shrutea.lua` into REAPER's Scripts folder (keeping `drift.py` in the same folder), or leave both files in this repository and load the Lua file from here.
2. In REAPER, open **Actions > Show Action List**.
3. Choose **New Action > Load ReaScript** and select `shrutea.lua`.
4. Render/bounce the vocal take to a WAV file using REAPER's normal render workflow.
5. Find `shrutea.lua` in the Action List and click **Run**.
6. Select the rendered WAV when REAPER opens the file picker.
7. Inspect the project timeline for markers and REAPER's console for the summary.

An example marker label is:

```text
A4: 50.0 cents off
```

## Test the pitch threshold

`test_drift.py` generates two temporary three-second WAVs and runs `drift.py` against both:

- `test_intune.wav`: 440 Hz / A4. Its JSON result must be `[]`.
- `test_flat.wav`: 427 Hz. Its JSON result must contain A4 as the expected note, G#4 as the detected note, and roughly 52 cents of drift.

Run it with:

```bash
python3 test_drift.py
```

## JSON output

`drift.py` writes a JSON array to standard output. Each drift result has this shape:

```json
[
  {
    "time": 0.0,
    "expected_note": "A4",
    "actual_note": "G#4",
    "cents_off": 50.0
  }
]
```

## Demo visual

Open `demo.html` in a browser for a presentation-ready pitch-drift timeline. It includes sample data immediately and can load a JSON file produced by `drift.py`.

## Sam Changes

This branch contains Sam's documentation and workflow updates for ShruTea.
