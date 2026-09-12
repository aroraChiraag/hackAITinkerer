"""Generate a three-second, 440 Hz WAV used for the end-to-end smoke test."""

import numpy as np
from scipy.io import wavfile


SAMPLE_RATE = 44_100
DURATION_SECONDS = 3
time = np.arange(SAMPLE_RATE * DURATION_SECONDS) / SAMPLE_RATE
samples = (0.5 * np.sin(2 * np.pi * 440 * time) * np.iinfo(np.int16).max).astype(np.int16)
wavfile.write("synthetic_440hz.wav", SAMPLE_RATE, samples)
