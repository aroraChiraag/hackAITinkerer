#!/usr/bin/env python3
"""Report pitch drift from a WAV file as JSON.

Two analysis modes are available:

* ``auto`` (default): split the vocal into sung notes and measure how far each
  note sits from its nearest equal-tempered semitone. This works on any take
  without configuring a melody first.
* ``reference``: compare each window of REFERENCE_SEQUENCE with the note the
  singer intended.

The output is deliberately stdout-only JSON so that shrutea.lua can redirect
and consume it without an additional dependency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
DRIFT_THRESHOLD_CENTS = 20.0
MAX_ANALYSIS_SECONDS = 20.0
MODES = ("auto", "reference")
# Auto mode: frames further than this from the running note median start a new note.
NOTE_SPLIT_SEMITONES = 0.75
# Auto mode: ignore voiced fragments shorter than this (scoops, consonants, noise).
MIN_NOTE_SECONDS = 0.12
# Each entry starts at a time in seconds and remains active until the next one.
# Add successive notes here to define a longer reference melody.
REFERENCE_SEQUENCE = ((0.0, "A4", 440.0),)


def midi_to_note(midi_note: int) -> str:
    """Return a scientific-pitch-notation note name for a MIDI note number."""
    return f"{NOTE_NAMES[midi_note % 12]}{midi_note // 12 - 1}"


def drift_entry(time: float, duration: float, expected: str, actual: str, cents: float) -> dict[str, float | str]:
    return {
        "time": round(time, 4),
        "duration": round(duration, 4),
        "expected_note": expected,
        "actual_note": actual,
        "cents_off": round(abs(cents), 2),
        "direction": "sharp" if cents > 0 else "flat",
    }


def reference_drift(pitches: np.ndarray, timestamps: np.ndarray, frame_seconds: float) -> list[dict[str, float | str]]:
    """Compare the median pitch of each REFERENCE_SEQUENCE window with its note."""
    results: list[dict[str, float | str]] = []
    for index, (start_time, expected_note, reference_frequency) in enumerate(REFERENCE_SEQUENCE):
        end_time = REFERENCE_SEQUENCE[index + 1][0] if index + 1 < len(REFERENCE_SEQUENCE) else np.inf
        in_window = (timestamps >= start_time) & (timestamps < end_time)
        voiced_pitches = pitches[in_window & ~np.isnan(pitches)]
        if not len(voiced_pitches):
            continue
        frequency = float(np.median(voiced_pitches))
        cents = float(1200 * np.log2(frequency / reference_frequency))
        if abs(cents) <= DRIFT_THRESHOLD_CENTS:
            continue
        actual_note = midi_to_note(int(np.rint(librosa.hz_to_midi(frequency))))
        results.append(drift_entry(float(start_time), len(voiced_pitches) * frame_seconds, expected_note, actual_note, cents))
    return results


def note_segments(midi: np.ndarray) -> list[tuple[int, int]]:
    """Group consecutive voiced frames of a steady pitch into [start, end) note spans."""
    segments: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(midi):
        if np.isnan(value):
            if start is not None:
                segments.append((start, index))
                start = None
        elif start is None:
            start = index
        elif abs(value - np.median(midi[start:index])) > NOTE_SPLIT_SEMITONES:
            segments.append((start, index))
            start = index
    if start is not None:
        segments.append((start, len(midi)))
    return segments


def auto_drift(pitches: np.ndarray, timestamps: np.ndarray, frame_seconds: float) -> list[dict[str, float | str]]:
    """Measure each sung note against its nearest equal-tempered semitone."""
    midi = librosa.hz_to_midi(pitches)
    results: list[dict[str, float | str]] = []
    for start, end in note_segments(midi):
        duration = (end - start) * frame_seconds
        if duration < MIN_NOTE_SECONDS:
            continue
        median_midi = float(np.median(midi[start:end]))
        nearest = int(np.rint(median_midi))
        cents = 100 * (median_midi - nearest)
        if abs(cents) <= DRIFT_THRESHOLD_CENTS:
            continue
        note = midi_to_note(nearest)
        results.append(drift_entry(float(timestamps[start]), duration, note, note, cents))
    return results


def analyze(wav_path: Path, max_seconds: float | None = None, mode: str = "auto") -> list[dict[str, float | str]]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if max_seconds is not None and max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    duration = min(max_seconds, MAX_ANALYSIS_SECONDS) if max_seconds is not None else MAX_ANALYSIS_SECONDS
    # Limit input duration at load time so pYIN never blocks a live demo on a
    # long render. librosa also handles common WAV variants more robustly.
    samples, sample_rate = librosa.load(wav_path, sr=None, mono=True, duration=duration)
    if sample_rate <= 0:
        raise ValueError("WAV has an invalid sample rate")
    # pyin's probability lattice requires the standard 2048-sample analysis
    # frame at this vocal pitch range. A quarter-frame hop resolves note
    # boundaries finely enough for auto mode's segmentation.
    frame_size = 2048
    hop_size = 512
    if len(samples) < frame_size:
        raise ValueError("WAV is shorter than the analysis frame")

    # pyin returns one fundamental-frequency estimate per frame, with unvoiced
    # frames represented as NaN. It is suitable for a monophonic vocal line.
    pitch_range = {"fmin": librosa.note_to_hz("E2"), "fmax": librosa.note_to_hz("C6")}
    pitches, _, _ = librosa.pyin(
        samples, sr=sample_rate, frame_length=frame_size, hop_length=hop_size, **pitch_range
    )
    # pyin snaps to 10-cent bins, too coarse for a 20-cent threshold. YIN
    # interpolates between samples; keep its estimate wherever it agrees with
    # pyin to within a semitone (which rejects YIN's octave errors).
    refined = librosa.yin(samples, sr=sample_rate, frame_length=frame_size, hop_length=hop_size, **pitch_range)
    agrees = np.abs(librosa.hz_to_midi(refined) - librosa.hz_to_midi(pitches)) < 1
    pitches = np.where(agrees, refined, pitches)
    timestamps = librosa.times_like(pitches, sr=sample_rate, hop_length=hop_size)
    frame_seconds = hop_size / sample_rate
    if mode == "reference":
        return reference_drift(pitches, timestamps, frame_seconds)
    return auto_drift(pitches, timestamps, frame_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze WAV pitch drift as JSON.")
    parser.add_argument("wav_file", type=Path, help="input WAV file")
    parser.add_argument("--max-seconds", type=float, help="analyze only the first N seconds")
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="auto",
        help="auto: nearest-semitone drift per sung note (default); reference: compare with REFERENCE_SEQUENCE",
    )
    args = parser.parse_args()
    if not args.wav_file.is_file():
        parser.error(f"WAV file not found: {args.wav_file}")

    try:
        json.dump(analyze(args.wav_file, args.max_seconds, args.mode), sys.stdout)
        sys.stdout.write("\n")
    except (OSError, ValueError) as error:
        print(f"drift.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
