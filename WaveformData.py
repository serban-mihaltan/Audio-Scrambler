# WaveformData.py

import wave
from typing import List

import numpy as np


def load_waveform(path: str, max_points: int = 4000) -> List[float]:
    """
    Load audio samples from a WAV file and return a downsampled mono waveform.

    Returns a list of floats in [-1.0, 1.0].
    If something goes wrong or format is unsupported, returns an empty list.
    """
    try:
        with wave.open(path, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()

            raw = wf.readframes(n_frames)
    except Exception as e:
        print(f"load_waveform: could not read WAV file: {e}")
        return []

    if not raw:
        return []

    # Select dtype based on sample width
    if sampwidth == 1:
        # 8-bit unsigned PCM [0, 255] -> convert to signed [-128, 127]
        dtype = np.uint8
        data = np.frombuffer(raw, dtype=dtype).astype(np.int16)
        data = data - 128  # center to signed
        max_abs = 127.0

    elif sampwidth == 2:
        # 16-bit signed PCM
        dtype = np.int16
        data = np.frombuffer(raw, dtype=dtype)
        max_abs = 32768.0

    elif sampwidth == 4:
        # 32-bit signed PCM
        dtype = np.int32
        data = np.frombuffer(raw, dtype=dtype)
        max_abs = 2147483648.0  # 2^31
    else:
        print(f"load_waveform: unsupported sample width: {sampwidth} bytes")
        return []

    if data.size == 0:
        return []

    # Reshape to (num_frames, n_channels)
    try:
        data = data.reshape(-1, n_channels)
    except ValueError:
        # Fallback if frames are incomplete
        frames = data.size // n_channels
        if frames == 0:
            return []
        data = data[: frames * n_channels].reshape(-1, n_channels)

    # Downmix to mono: average across channels
    mono = data.mean(axis=1)

    # Normalize to [-1.0, 1.0]
    
    mono = mono.astype(np.float32) / max_abs

    # Clip to safety
    mono = np.clip(mono, -1.0, 1.0)
    
    # Downsample to at most max_points points
    n = mono.size
    if n == 0:
        return []

    if n <= max_points:
        # No need to downsample
        return mono.tolist()

    # Use linear indices to sample evenly across the buffer
    indices = np.linspace(0, n - 1, num=max_points, dtype=np.int64)
    sampled = mono[indices]

    return sampled.tolist()
