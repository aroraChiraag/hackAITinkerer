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

import numpy as np
from scipy import signal
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


def estimate_frequency(frame: np.ndarray, sample_rate: int, low_hz: float = 80.0, high_hz: float = 1000.0) -> float | None:
    """Estimate a voiced frame's fundamental with normalized autocorrelation."""
    frame = frame - np.mean(frame)
    if np.sqrt(np.mean(frame * frame)) < 1e-4:
        return None

    windowed = frame * np.hanning(len(frame))
    correlation = signal.correlate(windowed, windowed, mode="full", method="fft")[len(frame) - 1 :]
    if correlation[0] <= 0:
        return None
    correlation /= correlation[0]

    minimum_lag = max(1, int(sample_rate / high_hz))
    maximum_lag = min(len(correlation) - 2, int(sample_rate / low_hz))
    if minimum_lag >= maximum_lag:
        return None

    # Choosing the strongest local maximum after the zero-lag peak avoids the
    # zero-lag artifact and makes the detector stable for a clean sine tone.
    peaks, _ = signal.find_peaks(correlation[minimum_lag : maximum_lag + 1])
    if not len(peaks):
        return None
    lag = int(peaks[np.argmax(correlation[minimum_lag : maximum_lag + 1][peaks])]) + minimum_lag
    if correlation[lag] < 0.2:
        return None

    # Parabolic interpolation improves the cents estimate beyond whole samples.
    left, center, right = correlation[lag - 1], correlation[lag], correlation[lag + 1]
    denominator = left - 2 * center + right
    fractional_lag = lag if denominator == 0 else lag + 0.5 * (left - right) / denominator
    return float(sample_rate / fractional_lag)


def analyze(wav_path: Path, frame_seconds: float = 0.20, hop_seconds: float = 0.20) -> list[dict[str, float | str]]:
    sample_rate, raw_samples = wavfile.read(wav_path)
    if sample_rate <= 0:
        raise ValueError("WAV has an invalid sample rate")
    samples = prepare_audio(raw_samples)
    frame_size = max(3, int(round(sample_rate * frame_seconds)))
    hop_size = max(1, int(round(sample_rate * hop_seconds)))
    if len(samples) < frame_size:
        raise ValueError("WAV is shorter than the analysis frame")

    results: list[dict[str, float | str]] = []
    for start in range(0, len(samples) - frame_size + 1, hop_size):
        timestamp = (start + frame_size / 2) / sample_rate
        reference = reference_at(timestamp)
        if reference is None:
            continue
        frequency = estimate_frequency(samples[start : start + frame_size], sample_rate)
        if frequency is None:
            continue
        expected_note, reference_frequency = reference
        midi_float = 69 + 12 * np.log2(frequency / 440.0)
        nearest_midi = int(np.rint(midi_float))
        cents_off = abs(float(1200 * np.log2(frequency / reference_frequency)))
        if cents_off <= DRIFT_THRESHOLD_CENTS:
            continue
        results.append(
            {
                "time": round(timestamp, 4),
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
