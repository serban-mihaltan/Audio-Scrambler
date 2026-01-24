import wave  # Standard library module for reading/writing WAV files.
from typing import Tuple  # Used for type hints on functions that return multiple values.

import numpy as np  # NumPy is used for fast array operations and RNG/bitwise operations.

#sample-domain stream scrambler
class AudioScrambler:
    """
    PRNG-based sample-masking scrambler for WAV PCM audio.

    FILE MODE (current project):
      - scramble_file: read whole file, generate XOR keystream from seed,
        mask all samples, write result.
      - unscramble_file: read scrambled file, regenerate same keystream
        from seed, XOR again, recover original.

    STREAMING MODE (real-time friendly):
      - init_stream(sampwidth, n_channels): initialize internal PRNG state.
      - scramble_chunk(chunk): XOR chunk with next part of keystream.
      - unscramble_chunk(chunk): XOR chunk with same keystream on receiver.

    NOTE: This is structurally similar to a stream cipher operating on
    PCM samples. It is NOT cryptographically secure; it’s only for
    educational / scrambling purposes.
    """

    def __init__(self, block_ms: int = 50, seed: int = 12345):
        """
        :param block_ms: kept only for compatibility; not used here.
        :param seed:     PRNG seed (must match between scrambler/unscrambler).
        """
        self.block_ms = block_ms  # Store the block size (unused in this scrambler, but kept for API compatibility).
        self.seed = seed  # Store the seed used to generate the pseudo-random keystream.

        # Streaming state (for real-time use)
        self._stream_rng: np.random.Generator | None = None  # Holds the persistent RNG for streaming mode.
        self._stream_sampwidth: int | None = None  # Holds bytes/sample for streaming mode (1, 2, or 4).
        self._stream_n_channels: int | None = None  # Holds channel count for streaming mode (1=mono, 2=stereo, etc.).

    # ======================================================================
    # Public FILE-LEVEL API (used by current project)
    # ======================================================================

    def scramble_file(self, input_path: str, output_path: str) -> None:
        # Read the WAV file into an integer PCM NumPy array and also get format parameters.
        data, sr, sampwidth, n_channels = self._read_wav_int(input_path)
        # If reading failed, data will be None.
        if data is None:
            # Print an error message for debugging.
            print(f"[SCRAMBLER] Could not read input file: {input_path}")
            # Stop the function early.
            return

        # For files, we use a local RNG starting at the beginning of the stream.
        # This ensures every scramble_file call starts from keystream position 0.
        rng = np.random.default_rng(self.seed)
        # Apply the XOR keystream to the entire file's samples (scrambling).
        scrambled = self._apply_mask_core(
            data, sampwidth, n_channels, rng, mode="scramble"
        )
        # Write the scrambled samples back to a WAV file with the same audio parameters.
        self._write_wav_int(output_path, scrambled, sr, sampwidth, n_channels)
        # Print confirmation for debugging.
        print(f"[SCRAMBLER] Scrambled written to: {output_path}")

    def unscramble_file(self, input_path: str, output_path: str) -> None:
        # Read the scrambled WAV file into an integer PCM NumPy array and get its parameters.
        data, sr, sampwidth, n_channels = self._read_wav_int(input_path)
        # If reading failed, data will be None.
        if data is None:
            # Print an error message for debugging.
            print(f"[SCRAMBLER] Could not read input file: {input_path}")
            # Stop the function early.
            return

        # XOR is its own inverse; same keystream, same operation.
        # We must generate the exact same keystream from the same seed.
        rng = np.random.default_rng(self.seed)
        # Apply the XOR keystream again to recover the original samples (unscrambling).
        unscrambled = self._apply_mask_core(
            data, sampwidth, n_channels, rng, mode="unscramble"
        )
        # Write the recovered samples back to a WAV file.
        self._write_wav_int(output_path, unscrambled, sr, sampwidth, n_channels)
        # Print confirmation for debugging.
        print(f"[SCRAMBLER] Unscrambled written to: {output_path}")

    # ======================================================================
    # Public STREAMING API (for real-time style operation)
    # ======================================================================

    def init_stream(self, sampwidth: int, n_channels: int) -> None:
        """
        Initialize streaming mode.

        Call this once on each side (TX/RX) with the same seed,
        sample width, and channel count. Then feed PCM chunks through
        scramble_chunk / unscramble_chunk.

        :param sampwidth: bytes per sample (1, 2, or 4).
        :param n_channels: number of channels (1=mono, 2=stereo, etc.).
        """
        # Create a persistent RNG for streaming mode.
        # The RNG keeps its state between chunks, so the keystream continues.
        self._stream_rng = np.random.default_rng(self.seed)
        # Store bytes/sample for later chunk processing.
        self._stream_sampwidth = sampwidth
        # Store channel count for later chunk processing.
        self._stream_n_channels = n_channels
        # Print confirmation for debugging.
        print(
            f"[SCRAMBLER] Stream initialized: sampwidth={sampwidth}, "
            f"n_channels={n_channels}, seed={self.seed}"
        )

    def scramble_chunk(self, chunk: np.ndarray) -> np.ndarray:
        """
        Scramble a PCM chunk in streaming mode.

        :param chunk: np.ndarray with shape (frames, n_channels) or
                      1D array length frames * n_channels.
                      dtype should be integer compatible with sampwidth.
        :return: scrambled chunk, same shape and dtype.
        """
        # Forward to the shared streaming chunk handler with mode="scramble".
        return self._process_stream_chunk(chunk, mode="scramble")

    def unscramble_chunk(self, chunk: np.ndarray) -> np.ndarray:
        """
        Unscramble a PCM chunk in streaming mode.

        Because XOR is symmetric and the PRNG state advances identically
        on both sides, calling this on the receiver reconstructs the
        original signal.

        :param chunk: scrambled PCM chunk (same shape/dtype as scramble).
        :return: unscrambled chunk.
        """
        # Forward to the shared streaming chunk handler with mode="unscramble".
        return self._process_stream_chunk(chunk, mode="unscramble")

    def _process_stream_chunk(self, chunk: np.ndarray, mode: str) -> np.ndarray:
        # Streaming requires init_stream() to have been called first.
        if self._stream_rng is None:
            # Without an RNG, we cannot generate the keystream for this chunk.
            raise RuntimeError("Stream not initialized. Call init_stream(...) first.")

        # Also require audio format parameters to be present.
        if self._stream_sampwidth is None or self._stream_n_channels is None:
            # Without sample width and channel count, we cannot interpret the chunk.
            raise RuntimeError("Stream parameters not fully initialized.")

        # Load format parameters into local variables for readability.
        sampwidth = self._stream_sampwidth
        n_channels = self._stream_n_channels

        # Ensure 2D (frames, channels)
        if chunk.ndim == 1:
            # If the chunk is 1D, it should contain frames*n_channels samples.
            if len(chunk) % n_channels != 0:
                # If it's not divisible, it cannot be reshaped correctly.
                raise ValueError(
                    f"Chunk length {len(chunk)} not divisible by n_channels={n_channels}"
                )
            # Reshape 1D flat array into 2D (frames, channels).
            data = chunk.reshape(-1, n_channels)
        else:
            # If it is already 2D, use it directly.
            data = chunk

        # Apply the XOR mask using the streaming RNG.
        # IMPORTANT: this consumes PRNG values and advances the keystream state.
        masked = self._apply_mask_core(
            data, sampwidth, n_channels, self._stream_rng, mode=mode
        )
        # Preserve input shape
        if chunk.ndim == 1:
            # If input was 1D, return a 1D array again.
            return masked.reshape(-1)
        # Otherwise return 2D as provided.
        return masked

    # ======================================================================
    # Core masking logic (shared by file and streaming APIs)
    # ======================================================================
    #


    def _apply_mask_core(
        self,
        data: np.ndarray,
        sampwidth: int,
        n_channels: int,
        rng: np.random.Generator,
        mode: str,
    ) -> np.ndarray:
        """
        Apply a deterministic XOR mask to the integer PCM data using
        the provided RNG. The RNG's state will advance, making this
        suitable for both whole-file and streaming use.

        :param data:       (frames, channels) integer PCM.
        :param sampwidth:  bytes per sample (1, 2, 4).
        :param n_channels: number of channels.
        :param rng:        numpy Generator used as keystream source.
        :param mode:       "scramble" or "unscramble" (logging only).
        """
        # Ensure we are working with a 2D array shaped (frames, channels).
        if data.ndim != 2:
            # If not, reshape it using the known channel count.
            data = data.reshape(-1, n_channels)

        # Extract the number of frames and ignore the channel dimension.
        n_frames, _ = data.shape
        # Total number of samples = frames * channels.
        n_samples_total = n_frames * n_channels

        # Log what we're doing (useful for debugging).
        print(
            f"[SCRAMBLER] _apply_mask_core mode={mode}, frames={n_frames}, "
            f"channels={n_channels}, sampwidth={sampwidth}"
        )

        # Flatten the 2D (frames, channels) array into a single 1D array
        # so we can generate one mask value per sample.
        flat = data.reshape(-1)

        # Handle different PCM sample widths (bytes per sample).
        if sampwidth == 1:
            # 8-bit unsigned PCM is typically stored as values in [0,255].
            # Our _read_wav_int converts it into a signed-like range [-128,127].
            # For XOR we want 0..255, so we add 128 back.
            dtype = np.uint8  # Use uint8 for 8-bit operations.
            base = (flat + 128).astype(dtype)  # Convert signed-like samples back to uint8.

            # Generate one random byte per sample (0..255).
            mask = rng.integers(low=0, high=256, size=n_samples_total, dtype=dtype)
            # XOR the base samples with the mask.
            masked = np.bitwise_xor(base, mask)

            # Convert back to signed-like range [-128,127] stored as int16 for internal consistency.
            result_flat = masked.astype(np.int16) - 128

        elif sampwidth == 2:
            # 16-bit signed PCM uses int16 values in [-32768,32767].
            dtype = np.int16  # Use int16 for mask and samples.
            base = flat.astype(dtype)  # Ensure samples are int16.

            # Generate one random int16 value per sample across full int16 range.
            mask = rng.integers(
                low=np.iinfo(dtype).min,  # -32768
                high=np.iinfo(dtype).max + 1,  # 32768 (exclusive end)
                size=n_samples_total,  # one per sample
                dtype=dtype,  # int16 mask values
            )
            # XOR samples with mask.
            masked = np.bitwise_xor(base, mask)
            # Ensure output is int16.
            result_flat = masked.astype(np.int16)

        elif sampwidth == 4:
            # 32-bit signed PCM uses int32 values.
            dtype = np.int32  # Use int32 for mask and samples.
            base = flat.astype(dtype)  # Ensure samples are int32.

            # Generate one random int32 value per sample across full int32 range.
            mask = rng.integers(
                low=np.iinfo(dtype).min,  # -2147483648
                high=np.iinfo(dtype).max + 1,  # 2147483648 (exclusive end)
                size=n_samples_total,  # one per sample
                dtype=dtype,  # int32 mask values
            )
            # XOR samples with mask.
            masked = np.bitwise_xor(base, mask)
            # Ensure output is int32.
            result_flat = masked.astype(np.int32)

        else:
            # If we reach here, sampwidth is not supported by this scrambler.
            print(f"[SCRAMBLER] Unsupported sample width for masking: {sampwidth}")
            # Return original data unchanged as a safe fallback.
            return data

        # Reshape the 1D result back into (frames, channels).
        result = result_flat.reshape(n_frames, n_channels)
        # Return the masked (scrambled/unscrambled) samples.
        return result

    # ======================================================================
    # WAV I/O helpers (integer PCM)
    # ======================================================================

    def _read_wav_int(
        self, path: str
    ) -> Tuple[np.ndarray | None, int, int, int]:
        """
        Read a WAV as integer PCM array.

        Returns: (data, sample_rate, sampwidth, n_channels)
        - data: np.ndarray shape (n_frames, n_channels), integer dtype
        """
        try:
            # Open the WAV file in read-binary mode.
            with wave.open(path, "rb") as wf:
                # Read number of channels (1=mono, 2=stereo).
                n_channels = wf.getnchannels()
                # Read sample width in bytes (1, 2, or 4).
                sampwidth = wf.getsampwidth()
                # Read sample rate (Hz).
                sample_rate = wf.getframerate()
                # Read total number of frames (a frame contains samples for all channels).
                n_frames = wf.getnframes()
                # Read all frame bytes from the file.
                raw = wf.readframes(n_frames)
        except Exception as e:
            # If anything fails (file missing, unsupported format), log and return failure.
            print(f"[SCRAMBLER] Error reading WAV: {e}")
            return None, 0, 0, 0

        # If no bytes were read, the WAV is empty or invalid.
        if not raw:
            print("[SCRAMBLER] Empty WAV data")
            return None, 0, 0, 0

        # Convert raw PCM bytes into a NumPy integer array based on sample width.
        if sampwidth == 1:
            # WAV 8-bit PCM is unsigned 0..255.
            data = np.frombuffer(raw, dtype=np.uint8).astype(np.int16)  # load bytes then widen to int16
            data = data - 128  # shift to signed-like [-128,127] for consistent internal handling
        elif sampwidth == 2:
            # WAV 16-bit PCM is signed int16.
            data = np.frombuffer(raw, dtype=np.int16)
        elif sampwidth == 4:
            # WAV 32-bit PCM is signed int32.
            data = np.frombuffer(raw, dtype=np.int32)
        else:
            # Unsupported sample width.
            print(f"[SCRAMBLER] Unsupported sample width: {sampwidth} bytes")
            return None, 0, 0, 0

        # Reshape to (frames, channels)
        try:
            # Each frame has n_channels samples.
            data = data.reshape(-1, n_channels)
        except ValueError:
            # If reshaping fails, trim to the largest whole number of frames we can form.
            frames = data.size // n_channels
            if frames == 0:
                # Not enough samples to form even one frame.
                print("[SCRAMBLER] No complete frames")
                return None, 0, 0, 0
            # Trim the extra samples then reshape.
            data = data[: frames * n_channels].reshape(-1, n_channels)

        # Return (samples, sample_rate, sample_width_bytes, channel_count)
        return data, sample_rate, sampwidth, n_channels

    def _write_wav_int(
        self,
        path: str,
        data: np.ndarray,
        sample_rate: int,
        sampwidth: int,
        n_channels: int,
    ) -> None:
        """
        Write integer PCM array to WAV with given parameters.
        data shape: (n_frames, n_channels), integer dtype.
        """
        # Ensure data is shaped as (frames, channels).
        if data.ndim != 2:
            data = data.reshape(-1, n_channels)

        # Flatten (frames, channels) into a single 1D array for writing bytes.
        flat = data.reshape(-1,)

        # Convert internal representation back to correct on-disk PCM format.
        if sampwidth == 1:
            # Internal 8-bit data is [-128,127]; convert back to unsigned [0,255].
            arr = np.clip(flat + 128, 0, 255).astype(np.uint8)
        elif sampwidth == 2:
            # Clip to valid int16 range and cast.
            arr = np.clip(flat, -32768, 32767).astype(np.int16)
        elif sampwidth == 4:
            # 32-bit PCM: ensure int32.
            arr = flat.astype(np.int32)
        else:
            # Unsupported sample width for writing.
            raise ValueError(f"Unsupported sample width {sampwidth} for writing")

        # Open the output WAV in write-binary mode.
        with wave.open(path, "wb") as wf:
            # Set number of channels (must match data).
            wf.setnchannels(n_channels)
            # Set sample width in bytes.
            wf.setsampwidth(sampwidth)
            # Set sample rate (Hz).
            wf.setframerate(sample_rate)
            # Write the PCM bytes to the file.
            wf.writeframes(arr.tobytes())
