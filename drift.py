#!/usr/bin/env python3
"""Report pitch drift from a WAV file as JSON.

Each result compares a detected fundamental frequency with the hardcoded
reference note active at that time. The output is deliberately stdout-only
JSON so that shrutea.lua can redirect and consume it without an additional
dependency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np
from scipy.io import wavfile


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
DRIFT_THRESHOLD_CENTS = 20.0
# Each entry starts at a time in seconds and remains active until the next one.
# Add successive notes here to define a longer reference melody.
REFERENCE_SEQUENCE = ((0.0, "A4", 440.0),)


def midi_to_note(midi_note: int) -> str:
    """Return a scientific-pitch-notation note name for a MIDI note number."""
    return f"{NOTE_NAMES[midi_note % 12]}{midi_note // 12 - 1}"


def reference_at(timestamp: float) -> tuple[str, float] | None:
    """Return the hardcoded reference entry that covers ``timestamp``."""
    active_reference: tuple[str, float] | None = None
    for start_time, note_name, frequency in REFERENCE_SEQUENCE:
        if start_time > timestamp:
            break
        active_reference = (note_name, frequency)
    return active_reference


def prepare_audio(samples: np.ndarray) -> np.ndarray:
    """Mix channels and normalize integer or floating WAV samples to floats."""
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1:
        raise ValueError("WAV audio must be mono or stereo")

    if np.issubdtype(samples.dtype, np.integer):
        scale = max(abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max)
        return samples.astype(np.float64) / scale
    return samples.astype(np.float64)


def analyze(wav_path: Path) -> list[dict[str, float | str]]:
    sample_rate, raw_samples = wavfile.read(wav_path)
    if sample_rate <= 0:
        raise ValueError("WAV has an invalid sample rate")
    samples = prepare_audio(raw_samples)
    # pyin's probability lattice requires the standard 2048-sample analysis
    # frame at this vocal pitch range. Analyze densely, then take one median
    # pitch per reference-note window below.
    frame_size = 2048
    hop_size = 512
    if len(samples) < 2048:
        raise ValueError("WAV is shorter than the analysis frame")

    # pyin returns one fundamental-frequency estimate per frame, with unvoiced
    # frames represented as NaN. It is suitable for a monophonic vocal line.
    pitches, _, _ = librosa.pyin(
        samples,
        fmin=librosa.note_to_hz("E2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sample_rate,
        frame_length=frame_size,
        hop_length=hop_size,
    )
    timestamps = librosa.times_like(pitches, sr=sample_rate, hop_length=hop_size)
    results: list[dict[str, float | str]] = []
    for index, (start_time, expected_note, reference_frequency) in enumerate(REFERENCE_SEQUENCE):
        end_time = REFERENCE_SEQUENCE[index + 1][0] if index + 1 < len(REFERENCE_SEQUENCE) else np.inf
        in_window = (timestamps >= start_time) & (timestamps < end_time)
        voiced_pitches = pitches[in_window & ~np.isnan(pitches)]
        if not len(voiced_pitches):
            continue
        frequency = float(np.median(voiced_pitches))
        midi_float = 69 + 12 * np.log2(frequency / 440.0)
        nearest_midi = int(np.rint(midi_float))
        cents_off = abs(float(1200 * np.log2(frequency / reference_frequency)))
        if cents_off <= DRIFT_THRESHOLD_CENTS:
            continue
        results.append(
            {
                "time": round(float(start_time), 4),
                "expected_note": expected_note,
                "actual_note": midi_to_note(nearest_midi),
                "cents_off": round(cents_off, 2),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze WAV pitch drift as JSON.")
    parser.add_argument("wav_file", type=Path, help="input WAV file")
    args = parser.parse_args()
    if not args.wav_file.is_file():
        parser.error(f"WAV file not found: {args.wav_file}")

    try:
        json.dump(analyze(args.wav_file), sys.stdout)
        sys.stdout.write("\n")
    except (OSError, ValueError) as error:
        print(f"drift.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
