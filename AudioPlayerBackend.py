from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class AudioPlayerBackend(QObject):
    """
    Thin wrapper around QMediaPlayer + QAudioOutput.
    Handles loading and controlling an audio file.
    """

    # ms = milliseconds
    position_changed = Signal(int)   # current position in ms
    duration_changed = Signal(int)   # total duration in ms

    def __init__(self, parent=None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)

        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.5)  # default 50%

        # forward internal signals to our own signals
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)

    # -------- internal slots --------

    def _on_position_changed(self, pos_ms: int) -> None:
        self.position_changed.emit(pos_ms)

    def _on_duration_changed(self, duration_ms: int) -> None:
        self.duration_changed.emit(duration_ms)

    # -------- public API --------

    def load_file(self, file_path: str) -> None:
        """Load a local file into the player and reset position."""
        if not file_path:
            print("AudioPlayerBackend.load_file: empty path, ignoring")
            return

        url = QUrl.fromLocalFile(file_path)
        print(f"AudioPlayerBackend.load_file: loading {url.toString()}")
        self._player.setSource(url)
        self._player.setPosition(0)

    def play(self) -> None:
        """Start playback from the beginning (always restart)."""
        if self._player.source().isEmpty():
            print("AudioPlayerBackend.play: no file loaded")
            return

        print("AudioPlayerBackend.play: starting from beginning")
        self._player.setPosition(0)
        self._player.play()

    def resume(self) -> None:
        """Resume playback from current position (do not restart)."""
        if self._player.source().isEmpty():
            print("AudioPlayerBackend.resume: no file loaded")
            return

        print("AudioPlayerBackend.resume: resuming from current position")
        self._player.play()

    def pause(self) -> None:
        """Pause playback (keep current position)."""
        print("AudioPlayerBackend.pause: pausing playback")
        self._player.pause()

    def stop(self) -> None:
        """Stop playback and rewind to the start."""
        print("AudioPlayerBackend.stop: stopping and rewinding to start")
        self._player.stop()
        self._player.setPosition(0)

    def seek_ms(self, pos_ms: int) -> None:
        """Seek to a specific position in ms (clamped to valid range)."""
        if self._player.source().isEmpty():
            print("AudioPlayerBackend.seek_ms: no file loaded")
            return

        pos_ms = max(0, int(pos_ms))
        duration = self._player.duration()
        if duration > 0:
            pos_ms = min(pos_ms, duration)

        print(f"AudioPlayerBackend.seek_ms: setting position to {pos_ms} ms")
        self._player.setPosition(pos_ms)

    def set_volume_0_1(self, value: float) -> None:
        """Set volume in [0.0, 1.0]."""
        value = max(0.0, min(1.0, float(value)))
        print(f"AudioPlayerBackend.set_volume_0_1: {value:.2f}")
        self._audio_output.setVolume(value)
