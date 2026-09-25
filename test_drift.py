#!/usr/bin/env python3
"""End-to-end threshold checks for drift.py using generated WAV fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile


ROOT = Path(__file__).resolve().parent
SAMPLE_RATE = 44_100
DURATION_SECONDS = 3
REQUIRED_KEYS = {"time", "duration", "expected_note", "actual_note", "cents_off", "direction"}


def tone(frequency: float, seconds: float) -> np.ndarray:
    time = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return 0.5 * np.sin(2 * np.pi * frequency * time)


def write_samples(path: Path, samples: np.ndarray) -> None:
    wavfile.write(path, SAMPLE_RATE, (samples * np.iinfo(np.int16).max).astype(np.int16))


def write_tone(path: Path, frequency: float) -> None:
    write_samples(path, tone(frequency, DURATION_SECONDS))


def run_drift(wav_path: Path, mode: str) -> list[dict[str, float | str]]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "drift.py"), str(wav_path), "--mode", mode],
        check=True,
        capture_output=True,
        text=True,
    )
    output = json.loads(completed.stdout)
    assert isinstance(output, list), "drift.py must output a JSON list"
    assert all(set(entry) == REQUIRED_KEYS for entry in output), "drift.py returned the wrong JSON shape"
    return output


def main() -> None:
    fixtures = {
        "intune": (ROOT / "test_intune.wav", tone(440.0, DURATION_SECONDS)),
        "flat": (ROOT / "test_flat.wav", tone(427.0, DURATION_SECONDS)),
        "slightly_flat": (ROOT / "test_slightly_flat.wav", tone(432.0, DURATION_SECONDS)),
        # In-tune A4, a short silence, then A4 sung 47 cents sharp.
        "two_notes": (
            ROOT / "test_two_notes.wav",
            np.concatenate([tone(440.0, 1.5), np.zeros(SAMPLE_RATE // 4), tone(452.0, 1.25)]),
        ),
    }
    for path, samples in fixtures.values():
        write_samples(path, samples)

    try:
        outputs = {}
        for mode in ("reference", "auto"):
            for name, (path, _) in fixtures.items():
                outputs[mode, name] = run_drift(path, mode)

        # Reference mode compares against REFERENCE_SEQUENCE (a single A4).
        assert outputs["reference", "intune"] == [], outputs["reference", "intune"]
        flat = outputs["reference", "flat"]
        assert len(flat) == 1, flat
        assert flat[0]["expected_note"] == "A4" and flat[0]["actual_note"] == "G#4", flat
        assert 50 <= float(flat[0]["cents_off"]) <= 54 and flat[0]["direction"] == "flat", flat

        # Auto mode measures each sung note against its nearest semitone.
        assert outputs["auto", "intune"] == [], outputs["auto", "intune"]
        slightly_flat = outputs["auto", "slightly_flat"]
        assert len(slightly_flat) == 1, slightly_flat
        assert slightly_flat[0]["expected_note"] == "A4" and slightly_flat[0]["direction"] == "flat", slightly_flat
        assert 29 <= float(slightly_flat[0]["cents_off"]) <= 34, slightly_flat
        two_notes = outputs["auto", "two_notes"]
        assert len(two_notes) == 1, two_notes
        assert 1.6 <= float(two_notes[0]["time"]) <= 1.9, two_notes
        assert two_notes[0]["expected_note"] == "A4" and two_notes[0]["direction"] == "sharp", two_notes
        assert 44 <= float(two_notes[0]["cents_off"]) <= 50, two_notes

        for (mode, name), output in outputs.items():
            print(f"{mode:9} {name:13} {json.dumps(output)}")
        print("Assertions passed: reference and auto modes flag drift and ignore in-tune notes.")
    finally:
        for path, _ in fixtures.values():
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
