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
REQUIRED_KEYS = {"time", "expected_note", "actual_note", "cents_off"}


def write_tone(path: Path, frequency: float) -> None:
    time = np.arange(SAMPLE_RATE * DURATION_SECONDS) / SAMPLE_RATE
    samples = (0.5 * np.sin(2 * np.pi * frequency * time) * np.iinfo(np.int16).max).astype(np.int16)
    wavfile.write(path, SAMPLE_RATE, samples)


def run_drift(wav_path: Path) -> list[dict[str, float | str]]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "drift.py"), str(wav_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    output = json.loads(completed.stdout)
    assert isinstance(output, list), "drift.py must output a JSON list"
    assert all(set(entry) == REQUIRED_KEYS for entry in output), "drift.py returned the wrong JSON shape"
    return output


def main() -> None:
    intune_wav = ROOT / "test_intune.wav"
    flat_wav = ROOT / "test_flat.wav"
    write_tone(intune_wav, 440.0)
    write_tone(flat_wav, 427.0)

    try:
        intune_output = run_drift(intune_wav)
        flat_output = run_drift(flat_wav)

        assert intune_output == [], f"440 Hz should be filtered out: {intune_output}"
        assert flat_output, "427 Hz should produce drift entries"
        assert all(entry["expected_note"] == "A4" for entry in flat_output), flat_output
        assert all(entry["actual_note"] == "G#4" for entry in flat_output), flat_output
        assert all(50 <= float(entry["cents_off"]) <= 54 for entry in flat_output), flat_output

        print("test_intune.wav JSON:")
        print(json.dumps(intune_output, indent=2))
        print("test_flat.wav JSON:")
        print(json.dumps(flat_output, indent=2))
        print("Assertions passed: intune filtered; flat drift detected.")
    finally:
        intune_wav.unlink(missing_ok=True)
        flat_wav.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
